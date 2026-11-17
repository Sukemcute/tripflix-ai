# TF31 — Tripi Giai đoạn B: xếp cả chuyến đi, chọn chỗ ở, cách đi, sửa kế hoạch

- Notion: TF31 · Nhánh: `bao/TF31-tro-ly-day-du` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-17
- Kế hoạch: bước B4–B8 (`tripi-agent-v3-de-xuat.md`, Giai đoạn B; thiết kế theo `docs/research/reports/DeepResearch_Tripi_tro_ly_du_lich_day_du.md` §3–§8).
- **Phụ thuộc:** PR #38 (A4, nhánh này đã merge vào). Core có `GET /api/places` từ BE #227 (đã merge). App dùng ở PR FE #175 (merge sau PR này).

## Đã làm

### B4. Cổng dữ liệu (commit `e44bad3`)
- `app/clients/places.py`: `PlacesClient` (Protocol), `CorePlaces` gọi `GET /api/places` của core. Test dùng bản giả.
- `app/services/assistant/route.py`: quãng đường = đường chim bay × 1,3; 30 km/h trong thành phố, 60 km/h liên tỉnh. Mọi chặng gắn "ước tính" **[HIỆU CHỈNH]**.
- `transport.py` + `transport.v1.yaml`: tuyến xe khách mẫu (bến, thời gian ước tính, loại xe).
  - Không có giá, giờ chạy hay tên nhà xe.
  - Nhãn "Tham khảo, chưa đặt được trên Tripflix" (Bảo chốt 16/11).
  - Đây là dữ liệu tham chiếu kiểu file luật (như `packing.v2.yaml`), không phải dữ liệu nghiệp vụ, nên không trái RULES §10. Khi có nguồn thật thì chuyển sang core.

### B5. Itinerary Engine (commit `c132ffa`)
- `app/services/assistant/itinerary.py`: code thuần, không gọi mạng, không gọi LLM.
  - Chọn điểm theo độ phổ biến × mức khớp sở thích.
  - Chia ngày theo hướng quanh nơi ở (sweep theo góc).
  - Trong mỗi ngày thử mọi hoán vị (≤ 6 điểm) để có vòng ngắn nhất.
  - Khung giờ theo luật: biển buổi sáng, hoàng hôn cuối ngày, có bữa ăn.
  - Mưa > 60% thì đưa điểm trong nhà lên trước và nói rõ.
  - Tối đa 40 km/ngày, không trùng điểm; vượt thì bỏ điểm có điểm số thấp nhất.
  - Chế độ "đi y chang" reel: giữ thứ tự người đăng, chỉ tính chặng.
  - Mọi hằng số ghi **[HIỆU CHỈNH]** (theo kiểu ItiNera, báo cáo §4.2).

### B6–B7. Bản nháp chuyến đi và Skill (commit `226e60a`, `baaf5ee`)
- **`TripContext` v2** (chỉ thêm, vẫn đọc được v1):
  - thêm `originCity`, `interests`, `stay`, `transport`;
  - `days` tối đa 7 ngày, `pending` tối đa 4 lựa chọn, `ops` tối đa 5 phép để hoàn tác.
- **`ChatRequest.action`** (nút trên thẻ): `select`, `remove_stop`, `undo`. Chạy thẳng bằng code, **không gọi LLM** (`llm_status="action"`).
- **`TripPlanner`** (`skills/plan.py`):
  - **Xếp chuyến:** lấy điểm từ core rồi Engine xếp, cuối cùng hỏi nơi xuất phát.
  - **Chỗ ở:** Tripflix trước (có giá thật). Chỗ ngoài lấy từ OSM `lodging`, ghi nhãn "Ngoài Tripflix", không có giá, không đặt được.
  - **Chọn chỗ ở:** chỗ Tripflix thì hỏi lại core (`/api/hotels/{id}`) xem còn bán không và lấy toạ độ, rồi xếp lại lộ trình từ chỗ mới.
  - **Cách đi:** có sân bay ở cả hai đầu thì tìm vé thật; không có thì đưa tuyến xe mẫu.
  - **Sửa kế hoạch:** bỏ một điểm, hoàn tác.
  - Đổi sang nơi khác thì xoá kế hoạch cũ.
