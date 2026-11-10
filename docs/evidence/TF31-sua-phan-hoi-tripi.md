# TF31 — Hỏi lại đúng thông tin thiếu và giới thiệu Tripi

- Jira [SCRUM-35](https://tripflix.atlassian.net/browse/SCRUM-35)
- Nhánh `bao/TF31-sua-phan-hoi-tripi` từ staging `164c7db`.

Prompt v2 coi điểm đến kèm thời lượng là yêu cầu tìm lộ trình. Khi LLM trả `clarify`, Chat API dùng `place` và `missing` để hỏi đúng thông tin còn thiếu. Với `small_talk`, Tripi giới thiệu tên và khả năng bằng câu trả lời mẫu.

Đã chạy hai câu báo lỗi qua Chat API local với DeepSeek và Core thật, dùng phiên giả lập trong TestClient. “3 ngày 2 đêm hà nội” đi qua bước tìm kiếm và trả `answer`. “Bạn là ai?” trả `answer` với lời giới thiệu Tripi. Test SSE mô phỏng thêm trường hợp thiếu ngày và trường hợp LLM đánh dấu thiếu nơi dù đã trả địa điểm.

Ruff, kiểm tra định dạng và Pyright đều qua. Pytest có 453 test pass và 5 skip. Bộ eval tóm tắt bình luận với LLM giả giữ nguyên 4/15 ca đúng trạng thái (0,267) trước và sau, với 11 ca trượt cùng tiêu chí `status_matches`.

Kiểm tra thêm câu không dấu “san may da lat”. Core public trả đúng video `018d9f20-0000-7000-8000-000000000004` qua cả API tìm kiếm tổng hợp và API tìm video. Prompt v1 với DeepSeek thật từng trả `find_flight` và query rỗng. Prompt v2 bổ sung ví dụ không dấu và quy tắc ưu tiên chủ đề của lượt mới. Chat API local dùng DeepSeek thật và Core public trả đúng thẻ video khi mở hội thoại mới và khi lượt trước hỏi vé máy bay. Ruff và 21 test chat qua. Điểm eval tóm tắt vẫn là 4/15.

Các ca SSE bổ sung được giữ local theo yêu cầu. Đã chạy lại bản test chat đang được Git theo dõi với mã mới và cả 17 ca đều qua.
