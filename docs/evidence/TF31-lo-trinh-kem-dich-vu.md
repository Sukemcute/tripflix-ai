# TF31 — Lộ trình Tripi lồng chuyến bay, khách sạn và nút "Đặt theo lộ trình"

- Notion: TF31 · Nhánh: `bao/TF31-lo-trinh-kem-dich-vu` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-18

## Đã làm
- **Lỗi Bảo gặp** ("Tôi muốn đi Đà Lạt 3 ngày 2 đêm, lên lịch trình cho tôi"):
  - Lịch trình được xếp trước khi biết đi từ đâu, ngày nào, nên ngày 1 vẫn đi Thác Prenn buổi sáng dù chuyến SGN → DLI tới lúc 14:30.
  - Chuyến bay hiện thành thẻ riêng, không có khách sạn, không có nút đặt.
- **Luồng mới:**
  1. Thiếu nơi đi hoặc ngày thì hỏi trước: "Bạn đi từ đâu và đi ngày nào để Tripi xếp lịch kèm vé máy bay và phòng nha?" (chip "Từ TP.HCM", "Từ Hà Nội"). Một câu trả lời điền được cả hai ("mình đi từ Sài Gòn, ngày 21/11"); thiếu phần nào thì chỉ hỏi phần đó. "Cứ lên trước", "chưa biết" thì xếp lịch thường như trước.
  2. Đủ nơi đi và ngày thì tìm song song (`asyncio.gather`, mỗi phần có thời gian chờ riêng, lỗi thì ghi `degraded` và bỏ phần đó): điểm ăn chơi, thời tiết, chuyến đi ngày đầu (chuyến sớm nhất còn chỗ), chuyến về ngày cuối (chuyến muộn nhất), khách sạn Tripflix còn phòng (lấy chỗ đầu, giữ tối đa 3 chỗ cho "Đổi chỗ ở").
  3. **Một thẻ lộ trình** lồng dịch vụ: ✈ bay đi → nhận phòng → các điểm (xuất phát từ khách sạn) → trả phòng → ✈ bay về. Tới từ 12:00 thì bỏ buổi sáng, trưa ngày đầu; từ 17:00 chỉ giữ buổi tối. Ngày cuối chỉ giữ buổi kết thúc trước giờ bay ít nhất 2 giờ [HIỆU CHỈNH].
  4. Dòng dịch vụ có `CardLine.service` (`flight`/`stay`, chỉ thêm vào hợp đồng) để app làm nổi bật.
  5. Có cả khách sạn Tripflix và chuyến đi thì thẻ có nút **"Đặt theo lộ trình"** → `/trip-builder`, cùng bộ tham số với bước chốt, thêm `returnFrom`, `returnTo`, `returnDate`. Không có giá hay mã phòng, mã vé.
  6. "Đổi chuyến bay", "Đổi chỗ ở" → chọn → lộ trình và nút xếp lại. "Chốt" kiểm lại cả chuyến về.
  7. Nơi không có tuyến bay: dòng xe khách tham khảo (không phải dịch vụ đặt được) và khách sạn, không có nút combo.
- Câu trả lời gồm cả nơi đi và ngày dài hơn 6 từ ("mình đi từ Sài Gòn, ngày 21/11" là 7 từ) từng bị bỏ qua, nên Tripi hỏi lại. Đã nới riêng cho trường hợp đang chờ nơi đi hoặc ngày, tối đa 10 từ [HIỆU CHỈNH].
- Giữ prompt Controller v9; phần trả lời ngắn xử lý bằng code.
- Eval: `cases.v7.jsonl` (4 ca), `chains.v5.jsonl` (chuỗi Đà Lạt). Các ca và chuỗi cũ có lượt "lên lịch" khi chưa có nơi đi hoặc ngày được đổi kết quả mong đợi thành "hỏi trước". Riêng chuỗi chép từ báo cáo Vũng Tàu **giữ nguyên câu gốc của người dùng**, chỉ chèn thêm lượt trả lời "từ TP.HCM, 21/11".

