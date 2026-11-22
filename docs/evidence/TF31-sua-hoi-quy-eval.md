# TF31 — Sửa hồi quy eval Tripi

- Notion: không được cung cấp · Nhánh: `bao/TF31-sua-hoi-quy-eval` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-19

## Đã làm

- Dùng chung bộ khớp tên điểm với move_stop để ép yêu cầu bỏ/xoá một điểm về remove_stop; không ép khi có tín hiệu thứ tự hoặc chuyển ngày/buổi.
- Giữ yêu cầu du lịch rõ ràng khi có lời chửi và Controller trả refusal; yêu cầu nguy hiểm vẫn bị từ chối.
- Sáu ca scope-travel-regression giữ nguyên câu người dùng, chấp nhận search/find_stay/clarify; CI kiểm cặp intent/kind/card, vẫn loại refusal/off_topic.
- Không đổi prompt, không commit. Snapshot đo live/chain trước bản sửa “bộ/bờ” đã giữ nguyên 258 file nguồn/test/contract trong suốt hai mode (kiểm SHA-256 trước/sau). Không tự sửa các lượt eval còn trượt.
- Sau review: giữ dấu NFC/lowercase để phân biệt động từ “bỏ” với “bộ/bờ”; từ không dấu bo/xoa/bot/loai phải đứng ngay trước tên điểm. Giữ luật “không (cần) đi” và các loại trừ thứ tự/ngày/buổi.

## Đối chiếu "Xong khi"

| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Bỏ điểm không thành move_stop | Có | test_delete_named_stop_overrides_model_move; test_delete_guard_does_not_override_order_or_day_moves |
| Không xoá điểm do nhầm “bộ/bờ” hoặc bo đứng xa | Có | test_delete_guard_preserves_accents_and_requires_adjacent_ascii_verb (9 ca) |
| alsoOk không làm CI hỏng hoặc nhận refusal | Có | test_travel_regression_cases_accept_legitimate_ci_alternatives; test_travel_regression_cases_reject_out_of_scope_answers |
| Câu chửi kèm tìm khách sạn không bị từ chối | Có | test_rude_explicit_stay_request_overrides_model_refusal; test_rude_refusal_is_not_overridden_by_unsafe_or_remembered_place |

## Kết quả kiểm tra

Bản sửa “bộ/bờ” chỉ được kiểm bằng lint, format, pyright, pytest và eval CI. **Không chạy lại live/chain.** Các số live 493/513, pass³ 159/170 và chain 212/216 dưới đây được đo trước bản sửa này; không phải số đo live/chain của code hiện tại.

| Lệnh | Kết quả |
|---|---|
| `uv run ruff check .` | Pass, 0 lỗi |
| `uv run ruff format --check app evals tests scripts` | Pass, 174 file đúng format |
| `uv run pyright` | 0 errors, 0 warnings, 0 informations |
| `uv run pytest --ignore tests/test_chat.py -q` | 1243 passed, 6 skipped, 0 failed (sau sửa “bộ/bờ”) |
| `PYTHONIOENCODING=utf-8 uv run python -m evals.assistant.run --mode ci` | 171/171 pass, 0 fail |
| `PYTHONIOENCODING=utf-8 uv run python -m evals.assistant.run --mode live` | 493/513 = 96.1% — đo trước sửa “bộ/bờ” |
| `PYTHONIOENCODING=utf-8 uv run python -m evals.assistant.run --mode chain` | 212/216 = 98.1% — đo trước sửa “bộ/bờ” |

### So sánh trước / sau ba sửa hồi quy (đo trước sửa “bộ/bờ”)

