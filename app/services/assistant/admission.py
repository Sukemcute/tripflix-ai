"""Who may start a chat turn now, and on which budget (DeepResearch_Tripi_2_agent_SWE §3).

Checks run cheapest first, before any LLM token is spent:
1. one turn at a time per identity (double taps, two tabs, parallel spending);
2. turns per minute;
3. turns running in this process (no queue: a waiting chat turn is worthless);
4. today's budget (turns and tokens per identity, USD for the whole system).
A guest over budget must log in; a member over budget, or the system over its cap, gets
Core search without the LLM.

Counters live in the key-value store so every process sees them. If it fails, the lock and
the system cap fall back to this process's memory and the per-identity limits let the turn
through: they stop abuse, they are not security, and blocking all chat on a store outage
would switch Tripi off.
"""

import hashlib
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Protocol

from redis.exceptions import RedisError

from app.core.config import ChatSettings

logger = logging.getLogger(__name__)
VIETNAM = timezone(timedelta(hours=7))  # no daylight saving; avoids tzdata on Windows
DAY_SECONDS = 86_400
MICRO = 1_000_000


@dataclass(frozen=True)
class Identity:
    key: str  # user:<sub> or ip:<salted hash>; never the raw IP
    is_guest: bool


class ChatRejectedError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        retry_after: int = 0,
        is_login_required: bool = False,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.is_login_required = is_login_required


@dataclass
class Ticket:
    identity: Identity
    token: str
    day: str
    degraded: list[str] = field(default_factory=list)
    is_released: bool = False


class Counters(Protocol):
    async def acquire(self, key: str, token: str, ttl_ms: int) -> bool: ...
    async def release(self, key: str, token: str) -> None: ...
    async def hit(self, key: str, ttl_seconds: int) -> int: ...
    async def read(self, key: str) -> dict[str, int]: ...
    async def add(self, key: str, values: dict[str, int], ttl_seconds: int) -> None: ...


class MemoryCounters:
    """This process only: tests, and the fallback when the shared store is down."""

    def __init__(self, clock=time.monotonic) -> None:
        self.clock = clock
        self.locks: dict[str, tuple[str, float]] = {}
        self.values: dict[str, dict[str, int]] = defaultdict(dict)

    async def acquire(self, key: str, token: str, ttl_ms: int) -> bool:
        held = self.locks.get(key)
        if held and held[1] > self.clock():
            return False
        self.locks[key] = (token, self.clock() + ttl_ms / 1000)
        return True

    async def release(self, key: str, token: str) -> None:
        if self.locks.get(key, ("", 0))[0] == token:
            del self.locks[key]

    async def hit(self, key: str, ttl_seconds: int) -> int:
        bucket = self.values[key]
        bucket["n"] = bucket.get("n", 0) + 1
        return bucket["n"]

    async def read(self, key: str) -> dict[str, int]:
        return dict(self.values.get(key, {}))

    async def add(self, key: str, values: dict[str, int], ttl_seconds: int) -> None:
        bucket = self.values[key]
        for name, amount in values.items():
            bucket[name] = bucket.get(name, 0) + amount


# Delete the lock only if it is still ours: a slow turn must not free the next turn's lock.
_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end"


class RedisCounters:
    def __init__(self, redis) -> None:  # redis.asyncio.Redis, decode_responses=True
        self.redis = redis

    async def acquire(self, key: str, token: str, ttl_ms: int) -> bool:
        return bool(await self.redis.set(key, token, nx=True, px=ttl_ms))

    async def aclose(self) -> None:
        await self.redis.aclose()

    async def release(self, key: str, token: str) -> None:
        await self.redis.eval(_RELEASE, 1, key, token)

    async def hit(self, key: str, ttl_seconds: int) -> int:
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, ttl_seconds)
        return int(count)

    async def read(self, key: str) -> dict[str, int]:
        return {name: int(value) for name, value in (await self.redis.hgetall(key)).items()}

    async def add(self, key: str, values: dict[str, int], ttl_seconds: int) -> None:
        async with self.redis.pipeline(transaction=True) as pipe:
            for name, amount in values.items():
                pipe.hincrby(key, name, amount)
            pipe.expire(key, ttl_seconds)
            await pipe.execute()


def guest_identity(ip: str, salt: str) -> Identity:
    digest = hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:16]
    return Identity(key=f"ip:{digest}", is_guest=True)


def user_identity(sub: str) -> Identity:
    return Identity(key=f"user:{sub}", is_guest=False)


