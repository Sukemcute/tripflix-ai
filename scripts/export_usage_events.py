import json
from pathlib import Path

from app.services.usage_events import ChatTurnEvent, UsageEvent

CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "events"
    / "ai.usage.recorded.v1.schema.json"
)
CHAT_TURN_CONTRACT = CONTRACT.with_name("ai.chat.turn.recorded.v1.schema.json")


def main() -> None:
    for model, path in [(UsageEvent, CONTRACT), (ChatTurnEvent, CHAT_TURN_CONTRACT)]:
        schema = model.model_json_schema(mode="serialization", by_alias=True)
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )


if __name__ == "__main__":
    main()
