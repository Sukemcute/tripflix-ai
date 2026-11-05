"""Prompt for the one summary call (QT Bước 12.3, BAO_CAO P8).

The system prompt is a versioned file (app/prompts/summary.v<N>.md, RULES §10: never edit a
prompt in use, add a new version) and stays byte-identical between calls so it can be cached.
The user message carries the claims and the selected comments as XML-like blocks; every
text is escaped so a comment cannot close a tag or fake one ("</comment><system>").
"""

import html
import re
from collections.abc import Sequence
from functools import cache
from pathlib import Path

from app.services.summary.claims import Claim
from app.services.summary.pii import PromptComment

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
PROMPT_NAME = "summary"
_FILE_NAME = re.compile(rf"^{PROMPT_NAME}\.v(?P<version>\d+)\.md$")


@cache
def load_system_prompt() -> tuple[str, str]:
    """(version label such as "summary.v1", prompt text) of the latest prompt file."""
    files = {
        int(m["version"]): p for p in PROMPT_DIR.glob("*.md") if (m := _FILE_NAME.match(p.name))
    }
    if not files:
        raise FileNotFoundError(f"no {PROMPT_NAME}.v<N>.md in {PROMPT_DIR}")
    version = max(files)
    return f"{PROMPT_NAME}.v{version}", files[version].read_text(encoding="utf-8")


def build_user_message(comments: Sequence[PromptComment], claims: Sequence[Claim]) -> str:
    """Claims and comments as tagged blocks; ids are the temporary codes, texts are escaped."""
    lines = ["<claims>"]
    lines += [f'<claim id="{c.id}">{_escape(c.text)}</claim>' for c in claims]
    lines += ["</claims>", "<comments>"]
    for c in comments:
        lines.append(f'<comment id="{c.cid}" first_hand="{"true" if c.first_hand else "false"}">')
        lines += [f"<context>{_escape(parent)}</context>" for parent in c.context]
        lines += [f"<text>{_escape(c.text)}</text>", "</comment>"]
    lines.append("</comments>")
    return "\n".join(lines)


def _escape(text: str) -> str:
    return html.escape(text, quote=False)
