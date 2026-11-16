import json

from app.services.assistant.schemas import ChatRequest
from app.services.summary.pii import mask_pii


def build_understanding_input(request: ChatRequest) -> str:
    return json.dumps(
        {
            "message": mask_pii(request.message),
            "history": [
                {"role": turn.role, "text": mask_pii(turn.text)} for turn in request.history[-6:]
            ],
        },
        ensure_ascii=False,
    )
