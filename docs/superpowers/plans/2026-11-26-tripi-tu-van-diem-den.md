# Tripi tư vấn điểm đến (consult) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Với câu mơ hồ hoặc kể tâm trạng mà chưa có nơi đến, Tripi tư vấn bằng LLM (hỏi gì, khi nào gợi ý là do LLM tự quyết), nhớ sở thích, và chỉ gợi ý điểm đến có trong danh mục.

**Architecture:** Controller v12 thêm intent `consult`. `Turn` gọi một hàm `consult` được truyền vào (Tư vấn LLM, dùng lại client Responder), hàm trả `Answer` + `TravelPrefs`. Code kiểm id trong danh mục, chạy Verifier, tạo chip, ghép prefs vào trip memory. Lượt consult không gọi Responder.

**Tech Stack:** Python 3, FastAPI, Pydantic v2, httpx, PyYAML (đã có, xem cách `packing.v2.yaml` được đọc), pytest, uv, ruff, pyright.

**Spec:** `docs/superpowers/specs/2026-11-26-tripi-tu-van-diem-den-design.md`

## Global Constraints

- Đọc `RULES.md`. Nhánh `bao/TF31-tripi-tu-van` (tách từ `bao/TF31-tripi-loc-sap-xep`, đã tạo). Không push, không mở PR.
- Prompt có version: tạo `assistant-controller.v12.md` và `assistant-consultant.v1.md`. **Không sửa** v11/v5.
- Không thêm thư viện. Không sửa BE/FE. Không xoá, skip hay nới test cũ. Case eval cũ đổi kỳ vọng thì liệt kê từng case trong report và evidence.
- Không thêm giá trị `step` mới vào usage event; lượt tư vấn ghi `step="responder"`.
- `contracts/` chỉ sinh lại bằng `PYTHONPATH=. uv run python scripts/export_openapi.py`.
- Commit: `<type>(<scope>): <mô tả tiếng Việt>` + dòng trống + `Refs: TF31`. Không `git add -A`/`.`. Không thêm `docs/research/`, `.fast/`.
- Kiểm tra mỗi task: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q` và `uv run python -m evals.assistant.run` (đang là 180/180).
- Literal dùng chung: `Vibe = Literal["quiet","lively","romantic","adventure","healing","foodie","nightlife"]`, `Terrain = Literal["beach","mountain","island","city","countryside","lake"]`, `Companions = Literal["solo","couple","friends","family","kids"]`.
- Câu dự phòng (chép đúng): `"Bạn đang muốn một chuyến yên tĩnh để nghỉ ngơi hay sôi động cho vui? Thích biển hay núi nè?"`, chip `["Yên tĩnh, chill", "Sôi động", "Biển", "Núi"]`.

## Review Focus

1. LLM trả `destination_ids` lạ hoặc nêu tên ngoài danh mục trong câu → bị bỏ; không còn câu thì dùng câu dự phòng (Task 3).
2. Người dùng đã có prefs, lượt sau nói "đổi sang núi" → `terrain` mới thắng, `vibe` cũ giữ nguyên (Task 1 `merge_prefs`, Task 4).
3. Lượt consult không làm `memory.asked` thành True (kind "answer"); lượt tìm phòng sau đó vẫn hỏi ngày (Task 4).
4. LLM hết giờ hoặc lỗi → dùng câu dự phòng, `degraded` có `consult`, không gọi search (Task 4).
5. "Tìm reel cuối tuần đi đâu" vẫn là `find_reel`; "Đà Lạt cuối tuần chơi gì" vẫn là `search` (Task 2).

---

### Task 1: Danh mục điểm đến và sở thích trong trip memory

**Files:**
- Create: `app/services/assistant/destinations.v1.yaml`, `app/services/assistant/destinations.py`
- Modify: `app/services/assistant/schemas.py` (`TravelPrefs`, `TripContext.prefs`, `Awaiting.intent` thêm `"consult"`)
- Modify: `contracts/openapi/ai-service.json` (sinh lại)
- Test: `tests/assistant/test_consult.py` (tạo mới)

**Interfaces — Produces:**
- `class Destination(BaseModel)`: `id: str` (kebab-case), `name: str`, `region: Literal["bac","trung","nam","tay-nguyen"]`, `terrain: list[Terrain]`, `vibe: list[Vibe]`, `good_months: list[int]` (1–12), `highlights: list[str]` (2–4 cụm, không chữ số).
- `destinations_by_id() -> dict[str, Destination]` (`@cache`, đọc YAML cạnh file, validate; id trùng thì raise `ValueError`).
- `class TravelPrefs(WireModel)`: `vibe: list[Vibe] = Field(default_factory=list, max_length=3)`, `terrain: list[Terrain]` (≤3), `companions: Companions | None = None`, `budget_per_person: int | None = Field(None, ge=0)`, `nights: int | None = Field(None, ge=0, le=14)`, `mood: str = Field("", max_length=60)`.
- `merge_prefs(old: TravelPrefs | None, new: TravelPrefs) -> TravelPrefs` trong `destinations.py`: trường có giá trị (list không rỗng, khác None, chuỗi không rỗng) ở `new` thắng; còn lại giữ `old`.
- `TripContext.prefs: TravelPrefs | None = None`.

- [ ] **Step 1: Write failing tests:**
  - `test_catalog_loads_and_is_valid`: ≥40 mục; id duy nhất, khớp `^[a-z0-9-]+$`; `name` không rỗng; tháng trong 1–12; highlights 2–4 mục, không chứa chữ số; có ít nhất một mục cho mỗi `region`.
  - `test_catalog_has_core_places`: có `da-lat`, `vung-tau`, `nha-trang`, `da-nang`, `phu-quoc`, `quy-nhon`, `sa-pa`, `ha-giang`, `hoi-an`, `ninh-binh` (tên trùng cách Core/transport.v1.yaml viết: "Đà Lạt", "Vũng Tàu", "Sa Pa"…).
  - `test_merge_prefs_new_wins_empty_keeps_old`: old `vibe=["quiet"], terrain=["beach"]`, new `terrain=["mountain"]` → `vibe==["quiet"]`, `terrain==["mountain"]`; `merge_prefs(None, new) == new`.
  - `test_trip_context_round_trips_prefs`: `TripContext(prefs=TravelPrefs(vibe=["quiet"]))` dump `by_alias=True` rồi validate lại ra cùng giá trị; JSON key là `prefs.vibe`, `budgetPerPerson`.
- [ ] **Step 2:** Run `uv run pytest tests/assistant/test_consult.py -q` → FAIL.
- [ ] **Step 3:** Implement. Viết YAML 40–50 nơi theo comment-header kiểu `transport.v1.yaml` (dữ liệu tham khảo, không giá/giờ/sự kiện có ngày, **chờ Bảo duyệt**). Đọc YAML theo cách module packing đang làm.
- [ ] **Step 4:** Sinh lại contract; lệnh kiểm tra đầy đủ → PASS.
- [ ] **Step 5: Commit** `feat(agents): danh mục điểm đến và sở thích chuyến đi trong trip memory`, rồi `build(contracts): sinh lại openapi cho sở thích chuyến đi` (chỉ `contracts/`, bỏ qua nếu không có diff).

### Task 2: Controller v12 có intent `consult`

**Files:**
- Modify: `app/services/assistant/controller.py` (`ControllerOutput.intent`, guard quanh dòng 817 và 819–825), `app/services/assistant/schemas.py` (`Understanding.intent`), `app/services/assistant/understand.py` (`PROMPT` → v12; input có `trip.prefs`)
- Create: `app/prompts/assistant-controller.v12.md` (chép v11 + mục consult)
- Test: `tests/assistant/test_consult.py`

**Interfaces — Produces:** `"consult"` có trong cả hai Literal intent. Input Controller có `trip.prefs` (dump `by_alias`, `None` khi chưa có).

- [ ] **Step 1: Write failing tests** (theo cách test guard hiện có gọi `apply_guards`/`to_understanding`):
  - `test_long_social_message_without_place_becomes_consult`: out `intent="off_topic"` hoặc `"ack"` với message "tôi vừa thất nghiệp buồn quá muốn tìm chỗ đi chơi cuối tuần" → `consult`.
  - `test_idea_clarify_without_place_becomes_consult`: out `clarify`, place "", message "vậy đi biển đâu cho chill" → `consult` (trước đây là `search`).
  - `test_idea_with_place_stays_search`: "đà lạt cuối tuần chơi gì", place "Đà Lạt" → không phải `consult`.
  - `test_reel_request_stays_find_reel`: out `find_reel`, "tìm reel cuối tuần đi đâu" → `find_reel`.
  - `test_awaiting_consult_short_reply_is_consult`: `awaiting=Awaiting(intent="consult", missing="place")`, message "chill thôi", out `search` → `consult`.
  - `test_controller_input_has_prefs`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Guard 817: tin nhắn dài, không có nơi đến và có cue đi chơi (`TRAVEL_CUE` hoặc `SUGGEST_CUE` hoặc "đi chơi/đi đâu/xả stress") → `consult`; các trường hợp khác giữ `search` như cũ. Guard 819–825: chưa có nơi đến → `consult`. Awaiting consult: theo cách awaiting các intent khác đang được ưu tiên trong `apply_guards`. Prompt v12: định nghĩa `consult` theo spec §2, kèm ví dụ: `"cuối tuần đi đâu chơi"` → consult; `"tôi vừa thất nghiệp, buồn quá, muốn đi đâu đó cuối tuần"` → consult; `"đi đâu chill chill"` → consult; `"chill thôi"` (awaiting consult) → consult; phản ví dụ: `"tìm reel cuối tuần đi đâu"` → find_reel; `"đà lạt cuối tuần chơi gì"` → search; `"chán quá à"` → off_topic.
- [ ] **Step 4:** Lệnh kiểm tra đầy đủ. Case eval cũ nào đổi từ `search` sang `consult`: **không sửa case**; ghi danh sách vào report (id case, message, kỳ vọng cũ) và để Task 4 xử lý sau khi Turn có route consult.
- [ ] **Step 5: Commit** `feat(agents): controller v12 nhận ra lượt cần tư vấn điểm đến`.

### Task 3: Vai Tư vấn (LLM) và kiểm đầu ra

**Files:**
- Create: `app/services/assistant/consultant.py`, `app/prompts/assistant-consultant.v1.md`
- Test: `tests/assistant/test_consult.py`

**Interfaces:**
- Consumes: `destinations_by_id`, `TravelPrefs` (Task 1); `get_role_llm("responder")` (`understand.py`); `verify` (`verifier.py`); `mask_pii`; `strict_json_schema`.
- Produces:
  - `class ConsultOutput(BaseModel)`: `sentences: list[str]` (≤4), `prefs: TravelPrefs`, `destination_ids: list[str]` (≤3), `chips: list[str]` (≤4), `is_done_asking: bool`.
  - `async def consult(request: ChatRequest, trip: TripContext, *, today: date, on_usage: Callable[[LlmResult], None] | None = None) -> tuple[Answer, TravelPrefs]`. Lỗi provider, JSON hỏng hoặc output bị cắt thì raise; caller sẽ dùng câu dự phòng.
  - `def fallback_consult_answer() -> Answer` (câu và chip dự phòng ở Global Constraints, `kind="answer"`, facts `[{"type":"consult","fallback":True}]`).
  - `CONSULT_FACT = "consult"`: mọi answer của module có fact `{"type": "consult", ...}`.

- [ ] **Step 1: Write failing tests** (LLM giả theo cách `tests/test_chat_two_agents.py` giả Responder):
  - `test_consult_asks_with_llm_chips`: LLM trả 1 câu hỏi, `destination_ids=[]`, chips `["Yên tĩnh thôi","Biển nha"]` → `answer.text` là câu đó, `suggestions` là 2 chip, prefs trả về đúng.
  - `test_consult_suggests_and_code_builds_chips`: ids `["quy-nhon","nha-trang"]` → suggestions `["Xem reel Quy Nhơn","Tìm phòng Quy Nhơn","Lên lịch trình Quy Nhơn","Nơi khác nha"]`.
  - `test_consult_drops_unknown_ids`: `["atlantis","quy-nhon"]` → chỉ còn Quy Nhơn.
  - `test_consult_drops_sentence_with_place_outside_catalog`: câu "Đi Bali đi bạn" bị bỏ; câu còn lại giữ.
  - `test_consult_all_dropped_uses_fallback`: mọi câu trượt → `answer == fallback_consult_answer()` (so text và suggestions), log `chat.consult.fallback`.
  - `test_consult_input_masks_pii_and_has_catalog`: payload gửi LLM có `catalog` chứa mọi id, `message` đã che PII.
  - `test_consult_raises_on_cut_output`: `finish_reason == "length"` → raise `ValueError`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement theo spec §4. Grounding cho `verify`: facts = các mục đã gợi ý (`dump`) cộng prefs; khi chưa gợi ý thì facts = cả catalog rút gọn; `extra_grounding` = `trip.origin_city` + `trip.place`. Chip của LLM cũng qua `verify` (chip trượt thì bỏ). Prompt v1 viết theo spec §4 (đồng cảm ngắn; LLM tự chọn hỏi gì, tối đa 2 ý mỗi lượt; đổi cách hỏi; có prefs thì có thể hỏi xác nhận hoặc dùng luôn; "gợi ý luôn" hoặc đã có vibe/địa hình thì gợi ý; tên chỉ lấy từ catalog; không giá, giờ, sự kiện, con số ngoài catalog; ưu tiên `goodMonths` có tháng hiện tại; giọng Tripi như responder v5). Thêm 3–4 ví dụ đa dạng (than buồn, xin ý tưởng ngắn, đã có prefs cũ, "gợi ý luôn đi").
- [ ] **Step 4:** Lệnh kiểm tra đầy đủ → PASS.
- [ ] **Step 5: Commit** `feat(agents): vai tư vấn điểm đến bằng LLM, chỉ gợi ý trong danh mục`.

### Task 4: Nối Tư vấn vào lượt chat

**Files:**
- Modify: `app/services/assistant/turn.py` (tham số `consult`, route, `SKILL_SECONDS_BY_NAME["consult"] = 6.0`, `LABELS["consult"]`, `next_trip`: prefs + awaiting), `app/api/chat.py` (truyền `consult`; không gọi Responder khi có fact consult)
- Modify: case eval cũ trong danh sách của Task 2, **chỉ khi** route consult làm chúng đổi hành vi. Mỗi case đổi kỳ vọng ghi vào report.
- Test: `tests/assistant/test_consult.py`, `tests/test_chat_switches.py` (hoặc file SSE có sẵn)

**Interfaces — Consumes:** `consult`, `fallback_consult_answer` (Task 3); `merge_prefs` (Task 1). `Turn.__init__(..., consult: Callable[[ChatRequest, TripContext], Awaitable[tuple[Answer, TravelPrefs]]] | None = None)`. chat.py truyền `partial(consultant.consult, today=today_in_vietnam(), on_usage=partial(add_usage, "responder"))` khi LLM bật; tắt thì truyền `None`.

- [ ] **Step 1: Write failing tests:**
  - `test_turn_routes_consult_without_search`: parsed `consult`, FakeCore không có route nào → answer từ hàm consult giả; Core không bị gọi.
  - `test_turn_consult_none_uses_fallback`: `consult=None` → `fallback_consult_answer()`.
  - `test_turn_consult_error_degrades`: hàm giả raise `httpx.HTTPError` hoặc timeout → câu dự phòng, `"consult" in turn.degraded`.
  - `test_next_trip_merges_prefs_and_awaits_consult`: hàm giả trả prefs `terrain=["beach"]`, không có điểm đến, memory có `vibe=["quiet"]` → `next_trip.prefs` có cả hai; `awaiting.intent == "consult"`; `asked` vẫn False.
  - `test_next_trip_no_awaiting_after_suggestion`: có điểm đến → `awaiting is None`.
  - `test_stay_after_consult_still_asks_dates`: memory sau lượt consult, lượt sau `find_stay` không có ngày → `kind == "clarify"`.
  - `test_chat_consult_calls_llm_once_no_responder` (SSE): lượt consult gọi hàm consult một lần, Responder không được gọi, usage ghi `step="responder"`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Route `intent == "consult"` trong `_answer`, đặt **sau** các nhánh unsafe/refusal/off_topic hiện có và **trước** `_fixed`. Hàm consult chạy qua `_run_value("consult", ...)`; `None` → fallback. Turn giữ `self.learned_prefs`; `next_trip` ghép bằng `merge_prefs`. Awaiting consult đặt khi answer có fact consult mà không có điểm đến (đưa `has_suggestions: bool` vào fact consult ở Task 3; nếu Task 3 chưa có thì thêm vào). Cập nhật `SOCIAL`/`AWAITABLE` nếu cần để `consult` không bị coi là social.
- [ ] **Step 4:** Lệnh kiểm tra đầy đủ + eval. Ghi điểm eval và danh sách case đổi kỳ vọng (id, message, cũ → mới, vì sao) vào report.
- [ ] **Step 5: Commit** `feat(agents): nối tư vấn điểm đến vào lượt chat, nhớ sở thích`.

### Task 5: Eval và evidence

**Files:**
- Create: `evals/assistant/cases.v12.jsonl`, `evals/assistant/chains.v10.jsonl` (chỉ case mới, giống v11/v9); Modify `evals/assistant/run.py` (thêm v12, chain v10)
- Create: `docs/evidence/TF31-tu-van-diem-den.md` (mẫu RULES §7)

- [ ] **Step 1:** Case mới: "cuối tuần đi đâu chơi", "tôi vừa thất nghiệp buồn quá muốn đi đâu đó cuối tuần", "đi đâu chill chill", "muốn đi biển mà chưa biết đi đâu", "chill thôi" (awaiting consult), "gợi ý luôn đi" (awaiting consult), "tìm reel cuối tuần đi đâu" → find_reel, "đà lạt cuối tuần chơi gì" → search. Chain 3 lượt: than buồn → "yên tĩnh, thích biển" → "Tìm phòng Quy Nhơn" (find_stay, place Quy Nhơn).
- [ ] **Step 2:** Chạy eval ci, ghi điểm trước (180/180) và sau.
- [ ] **Step 3:** Evidence: đã làm; bảng case đổi kỳ vọng (từ report Task 2/4); lệnh live cho Bảo (`--mode live`, `--mode chain`); việc Bảo phải làm: duyệt `destinations.v1.yaml`, thử `/api/suggest?q=<name>&types=place` trên staging cho mọi `name`; giới hạn: prefs chỉ lưu trên máy 7 ngày, chưa có API BE; lượt consult dùng `step="responder"`; ảnh hưởng FE: field tuỳ chọn mới `trip.prefs`, `awaiting.intent="consult"`.
- [ ] **Step 4:** Lệnh kiểm tra đầy đủ → PASS.
- [ ] **Step 5: Commit** `test(evals): case tư vấn điểm đến cho controller v12` và `docs(evidence): tư vấn điểm đến bằng hội thoại (TF31)`.
