# tripflix-ai

AI service của Tripflix, dùng FastAPI, Python 3.13 và uv.

## Chạy local

1. Cài Python 3.13 và [uv](https://docs.astral.sh/uv/).
2. Chạy `uv sync --locked`.
3. Chép `.env.example` thành `.env` nếu cần chỉnh URL của Core API.
4. Chạy `uv run fastapi dev app/main.py`.

Health check: <http://localhost:8000/health>. Tài liệu API: <http://localhost:8000/docs>.
Sinh hợp đồng OpenAPI cho FE bằng `uv run python -m scripts.export_openapi`.

## Kiểm tra

```sh
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

Đọc [RULES.md](RULES.md) trước khi làm việc. Docker image có stage `dev` và `prod`.
