# SCRUM-177 — Sự kiện lượt chat Tripi cho trang admin "Hành vi người dùng"

- Task: SCRUM-177 (chị Trang, trang admin "Hành vi người dùng" cho superadmin) · Nhánh: `bao/SCRUM-177-su-kien-luot-chat` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-18

## Đã làm
- Mỗi lượt chat của **người đã đăng nhập** phát một sự kiện `ai.chat.turn.recorded` v1 lên `stream:ai`, đi chung pipeline với `ai.usage.recorded`. Hợp đồng: `contracts/events/ai.chat.turn.recorded.v1.schema.json`, sinh bằng `uv run python -m scripts.export_usage_events`.
- Envelope như `ai.usage.recorded`, nhưng bắt buộc có `userId`. Payload gồm:
  - `conversationId`;
  - `question`: tối đa 120 ký tự, đã che;
  - `intent`: ý định Controller hiểu, `null` khi không gọi LLM hoặc khi người dùng bấm nút;
  - `answerKind`: loại câu trả lời, `error` khi lỗi hoặc ứng dụng đóng kết nối giữa chừng;
  - `isAction`: lượt bấm nút trên thẻ.
- **Che thông tin cá nhân trước, cắt 120 ký tự sau.** Nếu cắt trước, một email nằm vắt qua ký tự 120 sẽ không còn khớp mẫu và bị lộ một nửa. Dùng `mask_pii` có sẵn của phần tóm tắt: che email, số điện thoại, CCCD và tên có từ xưng hô đứng trước. Như vậy che nhiều hơn yêu cầu (chỉ email và số điện thoại).
- Không phát sự kiện cho:
  - khách: trang admin theo dõi theo tài khoản, và không giữ nội dung chat của người không đăng nhập;
  - lượt bị chặn 409/429/503: đó không phải lượt chat.
- Redis lỗi: sự kiện chi phí vẫn ghi log như cũ. Sự kiện lượt chat chỉ ghi `eventId`, không ghi câu hỏi, để log không chứa nội dung tin nhắn.

## Đối chiếu "Xong khi"
| Tiêu chí (tin nhắn của chị Trang) | Đạt | Bằng chứng |
|---|---|---|
| 1 sự kiện mỗi lượt chat | Đạt | `test_signed_in_turn_records_one_masked_question`, `test_usage_and_chat_turn_share_one_stream_pipeline` |
| Tối đa 120 ký tự, đã che email và số điện thoại | Đạt | Cùng test trên, có ca email vắt qua ký tự 120 |
| Khách và lượt bị chặn không phát | Đạt | `test_guest_does_not_record_a_chat_turn`, `test_gate_rejection_does_not_record_a_turn` (409, 429, 503) |
| Lỗi, đóng giữa chừng, bấm nút | Đạt | `test_failed_turn_records_error_kind`, `test_closing_stream_mid_turn_records_error`, `test_action_turn_records_no_controller_intent` |
| Hợp đồng khớp model, `userId` bắt buộc | Đạt | `test_checked_in_contract_matches_chat_turn_events`, `test_chat_turn_requires_a_user` |
| Log không chứa câu hỏi | Đạt | `test_redis_outage_does_not_log_chat_turn_question` |

## Kết quả kiểm tra
- `ruff check`, `ruff format --check` (218 file) và `pyright` (0 lỗi): đều sạch.
- `pytest --ignore tests/test_chat.py`, kèm bản `tests/test_chat.py` đã commit: **1051 passed, 6 skipped**.
- `REDIS_TEST_URL=redis://localhost:6379/15 pytest tests/test_usage_events.py`: **8 passed**, gồm test với Redis thật.
- Gửi thử lên Redis local (db 15, đã xoá sau khi xem). Câu "Mình là An, mail an.nguyen@gmail.com sđt 0912 345 678, muốn đi Đà Lạt 3n2đ" thành `"question":"Mình là An, mail [đã che] sđt [đã che], muốn đi Đà Lạt 3n2đ"`, kèm `intent: plan_trip`, `answerKind: answer`.

## Cách kiểm lại
1. `uv run pytest tests/test_usage_events.py tests/assistant/test_chat_switches.py -q`
2. Có Redis: `REDIS_TEST_URL=redis://localhost:6379/15 uv run pytest tests/test_usage_events.py -q`
3. Chạy thật: chat bằng một tài khoản, rồi `XREVRANGE stream:ai + - COUNT 5` sẽ thấy `ai.chat.turn.recorded` với `question` đã che. Chat bằng khách thì không có.

## Ảnh / video
- Không đổi giao diện.

## Ảnh hưởng tới phần của người khác
- Repo này: không.
- Phía BE (chị Trang đọc sự kiện này):
  - `libs/contracts` khai báo schema theo đúng file hợp đồng trên.
  - Group `core-analytics` trên `stream:ai` đang có `AiUsageConsumer`. Nếu thêm consumer thứ hai cùng group, Redis chia mỗi sự kiện cho một trong hai consumer và mỗi bên sẽ mất sự kiện. Cần gộp vào consumer đó hoặc dùng group khác.
  - `toAiUsageRecord` đã bỏ qua sự kiện khác loại, nên phần chi phí AI không bị ảnh hưởng.
- Giới hạn đã biết: tên không có từ xưng hô đứng trước ("Mình là An") hoặc viết không dấu thì không bị che (ghi chú `shortcut:` trong `pii.py`).
