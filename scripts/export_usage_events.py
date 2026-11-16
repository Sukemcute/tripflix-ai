import json
from pathlib import Path

from app.services.usage_events import UsageEvent

CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "events"
    / "ai.usage.recorded.v1.schema.json"
)


def main() -> None:
    schema = UsageEvent.model_json_schema(mode="serialization", by_alias=True)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    CONTRACT.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
