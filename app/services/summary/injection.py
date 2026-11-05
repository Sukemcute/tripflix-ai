"""Prompt-injection layer 1 (QT Bước 8): drop comments that try to steer the LLM.

Not a guarantee (OWASP LLM01): spotlighting in the prompt and the validator stay as
layers 2 and 3. Takes the original body so it can also see markup and hidden text
that normalize_text strips.
"""

import re

from app.services.summary.lexicon import load
from app.services.summary.vi_text import clean_text, normalize_text

# A comment that closes or opens our prompt blocks tries to escape spotlighting.
_FAKE_TAG = re.compile(r"</?\s*(?:comment|system|user|assistant|instructions?)\b", re.IGNORECASE)
# Invisible Unicode tag letters ("ASCII smuggling"). clean_text already strips them; a run of
# them is still an attack signal. Flag emoji (England, Scotland) end with U+E007F: allowed.
_HIDDEN_TEXT = re.compile(r"[\U000e0020-\U000e007e]{3,}(?![\U000e0020-\U000e007f])")


def match_injection(body: str) -> list[str]:
    """Names of the injection groups the comment matches; empty when clean."""
    groups = load("injection").matches(normalize_text(body))
    if _FAKE_TAG.search(clean_text(body)):
        groups.append("fake_tag")
    if _HIDDEN_TEXT.search(body):
        groups.append("hidden_text")
    return groups