- **Controller v5** (`assistant-controller.v5.md`; v4 giữ nguyên):
  - Intent mới: `plan_trip`, `change_stay`, `change_transport`, `remove_stop`, `undo`, `select_option`.
  - Trường mới: `interests`, `stop_name`, `pace`.
  - Chỉ gửi tên thành phố cho LLM, không gửi toạ độ.
- **Guard sau Controller** (eval live và chain bắt được):
  - `plan_trip` chỉ nhận khi câu có chữ chỉ việc xếp lịch ("xếp", "lên lịch trình"…).
  - "mình ở sài gòn" là hỏi cách đi và lấy nơi xuất phát. Cần chủ ngữ hoặc "từ…", và thành phố phải khác điểm đến, để "ăn gì ở Huế" không bị hiểu sai.
  - "lấy cái thứ 1" khi đang có lựa chọn → chọn.
  - "video này" khi đang mở reel → lộ trình reel.
  - Câu ngoài phạm vi ("bài văn", "viết code") → từ chối.
- Hợp đồng `contracts/openapi/ai-service.json` chỉ thêm. `TripContext.v` thành enum 1 | 2.

### B8. Eval Giai đoạn B
- `cases.v4.jsonl`: 12 ca (lên kế hoạch, đổi chỗ ở, chọn, bỏ điểm, hoàn tác, cách đi).
- `chains.v2.jsonl`: chuỗi Vũng Tàu §0A.2 ("muốn đi vũng tàu 2n1đ" → "mình ở sài gòn" → …).
- `run.py` có `/api/places` giả và toạ độ khách sạn cho chế độ ci.

### Chưa làm so với kế hoạch
- **Responder v3, Verifier v4** (dung sai làm tròn km/phút):
  - Câu trả lời kế hoạch vẫn qua Responder v2 và Verifier hiện có: số và tên phải có trong facts.
  - Nếu Responder làm tròn số khác facts thì câu bị loại, dùng câu do code viết.
- **Hạn chót riêng 15 giây cho lượt dựng lộ trình** và trạng thái "Đang xếp lộ trình…": lượt này dùng hạn chót chung của `/chat`.
- **Kiểm lại mọi ID trong bản nháp mỗi lượt:** hiện chỉ kiểm khi chọn chỗ ở Tripflix. Điểm tham quan không kiểm lại vì là dữ liệu tĩnh.

## Đối chiếu "Xong khi"
| Tiêu chí (kế hoạch B4–B8) | Đạt | Bằng chứng |
|---|---|---|
| 3 cổng dữ liệu có bản thật và bản giả | Đạt | `test_data_ports.py` 6 test |
| Engine: vòng ngắn nhất, ≤ 40 km, chỉnh theo mưa, giữ thứ tự reel | Đạt | `test_itinerary_engine.py` 10 test |
| Nút Chọn, bỏ điểm, hoàn tác chạy không cần LLM | Đạt | `test_tapping_choose_needs_no_llm_and_replans_from_the_new_stay`, `test_remove_a_stop_then_undo_puts_it_back_in_place` |
| Chỗ Tripflix trước, chỗ ngoài có nhãn, không giá | Đạt | `test_stay_options_put_tripflix_first_and_label_outside_ones_without_price` |
| Không có sân bay thì đưa xe mẫu có nhãn | Đạt | `test_no_airport_means_a_reference_bus_route_with_an_estimated_time` |
| Không bịa điểm khi core không có dữ liệu | Đạt | `test_no_places_with_coordinates_is_said_not_invented`, `test_no_places_means_no_invented_stops` |
| Hợp đồng chỉ thêm, đọc được app cũ (v1) | Đạt | `test_an_old_app_trip_v1_is_still_read`; diff `contracts/` |
| Bản nháp đủ nhỏ để app lưu | Đạt một phần | Kế hoạch 2 ngày 815 byte (< 1.800). Kế hoạch từ khoảng 4 ngày có thể vượt 2.048 byte của app |
| Eval live + chain, ghi trước/sau | Đạt | Bảng dưới |
| Responder v3, Verifier v4, hạn chót 15 giây | **Chưa** | Xem "Chưa làm" |

