# TF31 — Tripi v3, hai agent: Controller lập kế hoạch, Responder giọng Tripi

- Notion: TF31 · Nhánh: `bao/TF31-tripi-v3-hai-agent` (tách từ `bao/TF31-tripi-v3-nen`, **phụ thuộc PR phần nền**) · Người làm: Quốc Bảo (dùng AI: có) · Ngày: 2026-11-16
- Thiết kế: `docs/architecture/tripi-agent-v3-de-xuat.md` mục 2A, `docs/architecture/tripi-agent-kien-truc-chi-tiet.md` mục 2

## Đã làm

- **Controller** (OpenAI theo cấu hình), prompt mới `assistant-controller.v1.md`.
  - Chỉ ra ý định và thông tin: nơi, `day_ref`, số đêm, số người, `uses_context_post`.
  - Chỉ nhận `today` và cờ "có reel đang xem", **không nhận id reel**.
  - 5 ý định mới: `post_itinerary`, `post_reviews`, `check_room`, `weather`, `packing`.
  - Prompt v1, v2 cũ giữ nguyên.
- **Planner** (code thuần):
  - "t7 này", "cuối tuần sau"… đổi thành ngày theo giờ Việt Nam.
  - Mỗi hội thoại hỏi lại tối đa một lần; đã hỏi rồi thì giả định cuối tuần này.
- **Skill mới:**
  - lộ trình, review và khách sạn của reel đang xem (`contextPostId`, chỉ do app gửi);
  - thời tiết Open-Meteo, thẻ ghi nguồn "Open-Meteo.com";
  - đồ mang theo theo luật `packing.v1.yaml`, dựa trên nơi, mưa, nhiệt độ, số đêm.
- **Skill lỗi chỉ hỏng phần của nó.** Thẻ ghi "Tripi chưa kiểm được … lúc này", `done.degraded` có tên skill. **Không bao giờ báo thành hết chỗ hay không tìm thấy.**
- **Responder** (DeepSeek), prompt `assistant-responder.v1.md`:
  - Giọng Tripi: xưng mình–bạn, vui, ≤ 4 câu, ≤ 2 emoji.
  - Không có tool, không nhận giá.
  - Nhắc kết quả bằng mã `[rN]`; server thay mã bằng tên, hoặc "thẻ bên dưới" với thẻ thông tin.
- **Verifier** (code), bỏ từng câu nếu có:
  - mã lạ;
  - con số, tên địa điểm không có trong facts hay câu hỏi;
  - từ tạo khan hiếm;
  - nói sai còn/hết phòng;
  - liên kết, số điện thoại, email;
  - không phải tiếng Việt; quá emoji.
  - Hết câu thì dùng câu mẫu.
- **Luồng SSE** (chỉ thêm):
  - bước `searching`, `writing`;
  - chữ gửi theo câu;
  - sự kiện `suggestions` (chip do code sinh);
  - thẻ `weather`, `checklist`, `itinerary`, `summary` có `lines` và `source`.
- **Bộ eval** `evals/assistant/`: 40 câu có nhãn, nhiều câu không dấu, viết tắt, teencode, chen lệnh.
  - Chế độ `ci`: core giả, chạy trong pytest.
  - Chế độ `live`: hỏi Controller thật 3 lần mỗi câu, tính pass^3 và chi phí.

## Đối chiếu "Xong khi" (Giai đoạn A)

| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Không phải câu nào cũng ra 3 video: thẻ theo câu hỏi | Có | eval ci 40/40 (`card` theo ý định); chạy thật: thời tiết → `weather`, mang gì → `checklist`, lộ trình → `itinerary` |
| Trả lời thời tiết, đồ mang theo | Có | `test_weather_card_carries_numbers_and_attribution`, `test_packing_list_follows_place_and_weather`; chạy thật Vũng Tàu |
| Đọc lộ trình của reel đang xem | Có | `test_reel_itinerary_card_from_core`; chạy thật reel Nha Trang |
| Khách sạn trong reel còn phòng không, giá chỉ ở thẻ | Có | `test_reel_hotel_room_check_keeps_price_off_the_facts`; chạy thật: "đêm 21/11 vẫn còn phòng cho 2 người" |
| Giọng vui, trẻ, không bịa | Có | Verifier V1–V7 (`test_verifier_*`); `test_responder_replaces_refs_and_drops_invented_prices` |
| Hỏi lại tối đa một lần | Có | `test_one_clarifying_question_per_conversation`; eval `stay-04`, `room-03` |
| Skill lỗi không thành "không tìm thấy" | Có | `test_failed_skill_is_reported_as_unchecked_not_empty` |
| Reel bị ẩn không được mô tả | Có | `test_hidden_reel_is_never_described` |

## Kết quả kiểm tra

- `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`:
  - Ruff pass; Pyright 0 lỗi.
  - Pytest **619 pass, 5 skip** (5 test Redis thật cần `REDIS_TEST_URL`).
- `uv run python -m evals.assistant.run` (ci): **40/40** câu khớp loại câu trả lời và thẻ đầu tiên.
- `uv run python -m scripts.export_openapi`: hợp đồng không đổi; thẻ và sự kiện mới nằm trong SSE.

**Chạy thật ngày 16/11** (core, Redis local; cả 2 agent tạm dùng DeepSeek vì `.env` chưa có `CHAT_CONTROLLER_MODEL` và giá OpenAI; tài khoản seed `member@tripflix.local`; một hội thoại nhiều lượt):

