# Tripi tư vấn điểm đến bằng hội thoại tự nhiên (consult)

- Ngày 2026-11-26 · Người viết: Bảo (dùng AI) · Task: TF31 · Nhánh dự kiến: tiếp tục `bao/TF31-tripi-loc-sap-xep` hoặc nhánh mới tách từ nó (builder chọn theo RULES §2)
- Phạm vi: chỉ `tripflix-ai`. Không sửa BE/FE.

## Vì sao

Người dùng hay nhắn lan man: "Tôi vừa thất nghiệp... buồn quá, muốn tìm chỗ đi chơi cuối tuần", "cuối tuần đi đâu chơi", "muốn đi đâu đó chill chill".
Hiện nay Tripi gửi nguyên câu lên `/api/search` và trả về các reel có caption "Cuối tuần đi…". Kết quả bị dữ liệu dẫn,
không giống một người tư vấn. Bảo muốn Tripi hành xử như một LLM thật: đồng cảm, hỏi đúng chỗ còn thiếu (vibe yên tĩnh
hay sôi động, biển hay núi, đi với ai, ngân sách, đi từ đâu, mấy ngày). Mỗi lần hỏi một kiểu, không theo một kịch bản cố định.
Tripi nhớ vibe để lần sau không hỏi lại, hoặc hỏi "vẫn muốn yên tĩnh hay đổi gió". Đủ ý thì gợi ý vài điểm đến kèm lý do,
rồi mới dùng các skill hiện có (reel, phòng, lộ trình).

## Hiện trạng (đã đọc)

- `controller.py:817`: tin nhắn SOCIAL dài hơn 6 chữ bị ép thành `search`.
- `controller.py:819-825`: `clarify` không có nơi đến, có SUGGEST_CUE và TRAVEL_CUE thì bị ép thành `search`
  ("vậy đi biển đâu cho chill" hỏi ý tưởng).
- `turn._discover` → `skills/content.search` → `/api/search` → thẻ reel theo caption.
- Verifier V3 bỏ câu có tên riêng không có trong facts, nên Responder không thể gợi ý "Quy Nhơn" nếu Core không trả về.
- Đã có sẵn dữ liệu tham khảo dạng YAML: `packing.v2.yaml`, `transport.v1.yaml`.
- `TripContext` được app lưu trên máy 7 ngày, xoá khi đăng xuất. API sở thích ở BE (`/api/v1/me/assistant-preferences`) **chưa có**.
- Usage event `ai.usage.recorded` có `step` gồm `controller` và `responder`.
- `memory.asked` và `planner.has_asked_before` coi mọi answer `kind == "clarify"` là "đã hỏi lại một lần".
  Sau đó lượt tìm phòng thiếu ngày sẽ tự giả định cuối tuần thay vì hỏi.

## Mục tiêu

1. Câu mơ hồ, kể tâm trạng hoặc xin ý tưởng mà chưa có nơi đến → Tripi tư vấn bằng LLM, không gọi search.
2. LLM tự quyết lượt này hỏi gì (một ý hay hai ý), hỏi lại hay gợi ý luôn. Code không ép thứ tự câu hỏi.
3. Sở thích (vibe, địa hình, bạn đồng hành, ngân sách, nơi đi, số đêm, tâm trạng) được nhớ trong trip memory. Lần sau LLM tự quyết
   dùng lại luôn hay hỏi xác nhận.
4. Gợi ý 1–3 điểm đến chỉ lấy từ danh mục do team soạn (`destinations.v1.yaml`, khoảng 40–50 nơi ở Việt Nam). Lý do do LLM tự viết.
5. Sau gợi ý có chip để đi tiếp bằng skill cũ: "Xem reel {nơi}", "Tìm phòng {nơi}", "Lên lịch trình {nơi}".

## Không làm

- Không đổi luồng của các intent khác (find_stay, find_flight, plan_trip…).
- Không lưu sở thích ở BE, không đồng bộ nhiều máy (cần API của BE, làm task riêng).
- Không thêm loại thẻ mới cho FE. Gợi ý dùng câu chữ và `suggestions` (chip) có sẵn.
- Không tư vấn tâm lý. Câu nguy hiểm (tự hại…) vẫn đi đường `is_unsafe`/refusal như hiện nay.
- Không thêm `step` mới vào event usage (tránh đổi contract với analytics). Lượt tư vấn ghi `step="responder"`.

