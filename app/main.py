import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.moderation import router as moderation_router

app = FastAPI(title="Tripflix AI Service", version="0.1.0")
# App mobile chạy bằng Expo web gọi /chat thẳng từ trình duyệt; app native không cần CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS", "http://localhost:3100,http://localhost:8081"
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["POST"],
    allow_headers=["authorization", "content-type", "accept", "x-request-id", "idempotency-key"],
)
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(moderation_router)
