# TF14 — Tải model phân loại bình luận khi build image, loại dữ liệu nghiên cứu khỏi image

- Jira: [SCRUM-18](https://tripflix.atlassian.net/browse/SCRUM-18) · Nhánh: `trang/TF14-tai-model-khi-build` · Người làm: Trang (dùng AI: có) · Ngày: 2026-11-08

## Đã làm
- `publish.yml`: trước bước build, cài uv, `uv sync --no-dev`, chạy `scripts.fetch_classifier --tag comment-classifier-v1` (GH_TOKEN = GITHUB_TOKEN, quyền `contents: read`). Script tự kiểm sha256; tải lỗi thì build fail, tránh image không có model mà worker lặng lẽ tụt về luật.
- `.dockerignore`: thêm `data/`, `docs/research/` vì image dev `COPY . .` (dữ liệu nghiên cứu vài trăm MB, có dữ liệu YouTube không được phát tán).

## Đối chiếu "Xong khi"
| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Image prod có model | Chờ lần publish đầu sau merge | log job `image` trên develop |
| Tải lỗi thì build fail | Có | bước dùng `subprocess.run(check=True)` và `verify_bundle` |
| Image dev không chứa `data/`, `docs/research/` | Có | `.dockerignore` |

## Kết quả kiểm tra
- YAML hợp lệ; release `comment-classifier-v1` có đủ 4 file (`gh release view`); Bảo đã tải thử, sha256 khớp.
- Workflow chỉ chạy khi push lên develop/main nên kiểm thật ở lần publish đầu sau merge.

## Cách kiểm lại
1. Sau merge, mở run `publish` trên develop: bước "Tải model phân loại bình luận" in `comment-classifier-v1 from run ...`.
2. `docker run --rm ghcr.io/sukemcute/tripflix-ai/ai-service:develop ls app/models/comment_classifier` thấy 4 file.

## Ảnh hưởng tới phần của người khác
- Model mới thì tạo release tag mới rồi sửa `CLASSIFIER_TAG` trong `publish.yml`.