## Anti-goals

- Tripi nêu một điểm đến không có trong danh mục, hoặc bịa giá, giờ mở cửa, sự kiện.
- Tripi hỏi y hệt một câu ở mọi cuộc trò chuyện (lại thành một flow cứng).
- Tripi hỏi mãi không gợi ý. Người dùng nói "gợi ý luôn đi" mà vẫn bị hỏi tiếp.
- Hỏi tư vấn làm hỏng luật "chỉ hỏi lại một lần" của tìm phòng.
- Điểm eval cũ tụt mà không được Bảo duyệt.

## Các hướng đã cân nhắc

| Hướng | Đánh đổi | Kết luận |
|---|---|---|
| **1. Vai Tư vấn (LLM) quyết hỏi/gợi ý, trả JSON; code chỉ kiểm danh mục và lưu sở thích** | Thêm 1 lần gọi LLM cho lượt tư vấn; hội thoại tự nhiên | **Bảo chọn** |
| 2. Controller điền sở thích, code chọn điểm đến theo nhãn, Responder diễn đạt | Rẻ, dễ kiểm nhưng code quyết flow, trái ý Bảo | Bỏ |
| 3. Agent tool-calling tự do | Phá luồng, mất eval, chậm | Bỏ |
| Danh mục: A. YAML do team soạn / B. LLM tự nêu địa danh | B tự nhiên hơn nhưng có thể bịa nơi | **Bảo chọn A** |

## Thiết kế

### 1. Danh mục điểm đến `app/services/assistant/destinations.v1.yaml`
Theo kiểu `transport.v1.yaml`: dữ liệu tham khảo, có comment đầu file nói nguồn và giới hạn.
Mỗi mục: `id` (kebab-case, ví dụ `quy-nhon`), `name` (tên Core dùng, có dấu), `region` (bac/trung/nam/tay-nguyen),
`terrain` (list: beach, mountain, island, city, countryside, lake), `vibe` (list: quiet, lively, romantic, adventure, healing,
foodie, nightlife), `good_months` (list int 1–12), `highlights` (2–4 cụm ngắn, không số, không giá). Khoảng 40–50 nơi.
Builder soạn từ kiến thức chung; **Bảo phải duyệt nội dung** (ghi trong evidence). Không ghi giá, giờ, sự kiện có ngày.
Loader dạng hàm có `@cache`, validate bằng Pydantic model.

### 2. Intent mới `consult` (Controller v12, giữ v11)
- Thêm `consult` vào `ControllerOutput.intent`, `Understanding.intent`, `Awaiting.intent`.
- Prompt: dùng `consult` khi người dùng muốn đi chơi/du lịch nhưng **chưa có nơi đến**: xin ý tưởng ("cuối tuần đi đâu chơi",
  "đi đâu chill"), kể tâm trạng kèm ý muốn đi, hoặc đang trả lời câu tư vấn của Tripi (`trip.awaiting.intent == "consult"`).
  Có nơi đến cụ thể thì theo intent cũ. "Tìm reel cuối tuần đi đâu" (nói rõ reel) vẫn là `find_reel`. Chuyện buồn không nhắc đi chơi
  vẫn là `off_topic`.
- Đổi hai guard ở `controller.py:817` và `819-825`: chỗ trước đây ép sang `search` khi chưa có nơi đến nay ép sang `consult`
  (có nơi đến thì giữ `search` như cũ). Mọi case eval cũ đổi kỳ vọng phải được **liệt kê trong evidence** để Bảo duyệt.

### 3. Sở thích trong trip memory
`TripContext.prefs: TravelPrefs | None`, model mới (WireModel) với mọi trường tuỳ chọn:
`vibe: list[Literal[...]]` (≤3), `terrain: list[Literal[...]]` (≤3), `companions: Literal["solo","couple","friends","family","kids"] | None`,
`budget_per_person: int | None` (VND, ge 0), `nights: int | None` (0–14), `mood: str` (≤60 ký tự, ví dụ "đang buồn, muốn xả stress").
Nơi đi dùng `TripContext.origin_city` có sẵn. `next_trip` ghép prefs mới vào prefs cũ: trường mới khác rỗng thì thắng.
Prefs **không** bị xoá khi đổi `place`. Controller input có thêm `trip.prefs` (đã là dữ liệu do LLM chuẩn hoá, có giới hạn).

