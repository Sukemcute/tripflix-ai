# TF68 — Sửa CI/CD: chặn image khi CI đỏ, thêm cache và giới hạn thời gian

- Jira: [SCRUM-72](https://tripflix.atlassian.net/browse/SCRUM-72) · Nhánh: `trang/TF68-sua-ci-cd` · Người làm: Lê Thị Thùy Trang (dùng AI: có) · Ngày: 2026-11-07

## Đã làm
- `publish.yml`: thêm job `check` gọi `ci.yml`; job build image `needs: check`. Trước đây CI đỏ vẫn đẩy image `ai-service` lên GHCR.
- `ci.yml`: bỏ trigger `push`, thêm `workflow_call`. Push lên develop/main chỉ chạy CI một lần.
- `ci.yml`: `concurrency` huỷ lần chạy cũ của cùng PR; nhánh develop/main không huỷ.
- `timeout-minutes: 20` cho CI và build image.
- Build image: thêm `docker/setup-buildx-action` và cache `type=gha`.

## Kết quả kiểm tra
- Cả 3 repo: mọi file trong `.github/workflows/` parse YAML hợp lệ (`yaml.safe_load`).
- Chưa chạy được `actionlint` trên máy (Docker Desktop tắt, không tải được binary). Workflow chỉ chạy thật trên GitHub: kết quả xem ở tab Actions của PR này và của lần merge vào `develop`.

## Cách kiểm lại
1. Mở PR: workflow `ci` chạy một lần. Push thêm commit lên PR: lần chạy cũ bị huỷ (concurrency).
2. Sau khi merge vào `develop`: workflow `publish` có job `check / check` chạy trước, job build image chỉ chạy khi `check` xanh.
3. Lần publish thứ hai trở đi: log `build-push-action` có dòng `importing cache manifest from gha:...`, các bước cài dependency báo `CACHED`.

## Ảnh hưởng tới phần của người khác
- Có: `.github/` (chủ: Bảo). Không đổi lệnh kiểm tra. Cần Bảo duyệt.
