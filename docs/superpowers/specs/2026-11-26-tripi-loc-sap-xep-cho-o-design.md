# Tripi: lọc, sắp xếp chỗ ở theo lời nói và Responder tự nhiên hơn

- Ngày 2026-11-26 · Người viết: Bảo (dùng AI) · Task: TF31 · Nhánh dự kiến `bao/TF31-tripi-loc-sap-xep`
- Phạm vi: chỉ `tripflix-ai`. Không sửa BE/FE.

## Vì sao

Tripi tìm được khách sạn Nha Trang nhưng không hiểu câu nói tiếp: "tìm căn đắt hơn", "rẻ hơn chút",
"xếp từ rẻ đến đắt", "4 sao trở lên". Câu trả lời còn cứng vì code tự viết nhiều câu, còn Responder
bị cấm nhìn giá. Mục tiêu: Tripi hiểu và trả lời tự nhiên hơn, nhưng vẫn giữ luồng
Controller → code gọi Core → Responder → Verifier.

## Hiện trạng (đã đọc)

- `skills/stay.py` gọi `/api/stays` với `limit=5` và chỉ gửi `priceMax`.
- Core `/api/stays` (README discovery, `domain/stays.ts`) **đã hỗ trợ** `priceMin`, `priceMax`, `minStars`,
  `sort=price|price_desc|stars`, `limit` 1–50, trả `stars`, `rating`. Không cần sửa BE.
- `TripContext.last_cards` (`CardRef`) chỉ có ref/kind/id/title, không có giá → "đắt hơn" không có mốc so.
- `to_understanding` lấy `price_max_per_night` từ trip khi tin nhắn không nói → nói "dưới 500k" rồi
  "đắt hơn" thì trần cũ vẫn chặn.
- Responder v4: "Không bao giờ nói giá tiền"; `build_facts` bỏ giá; Verifier chặn "rẻ nhất" (SCARCITY).
- Responder chỉ chạy khi có thẻ/facts. Câu hỏi lại (`clarify`) và `no_result` không thẻ là câu code viết cứng.
- FE (mobile) giữ `trip` dạng blob và gửi lại nguyên vẹn → thêm field tuỳ chọn vào `CardRef` vẫn đi
  vòng được. Client cũ không gửi field mới vẫn hợp lệ.

## Mục tiêu

1. Lọc và sắp xếp chỗ ở bằng lời nói: khoảng giá (trên/dưới/trong khoảng), hạng sao, sắp xếp rẻ→đắt,
   đắt→rẻ, sao cao trước.
2. Câu tương đối so với kết quả vừa hiện: "đắt hơn", "rẻ hơn", "sang hơn" (sao cao hơn).
3. Responder thấy giá, số sao và thứ tự sắp xếp, nói được "căn rẻ nhất là [r1], 450.000đ/đêm".
   Mọi con số vẫn qua Verifier.
4. Responder viết lại câu hỏi lại và câu "chưa tìm thấy" cho tự nhiên. Câu cứng của code chỉ còn làm dự phòng.

## Không làm (non-goals)

- Không chuyển sang agent gọi tool tự do (tool-calling loop), không bỏ Controller/Verifier.
- Không gỡ các regex guard trong `controller.py` ở đợt này: chúng giữ ~100 kịch bản eval. Có thể làm sau, có eval đi kèm.
- Không lọc/sắp xếp chuyến bay (đã có `cheapest_only`), reel hay lộ trình.
- Không đổi API Core, không đổi contract event.

## Anti-goals (coi là hỏng dù chạy được)

- Tripi nói một giá, số sao hoặc tên không có trong kết quả Core.
- "Đắt hơn" mà vẫn trả lại đúng các căn vừa hiện, hoặc bị trần giá cũ chặn thành "không có".
- Câu hỏi lại sau khi viết lại mất ý hỏi hoặc tự thêm địa điểm.
- Điểm eval cũ tụt.

## Các hướng đã cân nhắc

| Hướng | Đánh đổi | Kết luận |
|---|---|---|
| **A. Controller thêm trường lọc/sắp xếp → code gửi Core; Responder thấy giá, có Verifier kiểm** | Ít đổi, giữ eval, số luôn đúng vì Core sắp xếp | **Bảo chọn** |
| B. Vẫn cấm giá, code tự viết câu "đã xếp từ rẻ đến đắt" | An toàn hơn nhưng vẫn cứng, không đạt mục tiêu 3–4 | Bỏ |
| C. Agent tool-calling, LLM tự gọi `search_stays(...)` | Linh hoạt nhất, nhưng phá luồng hiện tại, tăng độ trễ/chi phí, mất eval | Bỏ (trái "giữ luồng code") |

## Thiết kế (hướng A)

### 1. Controller v11 (`assistant-controller.v11.md`, giữ nguyên v10)
Thêm vào `ControllerOutput` (strict schema, mọi trường có mặt):
- `price_min_per_night: int | None`: "trên 1 triệu", "từ 800k".
- `stay_sort: Literal["none","price_asc","price_desc","stars_desc"]`.
- `price_relative: Literal["none","higher","lower"]`: "đắt hơn", "sang hơn về giá" → higher; "rẻ hơn" → lower.
- `min_stars: int | None` (1–5): "4 sao trở lên".

Prompt: "rẻ hơn/đắt hơn/xếp theo giá/4 sao" khi vừa hiện thẻ `stay` (`trip.lastCards` có kind stay)
là `find_stay` giữ nơi và ngày trong trip, không phải `search`. Khi đang có lộ trình (`planDays > 0`)
thì vẫn là `change_stay` như v10. Đưa vào input Controller: `lastCards` thêm `price` cho thẻ stay
(số đã có từ Core, không phải chữ người dùng viết).

