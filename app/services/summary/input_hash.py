"""Fingerprint of everything that changes the summary (QT Bước 11.3).

Hash exactly what goes to the LLM: masked comment texts with their real IDs and
first-hand flag, the claims, and the versions (lexicons now; prompt and model at P9), plus
the rule safety warnings saved with the summary.
Canonical JSON (sorted keys, fixed separators) so the same input always gives the same
hash. ai-service keeps no state: it returns the hash and core compares it with the last
one to skip a repeat LLM call. Likes are left out: they only reorder, never change text.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence

from app.services.summary.claims import Claim
from app.services.summary.pii import PromptComment
from app.services.summary.schemas import SummarySafety


def compute_input_hash(
    comments: Sequence[PromptComment],
    real_ids: Mapping[str, tuple[str, ...]],
    claims: Sequence[Claim],
    versions: Mapping[str, str | int],
    safety: SummarySafety | None = None,
) -> str:
    payload: dict[str, object] = {
        # keyed by real IDs, sorted: temporary codes c1..cN shift when order changes
        "comments": sorted(
            [list(real_ids[c.cid]), c.text, c.is_first_hand, list(c.context)] for c in comments
        ),
        "claims": [[c.id, c.text, c.source] for c in claims],
        "versions": dict(versions),
    }
    # Safety comes from comments the LLM may never see (stale, over budget): without it a hidden
    # safety comment leaves the old warning up. Added only when present, so hashes of posts
    # without warnings stay valid.
    if safety and (safety.warnings or safety.pending_warnings):
        groups = (("public", safety.warnings), ("pending", safety.pending_warnings))
        payload["safety"] = sorted(
            [visibility, sorted(w.categories), sorted(w.comment_ids)]
            for visibility, group in groups
            for w in group
        )
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
