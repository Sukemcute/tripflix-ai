# BE-09 đợt 2 — AI frame proof local

Endpoint production `/moderate/parts` và model `omni-moderation-latest` của đợt 1 được tái sử dụng cho từng frame; không đổi service production.

`tools/serve_frame_proof.py` chỉ chạy trong nghiệm thu local khi thiếu AWS credentials. Nó nhận URL CDN fixture có mẫu QA cố định, đọc JPEG thật do FFmpeg tạo, gửi bytes qua OpenAI client thật; JWT, route validation và verdict dùng code production. URL khác không bị thay nội dung. Tool không nằm trong luồng triển khai production và không chứa API key.

Ruff check/format, pyright và pytest qua: 1.234 passed, 7 skipped. Trong lần thử browser, caption, poster và ba frame đều có verdict riêng từ model thật. Fixture xanh–đỏ–xanh chỉ chứng minh coverage/timestamp; không dùng nó để khẳng định model sẽ gắn cờ cảnh màu đỏ.
