# TF31 — Tripi tư vấn điểm đến bằng hội thoại

- Notion: Chưa có link Notion (chờ Bảo dán) · Nhánh: `bao/TF31-tripi-tu-van` (phụ thuộc PR của nhánh `bao/TF31-tripi-loc-sap-xep`) · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-26

## Đã làm

Khi người dùng chưa có điểm đến ("cuối tuần đi đâu chơi", "buồn quá muốn đi đâu đó"), Tripi hỏi sở thích rồi gợi ý tối đa 3 nơi trong danh mục có sẵn, thay vì đẩy sang tìm reel. Spec: `docs/superpowers/specs/2026-11-26-tripi-tu-van-diem-den-design.md`.

- **Danh mục điểm đến** `destinations.v1.yaml`: 44 nơi (vùng, địa hình, không khí, tháng đẹp, điểm nhấn). Tripi chỉ được gợi ý nơi trong danh mục.
- **`TravelPrefs` trong trip memory** (`trip.prefs`): sở thích đã biết (không khí, địa hình, ngân sách…) được gộp qua các lượt (`merge_prefs`).
- **Controller v12** (`app/prompts/assistant-controller.v12.md`, v11 giữ nguyên): intent mới `consult` cho lượt chưa có nơi mà muốn đi chơi hoặc xin ý tưởng; guard trong `controller.py` giữ các luồng có nơi, `find_reel`, stay, flight nguyên hành vi; đang chờ `awaiting.intent="consult"` thì câu ngắn ("chill thôi", "gợi ý luôn đi") đi tiếp tư vấn, còn nêu tên nơi hoặc xin phòng/vé/reel thì rời tư vấn.
- **Consultant** (`app/services/assistant/consultant.py`, prompt `assistant-consultant.v1.md`): một lần gọi LLM trên cả danh mục, trả câu hỏi hoặc gợi ý + chip + sở thích hiểu được. Qua Verifier; câu nêu nơi viết hoa ngoài danh mục bị bỏ. Lỗi, hết giờ hoặc không có LLM thì dùng câu cố định (`fallback_consult_answer`) và hỏi tiếp về không khí/địa hình.
- **Nối vào lượt chat** (`turn.py`, `chat.py`): intent `consult` không gọi Core, kind `answer`, bỏ qua Responder; chưa gợi ý được thì đặt `awaiting` consult. Gợi ý xong thì lượt sau "Tìm phòng X" chạy luồng stay bình thường.
- **Contracts**: `contracts/openapi/ai-service.json` sinh lại (thêm `trip.prefs`, `awaiting.intent="consult"`).
- **Eval**: thêm `cases.v12.jsonl` (8 case ci) và `chains.v10.jsonl` (1 chain 3 lượt); `evals/assistant/run.py` nhận `v12` và chain v10. Các file version cũ giữ nguyên.

## Đối chiếu "Xong khi"

Chưa có link Notion nên chưa chép được tiêu chí gốc. Bảng đối chiếu theo phạm vi trong spec; Bảo đối chiếu lại với Notion.

| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Chưa có nơi mà muốn đi chơi thì Tripi hỏi sở thích / gợi ý, không đẩy sang reel | Đạt ở mức code | `tests/assistant/test_consult.py`; case ci `consult-*` (không gọi Core, kind answer). Chưa đo với LLM thật |
| Chỉ gợi ý nơi trong danh mục | Đạt ở mức Verifier | test `test_consult.py` (nơi ngoài danh mục bị bỏ, nơi người dùng tự nêu được giữ) |
| Nhớ sở thích qua các lượt | Đạt | test prefs merge + awaiting trong `test_consult.py`; `test_chat_consult_calls_llm_once_no_responder` |
| Có nơi hoặc xin reel/phòng thì không bị chặn vào tư vấn | Đạt | case `consult-not-reel`, `consult-not-with-place`; test "place leaves consult", "stay after consult still clarifies" |
| Lỗi LLM thì vẫn trả lời được | Đạt | test "error degrades" (3 loại lỗi) và "none fallback" |
| Điểm eval case cũ không tụt | Đạt | ci 180/180 trước, 188/188 sau (180 cũ vẫn đạt) |

## Điểm eval trước / sau

| Lệnh | Trước | Sau |
|---|---|---|
| `uv run python -m evals.assistant.run` (ci) | 180/180 | **188/188** (180 cũ + 8 case v12) |
| `uv run python -m evals.assistant.run --cases v12` | không có | 8/8 |
| `--mode live` / `--mode chain` | chưa chạy | chưa chạy (xem bên dưới) |

