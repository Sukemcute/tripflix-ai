# TF31 — Chửi tục mà không hỏi gì thì Tripi chỉ nhắc nhẹ, không tìm kiếm

- Notion: TF31 · Nhánh: `bao/TF31-chui-tuc-khong-tim` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-17

## Đã làm
- **Lỗi Bảo gặp:** đang nói chuyện về Đà Lạt, nhắn "cặc, chatbot như quần" thì Tripi trả câu nhắc nhẹ **kèm reel Hội An, Nha Trang và khách sạn**.
- **Nguyên nhân:** có ngữ cảnh chuyến đi thì Controller xếp câu này vào `search` 5/6 lần. Kiểu đáp "nhắc nhẹ" chỉ được chọn khi ý định là small talk, hỏi lại hoặc từ chối. Với `search`, Tripi coi đây là "chửi nhưng có yêu cầu thật": đem chính câu chửi đi tìm rồi gắn câu nhắc lên trước.
- **Sửa** (`social.py`): câu có chửi tục mà không kèm yêu cầu du lịch thì chỉ nhắc nhẹ, bất kể Controller xếp ý định gì.
  - Có yêu cầu nghĩa là: có từ như tìm, đặt, khách sạn, vé máy bay, thời tiết, lịch trình, đi đâu, ăn gì…, hoặc nhắc tên nơi ngay trong câu.
  - `REQUEST_CUE` **[HIỆU CHỈNH]**: "về"/"vé", "chuyện"/"chuyến" trùng nhau khi bỏ dấu nên chỉ tính dạng cụm ("vé máy bay", "chuyến bay").
- Câu chửi có kèm yêu cầu thật ("đm tìm ks đà lạt đi") vẫn được làm như trước, kèm một câu nhắc.

## Đối chiếu "Xong khi"
| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Chửi tục không kèm yêu cầu: chỉ nhắc nhẹ, không thẻ | Đạt | `test_a_rude_message_without_a_request_shows_no_cards`; chạy thật 2/2 lần |
| Chửi kèm yêu cầu thật: vẫn làm, nhắc một câu | Đạt | `test_venting_is_answered_with_a_reminder_not_a_search`, `test_a_rude_real_request_is_answered_with_one_reminder_first` |

## Kết quả kiểm tra
- ruff, pyright sạch. `pytest`: **783 passed, 6 skipped**; `tests/test_chat.py` bản đã commit 17/17. Eval ci: **112/112**.
- Chạy thật (Controller + Responder thật, core giả), 2 lần, ngữ cảnh Đà Lạt:
  - **cặc, chatbot như quần** → Controller vẫn trả `search`, nhưng Tripi chỉ đáp: "Tripi xin lỗi nếu lúc nãy chưa đúng ý bạn, mình nói chuyện nhẹ nhàng thôi nha. Bạn muốn mình chỉnh lại phần nào của chuyến Đà Lạt?" Không có thẻ.
  - **đm tìm ks đà lạt đi** → "Mình nói chuyện nhẹ nhàng thôi nha 😊 Bạn muốn nhận phòng và trả phòng vào ngày nào?"

## Cách kiểm lại
1. `uv run pytest tests/assistant/test_context_and_small_talk.py -q`
2. Trên app: hỏi "Giờ tôi muốn đi Đà Lạt" rồi nhắn "cặc, chatbot như quần": chỉ có câu nhắc nhẹ, không reel, không khách sạn.

## Ảnh / video
- Bảo bỏ việc chụp ảnh cho các task TF31 (2026-11-17).

## Ảnh hưởng tới phần của người khác
- Không.
