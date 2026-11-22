# tripflix-ai

AI service của Tripflix, dùng FastAPI, Python 3.13 và uv.

## Chạy local

1. Cài Python 3.13 và [uv](https://docs.astral.sh/uv/).
2. Chạy `uv sync --locked`.
3. Chép `.env.example` thành `.env` nếu cần chỉnh URL của Core API.
4. Chạy `uv run fastapi dev app/main.py`.

Health check: <http://localhost:8000/health>. Tài liệu API: <http://localhost:8000/docs>.
Sinh hợp đồng OpenAPI cho FE bằng `uv run python -m scripts.export_openapi`.

Worker tóm tắt bài viết (nghe `stream:core.content` trên Redis) chạy riêng: `uv run python -m app.workers.summary_worker`.

## Chạy bằng Docker (cùng cả hệ thống)

AI không chạy mặc định trong stack. Từ thư mục `tripflix-be`:

| Lệnh | Chạy gì |
|---|---|
| `pnpm stack:ai` | Bật `ai-service` (cổng 8000) và `ai-summary-worker` lên stack đang chạy |
| `pnpm stack:ai:down` | Tắt riêng AI |
| `pnpm stack:full` / `pnpm stack:watch:full` | Cả hệ thống kèm AI |

Đặt `LLM_PROVIDER` (và `OPENAI_API_KEY` nếu dùng OpenAI) trong `tripflix-be/deploy/.env`. Code ở máy thì dùng `LLM_PROVIDER=fake`.

## Kiểm tra

```sh
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

Đọc [RULES.md](RULES.md) trước khi làm việc. Docker image có stage `dev` và `prod`.
