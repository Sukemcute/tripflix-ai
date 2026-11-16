# TF31 — Tripi v3, phần nền: khách vãng lai, hạn mức, LLM theo vai

- Notion: TF31 · Nhánh: `bao/TF31-tripi-v3-nen` · Người làm: Quốc Bảo (dùng AI: có) · Ngày: 2026-11-16
- Thiết kế: `docs/architecture/tripi-agent-v3-de-xuat.md`, `docs/architecture/tripi-agent-kien-truc-chi-tiet.md`

## Đã làm

- **Tách `app/services/assistant.py` thành package** `schemas`, `skills/{content,stay,flight}`, `understand`. Không đổi hành vi; tên cũ vẫn import được.
- **Adapter LLM cho chat:**
  - `agenerate` bất đồng bộ, gọi một lần, không thử lại. Chat có hạn chót riêng và có đường dự phòng không cần LLM.
  - Số lần thử thành tham số; worker tóm tắt vẫn thử 3 lần.
  - `LlmResult.finish_reason`: output bị cắt (`length`) thì bỏ, không parse.
  - `GuardedLlmClient.agenerate` có breaker; adapter chưa có bản async thì chạy trong thread.
- **Controller dùng OpenAI, Responder dùng DeepSeek** (Bảo, 16/11). Mỗi vai một adapter và một breaker, cấu hình bằng `CHAT_CONTROLLER_*` và `CHAT_RESPONDER_*`. PR này mới dùng Controller (bước hiểu câu cũ); Responder dùng từ PR sau.
- **Khách chưa đăng nhập dùng được** (Bảo, 16/11).
  - Đếm hạn mức theo hash IP có salt; không lưu IP gốc.
  - Hết 5 lượt hoặc 8.000 token mỗi ngày thì trả `429 GUEST_LIMIT_REACHED` với `loginRequired: true`.
  - Token sai vẫn trả 401, không hạ ngầm xuống khách.
  - `CHAT_REQUIRE_LOGIN=true` đưa về chế độ bắt đăng nhập như cũ.
- **Cổng nhận trước khi tốn token** (`admission.py`):
  - mỗi danh tính 1 lượt đang chạy (409);
  - số lượt mỗi phút (429);
  - số lượt chạy trong process (503, không xếp hàng);
  - ngân sách ngày theo lượt và token thật.
  - Người đăng nhập hết ngân sách, hoặc cả hệ thống chạm trần 3 USD/ngày, thì chỉ tìm kiếm của core, `done.degraded=["quota"]`.
  - Bộ đếm ở Redis. Redis lỗi thì khóa và trần hệ thống dùng bộ nhớ process; hạn mức từng người cho qua.
- **Sửa phát hiện F1, F3, F6** trong báo cáo SWE:
  - không thử lại trong chat;
  - hạn chót tính từ lúc request tới;
  - khóa mỗi người một lượt.
  - Dùng chung một pool kết nối tới core.
  - Hết lượt thì nhả khóa và ghi usage trong vùng được che khỏi hủy, kể cả khi client ngắt giữa chừng.
- **Hợp đồng** (chỉ thêm): `contextPostId`; mã 409, 429, 503 có body `{code, message, retryAfterSeconds, loginRequired}` và header `Retry-After`; `done.degraded`. Đã sinh lại `contracts/openapi/ai-service.json`.

## Đối chiếu "Xong khi" (Giai đoạn A, phần nền)

| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Khách chưa đăng nhập chat được, hạn mức nhỏ hơn | Có | `test_guest_chats_then_is_asked_to_log_in`, `test_guest_over_daily_budget_must_log_in`, `test_guest_token_budget_counts_real_usage` |
| Khách hết hạn mức thì được mời đăng nhập | Có | 429 `GUEST_LIMIT_REACHED`, `loginRequired: true`, `Retry-After` tới nửa đêm giờ Việt Nam |
| Bấm gửi 2 lần không chạy 2 lượt | Có | `test_second_turn_of_the_same_identity_waits` |
| Quá tải thì từ chối ngay, không giữ khóa | Có | `test_full_process_rejects_at_once_without_queueing` |
| Hết ngân sách thì hạ cấp, không khóa | Có | `test_member_over_budget_is_degraded_not_blocked`, `test_system_cap_degrades_everyone` |
| Redis lỗi vẫn chạy | Có | `test_store_outage_keeps_the_lock_and_lets_turns_through` |
| Chat không thử lại LLM, bỏ output bị cắt | Có | `test_chat_call_is_async_single_and_reports_a_cut_output`, `test_chat_does_not_retry_a_server_error` |
| Không lưu IP gốc | Có | `test_guest_ip_is_never_kept_in_clear` |

## Kết quả kiểm tra

`uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`:
- Ruff: pass. Format: 157 file đúng định dạng. Pyright: 0 lỗi.
- Pytest: **583 pass, 5 skip** (5 test Redis thật cần `REDIS_TEST_URL`).
- `uv run python -m scripts.export_openapi` đã sinh lại hợp đồng.

**Chưa chạy:**
- Thử với server thật: core và Redis trên máy đang tắt (16/11). Sẽ chạy cả luồng sau PR Responder.
- Eval live: bộ eval hội thoại có ở PR sau.

**Thay đổi test cũ theo yêu cầu mới:**
- `test_chat_requires_login` đổi thành `test_chat_requires_login_when_guests_are_switched_off`, vì khách giờ được dùng theo quyết định 16/11.
- Test SSE dùng chữ ký mới `understand(request, *, max_turns)`.
- Bản local của `tests/test_chat.py` và `.env.example` (skip-worktree, có ca SSE và biến riêng của Bảo) giữ nguyên trên máy; commit chỉ chứa phần cần cho thay đổi này.

## Cách kiểm lại

1. `uv run pytest tests/assistant tests/test_chat.py tests/clients/test_deepseek.py`
2. Chạy thật:
   - Bật Redis và core (`pnpm stack:be` ở `tripflix-be`), đặt `CHAT_LLM_ENABLED=true`, `CHAT_CONTROLLER_MODEL` và 3 giá `CHAT_CONTROLLER_PRICE_*`.
   - Chạy `uv run uvicorn app.main:app --port 8000`.
   - Gửi `POST /chat` không token 6 lần: 5 lượt đầu là SSE, lượt 6 là 429 `GUEST_LIMIT_REACHED`.

## Ảnh hưởng tới phần của người khác

- Không đụng code người khác.
- **Cấu hình deploy cần anh Phong** (tin nhắn soạn sau khi xong Giai đoạn A):
  - Biến mới `CHAT_*`.
  - `CHAT_IDENTITY_SALT`.
  - `REDIS_URL` cho service `ai-service`.
  - `FORWARDED_ALLOW_IPS` để uvicorn đọc IP thật qua gateway.
  - `CHAT_MODEL` cũ không còn dùng.
