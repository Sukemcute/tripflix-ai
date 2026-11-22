# TF31 — Tripi gợi ý khách sạn, chuyến bay trong lộ trình và hiện nút "Đặt theo lộ trình"

- Notion: TF31 · Nhánh: `bao/TF31-nut-dat-cho` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-18

## Đã làm
- **Luồng (demo Đà Nẵng, bay từ TP.HCM, có dữ liệu thật ở core local):**
  1. Lên lộ trình: kèm tối đa 3 chỗ ở Tripflix còn phòng đúng ngày (tìm song song với lộ trình, quá 3 giây hoặc lỗi thì vẫn trả lộ trình). Mỗi chỗ có nút "Chọn". Tripi hỏi "Bạn bay từ đâu tới Đà Nẵng?" kèm chip "Bay từ TP.HCM", "Bay từ Hà Nội".
  2. Nơi xuất phát: các chuyến còn chỗ, mỗi chuyến có nút "Chọn chuyến này". Phân biệt "chưa có tuyến" với "hết chỗ", hết chỗ thì nêu tối đa 3 ngày gần đó (±3 ngày) còn chỗ. Chưa có ngày thì hỏi ngày bay; câu trả lời ngắn ("ngày 20/11") được nối vào đúng câu hỏi đó.
  3. Chọn chuyến bay hoặc chỗ ở: Tripi hỏi "Bạn muốn đổi chuyến bay hay chỗ ở không, hay chốt luôn?" kèm chip "Chốt và đặt", "Đổi chỗ ở", "Đổi chuyến bay".
  4. "Chốt": kiểm lại với core là phòng còn bán đúng ngày và đúng chuyến, hạng vé còn chỗ, rồi trả thẻ "Chốt chuyến" với **một nút "Đặt theo lộ trình"** → `/trip-builder` (trang Tự lên lộ trình của Thắng, giữ chỗ trong một đơn). Phần nào hết chỗ thì không đưa vào và mời chọn lại.
- **Hợp đồng (chỉ thêm):**
  - `Card.actions` gồm `select` (ref) và `book` (`path` chỉ nhận `/trip-builder`, `params`). Nút do code tạo, LLM không tạo được đường dẫn.
  - `params` không có giá, mã phòng hay mã hạng vé: trang đặt luôn lấy giá mới từ core.
  - `DraftTransport` thêm thông tin chuyến đã chọn; `TripContext.pendingFlights`; `Awaiting` thêm `change_transport`. Bản nháp cũ vẫn đọc được.
- **Controller v9** (v8 giữ nguyên): thêm `confirm_booking`, chọn chuyến bay theo số thứ tự. Phần dễ sai không để LLM quyết, mà code quyết:
  - Câu chốt khi đã có thứ để đặt → `confirm_booking`; chưa có gì để đặt → `ack` ("mình chốt vậy" sau danh sách đồ mang theo vẫn là `ack`).
  - Câu nêu nơi, ngày, số người, vé, phòng khi chưa chọn gì → `find_flight` hoặc `find_stay`, không phải `confirm_booking`.
  - "Chọn khách sạn đầu tiên" khi đang có cả hai danh sách → chọn theo chữ trong câu, không mặc định chuyến bay.
  - Câu trả lời ngày bay ("ngày 20/11") luôn nối vào câu Tripi vừa hỏi: code tự đọc ngày từ tin nhắn nếu model không điền, và nhận cả khi model trả `plan_trip` (trước đó bị đổi thành `search`).
- **Sân bay theo tuyến:** sau sáp nhập tỉnh, "Sài Gòn" khớp cả SGN và Côn Đảo (VCS). Tripi tra `/api/flights/routes` và chỉ giữ sân bay có tuyến tới nơi đến, không hỏi lại thừa.
- Tên chuyến không còn lặp giờ ("… 11:00 · 11:00").
- Eval: `cases.v6.jsonl` (10 ca, nhãn `dat-cho`), `chains.v4.jsonl` (`dn-dat-cho`, `dn-ngay-bay`). Test bộ ca kiểm thêm mỗi ca phải có `tags` (thiếu `tags` từng làm eval live dừng ở cuối).