## Kết quả kiểm tra
- ruff, pyright sạch.
- `pytest`: **729 passed, 6 skipped** + 17/17 `tests/test_chat.py` bản đã commit (sau khi merge develop có #36, #37 và A4; giải conflict `turn.py` giữ cả `places` và `disabled_skills`, `run.py` giữ cả `ab` và `v4`).
- Eval ci: **112/112** (70 ca cũ + 30 ca A4 + 12 ca Giai đoạn B).
- **Eval live** (112 ca × 3 lần, `gpt-5-nano`) và **chain** (6 chuỗi × 3 lần):

| Prompt | Intent + thông tin | pass^3 | Chain (lượt đúng, chuỗi đúng cả 3 lần) | Chi phí live |
|---|---|---|---|---|
| v5, chưa thêm guard | 90,2% | 87,4% | 90,1%, 4/6 | 0,037 USD |
| v5 + guard lần 1 | 94,3% | 93,7% | 95,1%, 4/6 | 0,037 USD |
| v5 + guard lần 2 | 95,2% | 93,7% | (lần chạy bị lỗi in tiếng Việt) | 0,036 USD |
| **v5 + guard lần 3 (bản cuối)** | **97,6%** | **94,6%** | **91,8%, 3/6** | 0,036 USD |

- So sánh: v4 + guard đạt 99,5% / 98,6% trên 70 ca cũ, nhưng không hiểu được các câu của Giai đoạn B.
- Độ trễ Controller lần cuối: p50 2,57 giây, p95 4,25 giây. Hôm đó mạng tới OpenAI chậm: 5/336 lượt live và 3 lượt chain bị ReadTimeout, tính là sai.
- Các ca còn lệch, không tính timeout:
  - `ctx-02` ("ks trong video này còn phòng"): ý định đúng, nhưng model ghi thừa `query`/`missing` ở 2/3 lần.
  - Chain `reel-6.1`: "Quay lại lộ trình reel đó, ngày cuối đi đâu?" chưa chọn đúng ngày; "Đi Đà Lạt cần mang phụ kiện gì?" lệch thẻ. Hai lỗi này đã có từ v4.
  - Chain `q2-rain-tshirt`: câu hỏi mặc gì sau thời tiết bị hiểu là hỏi thời tiết.
- Guard thêm sau lần 2 (bắt từ eval): giữ nơi xuất phát khi model trả kèm "thiếu nơi xuất phát"; đọc nhịp đi ("đi nhiều chỗ", "thong thả"); "video này" khi chưa mở reel thì hỏi mở reel, không tìm reel.

## Cách kiểm lại
1. `uv run pytest tests/assistant -q`
2. `PYTHONIOENCODING=utf-8 uv run python -m evals.assistant.run` (ci), `--mode live`, `--mode chain` (cần khoá OpenAI).
3. Chạy core (nhánh `bao/TF31-diem-tham-quan`) và ai-service, rồi chat:
   - "xếp lịch trình vũng tàu 2 ngày 1 đêm" → kế hoạch 2 ngày, có chặng km/phút ước tính.
   - "mình ở sài gòn" → tuyến xe tham khảo.
   - "đổi chỗ ở gần biển hơn" → danh sách, Tripflix trước.
   - Bấm "Chọn" (app gửi `action`) → xếp lại.
   - "Hoàn tác" → quay về.

## Ảnh / video
- Không đổi giao diện trong repo này. Ảnh app ở evidence FE `TF31-the-giai-doan-b.md`.

## Ảnh hưởng tới phần của người khác
- Không sửa code người khác.
- Tripi gọi thêm `GET /api/places` (discovery, Duy; PR BE riêng) và `GET /api/hotels/{id}` có sẵn (commerce, Thắng).
