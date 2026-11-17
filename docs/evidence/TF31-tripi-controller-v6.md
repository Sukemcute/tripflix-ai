# TF31 — Kiểm thử Controller v6 và tham chiếu Reel của Tripi

- Task TF31 · Nhánh `bao/TF31-sua-reel-do` · Commit code `289a481` · Bảo (dùng AI) · 2026-11-17

## Thay đổi

- Giữ Reel đang nhớ khi người dùng nói “reel đó” hoặc “video này”.
- Đặt trường `message` sau lịch sử trong đầu vào của Controller. Prompt v6 yêu cầu phân loại câu mới nhất và dùng lịch sử để tra ngữ cảnh.
- Nhận cách nói “lên cho tôi lịch trình” và “gợi ý lộ trình” trong bộ lọc ý định lập chuyến đi.

## Kết quả eval

| Phép đo | Log v5f | Log v6 |
|---|---:|---:|
| Live intent và slot | 317/336 (94,3%) | 325/336 (96,7%) |
| ID đạt trong mọi lần chạy | 101/111 | 104/111 |
| Lượt hội thoại chuỗi | 75/81 (92,6%) | 73/76 (96,1%) |
| Chuỗi đạt ở cả ba lần | 3/6 | 3/6 |
| Độ trễ Controller p50 / p95 | 2,43 s / 3,78 s | 2,34 s / 3,82 s |
| Chi phí live | 0,03579 USD | 0,03461 USD |

- Runner chạy 112 ca, mỗi ca ba lần. Có hai ca dùng ID `flight-03`, nên báo cáo độ ổn định gộp về 111 ID.
- Ba lượt trượt trong log chain v6 xuất hiện ở `reel-6.1`, `stay-memory` và `vung-tau-0A2`. Hai lượt đầu giữ được loại thẻ thời tiết nhưng assertion vẫn trượt. Lượt Vũng Tàu gặp `ReadTimeout`. Runner kết thúc sớm phần còn lại của lần chạy chuỗi khi lượt đó không có phản hồi, nên mẫu số v5f và v6 khác nhau.
- `search-10` mong đợi `search` cho “lich trinh hoi an 3 ngay”. V6 chọn `plan_trip` ở hai trong ba lần. Core local có điểm tham quan cho Đà Nẵng và trả danh sách rỗng cho Hội An từ `GET /api/places`. Độ chính xác phân loại và cách trả lời khi thiếu điểm được kiểm riêng.

## Kiểm tra trên Expo Web bằng Playwright

Trình duyệt Edge chạy headless trên Expo Web local. Hai bản AI dùng cùng Core local; mỗi bản dùng hạn mức và Redis DB riêng cho đợt kiểm thử.

| Ca | Kết quả quan sát |
|---|---|
| “Tôi muốn đi chơi Đà Nẵng, lên cho tôi lịch trình” trên v5 | HTTP 200. Hiện bài có sẵn và thẻ khách sạn. Lịch trình mới có 0 ngày trong trạng thái hội thoại. |
| Cùng câu trên v6 | HTTP 200. Hiện thẻ “Đà Nẵng 2 ngày” có nguồn OpenStreetMap. Hai ngày là mặc định vì chưa nêu thời lượng. |
| Câu đối chứng Đà Nẵng 3 ngày 2 đêm trên v5 | Lượt thử này báo “Tripi chưa kiểm được lộ trình lúc này”, với `degraded: ["plan"]`. |
| “lich trinh hoi an 3 ngay” và “Lên cho tôi lịch trình Hội An 3 ngày” trên v6 | Cả hai lượt HTTP 200, `no_result`. Tripi nói thiếu điểm tham quan có tọa độ và hiện gợi ý “Reel Hội An”. Thẻ lịch trình rỗng, trạng thái chuyến đi có 0 ngày. |

## Kiểm tra tự động

- `uv run --locked ruff check .`, `uv run --locked ruff format --check .` và `uv run --locked pyright` đều đạt.
- `uv run --locked pytest -q` có 751 ca đạt và 7 ca bỏ qua.
- `uv run --locked python -m evals.assistant.run` có 112/112 ca đạt về loại phản hồi, thẻ và lời gọi Core.
- `uv run --locked python evals/run_evals.py` chạy bộ tóm tắt với LLM giả, khớp 4/15 nhãn trạng thái. Đây là phép đo của chức năng tóm tắt.

## Cách kiểm lại

1. Chạy `uv run --locked python -m evals.assistant.run --mode live --runs 3` và `uv run --locked python -m evals.assistant.run --mode chain --runs 3` với cấu hình LLM của môi trường kiểm thử.
2. Mở Expo Web, bắt đầu cuộc chat mới và gửi “Tôi muốn đi chơi Đà Nẵng, lên cho tôi lịch trình”. Kiểm tra thẻ lịch trình theo ngày và nguồn OpenStreetMap.
3. Trong cuộc chat có Reel đang nhớ, gửi “reel đó đi mấy ngày?”. Kiểm tra câu trả lời và thẻ trỏ về đúng Reel.

Thay đổi nằm trong Controller, prompt và test của `tripflix-ai`. Phần xác nhận staging thực hiện sau khi merge và cập nhật image.
