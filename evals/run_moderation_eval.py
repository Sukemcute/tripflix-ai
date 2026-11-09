"""Vietnamese check of POST /moderate's provider (TF32): does it flag toxic and pass slang?

    uv run python -m evals.run_moderation_eval   # needs OPENAI_API_KEY in .env (free endpoint)

evals/moderation/vi_30.jsonl: 15 toxic (harassment, threat, self-harm, sexual, hate,
violence; with and without diacritics, teencode) and 15 clean comments that rules or models
often mistake (slang like "đẹp chết mất", "giá cắt cổ", complaints, safety reports). Texts go
through the same path as the endpoint (PII masking, one call per item). Not a gate: numbers
go to the evidence so core knows what to expect before the demo.
"""

import asyncio
import json
import sys
from pathlib import Path

from app.clients.moderation.openai import OpenAIModerationClient
from app.core.config import get_moderation_settings
from app.services.moderation import ModerationItem, moderate_items

DATA = Path(__file__).resolve().parent / "moderation" / "vi_30.jsonl"


async def main() -> None:
    settings = get_moderation_settings()
    if not settings.openai_api_key.get_secret_value():
        sys.exit("OPENAI_API_KEY is empty: put it in .env")
    rows = [json.loads(line) for line in DATA.read_text("utf-8").splitlines() if line.strip()]
    client = OpenAIModerationClient(
        settings.openai_api_key,
        model=settings.moderation_model,
        base_url=settings.openai_base_url,
        timeout_seconds=10,  # offline check: no 3 s budget
    )
    items = [ModerationItem(r["id"], r["text"], ()) for r in rows]
    results = dict(await moderate_items(items, client, timeout_seconds=60))
    await client.aclose()

    tp = sum(1 for r in rows if r["toxic"] and results[r["id"]].flagged)
    fp = sum(1 for r in rows if not r["toxic"] and results[r["id"]].flagged)
    fn = sum(1 for r in rows if r["toxic"] and not results[r["id"]].flagged)
    print(f"model {next(iter(results.values())).model}")
    print(f"precision {tp / (tp + fp) if tp + fp else 0:.2f}  recall {tp / (tp + fn):.2f}")
    print(f"toxic caught {tp}/{tp + fn}, clean flagged {fp}/{len(rows) - tp - fn}")
    for r in rows:
        result = results[r["id"]]
        if result.flagged != r["toxic"]:
            top = max(result.scores.items(), key=lambda kv: kv[1])
            print(
                f"  WRONG {r['id']} {r['kind']:13} flagged={result.flagged} top={top} {r['text']}"
            )


if __name__ == "__main__":
    asyncio.run(main())