class TurnGate:
    def __init__(
        self,
        settings: ChatSettings,
        shared: Counters | None,
        *,
        local: MemoryCounters | None = None,
        now=lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self.shared = shared
        self.local = local or MemoryCounters()
        self.now = now
        self.inflight = 0

    async def enter(self, identity: Identity) -> Ticket:
        s = self.settings
        today = self.now().astimezone(VIETNAM)
        ticket = Ticket(identity, uuid.uuid4().hex, today.strftime("%Y%m%d"))
        lock_ms = int((s.chat_timeout_seconds + 3) * 1000)
        if not await self._call("acquire", f"chat:busy:{identity.key}", ticket.token, lock_ms):
            raise ChatRejectedError(
                409,
                "TURN_IN_PROGRESS",
                "Tripi đang trả lời câu trước của bạn, chờ xíu nha.",
                retry_after=2,
            )
        try:
            self._check_minute(identity, await self._count_minute(identity, today))
            if self.inflight >= s.chat_max_inflight:
                raise ChatRejectedError(
                    503, "CHAT_BUSY", "Tripi đang đông khách, bạn thử lại sau vài giây nha.",
                    retry_after=3,
                )  # fmt: skip
            await self._check_day(ticket)
        except BaseException:
            await self._call("release", f"chat:busy:{identity.key}", ticket.token)
            raise
        self.inflight += 1
        return ticket

    async def settle(self, ticket: Ticket, *, tokens: int, cost_usd: float) -> None:
        """Count a finished turn; called once, from the stream's finally."""
        cost = int(round(cost_usd * MICRO))
        await self._call(
            "add", self._day_key(ticket), {"turns": 1, "tokens": tokens}, 2 * DAY_SECONDS
        )
        system = {"micro_usd": cost}
        await self.local.add(f"chat:spend:all:{ticket.day}", system, 2 * DAY_SECONDS)
        await self._shared_only("add", f"chat:spend:all:{ticket.day}", system, 2 * DAY_SECONDS)

    async def leave(self, ticket: Ticket) -> None:
        if ticket.is_released:
            return
        ticket.is_released = True
        self.inflight -= 1
        await self._call("release", f"chat:busy:{ticket.identity.key}", ticket.token)

    async def aclose(self) -> None:
        if isinstance(self.shared, RedisCounters):
            await self.shared.aclose()

    def history_turns(self, identity: Identity) -> int:
        s = self.settings
        return s.chat_guest_history_turns if identity.is_guest else s.chat_user_history_turns

    async def _count_minute(self, identity: Identity, today: datetime) -> int | None:
        key = f"chat:rate:{identity.key}:{today.strftime('%Y%m%d%H%M')}"
        return await self._shared_only("hit", key, 120)

    def _check_minute(self, identity: Identity, count: int | None) -> None:
        s = self.settings
        limit = s.chat_guest_turns_per_minute if identity.is_guest else s.chat_user_turns_per_minute
        if count is not None and count > limit:
            seconds_left = 60 - self.now().second
            raise ChatRejectedError(
                429, "RATE_LIMITED", "Bạn hỏi hơi nhanh, đợi Tripi một chút nha.",
                retry_after=max(1, seconds_left),
            )  # fmt: skip

    async def _check_day(self, ticket: Ticket) -> None:
        s = self.settings
        identity = ticket.identity
        used = await self._shared_only("read", self._day_key(ticket)) or {}
        turns_cap = s.chat_guest_daily_turns if identity.is_guest else s.chat_user_daily_turns
        tokens_cap = s.chat_guest_daily_tokens if identity.is_guest else s.chat_user_daily_tokens
        if used.get("turns", 0) >= turns_cap or used.get("tokens", 0) >= tokens_cap:
            if identity.is_guest:
                raise ChatRejectedError(
                    429,
                    "GUEST_LIMIT_REACHED",
                    "Bạn đăng nhập để chat tiếp với Tripi nha, cuộc trò chuyện vẫn được giữ.",
                    retry_after=self._seconds_to_midnight(),
                    is_login_required=True,
                )
            ticket.degraded.append("quota")
        shared = await self._shared_only("read", f"chat:spend:all:{ticket.day}")
        local = await self.local.read(f"chat:spend:all:{ticket.day}")
        spent = max((shared or {}).get("micro_usd", 0), local.get("micro_usd", 0))
        if spent >= s.chat_system_daily_usd * MICRO and "quota" not in ticket.degraded:
            ticket.degraded.append("quota")

    def _day_key(self, ticket: Ticket) -> str:
        return f"chat:spend:{ticket.identity.key}:{ticket.day}"

    def _seconds_to_midnight(self) -> int:
        local = self.now().astimezone(VIETNAM)
        midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return int((midnight - local).total_seconds())

    async def _call(self, method: str, *args):
        """Shared store first; this process's memory when it is down (locks must still hold)."""
        if self.shared is not None:
            try:
                return await getattr(self.shared, method)(*args)
            except (RedisError, OSError):
                logger.warning("chat counters unavailable, using process memory for %s", method)
        return await getattr(self.local, method)(*args)

    async def _shared_only(self, method: str, *args):
        """Per-identity limits fail open: None means 'not counted'."""
        if self.shared is None:
            return await getattr(self.local, method)(*args)
        try:
            return await getattr(self.shared, method)(*args)
        except (RedisError, OSError):
            logger.warning("chat counters unavailable, %s not enforced", method)
            return None
