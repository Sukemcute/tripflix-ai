# TF31 — Worker tóm tắt và Tripi đọc 204 của ai-summary

- Notion: TF31 · Nhánh: `bao/TF31-tom-tat-204` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-18

## Đã làm
- Core sắp đổi `GET /api/v1/posts/:id/ai-summary` từ 404 sang 204 (body rỗng) khi bài chưa có tóm tắt. Hai chỗ bên AI chỉ kiểm 404 rồi gọi `response.json()`, nên sẽ lỗi khi nhận 204:
  - `CoreApiClient.fetch_summary`: worker tóm tắt lỗi ở mọi bài chưa có tóm tắt.
  - `skills/trip.post_reviews`: Tripi lỗi khi hỏi "người xem nói gì" ở reel chưa có tóm tắt.
- Cả hai giờ đọc 204 và 404 đều là "chưa có tóm tắt". Vẫn chạy được với core bản cũ.

## Đối chiếu "Xong khi"
| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Worker nhận 204 không lỗi | Đạt | `tests/clients/test_core_api.py::test_empty_204_summary_is_none` |
| Tripi nhận 204 trả "chưa có tóm tắt" | Đạt | `test_reel_reviews_read_the_post_before_the_summary` (ca 204) |
| Core bản cũ (404) vẫn đúng | Đạt | Ca 404 cũ trong cùng hai test |

## Kết quả kiểm tra
- ruff, ruff format, pyright sạch.
- `pytest --ignore tests/test_chat.py`: 827 passed, 6 skipped; `tests/test_chat.py` bản đã commit 17/17.
- Không đổi prompt hay agent nên không chạy eval.

## Cách kiểm lại
1. `uv run pytest tests/clients/test_core_api.py tests/assistant/test_chat_two_agents.py -q`

## Ảnh / video
- Không đổi giao diện.

## Ảnh hưởng tới phần của người khác
- Không. Merge PR này **trước** PR core trả 204.
