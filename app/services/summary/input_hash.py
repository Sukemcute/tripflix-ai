"""Fingerprint of everything that changes the summary (QT Bước 11.3).

Hash exactly what goes to the LLM: masked comment texts with their real IDs and
first-hand flag, the claims, and the versions (lexicons now; prompt and model at P9).
Canonical JSON (sorted keys, fixed separators) so the same input always gives the same
hash. ai-service keeps no state: it returns the hash and core compares it with the last
one to skip a repeat LLM call. Likes are left out: they only reorder, never change text.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence

from app.services.summary.claims import Claim
from app.services.summary.pii import PromptComment


def input_hash(
    comments: Sequence[PromptComment],
    real_ids: Mapping[str, tuple[str, ...]],
    claims: Sequence[Claim],
    versions: Mapping[str, str | int],
) -> str:
    payload = {
        # keyed by real IDs, sorted: temporary codes c1..cN shift when order changes
        "comments": sorted(
            [list(real_ids[c.cid]), c.text, c.first_hand, list(c.context)] for c in comments
        ),
        "claims": [[c.id, c.text, c.source] for c in claims],
        "versions": dict(versions),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
