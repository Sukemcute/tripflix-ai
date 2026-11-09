# TF14 — Gửi cảnh báo an toàn dạng "nghe nói" cho core chờ kiểm duyệt

- Notion: (Bảo bổ sung link TF14) · Nhánh: `bao/TF14-canh-bao-cho-duyet` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-09

## Đã làm

- **Vấn đề:** cảnh báo an toàn dạng "nghe nói" (người viết không tự trải qua) trước đây bị bỏ, vì chưa có nơi nhận.
- **Đã chốt với chị Trang** (content/moderation, 2026-11-08):
  - ai-service gửi các cảnh báo này trong `safety.pendingWarnings` của `PUT ai-summary`;
  - core lưu lại, GET công khai lọc bỏ;
  - admin duyệt xong thì chuyển sang `warnings`.
  - Không dùng sự kiện, vì ai-service không có outbox.
- **Thay đổi:**
  - `SummarySafety` thêm `pending_warnings`. JSON gửi đi là `pendingWarnings: [{categories, commentIds}]`, cùng dạng với `warnings`.
  - `pipeline._rule_safety` (trước đây là `_public_safety`): người tự kể → `warnings` (công khai như cũ); nghe kể → `pendingWarnings`.

## Đối chiếu "Xong khi"

Chép từ thỏa thuận với chị Trang (chưa đối chiếu bản Notion).

| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Cảnh báo nghe kể được gửi cho core thay vì bị bỏ | Có | `test_classifier_decides_who_went_for_safety_warnings`: câu nghe kể nằm trong `pendingWarnings`, JSON dùng key camelCase |
| Cảnh báo tự kể vẫn công khai như cũ | Có | cùng test: câu tự kể nằm trong `warnings` |
| Cảnh báo chưa duyệt không lộ ra người dùng | Có, nhờ core | tripflix-be#91 (đã merge): GET công khai bỏ `pendingWarnings`, chỉ moderator/superadmin thấy |

## Kết quả kiểm tra

- `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`: ruff sạch, pyright 0 lỗi, 390 passed, 5 skipped. Đã chạy lại sau khi gộp `origin/develop`.
- Không đổi prompt hay LLM nên không chạy lại eval live: input hash và nội dung gửi LLM không đổi.

## Cách kiểm lại

1. Chạy lệnh kiểm tra của repo như trên.
2. Với stack có core từ be#91 trở lên: đăng một bình luận "nghe nói … bị ngộ độc", chờ worker tóm tắt.
   - GET `/api/v1/posts/:id/ai-summary` không token: `safety` chỉ có `warnings`.
   - GET bằng tài khoản moderator: thấy cả `pendingWarnings`.

## Ảnh / video

- Không đổi giao diện.

## Ảnh hưởng tới phần của người khác

- **Thêm trường** `safety.pendingWarnings` vào body `PUT ai-summary`: tương thích ngược, vì core nhận `safety` là object tự do.
- **Phụ thuộc:** tripflix-be#91 (chị Trang, đã merge) lọc trường này ở GET công khai. Đã chốt với chị Trang.
- **Còn chờ:** hàng chờ duyệt và thao tác chuyển `pendingWarnings` sang `warnings` ở trang admin (chị Trang làm tiếp).
- **Không gửi:** các câu an toàn mà chỉ LLM phát hiện (`safety_hints` của validator) chưa được gửi đi. Nếu cần đưa vào hàng chờ thì làm sau.
