# TF33 — Bình luận bị ẩn biến mất khỏi tóm tắt AI

- Jira: SCRUM-37 (TF33, chị Trang chính, Bảo phối hợp phần AI) · Nhánh: `bao/TF33-an-binh-luan-tom-tat-lai` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-09

## Đã làm

- **Worker nghe `content.comment.hidden` và `content.comment.restored`** (`app/workers/summary_worker.py`).
  - Core phát hai sự kiện này trên `stream:core.content`, chị Trang và Thành chốt ngày 2026-11-09:
    - giữ envelope, version 1;
    - payload `{ postId, commentId, authorId }`;
    - mỗi bình luận hoặc phản hồi đổi trạng thái phát một sự kiện riêng.
  - Worker dùng `postId` để gom, rồi đọc lại bình luận visible từ core.
- **Bình luận bị ẩn được xử lý nhanh** (chị Trang đồng ý):
  - Bài được tóm tắt lại chậm nhất 60 giây sau lần ẩn đầu, không chờ khoảng cách tối thiểu 10 phút giữa hai lần tóm tắt.
  - Ẩn hàng loạt (bình luận gốc kèm phản hồi) vẫn giữ mốc 60 giây của lần ẩn đầu.
  - Sự kiện thường đến sau không làm lùi lịch này.
  - Lý do: trong lúc chờ bản mới, core tạm ngừng trả phần tóm tắt bị ảnh hưởng.
  - `restored` đi đường thường, vì không có nội dung nào cần che.
- **Sửa lỗi: cảnh báo an toàn được đưa vào `inputHash`** (`input_hash.py`, `pipeline.py`).
  - **Lỗi cũ:** bình luận an toàn có thể không được gửi LLM (cũ hơn 1 năm theo luật L2, hoặc vượt ngân sách token). Khi bình luận đó bị ẩn, hash không đổi nên worker bỏ qua, và cảnh báo cũ vẫn hiện.
  - **Cách sửa:** chỉ đưa cảnh báo vào hash khi bài có cảnh báo, nên hash của bài không có cảnh báo vẫn giữ nguyên.
  - **Hệ quả khi deploy:** mỗi bài đang có cảnh báo sẽ tóm tắt lại một lần, tốn một lượt gọi LLM.
- **Gửi lặp vẫn an toàn:** nhận lại sự kiện chỉ xếp lịch lại cho bài. Khi chạy, hash trùng thì không gọi LLM.

## Đối chiếu "Xong khi"

| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Worker nhận sự kiện ẩn và khôi phục, gom theo bài, gửi lặp không gây hại | Có | `test_moderation_hide_and_restore_reschedule_the_post` |
| Ẩn bình luận thì tóm tắt lại trong khoảng 60 giây, sự kiện sau không làm lùi | Có | `test_a_hide_skips_the_min_gap_and_later_events_never_push_it_back` |
| Ẩn bình luận an toàn mà LLM chưa từng thấy thì cảnh báo vẫn được gỡ | Có | `test_hiding_a_safety_comment_the_llm_never_saw_still_resaves` (fail trước khi sửa) |
| Cảnh báo đổi thì hash đổi; không có cảnh báo thì hash cũ giữ nguyên | Có | `test_safety_warnings_change_the_hash_and_none_keeps_the_old_hash` |
| Bài bị ẩn biến mất khỏi app/web trong vài giây | Phần core | Chị Trang: endpoint flat chỉ trả bình luận visible; core lọc trích dẫn lúc trả GET ai-summary |

## Kết quả kiểm tra

- `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`: ruff sạch, pyright 0 lỗi, **422 passed**, 5 skipped. 5 test Redis thật bị skip vì máy không có Redis.

## Cách kiểm lại

1. Chạy lệnh kiểm tra ở trên.
2. Trên stack local, khi core đã phát sự kiện:
   - ẩn một bình luận đã nằm trong tóm tắt;
   - log worker phải ghi `summary saved` cho bài đó trong khoảng 60 giây;
   - `GET ai-summary` không còn trích dẫn bình luận đó.

## Ảnh / video

- Không đổi giao diện.

## Ảnh hưởng tới phần của người khác

- Chỉ sửa trong repo AI.
- **Core (chị Trang, Thành):** phát hai sự kiện, endpoint flat chỉ trả bình luận visible, lọc tóm tắt lúc trả GET. Đã thống nhất qua tin nhắn ngày 2026-11-09.
- **Còn chờ chốt:** cách nhận diện tóm tắt dùng đúng tập bình luận, để tránh lượt chạy trước lúc ẩn ghi kết quả cũ về sau. AI đề xuất gửi `sourceCommentIds` trong PUT, và core chỉ ghi đè khi `generatedAt` mới hơn. Phần này làm ở PR sau.
- **Chưa xử lý `content.post.hidden`:** bài bị ẩn thì tóm tắt nằm dưới bài cũng không hiện, và worker bỏ qua bài không còn công khai.