## Đối chiếu "Xong khi"
| Tiêu chí (yêu cầu của Bảo, 18/11) | Đạt | Bằng chứng |
|---|---|---|
| Lộ trình chi tiết lồng khách sạn, chuyến bay của Tripflix | Đạt | Chạy thật với core local; `test_plan_then_select_flight_and_stay_then_confirm` |
| Hỏi lại bay từ đâu, ngày nào; kiểm còn vé, ngày giờ | Đạt | chain `dn-ngay-bay`; `test_no_route_is_distinct_from_full_flights_with_bounded_nearby_dates` |
| Hỏi có đổi chuyến bay, chỗ ở không | Đạt | `_review`, chip "Đổi chỗ ở", "Đổi chuyến bay" |
| Đồng ý thì hiện nút đặt trỏ sang trang đặt (combo của Thắng) | Đạt | `test_confirm_rechecks_both_parts_and_returns_exact_booking_routes`; chain `dn-dat-cho` 3/3 |
| Không làm lùi ca cũ | Đạt (trong dao động) | Bảng dưới |

## Kết quả kiểm tra
- ruff, ruff format, pyright sạch. `pytest --ignore tests/test_chat.py`: **988 passed, 6 skipped**; `tests/test_chat.py` bản đã commit 17/17.
- Eval ci: trước 123/123, sau **133/133**.
- Eval live (DeepSeek thật, mỗi ca 3 lần):

| Chỉ số | v8 | v9 |
|---|---|---|
| Live, các ca cũ v1–v5 | 353/369 = 95,7% | 348/369 = 94,3% |
| Live, bộ đặt chỗ v6 | — | **30/30**, pass^3 10/10 |
| Chain | 126/132 = 95,5% | 135/143 = 94,4% (lần cuối; 5/8 lượt trượt là ReadTimeout, 3 lượt đã trượt từ v6/v7; `dn-ngay-bay` 3/3) |
| Độ trễ p50 | 2,70 s | 1,99 s |
| Chi phí mỗi lượt gọi | 0,000118 USD | 0,000119 USD |

- Các ca cũ lệch thêm 5 lượt, phần lớn do ReadTimeout và dao động đã thấy ở v8 (`search-03`, `search-05`, `pack-02`, `report-B16`); không có ca nào đổi hẳn ý định.
- Chạy thật (Controller và Responder thật, core local có dữ liệu): lộ trình Đà Nẵng 3 ngày kèm 3 chỗ ở Tripflix → "mình bay từ Sài Gòn" → 4 chuyến SGN → DAD → chọn chuyến, chọn chỗ ở → "chốt và đặt" → một nút "Đặt theo lộ trình" với `destination`, `adults`, `startDate`, `days`, `hotelId`, `checkIn`, `nights`, `flightFrom=SGN`, `flightTo=DAD`, `flightDate`.

## Cách kiểm lại
1. `uv run pytest tests/assistant/test_booking.py -q`
2. `PYTHONIOENCODING=utf-8 uv run python -m evals.assistant.run --mode live --cases v6` và `--mode chain`
3. Trên app (core local có `/api/places`): "Lên lịch trình Đà Nẵng 3 ngày 2 đêm cuối tuần này" → "mình bay từ Sài Gòn" → bấm chọn chuyến và chỗ ở → "Chốt và đặt" → bấm "Đặt theo lộ trình".

## Ảnh / video
- Chờ Bảo chụp trên Android; web chụp trong trình duyệt.

## Ảnh hưởng tới phần của người khác
- Không đụng code của người khác trong repo này. Phần app (mobile `trip-builder` của Thắng, Tripi web của Dũng) nằm ở PR FE cùng tên.
- Giới hạn đã biết: người dùng không nói số người thì mặc định 2 người lớn; lộ trình không có ngày thì chưa gợi ý chỗ ở cho tới khi biết ngày (chip "Đổi chỗ ở").
