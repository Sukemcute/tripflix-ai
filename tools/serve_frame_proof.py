"""Local acceptance adapter: substitute only QA CDN bytes for missing S3, call real OpenAI.

Not used by production. Core JWT, /moderate/parts validation and all verdicts remain real.
Set BE09_FRAME_PROOF_DIR and BE09_FRAME_PROOF_ENV; never put keys in arguments or logs.
"""

import base64
import os
import re
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from app.api.moderation import get_moderation_client, get_visobert_client
from app.clients.moderation.base import ModerationResult
from app.clients.moderation.openai import OpenAIModerationClient
from app.core.config import ModerationSettings, get_moderation_settings
from app.main import app

settings = ModerationSettings(
    _env_file=os.environ["BE09_FRAME_PROOF_ENV"],  # pyright: ignore[reportCallIssue]
    core_api_url="http://localhost:3000",
    moderation_timeout_seconds=20,
    is_visobert_enabled=False,
)
provider = OpenAIModerationClient(
    settings.openai_api_key,
    model=settings.moderation_model,
    base_url=settings.openai_base_url,
    timeout_seconds=20,
)
directory = Path(os.environ["BE09_FRAME_PROOF_DIR"]).resolve()
pattern = re.compile(
    r"/qa/videos/[0-9a-f-]{36}/r1/(?:moderation/uniform-v1/[0-9a-f-]{36}/(\d+)\.jpg|poster_540\.jpg)$"
)


class FrameProofClient:
    async def moderate(self, text: str, image_urls: Sequence[str]) -> ModerationResult:
        inputs: list[str] = []
        for url in image_urls:
            match = pattern.search(url)
            if match:
                timestamp = match.group(1) or "0"
                if timestamp not in {"0", "2950", "5900"}:
                    raise ValueError("unknown proof frame")
                encoded = base64.b64encode((directory / f"{timestamp}.jpg").read_bytes()).decode()
                inputs.append(f"data:image/jpeg;base64,{encoded}")
            else:
                inputs.append(url)
        return await provider.moderate(text, inputs)


app.dependency_overrides[get_moderation_client] = FrameProofClient
app.dependency_overrides[get_visobert_client] = lambda: None
app.dependency_overrides[get_moderation_settings] = lambda: settings

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("BE09_FRAME_PROOF_PORT", "8001")))
