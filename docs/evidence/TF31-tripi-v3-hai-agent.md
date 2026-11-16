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
  - Pytest **615 pass, 5 skip** (5 test Redis thật cần `REDIS_TEST_URL`).
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

**Chưa chạy:**
- Eval live 3 lần mỗi câu (`--mode live`, ước khoảng 0,02 USD), chờ Bảo đồng ý.
- Controller trên OpenAI: chờ `CHAT_CONTROLLER_MODEL` và giá trong `.env`.

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
