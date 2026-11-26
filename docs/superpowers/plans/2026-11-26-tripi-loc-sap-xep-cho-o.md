# Tripi lọc/sắp xếp chỗ ở + Responder tự nhiên hơn — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tripi hiểu "đắt hơn / rẻ hơn / xếp từ rẻ đến đắt / 4 sao trở lên" cho chỗ ở, nói được giá đúng từ Core, và viết lại câu hỏi lại bằng LLM.

**Architecture:** Giữ luồng Controller (LLM → JSON) → `Turn` gọi Core → Responder (LLM viết câu) → Verifier (code kiểm). Controller có thêm trường lọc/sắp xếp; code đổi lời tương đối thành `priceMin/priceMax` dựa trên giá các thẻ vừa hiện; Core (`/api/stays`) lọc và sắp xếp. Responder thấy giá qua `Answer.facts`.

**Tech Stack:** Python 3, FastAPI, Pydantic v2, httpx, pytest, uv, ruff, pyright.

**Spec:** `docs/superpowers/specs/2026-11-26-tripi-loc-sap-xep-cho-o-design.md`

## Global Constraints

- Đọc `RULES.md` trước. Nhánh `bao/TF31-tripi-loc-sap-xep` (đã tạo). Không push, không mở PR.
- Prompt có version: tạo `assistant-controller.v11.md`, `assistant-responder.v5.md`; **không sửa** v10, v4.
- Không sửa tay `contracts/`; sinh lại bằng `uv run python scripts/export_openapi.py` (xem script để biết cách dùng).
- Không thêm thư viện. Không sửa code BE/FE. Không xoá/skip/nới test cũ.
- Python `snake_case`, JSON wire `camelCase` (qua `WireModel` alias). Chữ hiện cho người dùng bằng tiếng Việt.
- Commit: `<type>(<scope>): <mô tả tiếng Việt>` + dòng trống + `Refs: TF31`. Scope: `agents`, `prompts`, `evals`, `contracts`. Không `Co-Authored-By`, không "Generated with". Không `git add -A`/`.`.
- Lệnh kiểm tra mỗi task: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q`.
- Core `/api/stays` nhận: `placeId, checkIn, checkOut, adults, priceMin?, priceMax?, minStars?, sort=price|price_desc|stars, limit 1–50`; trả `items[{hotelId, name, stars, unitPrice, totalPrice, rating, ...}]`.
- Giá trong câu cho người dùng viết bằng `vnd()` có sẵn (`450.000đ`).

## Review Focus

1. "Đắt hơn" khi trip còn nhớ trần giá cũ (`price_max_per_night=500000`) và các thẻ vừa hiện ≤ 500k → phải bỏ trần cũ, không trả "không có" (test ở Task 2).
2. "Đắt hơn" khi `last_cards` không có giá (client cũ) → không crash, sắp xếp `price_desc` (Task 2).
3. Người dùng nói "đắt hơn nhưng dưới 2tr" → giữ trần 2tr vì nó cao hơn mốc mới (Task 2).
4. Responder viết "rẻ nhất" khi kết quả không sắp xếp theo giá → Verifier bỏ câu đó (Task 3).
5. Câu clarify viết lại mất dấu "?" hoặc thêm địa danh mới → dùng câu cứng (Task 4).

---

### Task 0: Ghi điểm eval trước khi đổi

- [ ] **Step 1:** Trên nhánh hiện tại (chưa đổi code), chạy `uv run python evals/run_evals.py --out /tmp/claude-1000/-home-lnqb-Documents-tripflix-tripflix-ai/617111c4-928a-4b76-8d52-b89512c12f94/scratchpad/eval-before.json` (mặc định `--llm fake`). Đọc `evals/run_evals.py` và `evals/assistant/run.py` để biết các mode khác; nếu `OPENAI_API_KEY`/`DEEPSEEK_API_KEY` có trong môi trường (kiểm bằng `test -n "$OPENAI_API_KEY"`, **không in giá trị, không đọc `.env`**) thì chạy thêm mode live/chain một lần. Ghi lại tóm tắt điểm (lệnh + số) vào báo cáo task. Không commit gì.

### Task 1: Controller v11 hiểu lọc/sắp xếp chỗ ở

**Files:**
- Modify: `app/services/assistant/controller.py` (`ControllerOutput`, `to_understanding`)
- Modify: `app/services/assistant/schemas.py` (`Understanding`, `CardRef`)
- Modify: `app/services/assistant/understand.py` (`PROMPT` → v11; `build_understanding_input` thêm giá thẻ stay)
- Create: `app/prompts/assistant-controller.v11.md` (chép v10 rồi thêm phần mới)
- Test: `tests/assistant/test_stay_filters.py` (tạo mới)

**Interfaces — Produces:**
- `ControllerOutput` thêm (đều bắt buộc, strict schema): `price_min_per_night: int | None`, `stay_sort: Literal["none", "price_asc", "price_desc", "stars_desc"]`, `price_relative: Literal["none", "higher", "lower"]`, `min_stars: int | None`.
- `Understanding` thêm: `price_min_per_night: int | None = Field(default=None, ge=0)`, `stay_sort: Literal["none","price_asc","price_desc","stars_desc"] = "none"`, `price_relative: Literal["none","higher","lower"] = "none"`, `min_stars: int | None = Field(default=None, ge=1, le=5)`.
- `CardRef` thêm `price: int | None = Field(default=None, ge=0)`.
- `TripContext` thêm `price_min_per_night: int | None = Field(default=None, ge=0)`, `min_stars: int | None = Field(default=None, ge=1, le=5)`.

- [ ] **Step 1: Write failing tests** trong `tests/assistant/test_stay_filters.py`. Dựng `ControllerOutput` theo cách các test hiện có làm (tìm helper `plan(...)`/`out(...)` trong `tests/assistant/test_report_regressions.py` hoặc `tests/test_chat.py`):
  - `test_to_understanding_reads_stay_filters`: out `find_stay`, `price_min_per_night=1_000_000`, `stay_sort="price_asc"`, `min_stars=4`, `price_relative="higher"` → `Understanding` có đúng 4 giá trị đó.
  - `test_to_understanding_drops_bad_stars_and_price`: `min_stars=7` → `None`; `price_min_per_night=0` → lấy `trip.price_min_per_night` (giống cách `price_max_per_night` đang làm).
  - `test_to_understanding_falls_back_to_trip_min_filters`: out không nói giá sàn/sao, `trip.price_min_per_night=800_000, trip.min_stars=3` → understanding có 800_000 và 3.
  - `test_controller_input_has_stay_card_prices`: `TripContext(last_cards=[CardRef(ref="r1", kind="stay", id="h1", title="A", price=450_000), CardRef(ref="r2", kind="video", id="p1", title="B")])` → JSON của `build_understanding_input` có `lastCards == [{"ref":"r1","kind":"stay","price":450000},{"ref":"r2","kind":"video"}]` (không có key `price` cho thẻ không phải stay hoặc khi giá None).
- [ ] **Step 2:** Run `uv run pytest tests/assistant/test_stay_filters.py -q` → FAIL.
- [ ] **Step 3:** Thêm field, map trong `to_understanding` (min_stars ngoài 1–5 → None; giá ≤0 → fallback trip), cập nhật `build_understanding_input`. Tạo prompt v11 = v10 + mục mới:
  - Mô tả 4 trường mới với ví dụ: "trên 1 triệu" → `price_min_per_night` 1000000; "từ 1tr đến 2tr" → min 1000000, max 2000000; "xếp từ rẻ đến đắt"/"rẻ nhất trước" → `price_asc`; "đắt nhất trước" → `price_desc`; "sao cao nhất trước" → `stars_desc`; "4 sao trở lên" → `min_stars` 4; "đắt hơn", "xịn hơn", "cao cấp hơn" → `price_relative` higher; "rẻ hơn", "mềm hơn" → lower.
  - Quy tắc: `trip.lastCards` có thẻ `kind` "stay" và tin nhắn chỉ lọc/sắp xếp/so sánh ("căn đắt hơn", "xếp theo giá", "có căn 5 sao không") → `find_stay`, giữ `place` của trip, `day_ref` "none". Có lộ trình (`planDays > 0`) thì vẫn `change_stay` như v10.
  - Ví dụ: `"tìm căn đắt hơn"` (trip.place Nha Trang, lastCards stay) → `{"intent":"find_stay","place":"Nha Trang","price_relative":"higher"}`; `"xếp từ rẻ nhất đến đắt nhất"` → `{"intent":"find_stay","place":"Nha Trang","stay_sort":"price_asc"}`; `"có căn nào 4 sao trở lên không"` → `{"intent":"find_stay","place":"Nha Trang","min_stars":4}`.
  - Đổi `PROMPT` trong `understand.py` sang v11. Kiểm `apply_guards` không ép các câu trên sang intent khác (nếu ép, thêm điều kiện hẹp, có test).
- [ ] **Step 4:** Chạy lệnh kiểm tra đầy đủ (Global Constraints) → PASS. Nếu test cũ so sánh nguyên JSON input của Controller thì cập nhật kỳ vọng cho đúng key mới, **không** xoá test.
- [ ] **Step 5: Commit** `feat(agents): controller v11 hiểu lọc giá, sao và sắp xếp chỗ ở`.

### Task 2: Đổi lời tương đối thành bộ lọc và gửi Core

**Files:**
- Modify: `app/services/assistant/skills/stay.py`
- Modify: `app/services/assistant/schemas.py` (`Stay` thêm `stars: int | None = None`, `rating: float | None = None`)
- Modify: `app/services/assistant/turn.py` (`_stay` gọi refine; `next_trip` lưu bộ lọc và giá thẻ)
- Modify: `contracts/openapi/ai-service.json` (chỉ bằng script sinh)
- Test: `tests/assistant/test_stay_filters.py`

**Interfaces:**
- Consumes: các field ở Task 1.
- Produces: `refine_stay_filters(understood: Understanding, shown: list[CardRef]) -> Understanding` trong `skills/stay.py` (trả bản copy, không sửa input). `STAY_SORT_PARAM = {"price_asc": "price", "price_desc": "price_desc", "stars_desc": "stars"}`.

Quy tắc `refine_stay_filters` (giá các thẻ `kind == "stay"` có `price` trong `shown`):
- `higher` có giá: `price_min = max(giá) + 1`; nếu `price_max` đang có và `<= price_min` thì bỏ (`None`); `stay_sort` "none" → "price_asc".
- `lower` có giá: `price_max = min(giá) - 1`; nếu `price_min` đang có và `>= price_max` thì bỏ; sort "none" → "price_desc".
- `higher` không có giá → sort "price_desc"; `lower` không có giá → "price_asc"; không đặt mốc.
- `none`: chỉ bỏ cặp không hợp lệ `price_min > price_max` bằng cách bỏ `price_max`.

- [ ] **Step 1: Write failing tests** (dùng `FakeCore` + `run_turn` như `tests/assistant/test_report_regressions.py` để kiểm params gửi Core):
  - `test_higher_drops_remembered_cap`: `Understanding(find_stay, price_relative="higher", price_max_per_night=500_000)`, shown giá 300_000/450_000 → `price_min_per_night == 450_001`, `price_max_per_night is None`, `stay_sort == "price_asc"`.
  - `test_higher_keeps_explicit_cap_above_new_floor`: price_max 2_000_000, shown 450_000 → min 450_001, max 2_000_000.
  - `test_lower_sets_cap_below_cheapest`: shown 300_000/450_000 → max 299_999, sort "price_desc".
  - `test_relative_without_prices_only_sorts`: shown CardRef stay không có price → higher → sort "price_desc", min None.
  - `test_stay_search_sends_filters_to_core`: chạy turn `find_stay` Nha Trang có `price_min_per_night=1_000_000, min_stars=4, stay_sort="price_asc"` → params `/api/stays` có `priceMin=1000000, minStars=4, sort="price"`; không có `sort` khi "none".
  - `test_stay_search_rechecks_floor_and_stars`: Core trả 1 căn dưới `priceMin` và 1 căn `stars=3` khi `minStars=4` → cả hai bị loại khỏi thẻ.
  - `test_next_trip_keeps_card_prices_and_filters`: sau lượt tìm phòng, `next_trip(answer).last_cards[0].price == int(card.price_from)`, `price_min_per_night` và `min_stars` được nhớ.
  - `test_turn_higher_after_capped_search`: trip có `price_max_per_night=500_000`, `last_cards` stay giá 450_000, Controller trả `find_stay` + `higher` → Core nhận `priceMin=450001` và **không** có `priceMax`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. `search_stays`: gửi `priceMin`, `priceMax`, `minStars`, `sort` (chỉ khi có), `limit` giữ 5; kiểm lại sau Core cả min/max/sao. Text cố định nói đúng bộ lọc: thêm cụm "xếp từ rẻ đến đắt" / "xếp từ đắt đến rẻ" / "sao cao trước", "trên {vnd(min)}/đêm", "từ {n} sao". `no_result` khi `price_relative == "higher"`: "Ngày đó chưa có chỗ nào còn phòng đắt hơn các căn vừa rồi, đây đã là nhóm cao nhất Tripi thấy." (gợi ý `["Xem căn rẻ hơn", "Đổi ngày"]`); `lower`: tương tự với "rẻ hơn". `Turn._stay` gọi `refine_stay_filters(parsed, self.memory.last_cards)` trước khi tìm. `next_trip`: `CardRef.price = int(c.price_from)` cho thẻ stay có giá; nhớ `price_min_per_night`, `min_stars` như `price_max_per_night`. Thẻ "stay" từ `TripPlanner.stay_options` dùng chung `search_stays`, không cần sửa thêm.
- [ ] **Step 4:** Sinh lại contract (`scripts/export_openapi.py`), chạy lệnh kiểm tra đầy đủ → PASS.
- [ ] **Step 5: Commit** hai commit: `feat(agents): lọc chỗ ở đắt hơn, rẻ hơn theo thẻ vừa hiện` (code + test) và `build(contracts): sinh lại openapi cho bộ lọc chỗ ở` (chỉ `contracts/`).

### Task 3: Responder thấy giá, Verifier cho "rẻ nhất" khi có sắp xếp

**Files:**
- Modify: `app/services/assistant/skills/stay.py` (`search_stays` điền `Answer.facts`)
- Modify: `app/services/assistant/verifier.py`
- Modify: `app/services/assistant/responder.py` (`PROMPT` → v5)
- Create: `app/prompts/assistant-responder.v5.md` (chép v4, sửa phần giá)
- Test: `tests/assistant/test_stay_filters.py`, test verifier hiện có (tìm `tests/**/test_verifier*.py`)

**Interfaces — Produces:** facts của lượt tìm phòng:
- mỗi căn: `{"ref": "r1", "kind": "stay", "title": name[:80], "pricePerNight": int, "priceText": vnd(int), "stars": int|None, "rating": float|None}`
- một dòng: `{"type": "stay_filter", "sort": stay_sort, "priceMin": int|None, "priceMax": int|None, "minStars": int|None, "relative": price_relative}`

- [ ] **Step 1: Write failing tests:**
  - `test_stay_answer_facts_have_prices_and_filter`: answer.facts có 2 dạng trên, `priceText == "450.000đ"`.
  - `test_verifier_allows_cheapest_when_sorted_by_price`: facts có `stay_filter.sort="price_asc"` + stay r1 450000 → câu "Căn rẻ nhất là [r1], 450.000đ/đêm nè." được giữ.
  - `test_verifier_drops_cheapest_without_price_sort`: `sort="none"` → câu đó bị bỏ, rule `scarcity` (hoặc tên rule hiện có).
  - `test_verifier_drops_invented_price`: "[r1] chỉ 300.000đ/đêm" khi facts 450000 → bị bỏ.
  - `test_verifier_still_drops_scarcity_words`: "sắp hết phòng", "nhanh tay" vẫn bị bỏ dù có sort.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Verifier: tách "re nhat" khỏi `SCARCITY` thành `CHEAPEST = re.compile(r"\b(re nhat|dat nhat)\b")`, chỉ chấp nhận khi có fact `type == "stay_filter"` với `sort in {"price_asc","price_desc"}`. Kiểm số giữ nguyên cơ chế cũ. Prompt v5 (đổi so với v4): bỏ "Không bao giờ nói giá tiền"; thay bằng: được nói giá một đêm **chỉ khi chép đúng `priceText`** của căn đó; "rẻ nhất/đắt nhất" chỉ khi `stay_filter.sort` theo giá và nói về căn đầu danh sách; khi `relative` higher/lower thì nói đây là các căn đắt/rẻ hơn lần trước; vẫn cấm "sắp hết", "chỉ còn", "nhanh tay", "giá sốc", số phòng còn lại, giảm giá. Thêm 1 ví dụ stay có giá. Sửa comment `Answer.facts` trong `schemas.py` ("never prices") cho đúng.
- [ ] **Step 4:** Lệnh kiểm tra đầy đủ → PASS.
- [ ] **Step 5: Commit** `feat(agents): responder v5 nói giá chỗ ở đã kiểm, cho phép "rẻ nhất" khi đã xếp`.

### Task 4: Responder viết lại câu hỏi lại và câu "chưa tìm thấy"

**Files:**
- Modify: `app/services/assistant/responder.py` (`build_facts`, `respond`)
- Modify: `app/api/chat.py` (điều kiện gọi Responder, quanh dòng 263–270)
- Modify: `app/prompts/assistant-responder.v5.md` (thêm mục "fixed")
- Test: `tests/test_chat.py` hoặc `tests/assistant/test_responder*.py` (theo chỗ test responder hiện có)

**Interfaces — Produces:** fact `{"type": "fixed", "answerKind": "clarify"|"no_result", "fallback": answer.text}` do `build_facts` tạo khi answer không có cards/facts và `kind in {"clarify","no_result"}`.

- [ ] **Step 1: Write failing tests** (LLM giả theo cách test responder hiện có làm):
  - `test_clarify_is_rewritten`: answer clarify "Bạn muốn đi đâu?", LLM trả `["Bạn đang tính đi đâu chơi nè?"]` → respond trả câu đó.
  - `test_clarify_rewrite_without_question_mark_falls_back`: LLM trả `["Mình tìm cho bạn nha."]` → `None`.
  - `test_clarify_rewrite_with_new_place_falls_back`: fallback không có địa danh, LLM trả "Bạn muốn đi Phú Quốc không?" → `None`.
  - `test_fixed_rewrite_keeps_at_most_two_sentences`.
  - `test_chat_calls_responder_for_clarify` (theo kiểu test SSE trong `tests/test_chat.py`): turn trả clarify, LLM bật → Responder được gọi; `refusal` thì **không** gọi.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. `chat.py`: cho phép `answer.kind in {"answer","no_result","clarify"}` và điều kiện `(off_topic or cards or facts or kind in {"clarify","no_result"})`; giữ `parsed is not None` và `RESPONDER_MIN_SECONDS`. `respond`: với fact `fixed`, giữ tối đa 2 câu; `clarify` cần ít nhất một câu kết bằng "?"; Verifier chạy như cũ với `extra_grounding` gồm fallback (từ mới không có trong fallback/question/place bị bỏ theo luật tên hiện có); rỗng → `None`. Prompt mục mới: "facts có type fixed: viết lại `fallback` cùng ý, giọng Tripi, tối đa 2 câu; clarify giữ đúng một câu hỏi; không thêm địa điểm, số, ngày". `answer.kind`, `suggestions`, `awaiting` không đổi.
- [ ] **Step 4:** Lệnh kiểm tra đầy đủ → PASS.
- [ ] **Step 5: Commit** `feat(agents): responder viết lại câu hỏi lại và câu chưa tìm thấy`.

### Task 5: Eval mới, điểm trước/sau, evidence

**Files:**
- Create: `evals/assistant/cases.v11.jsonl` (chép v10 + case mới), `evals/assistant/chains.v9.jsonl` (chép v8 + chain mới) — xem cách `run.py` chọn version mới nhất; nếu hard-code version thì cập nhật.
- Create: `docs/evidence/TF31-loc-sap-xep-cho-o.md` (mẫu ở `RULES.md` §7)

- [ ] **Step 1:** Thêm ≥8 case Controller: "tìm căn đắt hơn", "có chỗ nào rẻ hơn không" (không có lộ trình → find_stay), "xếp từ rẻ nhất đến đắt nhất", "đắt nhất trước", "4 sao trở lên", "từ 1tr đến 2tr một đêm", "căn nào xịn hơn", "có chỗ nào rẻ hơn không" khi `planDays>0` → change_stay. Thêm 1 chain: "tìm khách sạn Nha Trang 20/12-22/12" → "tìm căn đắt hơn" → "xếp từ rẻ đến đắt".
- [ ] **Step 2:** Chạy cùng các lệnh eval như Task 0 → ghi điểm sau. Điểm case cũ không được tụt; nếu tụt, báo lại thay vì sửa case.
- [ ] **Step 3:** Viết evidence (bảng trước/sau, lệnh kiểm tra + số test pass, "Ảnh hưởng tới phần của người khác: Không — chỉ tripflix-ai; FE nhận thêm field tuỳ chọn `lastCards[].price`, `priceMinPerNight`, `minStars` trong `trip`").
- [ ] **Step 4:** Lệnh kiểm tra đầy đủ → PASS.
- [ ] **Step 5: Commit** `test(evals): case lọc và sắp xếp chỗ ở cho controller v11` và `docs(evidence): lọc, sắp xếp chỗ ở và responder tự nhiên (TF31)`.