### 4. Vai Tư vấn `app/services/assistant/consultant.py`
- Prompt `app/prompts/assistant-consultant.v1.md`. LLM client: `get_role_llm("responder")` (dùng lại client và breaker; không thêm cấu hình).
- Input JSON: `today`, `message` (che PII), `history` (6 lượt gần nhất, che PII), `prefs` hiện có, `originCity`,
  `catalog` (toàn bộ danh mục rút gọn: id, name, region, terrain, vibe, goodMonths, highlights).
- Output strict schema `ConsultOutput`: `sentences: list[str]` (≤4), `prefs: TravelPrefs` (những gì hiểu thêm ở lượt này),
  `destination_ids: list[str]` (0–3), `chips: list[str]` (0–4, mỗi chip ≤30 ký tự), `is_done_asking: bool`.
- Prompt dặn: đồng cảm ngắn nếu người dùng kể chuyện; tự chọn hỏi điều quan trọng nhất còn thiếu, đổi cách hỏi theo ngữ cảnh, tối đa
  2 ý mỗi lượt; khi đã nhớ prefs thì có thể hỏi xác nhận ("vẫn muốn chỗ yên tĩnh hay đổi gió?") hoặc dùng luôn; người dùng nói
  "gợi ý luôn", hoặc đã có ít nhất vibe hoặc địa hình, thì gợi ý; tên điểm đến chỉ lấy từ catalog; không giá, giờ, sự kiện, số liệu
  ngoài catalog; ưu tiên nơi có `goodMonths` chứa tháng hiện tại; chip là câu trả lời ngắn người dùng có thể bấm ("Yên tĩnh thôi",
  "Biển nha", "Gợi ý luôn đi").
- Code sau LLM:
  - bỏ id không có trong danh mục;
  - chạy `verify` với facts = mục danh mục đã gợi ý (hoặc cả danh mục khi chỉ hỏi) cộng prefs, `extra_grounding` gồm `origin_city`
    và `trip.place`; chip cũng phải qua V3/V2 (chip trượt thì bỏ);
  - còn câu nào thì dùng, rỗng thì dùng câu dự phòng.
- Có điểm đến → `suggestions` do **code** tạo cho điểm đầu: "Xem reel {name}", "Tìm phòng {name}", "Lên lịch trình {name}",
  cộng một chip "Nơi khác nha" (≤4 chip). Chưa có điểm đến → dùng chip của LLM.
- Answer: `kind="answer"` (cả khi đang hỏi), để không đụng luật "chỉ hỏi lại một lần" của `memory.asked`.
  `facts=[{"type":"consult", ...}]` để chat.py **không** gọi Responder lần nữa. Lời đã viết đặt trong `answer.text`
  (chat.py tách câu như hiện nay).
- Khi còn hỏi (`destination_ids` rỗng) → `next_trip` đặt `awaiting = Awaiting(intent="consult", missing="place")`,
  để câu trả lời cụt ("chill thôi") quay lại `consult`.
- Usage: ghi qua `on_usage` với `step="responder"`. Hết giờ, LLM lỗi hoặc LLM tắt → câu dự phòng cố định
  "Bạn đang muốn một chuyến yên tĩnh để nghỉ ngơi hay sôi động cho vui? Thích biển hay núi nè?" kèm chip
  `["Yên tĩnh, chill", "Sôi động", "Biển", "Núi"]`, `degraded` có `consult`.

### 5. Nối vào luồng
- `Turn` nhận thêm tham số tuỳ chọn `consult: Callable[[ChatRequest, TripContext], Awaitable[Answer]] | None` (chat.py truyền vào,
  test truyền bản giả). `_answer` route `intent == "consult"` → `self._consult()`. Không có hàm (LLM tắt) → câu dự phòng.
