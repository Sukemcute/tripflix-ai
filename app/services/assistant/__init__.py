"""TF31: bounded discovery workflow. Product claims are rendered from Core cards."""

from app.services.assistant.schemas import (
    Answer,
    Card,
    ChatRequest,
    SearchResponse,
    Section,
    Turn,
    Understanding,
)
from app.services.assistant.skills.content import MAX_VIDEO_CARDS, build_cards, search
from app.services.assistant.skills.flight import search_flights
from app.services.assistant.skills.stay import search_stays
from app.services.assistant.understand import build_understanding_input

__all__ = [
    "MAX_VIDEO_CARDS",
    "Answer",
    "Card",
    "ChatRequest",
    "SearchResponse",
    "Section",
    "Turn",
    "Understanding",
    "build_cards",
    "build_understanding_input",
    "search",
    "search_flights",
    "search_stays",
]
