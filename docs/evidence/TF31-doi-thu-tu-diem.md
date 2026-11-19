# TF31 — Đổi thứ tự điểm trong lộ trình

- Notion: chưa cung cấp · Nhánh: `bao/TF31-doi-thu-tu-diem` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-19

## Đã làm
- Thêm `move_stop`: trước/sau mốc, đổi ngày hoặc cuối buổi; kiểm khung giờ bay trước khi sửa. Chỉ sửa điểm trong `trip.days`, render lại khoảng cách; dòng dịch vụ giữ nguyên.
- Undo dùng bản chụp `DraftOp.stop` (đã có `slot`), `day` và `position` để trả đúng ngày, vị trí, buổi; không cần thêm trường slot trùng lặp. Draft cũ vẫn đọc được.
- Controller v10 bổ sung intent/slots và ví dụ; v9 giữ nguyên. Guard ưu tiên chuyển điểm khi có lộ trình và các trường đích tương ứng; ngày thứ N không đổi ngày đi/điểm đến.
- Cờ `Answer.edit_applied` do Turn so sánh dữ liệu trước/sau, không do LLM quyết định. Responder nhận cờ; Verifier bỏ câu khẳng định đã sửa nếu không có sửa thành công. Cờ nội bộ không thêm vào SSE.
- Sau review, thu hẹp `EDIT_CLAIM`: không bắt “xếp”, “bỏ”, “thêm” trần kèm “rồi”. Thêm 5 câu hồi quy đúng nguyên văn, câu đã chuyển sau sửa thật và test lượt lên lịch đầu qua Turn → Responder/Verifier.
- Sinh lại OpenAPI bằng `uv run python -m scripts.export_openapi`; thay đổi contract chỉ thêm `move_stop` trong enum DraftOp.
- Thêm 6 ca CI v8 (có tags, kiểm cả thứ tự điểm) và chain v6 giữ nguyên hai câu thật của Bảo. Runner hỗ trợ dữ liệu core giả và trip ban đầu cho chain.

## Đối chiếu "Xong khi"
| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Chuyển trước/sau, sang ngày/buổi, undo, khoảng cách và giữ dòng dịch vụ | Có | `tests/assistant/test_move_stop.py` |
| Khung giờ bay, điểm/mốc không có, yêu cầu không đổi dữ liệu | Có | Test clarify và đối chiếu nguyên draft |
| Không nói đã sửa khi chưa sửa | Có | Câu thật được kiểm qua Verifier và Responder với cả hai giá trị cờ |
| Contract tương thích và prompt có version | Có | Draft cũ parse được; OpenAPI sinh lại; v9 không đổi |
| Eval CI và chain tái hiện | Có / chờ chạy | `cases.v8.jsonl`, `chains.v6.jsonl`; không chạy live/chain |

## Kết quả kiểm tra
- Trước thay đổi: `PYTHONIOENCODING=utf-8 uv run python -m evals.assistant.run --mode ci`: 137/137 pass, 0 fail.
- `uv run python -m scripts.export_openapi`: thành công.
- `uv run ruff check .`: pass, 0 lỗi.
- `uv run ruff format --check .`: 227 file đã đúng format, 0 fail.
- `uv run pyright`: 0 errors, 0 warnings.
- `uv run pytest --ignore tests/test_chat.py -q`: 1.102 passed, 6 skipped, 0 failed.
- `PYTHONIOENCODING=utf-8 uv run python -m evals.assistant.run --mode ci`: 143/143 pass, 0 fail.
- Live / chain: chờ chạy, theo yêu cầu không chạy trong task này.

## Cách kiểm lại
1. Chạy các lệnh kiểm tra trên trong repo AI; PowerShell đặt `$env:PYTHONIOENCODING='utf-8'` trước eval.
2. Xem `tests/assistant/test_move_stop.py` cho thứ tự, khung giờ, undo, dịch vụ và cờ Verifier.
3. Chain `dn-doi-thu-tu-diem` giữ nguyên `lên lịch Đà Nẵng 2 ngày` và `Tôi muốn đi cầu rồng trước rồi mới sang bảo tàng nghệ thuật điêu khắc, xếp lại`. Khai báo nơi đi/ngày đã biết để lượt đầu tạo itinerary theo chính sách hiện tại; core giả có các điểm Đà Nẵng. Claude chạy chain sau.

## Ảnh / video
- Không đổi UI; chưa có ảnh chạy thật.

## Ảnh hưởng tới phần của người khác
- Phần AI của Bảo; không sửa repo FE/BE, không sửa `tests/test_chat.py`, không thêm thư viện. Không đổi nhánh, commit, push hoặc stash.