Kiểm chứng case có phân biệt được: sửa tạm `textContains` của 6 case consult thành chuỗi sai thì 6/8 fail; đã trả lại.

### Chế độ ci chứng minh gì, không chứng minh gì

Ở ci, Controller không được gọi (kế hoạch cho sẵn trong `expect.controller`) và runner không có cách giả cuộc gọi Consultant (chỉ truyền `core` và `weather` vào `Turn`, không truyền `consult`). Vì vậy các case consult chỉ chứng minh **định tuyến**: intent `consult` đi đúng nhánh, không gọi Core (`neverCalls: ["/api/"]`), kind `answer`, không thẻ, văn bản là câu cố định khi không có hàm consult (chứa "yên tĩnh"). Các case có `trip.awaiting.intent="consult"` kiểm đường đang chờ. ci **không** chứng minh prompt Controller v12 làm LLM xuất `consult`, không đo chất lượng gợi ý của Consultant. Hai case `consult-not-reel`, `consult-not-with-place` chỉ kiểm code sau Controller khi plan là find_reel/search.

### Chưa chạy với LLM thật

Máy này không có `OPENAI_API_KEY`/`DEEPSEEK_API_KEY` nên chưa chạy live và chain; chưa có điểm trước/sau cho prompt Controller v12 và Consultant v1, trái với RULES §10 ở phần "ghi điểm trước/sau". Bảo cần chạy sau khi có key và ghi điểm vào file này:

```
uv run python -m evals.assistant.run --mode live --cases v12   # intent + slot, 3 lần mỗi case
uv run python -m evals.assistant.run --mode live               # toàn bộ, để thấy case cũ có đổi (xem dưới)
uv run python -m evals.assistant.run --mode chain              # gồm chain v10 (3 lượt: than buồn, sở thích, Tìm phòng Quy Nhơn)
```

Để có điểm "trước", chạy cùng lệnh live trên Controller v11 (đổi `PROMPT` trong `understand.py` về v11) rồi so với v12.

## Test và expectation cũ đã đổi

Không xoá, không skip test nào. Hai unit test trong `tests/assistant/test_context_and_small_talk.py` khẳng định đúng hành vi mà tính năng này thay (chưa có nơi thì `search`), nên chỉ đổi `search` thành `consult`, giữ nguyên độ chặt:

- `test_off_topic_is_only_harmless_chit_chat`, case `cuoi tuan di dau chill duoi 3 cu` (off_topic, không nơi): `search` thành `consult`.
- `test_asking_for_ideas_is_a_search_not_a_question_back` (đổi tên thành `..._is_a_consult_not_a_question_back`): "vậy đi biển đâu cho chill" với intent clarify / ask_why / clarify + place "null": `search` thành `consult`. "mình muốn đi chơi 3 ngày" vẫn `clarify`.

Case eval cũ không đổi file nào. Ở ci chúng vẫn đạt vì ci không chạy guard của Controller (đã so sánh: 0 khác biệt intent khi chạy mọi case có `controller` qua `apply_guards` bản cũ và mới).

## Thay đổi dự kiến ở chế độ live

Các case cũ này (không nơi, xin ý tưởng hoặc than + muốn đi) kỳ vọng cũ có thể không còn đúng khi chạy `--mode live`; không sửa file case cũ, Bảo xem kết quả live rồi quyết định:

| Case | Kỳ vọng cũ | Dự kiến |
|---|---|---|
| cases.v1 `search-03` "cuoi tuan di dau chill duoi 3 cu" | search | consult |
| cases.v9 `scope-travel` "đi biển đâu cho chill" | search | consult |
| chains.v3 `small-talk` lượt 6 "vậy đi biển đâu cho chill" | search | consult |
| cases.v3 `search-14` "biển nào đẹp ở miền Trung tháng 12" | search | có thể consult (ranh giới, model quyết định) |
| cases.v3 `ask-03` "mình muốn đi chơi 3 ngày" | clarify (alsoOk search) | có thể consult (ranh giới; guard giữ clarify) |

Không bị ảnh hưởng: `scope-travel-regression-3` (có nơi Hà Nội), các case find_reel, plan/stay/flight.

## Kết quả kiểm tra

Chạy ngày 2026-11-26 trên nhánh, trước commit evidence:

- `uv run ruff check .`: đạt.
- `uv run ruff format --check .`: đạt.
- `uv run pyright`: 0 lỗi.
- `uv run pytest -q`: **1331 pass, 7 skip** (7 skip có sẵn từ trước).
- `uv run python -m evals.assistant.run`: **188/188**.

## Cách kiểm lại

