# TF32 — Endpoint `POST /moderate` lọc chữ và ảnh cho core

- Notion/Jira: (Bảo bổ sung link TF32) · Nhánh: `bao/TF32-moderate-endpoint` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-09

## Đã làm

- **`POST /moderate`** cho core gọi khi đăng bài hoặc bình luận (PRD F8: regex ở core + model). Bọc OpenAI `omni-moderation-latest` (miễn phí, nhận chữ và ảnh). Không lưu nội dung.
- **Hợp đồng** (chị Trang đề xuất, Bảo chốt thêm giới hạn và mã lỗi):
  ```
  Req: { "items": [ { "id": "post:<uuid>", "text": "...", "imageUrls": ["https://..."] } ] }
  Res: { "results": [ { "id", "flagged", "categories": {...}, "scores": {...} } ], "model": "..." }
  ```
  - **Giới hạn:** 1–20 item; `text` tối đa 10.000 ký tự; tối đa 4 ảnh `https` mỗi item; mỗi item phải có chữ hoặc ảnh. Vượt giới hạn trả 422.
  - **Lỗi:**
    - 401: token sai hoặc hết hạn;
    - 403: service khác `core-api`;
    - 502: OpenAI lỗi;
    - 504: quá 2,5 giây;
    - 503: chưa có `OPENAI_API_KEY`.
    - Lỗi thì cả request lỗi, core rơi về regex.
- **Xác thực service token của core** (`app/api/auth.py`), kiểm giống guard của core:
  - chữ ký ES256 qua `{CORE_API_URL}/.well-known/jwks.json`;
  - `iss = tripflix-core`, `aud = ai-service`;
  - bắt buộc có `sub`/`typ`/`iat`/`exp`, `typ = service`;
  - chỉ nhận `sub = core-api`.
- **Riêng tư:** che số điện thoại, email, CCCD, tên người trong text trước khi gửi OpenAI (dùng lại `mask_pii`). Không log token.
- **Thời gian:** gọi song song các item, ngắt ở 2,5 giây (core chờ 3 giây).
- **Chi phí:** ghi log `ai.usage.recorded`, chi phí bằng 0.
- **Cấu hình riêng `ModerationSettings`:** container `ai-service` không có `LLM_PROVIDER`, nên endpoint này không phụ thuộc biến đó. Không phải sửa compose.
- **Thư viện mới:** `pyjwt[crypto]`, để kiểm chữ ký ES256 của service token qua JWKS. Bảo đã đồng ý.

## Đối chiếu "Xong khi"

| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Core gọi được `POST /moderate`, mỗi item một kết quả, đúng thứ tự, camelCase | Có | `test_core_gets_one_result_per_item_in_order_in_camel_case` |
| Chỉ core gọi được | Có | `test_bad_tokens_are_401` (7 kiểu token sai), `test_another_service_is_403` |
| Không gửi PII sang OpenAI | Có | `test_images_are_passed_and_pii_is_masked_before_the_provider` |
| Lỗi hoặc chậm không làm core treo | Có | `test_provider_error_is_502_and_slow_provider_is_504`, `test_missing_key_is_503_but_only_after_auth` |
| Gửi đúng định dạng OpenAI, gộp nhiều kết quả | Có | `tests/clients/test_openai_moderation.py` |
| Chất lượng với tiếng Việt | Chờ key | `uv run python -m evals.run_moderation_eval` trên `evals/moderation/vi_30.jsonl` (15 câu độc hại, 15 câu sạch hoặc lóng) |

## Kết quả kiểm tra

- `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`: ruff sạch, pyright 0 lỗi, **417 passed**, 5 skipped. Trong đó có 27 test mới cho moderation.
- `contracts/openapi/ai-service.json` sinh lại bằng `uv run python -m scripts.export_openapi`.
- Đo tiếng Việt: (điền khi có key).

## Cách kiểm lại

1. Đặt `OPENAI_API_KEY` trong `.env`, chạy `uv run fastapi dev app/main.py`.
2. Trên core local: `auth:create-service-client core-api ai-service`, lấy service token.
3. `POST http://localhost:8000/moderate` kèm `Authorization: Bearer <token>`, gửi một câu sạch, một câu xúc phạm và một ảnh.

## Ảnh / video

- Không đổi giao diện.

## Ảnh hưởng tới phần của người khác

- Endpoint mới, không sửa code của người khác.
- **Core (chị Trang):** tạo service client `core-api` với audience `ai-service`, rồi gọi kèm service token.
- **Staging (anh Phong):** cần `OPENAI_API_KEY` trong `.env.server` (key do chị Trang cấp).