| Câu | Thời gian | Kết quả |
|---|---|---|
| muon di vung tau 2n1d | 1,5 s | `no_result`: seed chưa có reel Vũng Tàu (X9) |
| thoi tiet t7 nay sao | 4,7 s | thẻ thời tiết; "Thứ Bảy này Vũng Tàu khoảng 26–32°C… mưa tới 52%" (đúng số Open-Meteo) |
| can mang gi | 2,0 s | checklist đồ biển + áo mưa theo dự báo |
| lo trinh video nay di nhung dau (reel Nha Trang) | 2,0 s | thẻ lộ trình + 3 chip |
| ks trong reel t7 nay con phong k | 2,1 s | "Vinpearl Beach Nha Trang, đêm 21/11 vẫn còn phòng cho 2 người"; giá chỉ trên thẻ |
| moi nguoi review reel nay sao | 0,9 s | "chưa đủ bình luận" (reel chưa có tóm tắt) |

- Chi phí cả 2 agent: 0,00017–0,00039 USD mỗi lượt.
- **Sửa sau lần chạy đầu:**
  - Thời tiết là 2 lần gọi nối nhau và vượt 3 s, nên nâng lên 6 s riêng cho skill thời tiết.
  - Core trả 404 khi bài chưa có tóm tắt; Tripi từng báo nhầm thành "reel không còn". Đã sửa và có test.
  - Mã thẻ lộ trình được đổi thành "thẻ bên dưới".

**Eval live trên OpenAI** (Bảo đã thêm `CHAT_CONTROLLER_MODEL=gpt-5-nano` và giá vào `.env`; 40 câu × 3 lần; `uv run python -m evals.assistant.run --mode live --runs 3`):

| Lần | Độ đúng ý định | pass^3 | p50 / p95 | Chi phí 120 lần gọi |
|---|---|---|---|---|
| Trước: prompt Controller v1 | 99/120 = **82,5%** | 31/40 = **77,5%** | 1,58 s / 2,16 s | 0,0060 USD |
| Sau: prompt v2 + luật code | 117/120 = **97,5%** | 39/40 = **97,5%** | 1,59 s / 1,93 s | 0,0061 USD |

**Lỗi v1 và cách sửa:**
- Câu ngoài du lịch (giải toán, viết code) bị hiểu thành `small_talk`/`clarify` (1/6). Thêm luật và ví dụ vào prompt v2: còn 6/6.
- Strict mode của OpenAI bắt điền mọi trường, nên model viết `"checkIn": "0000-01-01"` cho "không có ngày", và `"Hanoi"` thay vì mã `HAN`. Hai lỗi này làm hỏng cả kế hoạch. Sửa ở ranh giới nhận dữ liệu: năm trước 2000 và mã không đúng dạng IATA coi như chưa có.
- Vé khứ hồi có em bé vẫn bị đem đi tìm vé một chiều. Thêm luật code `UNSUPPORTED_FARES` để hỏi lại.
- "reel này đi mấy ngày" bị hiểu thành tìm reel. Thêm ví dụ vào prompt v2.

**Đổi nhãn eval** (các ca mà kết quả cuối vẫn đúng):
- `stay-03`: chấp nhận `find_stay`, vì code vẫn hỏi lại ngày.
- `search-07`: chấp nhận `refusal`, vì từ chối câu chen lệnh là an toàn.
- `reel-02`: chấp nhận `search`, vì vẫn ra video.
- `flight-03`: plan CI đổi sang `find_flight` để kiểm luật hỏi lại.

**Còn sai:** `flight-02` "bay re nhat tu ha noi vao sai gon t7" bị hiểu thành `search` cả 3 lần.

**Chạy thật với cấu hình cuối** (Controller OpenAI `gpt-5-nano`, Responder DeepSeek, core local; chạy lại hội thoại ở trên):
- Cả 6 lượt đúng, mỗi lượt 1,7–5,5 s, 0,00005–0,00025 USD.
- "ks trong reel t7 nay con phong k" từng bị hiểu thành hỏi lộ trình khi lượt trước đang nói lộ trình. Thêm luật code `ROOM_QUESTION`: đang xem reel mà hỏi "còn phòng" thì luôn kiểm phòng. Sau sửa: "Vinpearl Beach Nha Trang vẫn còn phòng cho 2 người đêm 21/11".
- Trang demo local (`localhost:3100`, khách chưa đăng nhập) hỏi "thoi tiet vung tau t7 nay": 3,5 s, 3.395 token, 0,00031 USD, thẻ thời tiết có ghi nguồn Open-Meteo và 2 chip gợi ý.

**Hiệu chỉnh hạn mức:**
- Số đo thật: một lượt hai agent khoảng **3.500 token** (ước tính cũ là 2.500). Tài khoản test chạm trần 60.000 token sau khoảng 20 lượt và bị hạ cấp đúng thiết kế.
- Mặc định mới: người đăng nhập 150.000 token (khoảng 40 lượt, khoảng 0,01 USD mỗi ngày); khách 20.000 token (khoảng 5 lượt).

## Cách kiểm lại

1. `uv run pytest tests/assistant` và `uv run python -m evals.assistant.run`.
2. Chạy thật:
   - `pnpm stack:be` (tripflix-be).
   - `CHAT_LLM_ENABLED=true uv run uvicorn app.main:app --port 8000`.
   - Đăng nhập lấy token, gửi `POST /chat`; với reel thì gửi thêm `contextPostId` của một bài có `tripAttachment`.

## Ảnh / video

- Chưa có: phần app mobile ở PR `tripflix-fe` (`bao/TF31-tripi-v3-mobile`).

## Ảnh hưởng tới phần của người khác

- Không sửa code người khác.
- Đọc thêm `day`, `hotelId`, `daysCount` trong bài của core (đã có trong hợp đồng core).
- App cần hiển thị thẻ và sự kiện mới. Mọi thứ chỉ thêm; app cũ vẫn chạy, bỏ qua sự kiện lạ.
