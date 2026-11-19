# SCRUM-179 — Nối lượt chat và đo độ trễ LLM

- Task: [SCRUM-179](https://tripflix.atlassian.net/browse/SCRUM-179) (chị Trang: chi phí AI theo người dùng, trace từng lượt chat; BE PR #278).
- Nhánh: `bao/SCRUM-179-turn-id-latency` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-19.

## Đã làm

- Mỗi run_turn tạo một UUID dùng chung cho usage controller/responder và ChatTurnEvent. Hai lượt trong cùng conversation vẫn có turnId khác nhau.
- GuardedLlmClient.agenerate đo perf_counter quanh lời gọi native/to_thread sau khi breaker cho qua, trả bản sao LlmResult chỉ bổ sung latency_ms. Giữ nguyên generate sync, nhánh lỗi và huỷ.
- ChatUsage giữ độ trễ provider; ChatTurn đo từ thời điểm request tới suy ra từ deadline, kể cả lỗi/đóng stream. Không thêm prompt/câu trả lời vào sự kiện hoặc log.
- turnId/latencyMs mặc định None để model vẫn nhận sự kiện cũ; latencyMs không âm. Sinh lại cả hai contract bằng script.

## Đối chiếu "Xong khi"

| Tiêu chí theo yêu cầu | Đạt | Bằng chứng |
|---|---|---|
| Usage và ChatTurn cùng turnId; hai lượt khác nhau khác ID | Có | `test_llm_calls_share_the_turn_id_and_keep_their_latency` |
| Độ trễ usage đúng LlmResult; lượt lỗi/huỷ vẫn có độ trễ | Có | Test trên và `test_failed_turn_records_error_kind`, `test_closing_stream_mid_turn_records_error` |
| Native/to_thread chỉ thêm độ trễ, giữ các trường khác | Có | `test_async_llm_measures_provider_latency_without_changing_result` |
| Breaker mở/lỗi/huỷ giữ hành vi cũ | Có | `test_async_open_breaker_never_starts_latency_timer`, `test_async_failure_and_cancellation_keep_breaker_behavior` |
| Sự kiện cũ validate; contract khớp model | Có | `test_old_events_without_turn_metadata_still_validate` và hai test contract hiện có |

## Kết quả kiểm tra

- `uv run python -m scripts.export_usage_events`: pass, sinh lại hai contract events.
- `uv run ruff check .`: pass, 0 lỗi.
- `uv run ruff format --check .`: 219 file đúng format.
- `uv run pyright`: 0 errors, 0 warnings, 0 informations.
- `uv run pytest --ignore tests/test_chat.py` cùng bản `tests/test_chat.py` đã commit: **1061 passed, 6 skipped**.
- `REDIS_TEST_URL=redis://localhost:6379/15 uv run pytest tests/test_usage_events.py`: **12 passed** (Redis thật).
- `tests/test_chat.py::test_sse_refusal_uses_fixed_text` so khớp nguyên payload chi phí nên được cập nhật: `turnId` là UUID, `latencyMs` là `null` (LLM giả trong test không đi qua `GuardedLlmClient`). Đây là cập nhật đúng hình dạng mới, không nới lỏng test.

## Cách kiểm lại

1. Chạy các lệnh kiểm tra phía trên.
2. Chat hai lượt bằng một tài khoản và cùng conversation: đối chiếu turnId giữa usage từng role với ChatTurnEvent; ID phải khác giữa hai lượt.
3. Đối chiếu latencyMs: usage chỉ đo provider, ChatTurn đo cả lượt từ lúc request tới. Thử lỗi/đóng stream và kiểm tra vẫn có latencyMs không âm.

## Ảnh / video

- Không đổi giao diện; không có ảnh/video.

## Ảnh hưởng tới phần của người khác

- Không sửa code của người khác.
- **Thứ tự merge:** payload `ai.chat.turn.recorded` bên BE (#278) là `strictObject`. PR này chỉ merge sau khi #278 lên staging, nếu không BE coi sự kiện lượt chat là sai hợp đồng và bỏ qua. Merge xong thì anh Phong đổi `AI_TAG` trên staging.
- Phần tóm tắt dùng `generate` (đồng bộ) nên không có `latency_ms`; không đổi sự kiện của phần tóm tắt.
