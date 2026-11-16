# TF31 — Kiểm thử hồi quy Tripi trước demo

- Task TF31 · Nhánh `bao/TF31-tripi-demo-regression` · Người làm Bảo (dùng AI) · 2026-11-16

## Đã làm

- Nhận lời chào độc lập như «Hii» hoặc «Hiiii» sau checklist. Lời chào đi kèm yêu cầu vẫn được xử lý như một yêu cầu du lịch.
- Ưu tiên ngày tương đối ghi rõ trong câu hỏi thời tiết và hành lý. Giữ cách xử lý hiện có nếu câu hỏi cũng ghi ngày theo lịch.
- Sửa lỗi stream SSE bị ngắt khi Responder kiểm một thẻ lộ trình. `days` của lộ trình là số ngày, còn `days` của dự báo là danh sách.

## Kiểm thử live local

Expo Web, ai-service, Core local có seed, Controller/Responder và nguồn thời tiết thực. Kiểm thử sau sửa qua một chuỗi API có mang `trip`, `history` và `contextPostId` giữa các lượt.

| Ca | Trước sửa hoặc kỳ vọng | Sau sửa |
|---|---|---|
| Tìm Reel săn mây Đà Lạt | Mở đúng Reel từ kết quả tìm kiếm | Expo Web trả thẻ Săn mây Đà Lạt 4h sáng |
| «Reel này đi mấy ngày?» | SSE ngắt trong Verifier khi gặp `days: 3` | Trả lộ trình Đà Lạt 3 ngày |
| Checklist Đà Lạt ngày mai | Expo Web dùng số liệu 18/11 cho câu hỏi ngày 17/11 | Checklist gợi ý áo khoác, 15°C ngày 17/11 |
| «Hii» sau checklist | Expo Web nhắc lại checklist | Chào người dùng, 0 thẻ. `reelId` và ngày đi không đổi |
| «Ngày 2 trong reel này đi đâu?» | Lượt hỏi cách vài tin, vẫn trỏ về Reel đang mở | Trả đúng Săn mây Cầu Đất và Vườn hồng treo gió |
| Ý kiến của người đã đi | Reel còn xem được nhưng seed chưa có tóm tắt | Trả «Reel này chưa có tóm tắt ý kiến người xem» |
| Chuyển từ Reel Đà Lạt sang Reel VinWonders | `contextPostId` của Reel mới phải được ưu tiên | Thẻ lộ trình và `trip.reelId` chuyển sang Reel Nha Trang. Lời văn vẫn thiên về khách sạn dù người dùng hỏi lộ trình |
| Dự báo trực tiếp Đà Lạt ngày mai | Dữ liệu cần đúng ngày hoặc báo chưa kiểm được | `trip.dateFrom` là 17/11. Lượt dự báo trả `fallback` với `degraded: ["weather"]`. Checklist ở lượt sau lấy được dữ liệu đúng ngày |

## Test tự động

- `uv run ruff check .`, `uv run ruff format --check .` và `uv run pyright` pass.
- `uv run pytest` có **667 pass, 6 skip**.
- `uv run python -m evals.assistant.run` có **70/70** ca đạt theo loại phản hồi, thẻ và lời gọi Core.

## Staging

AI PR #31 đã merge và [workflow publish](https://github.com/Sukemcute/tripflix-ai/actions/runs/43832123714) hoàn thành. Smoke check công khai thấy Core trả HTTP 200; `OPTIONS /ai/chat` trả 404 và một `POST` thiếu thông tin đăng nhập trả 401. Các mã đó chưa xác nhận tag image đang chạy hay việc reload Traefik.

Phép đo 10/30 lượt chat đồng thời cần thực hiện từ môi trường có quyền gọi moderation nội bộ và quan sát log, bộ nhớ, restart. Mốc đạt là p95 `/moderate` dưới 3 giây mỗi request và ai-service không restart do hết RAM.

## Ảnh và phạm vi

Ảnh tái hiện lỗi được chụp ở Expo Web trước khi sửa. Thay đổi code giới hạn trong Controller, Verifier và test của ai-service.