## Đối chiếu "Xong khi"
| Tiêu chí (yêu cầu của Bảo, 18/11) | Đạt | Bằng chứng |
|---|---|---|
| Hỏi đi từ đâu (và ngày nào) rồi mới soạn lịch | Đạt | `test_plan_asks_for_missing_services_inputs_before_any_core_call`; `test_a_longer_origin_and_day_reply_finishes_the_plan` |
| Lịch trình lồng dịch vụ: "Ngày 1 bay từ … tới …, nhận phòng …" | Đạt | `test_city_and_date_reply_builds_woven_services`; chạy thật Đà Lạt bên dưới |
| Thẻ máy bay và phòng được làm nổi bật | Đạt (AI gửi `service`) | Phần hiển thị ở PR FE |
| Có hai dịch vụ thì hiện nút "Đặt theo lộ trình" → trang Đặt của Thắng | Đạt | `test_city_and_date_reply_builds_woven_services`; chain `chains.v5` |
| Có chuyến về ngày cuối | Đạt | params có `returnFrom`, `returnTo`, `returnDate`; `test_confirm_rechecks_the_return_fare` |
| Vé lỗi hoặc không có tuyến vẫn có lịch, không có nút combo | Đạt | `test_flight_failure_keeps_stay_and_itinerary_without_button`, `test_no_airport_weaves_reference_bus_and_stay_without_button` |

## Kết quả kiểm tra
- ruff, ruff format, pyright sạch. `pytest --ignore tests/test_chat.py`: **1020 passed, 6 skipped**.
- Eval ci: trước 133/133, sau **137/137**.
- Eval live và chain (Controller `gpt-5-nano`, Responder DeepSeek, mỗi ca 3 lần):

| Chỉ số | Trước (v9, PR #46) | Sau |
|---|---|---|
| Live | 363/399 = 91,0% | 395/411 = 96,1% (thêm 4 ca v7) |
| pass^3 | 112/132 = 84,8% | 125/136 = 91,9% |
| Chain | 135/143 = 94,4% | 172/180 = 95,6% |
| Độ trễ p50 | 1,99 s | 2,29 s |
| Chi phí mỗi lượt gọi | 0,000119 USD | 0,000121 USD |

- Chuỗi Đà Lạt (`chains.v5`) và các chuỗi Vũng Tàu đã chèn lượt trả lời đều đúng. Lượt chain còn trượt: `reel-6.1`, `small-talk` (đã trượt từ các bản trước), 2 ReadTimeout, 1 lần "Thôi chuyển sang 2 ngày 1 đêm đi" lệch số đêm.
- Lần chạy đầu bắt được 3 lỗi và đã sửa: ngày trả phòng bị model chép trùng ngày nhận ("từ TP.HCM, 21/11" bị hỏi lại ngày trả phòng); tên thành phố lúc "Sài Gòn", lúc "TP.HCM" (nay code đổi về một tên chuẩn); kết quả mong đợi của chuỗi Đà Lạt sai với dữ liệu core giả (chỉ có một khách sạn Tripflix ở Đà Lạt, chọn chỗ ngoài Tripflix thì đúng là không có nút combo).
- Chạy thật (Controller và Responder thật, core local có dữ liệu): "Tôi muốn đi Đà Lạt 3 ngày 2 đêm, lên lịch trình cho tôi" → Tripi hỏi nơi đi và ngày → "mình đi từ Sài Gòn, ngày 21/11" → một thẻ lộ trình:
  - ★ Ngày 1 · ✈ Bay SGN → DLI 14:30–16:10 · ★ Nhận phòng D. House Đà Lạt Homestay (21/11) · chiều Chùa Tàu, Nhà Pháp gần tu viện · tối Quán cơm Linh;
  - Ngày 2 · Thung Lũng Tình Yêu, công viên Nguyễn Du, Bảo tàng Lâm Đồng, Cà Phê Xóm Ruộng;
  - Ngày 3 · sáng Ga Đà Lạt · ★ Trả phòng (23/11) · ★ ✈ Bay DLI → SGN 14:00–15:40;
  - nút "Đặt theo lộ trình" với `hotelId`, `checkIn=2026-11-21`, `nights=2`, `flightFrom=SGN`, `flightTo=DLI`, `returnFrom=DLI`, `returnTo=SGN`, `returnDate=2026-11-23`.

## Cách kiểm lại
1. `uv run pytest tests/assistant/test_plan_services.py -q`
2. `PYTHONIOENCODING=utf-8 uv run python -m evals.assistant.run --mode chain`
3. Trên app (core local có `/api/places`): chuỗi Đà Lạt như trên, bấm "Đặt theo lộ trình".

## Ảnh / video
- Chờ Bảo chụp trên Android và web.

## Ảnh hưởng tới phần của người khác
- Không trong repo này. Phần hiển thị (mobile của chị Trang, trang `trip-builder` của Thắng, Tripi web của Dũng) ở PR FE.
- Giới hạn đã biết: ngày 1 tới lúc 16:10 vẫn còn 2 điểm buổi chiều (hơi sát giờ); mặc định 2 người lớn khi không nói số người.