- Timeout của bước tư vấn dùng `SKILL_SECONDS_BY_NAME["consult"] = 6.0` qua `_run`.
- Prefs từ `ConsultOutput.prefs` được ghép vào memory trong `next_trip`. Turn giữ prefs của lượt, giống cách giữ `planned_trip`.
- `chat.py`: điều kiện gọi Responder loại answer có fact `type == "consult"`.

### 6. Test và eval
- Unit: loader danh mục hợp lệ (id duy nhất, tên không rỗng, tháng 1–12); consultant bỏ id lạ; câu nêu nơi ngoài danh mục bị bỏ;
  không còn câu → câu dự phòng; có điểm đến → chip do code tạo; awaiting consult được đặt khi còn hỏi; prefs ghép đúng
  (mới thắng, rỗng không xoá cũ); guard 817/819 trả `consult` khi chưa có nơi đến; LLM lỗi → dự phòng + degraded.
- SSE (`tests/test_chat*.py`): lượt consult gọi LLM tư vấn một lần, không gọi Responder.
- Eval ci: case mới cho Controller ("cuối tuần đi đâu chơi", "tôi vừa thất nghiệp buồn quá muốn đi đâu đó cuối tuần",
  "đi đâu chill chill", "chill thôi" với awaiting consult, "tìm reel cuối tuần đi đâu" vẫn find_reel,
  "đà lạt cuối tuần chơi gì" vẫn search) và một chain 3 lượt (than buồn → trả lời vibe → bấm "Tìm phòng {nơi}").
- Lệnh kiểm tra repo như RULES §10. Live eval ghi lệnh cho Bảo chạy khi có key.

### 7. Trả lời câu hỏi của builder check
- **Thoát khỏi tư vấn:** `next_trip` tính lại `awaiting` ở mọi lượt (code hiện có). Lượt sau không phải `consult` thì awaiting tự bỏ.
  Bấm chip "Tìm phòng Quy Nhơn" là một tin nhắn thường, đi qua Controller → `find_stay` với `place`; `place` được ghi như luồng cũ.
- **Tên trong danh mục phải khớp Core:** chip dẫn vào `find_stay`/`plan_trip`. Nếu Core không nhận tên, luồng cũ đã hỏi lại
  "ghi rõ tên thành phố". Evidence ghi việc cho Bảo: thử `/api/suggest?q=<name>&types=place` trên staging cho mọi `name`
  và sửa tên lệch. *(quyết định của Claude)*
- **Sở thích ở lượt không phải tư vấn:** đợt này chỉ Tư vấn ghi prefs. Controller không thêm trường prefs
  (đã có `interests`, `adults`, `price_max_per_night` cho các luồng cũ). *(quyết định của Claude)*
- **Khi chỉ hỏi:** facts là cả danh mục, nên câu hỏi có thể nêu tên ví dụ trong danh mục ("biển kiểu Quy Nhơn hay Phú Quốc?"). Như vậy
  hợp lệ. Câu nào cũng bị Verifier bỏ thì dùng câu dự phòng, chỉ ghi log `chat.consult.fallback`, không tính là `degraded`
  (degraded nghĩa là skill/LLM lỗi). *(quyết định của Claude)*
- **Mức đạt eval:** mọi case cũ phải giữ nguyên, trừ các case nằm trong danh sách đổi `search`→`consult` đã ghi trong evidence.
  Live eval do Bảo chạy khi có key. *(quyết định của Claude)*
- **Duyệt danh mục:** PR được mở khi danh mục ghi "chờ Bảo duyệt" trong evidence; chỉ merge sau khi Bảo duyệt. *(quyết định của Claude)*

## Để builder tự quyết
- Danh sách Literal cụ thể của vibe/terrain (gợi ý như trên), câu chữ prompt, tên test.
- Rút gọn catalog trong input nếu quá dài (giữ mọi id).

## Quyết định là của mình (Claude), Bảo kiểm lại
- Lượt tư vấn trả `kind="answer"` để không phá luật hỏi lại một lần của tìm phòng.
- Dùng lại client Responder và `step="responder"` để không thêm cấu hình hay đổi contract event.
- Gợi ý chỉ qua chip, không thêm loại thẻ (FE không phải sửa).
- "Đủ ý" do LLM quyết. Code chỉ có hai chốt cứng: tối đa 3 điểm đến và mọi tên phải nằm trong danh mục.