1. `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q`
2. `uv run python -m evals.assistant.run` phải ra `188/188`.
3. Với key LLM trong môi trường, chạy các lệnh live/chain ở trên.

## Việc Bảo phải làm trước khi merge

1. Duyệt nội dung `destinations.v1.yaml` (44 nơi: vùng, địa hình, không khí, tháng đẹp, điểm nhấn). Đây là dữ liệu Tripi nói ra với người dùng.
2. Với mọi `name` trong danh mục, thử `/api/suggest?q=<name>&types=place` trên staging, sửa tên nào không khớp địa danh Core nhận (để "Tìm phòng X", "Xem reel X" sau gợi ý chạy được).
3. Chỉ merge PR sau khi danh mục đã được duyệt và hai bước trên xong.

## Giới hạn đã biết

- Sở thích (`trip.prefs`) chỉ lưu trên máy người dùng, giữ 7 ngày; chưa có API BE để lưu lâu dài.
- Usage của lượt consult được ghi với `step="responder"` (chưa có step riêng trong sự kiện `ai.usage.recorded`).
- Mỗi lượt consult tốn khoảng 7k token đầu vào (prompt khoảng 2,5k + danh mục khoảng 4–5k), ước lượng chưa đo bằng tokenizer, chưa gồm lịch sử.
- Code chỉ bắt được tên nơi viết hoa ngoài danh mục; tên nước ngoài viết thường hoặc một từ trùng từ thường (ví dụ "Biển") không bị bắt.
- Quy tắc "rẻ nhất/đắt nhất" và "tối đa một câu hỏi" từ PR trước vẫn chỉ nằm trong prompt, Verifier không kiểm.
- Chưa có đánh giá LLM thật cho Controller v12 và Consultant v1; ví dụ trong prompt Consultant viết cho tháng hiện tại là 5, chưa thử với model thật.

## Sửa sau khi test local với LLM thật (26/11)

Stack local: BE `develop` (Docker), AI nhánh này ở cổng 8001, web ở cổng 3100; Controller `gpt-5-nano`, Responder và Consultant DeepSeek.

- `rating` của Core là object `{average, count}`: trước đó mọi lượt tìm phòng với Core thật đều lỗi. Đã sửa (`0cbd4b4`).
- Câu hỏi ngày ("hôm nay/mai/cuối tuần này là ngày mấy", "Tết năm nay ngày mấy") có intent `ask_date`, code trả lời từ lịch và giữ câu hỏi lộ trình còn dở.
- Hiểu "mốt", "ngày kia", thứ 2 đến thứ 6. Ngày người dùng vừa nói thắng ngày đang nhớ. "Cuối tuần này 2N1Đ" ra đúng thứ Bảy đến Chủ nhật. Hỏi thời tiết một ngày không kéo dài ngày về của chuyến.
- Lịch thời gian thực (`calendar.py`) và ngày lễ (`holidays.v1.yaml`, Tết và Giỗ Tổ 2026–2030; ngày nào chưa đối chiếu web thì đã ghi chú) được đưa vào Controller, Consultant, Responder. Spec: `docs/superpowers/specs/2026-11-26-tripi-lich-thoi-gian-design.md`.
- Vé bay hôm nay bỏ các chuyến cất cánh trước giờ hiện tại + 120 phút. Thành phố có nhiều sân bay chọn sân bay chính (TP.HCM→SGN…).
- Tìm tiếp mà tin nhắn không nêu nơi thì tìm theo nơi đang nói, hết thẻ lạc đề. Tên thẻ không còn bị lặp.
- Test đổi kỳ vọng: 3 dòng `test_ambiguous_airports_only_offer_connected_pairs` (Sài Gòn, Đà Nẵng giờ chọn sân bay chính). Mock nhận thêm kwarg `now`.
- Kết quả: ruff, format, pyright sạch; pytest 1384 pass, 7 skip; eval ci 194/194. Eval live/chain trước/sau **chưa chạy xong** (Bảo cho dừng); lệnh ở mục "Cách kiểm lại".
- Việc của Bảo: kiểm ngày âm lịch có ghi chú `chưa đối chiếu` trong `holidays.v1.yaml`, kiểm bảng sân bay chính với dữ liệu Core.

## Ảnh / video

- Không đổi giao diện; FE không sửa.

## Ảnh hưởng tới phần của người khác

- Không: chỉ sửa `tripflix-ai` (chủ: Bảo). FE nhận thêm field tuỳ chọn `trip.prefs` và `trip.awaiting.intent="consult"`; app trả nguyên khối `trip` về nên không cần sửa. `contracts/openapi` đã sinh lại đúng quy trình, chỉ thêm trường. Không đổi BE.
