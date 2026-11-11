# TF44 — Tên consumer cố định cho summary worker và label worker

- Nhánh: `bao/TF44-ten-consumer-co-dinh` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-11
- **Lý do** (anh Phong, sau khi deploy staging ngày 2026-11-11): tên consumer đang là `hostname-PID`, nên mỗi lần tạo lại container, group lại có thêm một consumer chết. Group `ai-summary` trên staging đã có 4 consumer.

## Đã làm

- Thêm 2 biến tuỳ chọn `SUMMARY_WORKER_CONSUMER_NAME` và `LABEL_WORKER_CONSUMER_NAME`, theo cách video-worker đang làm (`VIDEO_WORKER_CONSUMER_NAME || hostname()`, compose server đặt `server-1`). Để trống thì giữ cách cũ (`hostname-PID`, label worker thêm `-labels`).
- `main()` của hai worker truyền tên này vào. Code bên trong worker không đổi.
- `.env.example` có thêm 2 biến, kèm ghi chú: hai replica của cùng một worker phải dùng tên khác nhau.

## Đối chiếu tiêu chí

| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Đặt biến thì cả hai worker dùng đúng tên đó | Có | `test_both_workers_take_their_consumer_name_from_settings[server-1]` |
| Để trống thì giữ `hostname-PID` như cũ | Có | `test_both_workers_take_their_consumer_name_from_settings[]`, `test_worker_consumer_names_are_empty_unless_set` |

## Kết quả kiểm tra

- `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`: ruff sạch, pyright 0 lỗi, **528 passed**, 5 skipped. Trước khi sửa: 525 passed.

## Cách kiểm lại

1. `uv run pytest tests/test_config.py tests/workers/test_label_worker.py`
2. Trên staging, sau khi đặt biến và tạo lại container: `XINFO CONSUMERS stream:core.content ai-summary` và `XINFO CONSUMERS stream:core.content ai-labels` chỉ còn consumer `server-1`, cộng các consumer cũ chưa xoá.

## Ảnh hưởng tới phần của người khác

- Chỉ sửa repo AI.
- **Anh Phong:**
  - đặt `SUMMARY_WORKER_CONSUMER_NAME=server-1` cho `ai-summary-worker` và `LABEL_WORKER_CONSUMER_NAME=server-1` cho `ai-label-worker`;
  - consumer cũ: chỉ xoá (`XGROUP DELCONSUMER`) khi `pending` đã về 0.
