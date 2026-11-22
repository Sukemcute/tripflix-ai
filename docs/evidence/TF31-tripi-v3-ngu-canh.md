# TF31 — Tripi v3.1: nhớ chuyến đi và sửa lỗi theo báo cáo Expo Web

- Notion: TF31 · Nhánh: `bao/TF31-tripi-v3-ngu-canh` (tách từ `bao/TF31-tripi-v3-hai-agent`, **phụ thuộc PR phần nền và PR hai agent**) · Người làm: Quốc Bảo (dùng AI: có) · Ngày: 2026-11-16
- Đầu vào: báo cáo `docs/evidence/TF31-bao-cao-loi-tripi-expo-web.md` (khoảng 260 lượt thử). Kế hoạch đã duyệt: PR5 (AI) → PR3 (mobile) → PR4 (gateway).

## Đã làm

### Bộ nhớ chuyến đi
- Request thêm `trip`, SSE thêm sự kiện `trip`. Chỉ thêm, app cũ vẫn chạy.
- App giữ `trip` và gửi lại mỗi lượt; server kiểm lại tất cả.
- `TripContext` gồm: nơi, ngày đi/về, số người, trần giá, reel đang chọn, `lastCards` (≤ 5 thẻ vừa hiện), đã hỏi lại chưa.
- Controller chỉ thấy `{ref, kind}` của thẻ, không thấy id hay tiêu đề.

### Controller v3 (`assistant-controller.v3.md`; v1, v2 giữ nguyên)
- **Ý định xã giao mới:** `greeting`, `identity`, `thanks`, `ack`, `goodbye`. Không gọi Skill nào.
- **Ngày:** LLM chỉ ghi ngày/tháng, code gán năm. Hết lỗi năm 2126, 2108 (V11, B09).
- **Thông tin mới:** trần giá, giờ bay sau/trước, trẻ em, em bé, khứ hồi, tên khách sạn, thứ tự thẻ, tên reel, ngày của lộ trình, hỏi số ngày, món đã có, chỉ nhóm nào, số món, có đi biển không.
- **Guard bằng code ngay sau Controller** (`apply_guards`, [ĐỀ XUẤT] từ eval live): thông tin tin nhắn không nói tới thì không tin.
  - Bỏ "hôm nay", "mai", "hôm qua" khi tin nhắn không có chữ đó.
  - Bỏ khứ hồi khi không viết "khứ hồi"; "em bé" là infant.
  - Bỏ tên khách sạn không có trong tin nhắn.
  - Hỏi phòng mà không có reel, không có tên → tìm chỗ ở.
  - Câu dài không phải `ack`; câu có từ chỗ ở → tìm chỗ ở; câu hỏi mưa nắng mà không hỏi đồ mang → thời tiết.
  - "bạn làm được gì" không bị từ chối; đủ 2 sân bay không bị từ chối.

### Planner và Turn
- **Khoảng ngày sai thì hỏi lại, không tự đổi** (B11, B12).
  - Ngày đã qua hoặc quá 365 ngày → hỏi lại.
  - Chỉ có ngày nhận → tính 1 đêm và nói rõ "Tripi tạm tính 1 đêm" (B16).
- **Khách sạn gọi tên thắng khách sạn của reel** (R11):
  - dùng `/api/suggest?types=hotel` rồi `GET /api/hotels/{id}`;
  - lời đáp và thẻ luôn nói cùng một khách sạn, đúng ngày gửi core;
  - bỏ luật `ROOM_QUESTION` cũ.
- **Chỗ ở:** gửi `priceMax` cho core và lọc lại; không còn chỗ thì hỏi nới ngân sách (D01, D03).
- **Chuyến bay:**
  - lọc giờ trước khi cắt 5 thẻ, gộp hạng vé cùng chuyến (I08, I09);
  - gửi trẻ em, em bé cho core;
  - thiếu nơi đi thì chỉ hỏi nơi đi.
- **Reel:**
  - chọn theo thứ tự thẻ ("video thứ hai") hoặc theo tên: khớp ≥ một nửa số chữ, hoà điểm thì hỏi chọn;
  - reel vừa chọn từ thẻ không bị so tên lại với tiêu đề bài (chuỗi §6.1);
  - hỏi ngày N → câu trả lời nêu đúng các điểm của ngày đó; hỏi số ngày → "Reel này đi N ngày".

### Thời tiết và checklist dùng chung một nguồn
- Đúng ngày được hỏi. Ngày đã qua → nói chưa có dữ liệu. Ngoài 16 ngày → nói chưa có dự báo.
- Checklist lấy dự báo đúng khoảng ngày của chuyến; mỗi món có lý do.
- Bỏ món đã có, chỉ giữ nhóm người dùng muốn, cắt theo số món, không đi biển thì bỏ đồ biển.
- Luật mới ở `packing.v2.yaml`; v1 giữ nguyên.

### Verifier v3, Responder v2 (`assistant-responder.v2.md`)
- **V8 mới:** con số thời tiết phải thuộc đúng ngày câu văn nhắc tới (T20, W14). Câu nói thời tiết "hôm qua" bị bỏ.
- **Tên địa điểm kiểm theo từng chữ**, không bắt nguyên cụm. Trước đây 35/37 câu bị bỏ là câu đúng.
- **Tối đa 4 câu**, khớp với prompt.
- **Câu trả lời chính do code viết đứng đầu**, Responder chỉ thêm ý. Nếu chỉ còn câu mời bấm thẻ thì chèn câu mẫu (T25).
- Không còn "thẻ thẻ bên dưới" (T24).

### Bỏ kiểm "ngày đã qua" theo đồng hồ thật trong Skill
- Planner đã kiểm theo `today` của lượt, nên eval ngày cố định không hỏng theo thời gian.

