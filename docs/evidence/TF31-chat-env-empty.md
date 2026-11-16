# TF31 — Bỏ qua biến chat để trống

- Task TF31 · Nhánh `bao/TF31-chat-env-empty` · Người làm Bảo (dùng AI) · 2026-11-16

## Đã làm

- Bật `env_ignore_empty=True` trong `ChatSettings` để ba biến `CHAT_CONTROLLER_PRICE_*` để trống như trong `.env.example` được coi là chưa đặt. Biến có giá trị số vẫn được đọc bình thường.
- Thêm kiểm tra hồi quy cho ba giá để trống và `CHAT_MAX_INFLIGHT` để trống.

## Đối chiếu phản hồi deploy

| Tiêu chí | Kết quả | Bằng chứng |
|---|---|---|
| Biến giá trống được đọc mà không phát sinh lỗi `float_parsing` | Đạt | `test_empty_chat_lines_mean_not_set` và kiểm tra bằng file `.env` mẫu |
| Giá triển khai vẫn đọc được | Đạt | Thử `0.05 / 0.005 / 0.4` theo compose của BE #207 |
| p95 của `/moderate` dưới timeout Core 3 giây khi chat đồng thời | Chờ đo staging | Core khởi tạo `AiModerationClient` với timeout mặc định `3000 ms` mỗi request |

## Kết quả kiểm tra

- `uv run ruff check .` và `uv run ruff format --check .` pass.
- `uv run pyright` pass, 0 lỗi.
- `uv run pytest` có 661 test pass và 6 test skip.
- Xuất lại OpenAPI và kiểm tra diff trong `contracts/` pass.
- Kiểm tra cục bộ với file `.env` mẫu cho cả giá trống và giá đã điền pass.

## Cách kiểm lại

1. Chạy `uv run pytest tests/test_config.py -k empty_chat_lines`.
2. Đọc `ChatSettings` với ba biến giá để trống rồi thử lại với giá số trong compose. Kỳ vọng giá trống là `None`, giá số được parse theo giá trị nhập.

## Ảnh / video

Thay đổi cấu hình API.

## Ảnh hưởng tới phần của người khác

Anh Phong yêu cầu sửa `ChatSettings` để phục vụ deploy Tripi. Các giá trị mặc định rollout nằm ở [BE #207](https://github.com/Sukemcute/tripflix-be/pull/207).