| Chỉ số | #47 (v9 + Responder v3) | #56 | Sau sửa hồi quy |
|---|---|---|---|
| Live | 395/411 = 96,1% | 468/513 = 91.2% | 493/513 = 96.1% |
| pass³ | 125/136 = 91,9% | 143/170 = 84.1% | 159/170 = 93.5% |
| Chain | 172/180 = 95,6% | 206/214 = 96.3% | 212/216 = 98.1% |
| p50 | 2,29 s | 2,54 s | 2,53 s (p95 3,55 s) |
| Chi phí/lượt gọi live | 0,000121 USD | 0,000125 USD | 0,000126 USD (tổng 0,06475 USD; 3.614.733 token) |
| ReadTimeout live | Không có số tách riêng | 8 | 4 |
| ReadTimeout chain | 2 (evidence #47) | 1 | 1 |

- #47 lấy từ docs/evidence/TF31-lo-trinh-kem-dich-vu.md; #56 lấy từ pr55-live.log và pr55-chain.log do Bảo cung cấp.
- Bộ ca mở rộng: không so trực tiếp phần trăm tổng như cùng một tập ca. flight-03 trùng ID ở v1/v3: 171 dòng ca nhưng pass³ gộp 170 ID, giữ đúng cách runner chấm.
- Tám lượt v9 của #56 đổi từ trượt sang chấp nhận nếu chấm bằng alsoOk mới (find_stay/clarify); đây là thay tiêu chí, không phải tám sửa lỗi Controller.
- Live chấm Controller + guards/slots; chain thêm Turn/skills với fake core. Hai mode này không đo lời văn Responder và không gọi core thật.

### Tách bộ ca (đo trước sửa “bộ/bờ”)

| Bộ | #56 live | Sau live | #56 pass³ | Sau pass³ |
|---|---|---|---|---|
| Cũ v1–v7 (#47: 395/411, pass³ 125/136) | 379/411 = 92.2% | 395/411 = 96.1% | 115/136 = 84.6% | 127/136 = 93.4% |
| v8 — đổi thứ tự | 13/18 = 72.2% | 15/18 = 83.3% | 3/6 = 50.0% | 5/6 = 83.3% |
| v9 — ngoài lề | 52/60 = 86.7% | 59/60 = 98.3% | 17/20 = 85.0% | 19/20 = 95.0% |
| v10 — sửa thứ tự | 24/24 = 100.0% | 24/24 = 100.0% | 8/8 = 100.0% | 8/8 = 100.0% |

| Chuỗi | #56 | Sau |
|---|---|---|
| Cũ v1–v5 | 179/186 = 96.2% | 182/186 = 97.8% |
| v6 — Đà Nẵng | 6/6 = 100.0% | 6/6 = 100.0% |
| v7 — hỏi ngoài lề lặp | 9/9 = 100.0% | 9/9 = 100.0% |
| v8 — Đà Lạt | 12/13 = 92.3% | 15/15 = 100.0% |

- Chain sau: chains right in all 3 runs: 13/16; số lượt không chạy sau exception: 0 (không tính vào mẫu số theo runner).

### Từng lượt live còn trượt (log trước sửa “bộ/bờ”)

| Ca / phiên bản / lần | Câu thật | Want | Got | Đối chiếu #56 / flake cũ |
|---|---|---|---|---|
| search-03 / v1 / 2 | cuoi tuan di dau chill duoi 3 cu | {"intent":"search"} | {"intent":"clarify","missing":"place"} | Cũng trượt #56 |
| search-03 / v1 / 3 | cuoi tuan di dau chill duoi 3 cu | {"intent":"search"} | {"intent":"clarify","missing":"place"} | Cũng trượt #56 |
| review-02 / v1 / 1 | nguoi di roi noi gi ve cho nay | {"intent":"post_reviews"} | "ReadTimeout: []" | Không thấy trượt trong 3 lần #56; chưa đủ kết luận nguyên nhân; ReadTimeout (loại lỗi đã có ở #47) |
| report-V11 / v2 / 3 | ks vung tau dem 21/11 con phong k | {"intent":"find_stay","slots":{"check_in":"2026-11-21"}} | "ReadTimeout: []" | Không thấy trượt trong 3 lần #56; chưa đủ kết luận nguyên nhân; ReadTimeout (loại lỗi đã có ở #47) |
| report-B16 / v2 / 1 | tối 21/11 ở vũng tàu chỗ nào ok | {"intent":"find_stay","slots":{"check_in":"2026-11-21"}} | {"intent":"find_stay","check_in":null,"place":"Vũng Tàu"} | Cũng trượt #56 |
| report-K08 / v2 / 3 | di vung tau hop thoi khong di bien, mang gi | {"intent":"packing","slots":{"is_beach_trip":false}} | {"intent":"packing","is_beach_trip":null,"place":"Vũng Tàu"} | Không thấy trượt trong 3 lần #56; chưa đủ kết luận nguyên nhân |
| ctx-02 / v3 / 1 | ks trong video này còn phòng cuối tuần không | {"intent":"check_room","slots":{"day_ref":"this_weekend"}} | {"intent":"check_room","day_ref":"none"} | Cũng trượt #56 |
| ctx-02 / v3 / 2 | ks trong video này còn phòng cuối tuần không | {"intent":"check_room","slots":{"day_ref":"this_weekend"}} | {"intent":"check_room","day_ref":"none","place":"Video có context reel"} | Cũng trượt #56 |
| ctx-02 / v3 / 3 | ks trong video này còn phòng cuối tuần không | {"intent":"check_room","slots":{"day_ref":"this_weekend"}} | {"intent":"check_room","day_ref":"none","missing":"place"} | Cũng trượt #56 |
| remove-01 / v4 / 2 | bỏ Tượng Chúa đi | {"intent":"remove_stop"} | "ReadTimeout: []" | Cũng trượt #56; ReadTimeout (loại lỗi đã có ở #47) |
| tone-rude-03 / v5 / 1 | trả lời như cái bô | {"intent":"off_topic","alsoOk":["search","find_reel","find_stay","clarify","refusal","small_talk","plan_trip","off_topic","weather"],"slots":{"is_rude":true}} | {"intent":"ack","is_rude":true,"place":"Hà Nội"} | Cũng trượt #56 |
| tone-rude-03 / v5 / 2 | trả lời như cái bô | {"intent":"off_topic","alsoOk":["search","find_reel","find_stay","clarify","refusal","small_talk","plan_trip","off_topic","weather"],"slots":{"is_rude":true}} | {"intent":"ack","is_rude":true,"place":"Hà Nội"} | Cũng trượt #56 |
| tone-rude-03 / v5 / 3 | trả lời như cái bô | {"intent":"off_topic","alsoOk":["search","find_reel","find_stay","clarify","refusal","small_talk","plan_trip","off_topic","weather"],"slots":{"is_rude":true}} | {"intent":"ack","is_rude":true,"place":"Hà Nội"} | Cũng trượt #56 |
| tone-rude-req-02 / v5 / 1 | vcl thời tiết hà nội mai sao | {"intent":"weather","slots":{"is_rude":true}} | {"intent":"weather","is_rude":false,"place":"Hà Nội"} | Cũng trượt #56 |
| tone-rude-req-02 / v5 / 2 | vcl thời tiết hà nội mai sao | {"intent":"weather","slots":{"is_rude":true}} | {"intent":"weather","is_rude":false,"place":"Hà Nội"} | Cũng trượt #56 |
| tone-rude-req-02 / v5 / 3 | vcl thời tiết hà nội mai sao | {"intent":"weather","slots":{"is_rude":true}} | {"intent":"weather","is_rude":false,"place":"Hà Nội"} | Cũng trượt #56 |
| move-unknown / v8 / 1 | chuyển điểm không có sang ngày 2 | {"intent":"move_stop","slots":{"stop_name":"không có","target_day":2}} | {"intent":"move_stop","stop_name":"Chợ Hàn","target_day":2,"place":"Đà Nẵng","from_city":"TP.HCM","to_city":"Đà Nẵng","placement":"after"} | Cũng trượt #56 |
| move-unknown / v8 / 2 | chuyển điểm không có sang ngày 2 | {"intent":"move_stop","slots":{"stop_name":"không có","target_day":2}} | {"intent":"move_stop","stop_name":"Điểm 2","target_day":2,"place":"Đà Nẵng","from_city":"TP.HCM","to_city":"Đà Nẵng"} | Cũng trượt #56 |
| move-unknown / v8 / 3 | chuyển điểm không có sang ngày 2 | {"intent":"move_stop","slots":{"stop_name":"không có","target_day":2}} | {"intent":"move_stop","stop_name":"Bảo tàng Nghệ thuật Điêu khắc Chăm Đà Nẵng","target_day":2,"place":"Đà Nẵng","from_city":"TP.HCM","to_city":"Đà Nẵng","anchor_name":"Cầu Rồng","placement":"before"} | Cũng trượt #56 |
| scope-travel-regression-5 / v9 / 3 | tour 2+1 người lớn | {"intent":"search","alsoOk":["find_stay","clarify"]} | "ReadTimeout: []" | Cũng trượt #56; ReadTimeout (loại lỗi đã có ở #47) |

### Từng lượt chain còn trượt (log trước sửa “bộ/bờ”)

“Lần xuất hiện” là thứ tự lỗi cùng câu trong log; runner không in số run cho từng MISS.
| Chuỗi / lượt / lần xuất hiện | Câu thật | Want | Got | Flake cũ |
|---|---|---|---|---|
| reel-in-view / 3 / 1 | ks trong reel t7 nay con phong k | {"intent":"check_room","card":"stay"} | check_room/None {"slots": {"intent": "check_room", "uses_context_post": true}, "kind": "clarify", "stopOrder": [], "text": "Bạn muốn nhận phòng và trả phòng vào ngày nào?"} | Cũng trượt #56 |
| vt-report-sua-lich / 6 / 1 | chuyển thành 2n1d thôi | {"intent":"plan_trip","card":"itinerary","slots":{"nights":1}} | ReadTimeout | Không thấy lỗi cùng lượt trong #56; ReadTimeout đã có #47 |
| small-talk / 7 / 1 | vậy đi biển đâu cho chill | {"intent":"search","alsoOk":["find_reel","plan_trip"]} | clarify/None {"slots": {"intent": "clarify", "query": "vậy đi biển đâu cho chill", "missing": "place"}, "kind": "clarify", "stopOrder": [], "text": "Bạn muốn đi đâu?"} | Cũng trượt #56; chuỗi đã flake #47 |
| small-talk / 7 / 2 | vậy đi biển đâu cho chill | {"intent":"search","alsoOk":["find_reel","plan_trip"]} | clarify/None {"slots": {"intent": "clarify", "query": "vậy đi biển đâu cho chill", "missing": "place"}, "kind": "clarify", "stopOrder": [], "text": "Bạn muốn đi đâu?"} | Cũng trượt #56; chuỗi đã flake #47 |

### Nhận định lỗi còn lại (không sửa tiếp)

- Ca cũ v1–v7 phục hồi tổng điểm bằng #47, nhưng không đồng nghĩa mọi ca đều phục hồi. So với #56: search-03 tăng từ 1 lên 2 lần clarify thay search; report-K08 thêm 1 lần is_beach_trip=null thay false. review-02 và report-V11 mỗi ca thêm 1 ReadTimeout. Không có log từng ca #47 để kết luận chính xác từng ca này mới tụt so với #47.
- Dự đoán: search-03 còn bất ổn giữa gợi ý điểm đến và hỏi lại nơi; report-K08 bỏ sót phủ định “không đi biển”. ctx-02 vẫn không đọc được cuối tuần; tone-rude-03 ra ack ngoài tập intent chấp nhận, tone-rude-req-02 làm đúng weather nhưng bỏ cờ is_rude. Đây là các lệch Controller/slot, không phải chứng minh nguyên nhân từ ba thay đổi của task.
- move-unknown còn 3/3 sai tên: “Chợ Hàn”, “Điểm 2”, “Bảo tàng Nghệ thuật Điêu khắc Chăm Đà Nẵng” thay “không có”. Controller đang tự gán điểm khác; chưa sửa vì đã chốt snapshot trước live.
- remove-01: hai phản hồi đều remove_stop; lần còn lại ReadTimeout. tone-rude-req-01 đạt 3/3. Sáu scope-travel-regression không còn lỗi ngữ nghĩa; còn một ReadTimeout ở câu “tour 2+1 người lớn”.
- Chain: reel-in-view vẫn hỏi ngày thay thẻ stay; small-talk vẫn hỏi nơi thay search (flake đã có #47). Một ReadTimeout ở “chuyển thành 2n1d thôi”. Không có lỗi bỏ điểm trong vung-tau-0A2. Chuỗi v6/v7/v8 đều đạt trọn lượt.

### Log gốc

- Live: `C:\Users\lnqba\AppData\Local\Temp\eval-regress-live.log`
- Chain: `C:\Users\lnqba\AppData\Local\Temp\eval-regress-chain.log`

### Kiểm tra sau review “bộ/bờ”

- Test tập trung: `uv run pytest tests/assistant/test_move_stop.py -q` → 95 passed, 0 failed.
- Toàn bộ pytest → 1243 passed, 6 skipped, 0 failed; CI → 171/171. Ruff check sạch, format 174 file đúng, pyright 0 errors/0 warnings. Lần format check đầu yêu cầu một khoảng trắng ở slice; đã sửa đúng dòng đó và chạy lại pass.
- Không có file unmerged, không có marker conflict trong các file code thay đổi; `git diff --check` pass.
- Không chạy live/chain sau review, không đổi prompt hoặc ca eval cho bản sửa “bộ/bờ”.

## Cách kiểm lại

1. Chạy năm lệnh lint/format/typecheck/pytest/CI ở trên.
2. Hai log live/chain là kết quả lịch sử trước sửa “bộ/bờ”, đã chạy tuần tự trên snapshot cố định. Theo yêu cầu review, không chạy lại chúng cho bản sửa này.
3. Đối chiếu UNSTABLE/MISS trong hai log gốc; không sửa code giữa hai mode.

## Ảnh / video

- Không đổi UI; không có ảnh/video.

## Ảnh hưởng tới phần của người khác

- Code AI/assistant và evals thuộc Bảo. Không đổi FE/BE, API contract, prompt, dependencies hoặc tests/test_chat.py.