## Đối chiếu "Xong khi"
| Tiêu chí (kế hoạch đã duyệt) | Đạt | Bằng chứng |
|---|---|---|
| Năm do code gán, không có năm lạ gửi core | Đạt | `test_v11_b09_year_comes_from_code_not_the_model`; eval v2 `report-B09`, `report-V11` kiểm `checkIn=2026-11-21` |
| Khoảng ngày sai thì hỏi, không gọi `/api/stays` | Đạt | `test_b11_b12_…`; eval v2 `neverCalls` |
| Xã giao không gọi Skill | Đạt | `test_a04_a16_v12_social_turns_call_nothing`; eval v2 `report-A04/A16/V12/V03/V04/V05/V01` |
| Giữ ràng buộc giá, giờ, khách sạn, em bé | Đạt | `test_d01_d03…`, `test_i08_i09…`, `test_r11…`; eval v2 kiểm `priceMax`, `infants` |
| Thời tiết đúng ngày, không có quá khứ, số đúng ngày | Đạt | `test_w01…`, `test_c04…`, `test_w14_t20…` |
| Checklist theo món đã có, không đi biển, số món | Đạt | `test_k06…`, `test_k08…`, `test_k09…` |
| Không "thẻ thẻ", giữ câu trả lời chính | Đạt | `test_t24…`, `test_t25…` |
| Nhớ chuyến đi qua nhiều lượt | Đạt một phần | Chain 91,7% lượt đúng (xem dưới) |
| Hợp đồng chỉ thêm | Đạt | `contracts/openapi/ai-service.json`: +146 dòng, 0 dòng xoá |

## Kết quả kiểm tra
- `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`: sạch, **660 passed, 5 skipped**.
- Test mới: `tests/assistant/test_report_regressions.py`, mỗi mã lỗi trong báo cáo một test, cộng 14 ca guard.
- `uv run python -m evals.assistant.run` (ci): **70/70** (v1 40 ca + v2 30 ca từ báo cáo). Ca v2 kiểm cả request gửi core và request không được gửi.
- Đã thử sửa kỳ vọng sai cho B09 và R11: bộ kiểm báo lỗi đúng.

### Eval live (Controller OpenAI `gpt-5-nano` thật, 70 ca × 3 lần; chấm intent và thông tin)
| Lần chạy | Intent + thông tin | pass^3 | Chi phí |
|---|---|---|---|
| PR2, prompt v2 (chỉ 40 ca v1, chỉ chấm intent) | 97,5% | 97,5% | — |
| v3 lần đầu | 78,6% | 65,7% | 0,019 USD |
| v3 + guard + thêm ví dụ | 96,2% | 92,9% | 0,020 USD |
| v3 + 2 guard cuối (`identity`, chuyến bay) | **95,2%** | **90,0%** | 0,020 USD |

- Độ trễ Controller: p50 1,9 giây, p95 2,4 giây.
- Hai lần chạy cuối khác nhau 1 điểm là do dao động của model. Ca được sửa (`talk-03`, `flight-02`) không còn trượt.
- Bảng trên không so ngang với PR2: bộ v3 có thêm 30 ca khó và chấm cả thông tin.
- **Còn trượt (không ổn định 1/3 lần):**
  - I09: thiếu sân bay đi → Tripi chỉ hỏi lại nơi đi.
  - K06, K08: thiếu "món đã có", "không đi biển" → checklist dư món.
  - V03: `thanks` thay `ack` → kết quả như nhau.
  - B16: câu "chỗ nào ok" mơ hồ, bị hiểu là `search`.
  - trip-03: 1/3 thành `find_reel`.

### Eval chain (nhiều lượt; mỗi lượt gửi history và `trip` của lượt trước)
| Lần chạy | Lượt đúng | Chuỗi đúng cả 3 lần |
|---|---|---|
| v3 lần đầu | 60,0% | 0/5 |
| v3 + guard | 88,3% | 2/5 |
| v3 + 2 guard cuối, không so tên lại khi chọn từ thẻ | **91,7%** | 2/5 |

- Sau lần chạy cuối, sửa thêm một lỗi code: "reel **này**", "video **đó**" không còn bị coi là tên một reel khác.
  - Lỗi này làm mất thẻ ở lượt "reel nay di may ngay" và "ngày cuối đi đâu".
  - Có test `test_words_pointing_at_the_open_reel_are_not_a_name`. **Chưa chạy lại chain sau bản sửa này.**
- Còn trượt chưa rõ nguyên nhân: 1/3 lần "ks trong reel t7 nay con phong k" không ra thẻ; 1/3 lần "dưới 500k" thiếu trần giá.

## Cách kiểm lại
1. `uv run pytest tests/assistant -q`
2. `PYTHONIOENCODING=utf-8 uv run python -m evals.assistant.run` (miễn phí)
3. Cần khoá OpenAI trong `.env`, tốn khoảng 0,02 USD mỗi lệnh:
   - `uv run python -m evals.assistant.run --mode live --runs 3`
   - `uv run python -m evals.assistant.run --mode chain --runs 3`

## Ảnh / video
- Không đổi giao diện trong repo này. Ảnh mobile nằm trong evidence `tripflix-fe` `TF31-tripi-v3-mobile.md` (chưa chụp được, ghi rõ lý do ở đó).

## Ảnh hưởng tới phần của người khác
- Không đụng code của người khác.
- Tripi gọi thêm API core có sẵn:
  - `/api/suggest?types=hotel`, `GET /api/hotels/{id}` (Duy, Thắng);
  - `priceMax` của `/api/stays`, `children`/`infants` của `/api/flights` (Thắng).
- Đã soạn tin báo trong `TF31-tin-nhan-lien-quan.md`.
