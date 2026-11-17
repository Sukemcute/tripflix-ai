# TF31 — Đủ 100 kịch bản trợ lý và 50 câu tìm kiếm theo PRD

- Notion: TF31 · Nhánh: `bao/TF31-eval-du-pham-vi` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-17
- Kế hoạch: bước A4. PRD yêu cầu benchmark 50 câu tìm kiếm và 100 kịch bản trợ lý. Trước đây có 70 ca và 5 chuỗi.
- Nhánh tách từ `bao/TF31-san-bay-theo-ten` (PR #37, đã merge). Đã merge `develop` mới nhất: giữ cả chế độ `ab` (#36) và `search` của nhánh này trong `evals/assistant/run.py`.

## Đã làm
- **`evals/assistant/cases.v3.jsonl`: thêm 30 ca**, nâng tổng lên 100.
  - Các nhóm: tìm kiếm, reel, bay theo tên thành phố, khách sạn không có thật, chen lệnh, ngoài phạm vi, hỏi lại, reel đang mở, xã giao.
  - Mỗi ca ghi intent, thông tin cần đọc, loại thẻ và lời gọi core mong đợi.
- **`evals/assistant/search.v1.jsonl`: 50 câu tìm kiếm** kiểu người trẻ (không dấu, viết tắt, lóng).
  - Chế độ mới `--mode search` chạy Controller và core thật.
  - Một câu tính là đúng khi một trong 3 kết quả đầu nêu đúng nơi người dùng hỏi. Đây là cách đo chỉ số PRD "≥ 80% đúng ý ngay lần đầu".
- **Sửa lỗi eval bắt được (`fake-01`):**
  - Hỏi một khách sạn không có thật ("Hoàng Hôn Mộc Châu"), suggest của core tìm gần đúng ra khách sạn khác, rồi Tripi báo khách sạn đó còn phòng.
  - Nay nếu không khớp đúng tên, tên tìm được phải chứa đủ các chữ riêng trong tên người dùng gọi (`_has_every_word` trong `skills/trip.py`).
- `tests/assistant/test_chat_eval_cases.py`: đếm đủ số ca của mọi bộ.

## Đối chiếu "Xong khi"
| Tiêu chí (kế hoạch A4) | Đạt | Bằng chứng |
|---|---|---|
| 100 kịch bản trợ lý | Đạt | `cases.v1`–`v3` = 100 ca; eval ci **100/100** |
| 50 câu tìm kiếm | Đạt (bộ câu) | `search.v1.jsonl` 50 câu, `--mode search` |
| Chạy ci + live + chain, ghi trước/sau | Đạt một phần | ci và live xong. **Search chưa chạy** vì cần core có dữ liệu, mà Docker trên máy tắt |
| Khách sạn không có thật không bị nhận nhầm | Đạt | Ca ci `fake-01`: không được gọi `/api/hotels/`, phải trả `no_result`; pytest chạy ca này qua `test_every_labelled_case_matches_in_ci_mode` |

## Kết quả kiểm tra
- ruff, pyright sạch; `pytest`: **677 passed, 6 skipped** + 17/17 `tests/test_chat.py` bản đã commit (sau khi merge develop có #36, #37).
- **Eval live 30 ca mới** (× 3 lần, Controller v4 + guard): **95,6%** intent + thông tin, **pass^3 93,3%**, p50 2,16 giây, chi phí 0,0087 USD.
- Eval live trên toàn bộ ca, v5 cuối: xem evidence `TF31-tro-ly-giai-doan-b.md`.

## Cách kiểm lại
1. `PYTHONIOENCODING=utf-8 uv run python -m evals.assistant.run` (ci) và `--mode live --cases v3`.
2. Chạy core có seed (`pnpm stack:up` ở tripflix-be), rồi `--mode search`: in tỉ lệ câu có kết quả đúng trong top 3.

## Ảnh / video
- Không đổi giao diện.

## Ảnh hưởng tới phần của người khác
- Không.
