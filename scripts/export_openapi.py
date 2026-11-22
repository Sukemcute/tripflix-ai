import json
from pathlib import Path

from app.main import app
from app.services.assistant.schemas import Card

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "openapi" / "ai-service.json"


def main() -> None:
    document = app.openapi()
    # StreamingResponse does not expose the cards event payload to FastAPI's model discovery.
    card = Card.model_json_schema(by_alias=True, ref_template="#/components/schemas/{model}")
    document["components"]["schemas"].update(card.pop("$defs", {}))
    document["components"]["schemas"]["Card"] = card
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