### 2. Schemas
- `CardRef.price: int | None = None` và `CardRef.stars: int | None = None` (tuỳ chọn, tương thích ngược).
- `Understanding` thêm `price_min_per_night`, `stay_sort`, `price_relative`, `min_stars`.
- `TripContext.price_min_per_night`, `TripContext.min_stars` để giữ bộ lọc cho lượt sau như `price_max_per_night`.
- `Stay` đọc thêm `stars: int | None`, `rating: float | None`.
- Sinh lại `contracts/openapi/ai-service.json` bằng lệnh có sẵn của repo, không sửa tay.

### 3. Code đổi lời tương đối thành bộ lọc (`controller.to_understanding` hoặc hàm mới trong `skills/stay.py`)
Lấy giá các thẻ stay vừa hiện trong `trip.last_cards`:
- `higher`: `price_min = max(giá đã hiện) + 1`, bỏ `price_max` đang nhớ, sắp xếp mặc định `price_asc`
  (các căn đắt hơn gần nhất trước).
- `lower`: `price_max = min(giá đã hiện) - 1`, bỏ `price_min` đang nhớ, sắp xếp mặc định `price_desc`.
- Không có giá cũ (client cũ, thẻ cũ): `higher` → `price_desc`, `lower` → `price_asc`, không đặt mốc.
- Khi người dùng nói giá mới hoặc sắp xếp mới, giá trị mới thắng giá trị đang nhớ. Khoảng giá không
  hợp lệ (min > max) thì bỏ trần cũ.

### 4. Skill `search_stays`
Gửi `priceMin`, `priceMax`, `minStars`, `sort` (map `price_asc→price`, `price_desc→price_desc`,
`stars_desc→stars`). Giữ bước kiểm lại sau Core cho cả min, max và sao. Card thêm `stars` nếu Card có chỗ chứa;
không thì đưa vào facts. Câu `text` cố định nói đúng bộ lọc/thứ tự ("xếp từ rẻ đến đắt", "trên 1.000.000đ/đêm").
`no_result` gợi ý theo hướng: đã lọc "đắt hơn" mà hết thì nói "đây đã là nhóm đắt nhất còn phòng ngày đó".
`TripPlanner.stay_options` dùng chung skill nên cũng được hưởng, không sửa thêm.

### 5. Responder v5 (`assistant-responder.v5.md`, giữ v4)
- `build_facts` với thẻ stay: thêm `pricePerNight` (số), `priceText` ("450.000đ"), `stars`, và facts
  chung `{"type":"stay_filter","sort":...,"priceMin":...,"priceMax":...,"minStars":...}`.
- Prompt: được nói giá, nhưng chỉ chép đúng `priceText`. Được nói "rẻ nhất/đắt nhất" chỉ khi facts có
  sort tương ứng và nói về thẻ đầu danh sách. Vẫn cấm "sắp hết", "chỉ còn", "nhanh tay", "giá sốc".
- Verifier: bỏ "re nhat" khỏi SCARCITY **chỉ khi** facts có `stay_filter.sort` theo giá. Kiểm con số vẫn
  như cũ (số phải có trong facts).

### 6. Viết lại câu cứng
Trong `app/api/chat.py`, Responder cũng chạy cho `clarify` và `no_result` không có thẻ (trừ refusal/unsafe):
facts `[{"type":"fixed","answerKind":...,"fallback": text}]`. Prompt: viết lại cùng ý, ngắn, giọng Tripi;
`clarify` phải giữ đúng một câu hỏi. Verifier thêm quy tắc: với `clarify` phải còn dấu "?", không có
tên/số mới (grounding = `fallback`). Lỗi hoặc rỗng thì dùng câu cứng như hiện nay. Gợi ý (suggestions) giữ nguyên.

### 7. Eval và test
- Unit test: map tương đối → bộ lọc (có/không có giá cũ, trần cũ bị bỏ), tham số gửi Core, kiểm lại sau
  Core, facts có giá, Verifier cho/không cho "rẻ nhất", câu clarify viết lại mất "?" thì bị bỏ.
- Eval mới: `cases.v11.jsonl` (Controller: "đắt hơn", "rẻ hơn", "xếp từ rẻ đến đắt", "4 sao trở lên",
  "từ 1tr đến 2tr", "có căn nào sang hơn không") và `chains.v9.jsonl` (tìm KS Nha Trang → "đắt hơn" →
  "xếp từ rẻ nhất"). Chạy `uv run python evals/run_evals.py` trước/sau, ghi điểm vào evidence.
- Lệnh kiểm tra repo: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`.

## Để builder tự quyết
- Đặt hàm đổi lời tương đối ở đâu (khuyên đặt trong `skills/stay.py` để `controller.py` đỡ phình).
- `CardRef.price` lưu `price_from` dạng int VND.
- Chi tiết câu chữ trong prompt và tên test.

## Quyết định là của mình (Claude), Bảo kiểm lại khi đọc
- "Đắt hơn" sắp xếp mặc định rẻ→đắt trong nhóm đắt hơn; "rẻ hơn" sắp xếp đắt→rẻ trong nhóm rẻ hơn.
- Responder chạy thêm cho clarify sẽ thêm khoảng 1–2 giây cho các lượt đó; chấp nhận được, có `RESPONDER_MIN_SECONDS` chặn.
- Không gỡ regex guard ở đợt này.
