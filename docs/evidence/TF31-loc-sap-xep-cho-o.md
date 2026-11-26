# TF31 — Lọc, sắp xếp chỗ ở và Responder nói tự nhiên hơn

- Notion: Chưa có link Notion (chờ Bảo dán) · Nhánh: `bao/TF31-tripi-loc-sap-xep` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-26

## Đã làm

- **Controller v11** (`app/prompts/assistant-controller.v11.md`, v10 giữ nguyên): thêm 4 trường `price_min_per_night`, `stay_sort`, `price_relative`, `min_stars` để hiểu "từ 1tr", "4 sao trở lên", "xếp từ rẻ đến đắt", "tìm căn đắt hơn". `to_understanding` map các trường này; số sao ngoài 1–5 và giá sàn không dương bị bỏ.
- **Lọc và sắp xếp chỗ ở** (`skills/stay.py`): `refine_stay_filters` đổi "đắt hơn"/"rẻ hơn" thành mốc giá lấy từ giá các thẻ vừa hiện (`lastCards[].price`), bỏ trần/sàn giá cũ chỉ khi nó là giá đang nhớ hoặc mâu thuẫn mốc mới. Gửi cho Core `priceMin`, `priceMax`, `minStars`, `sort`; kiểm lại sàn giá và số sao ở phía mình. Hết kết quả cho "đắt hơn"/"rẻ hơn" thì trả `no_result` nói rõ mốc giá.
- **Responder v5** (`assistant-responder.v5.md`, v4 giữ nguyên): nói giá chỗ ở đã kiểm; Verifier chỉ cho "rẻ nhất"/"đắt nhất" khi `stay_filter.sort` đúng chiều (`price_asc`/`price_desc`), giá bịa bị V2 loại.
- **Câu hỏi lại và câu chưa tìm thấy**: Responder viết lại (tối đa 2 câu, câu hỏi lại phải kết thúc bằng "?"); lỗi quy tắc hoặc rỗng thì dùng lại câu cố định. Refusal và fallback không qua Responder.
- **Eval**: thêm `cases.v11.jsonl` (9 case ci) và `chains.v9.jsonl` (1 chain 3 lượt); `evals/assistant/run.py` nhận `v11` và chain v9. Các file version cũ giữ nguyên.
- **Contracts**: `contracts/openapi` sinh lại (`CardRef.price`, `TripContext.minStars`, `priceMinPerNight`).

## Đối chiếu "Xong khi"

Chưa có link Notion nên chưa chép được tiêu chí gốc. Bảng dưới đối chiếu theo phạm vi yêu cầu trong spec `docs/superpowers/specs/2026-11-26-tripi-loc-sap-xep-cho-o-design.md`; Bảo đối chiếu lại với Notion.

| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Hiểu lọc giá sàn, số sao, sắp xếp, "đắt hơn/rẻ hơn" | Đạt ở mức code | `tests/assistant/test_stay_filters.py`; case ci `stay-filter-*` (Core nhận đúng `priceMin`/`priceMax`/`minStars`/`sort`). Chưa đo với LLM thật |
| Core nhận bộ lọc, thẻ không vi phạm điều kiện | Đạt | `test_stay_search_sends_filters_to_core`; case ci kiểm tham số gửi Core |
| "đắt hơn/rẻ hơn" dựa trên giá thẻ đang hiện, hết thì báo rõ | Đạt | `test_higher_*`, `test_lower_*`, case `stay-filter-higher-none` |
| Responder nói giá đã kiểm, không bịa giá, "rẻ nhất" đúng chiều sắp xếp | Đạt ở mức Verifier | test Verifier (V2, V4_scarcity) trong `test_stay_filters.py` |
| Câu hỏi lại và "chưa tìm thấy" tự nhiên hơn, có đường lui | Đạt ở mức code | 4 test trong `test_chat_two_agents.py`, SSE test trong `test_chat_switches.py` |
| Điểm eval case cũ không tụt | Đạt | ci 171/171 trước, 180/180 sau (171 cũ vẫn đạt) |

## Điểm eval trước / sau

| Lệnh | Trước (đầu Task 1) | Sau |
|---|---|---|
| `uv run python -m evals.assistant.run` (ci) | 171/171 | **180/180** (171 cũ + 9 case v11) |
| `uv run python -m evals.assistant.run --cases v11` | không có | 9/9 |
| `--mode live` / `--mode chain` | chưa chạy | chưa chạy (xem bên dưới) |

Kiểm chứng case có phân biệt được: sửa tạm `priceMin` mong đợi của case `stay-filter-higher` thành giá trị sai thì 2/9 case fail; đã trả lại.

### Chế độ ci chứng minh gì, không chứng minh gì

Ở ci, Controller **không** được gọi: mỗi case cho sẵn kế hoạch Controller (`expect.controller`), rồi chạy code phía sau là `to_understanding`, `refine_stay_filters`, Skill, tham số gửi Core (Core giả), thẻ, nhớ `trip` cho lượt sau. Vì vậy ci chứng minh code xử lý đúng khi Controller đã xuất đúng trường. ci **không** chứng minh prompt Controller v11 thật sự làm LLM xuất `price_relative="higher"` cho "tìm căn đắt hơn", và không đo chất lượng câu Responder v5 (ci không gọi Responder).

### Chưa chạy với LLM thật

Máy này không có `OPENAI_API_KEY`/`DEEPSEEK_API_KEY` nên chưa chạy live và chain; chưa có điểm trước/sau cho prompt Controller v11 và Responder v5, trái với RULES §10 ở phần "ghi điểm trước/sau". Bảo cần chạy sau khi có key, và ghi điểm vào file này:

```
uv run python -m evals.assistant.run --mode live --cases v11   # intent + slot, 3 lần mỗi case
uv run python -m evals.assistant.run --mode chain              # gồm chain v9
uv run python -m evals.assistant.run --mode ab                 # Responder qua Verifier
```

Để có điểm "trước", chạy cùng lệnh live trên Controller v10 (đổi `PROMPT` về v10) rồi so với v11.

## Kết quả kiểm tra

Chạy ngày 2026-11-26 trên nhánh, trước commit evidence:

- `uv run ruff check .`: đạt.
- `uv run ruff format --check .`: đạt (245 file).
- `uv run pyright`: 0 lỗi.
- `uv run pytest -q`: **1297 pass, 7 skip** (7 skip có sẵn từ trước).
- `uv run python -m evals.assistant.run`: **180/180**.
- Sinh lại OpenAPI: `PYTHONPATH=. uv run python scripts/export_openapi.py` (script cần `PYTHONPATH=.`).

## Cách kiểm lại

1. `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q`
2. `uv run python -m evals.assistant.run` phải ra `180/180`.
3. Với key LLM trong môi trường, chạy 3 lệnh live/chain/ab ở trên.

## Giới hạn đã biết

- "Rẻ nhất"/"đắt nhất" chỉ nói về căn đầu (r1) là do prompt Responder yêu cầu, Verifier không kiểm.
- Câu hỏi lại do Responder viết lại có thể có 2 câu hỏi; code chỉ cắt tối đa 2 câu và đòi có dấu "?", không chặn 2 câu hỏi.
- Khi đã đặt `minStars`, các căn Core trả về với `stars` rỗng vẫn được giữ lại (không kiểm được).
- Chưa có đánh giá LLM thật cho Controller v11 và Responder v5.

## Ảnh / video

- Không đổi giao diện; FE không sửa.

## Ảnh hưởng tới phần của người khác

- Không: chỉ sửa `tripflix-ai` (chủ: Bảo). FE nhận thêm các trường tuỳ chọn trong `trip`: `lastCards[].price`, `priceMinPerNight`, `minStars`; app trả nguyên khối `trip` về nên không cần sửa. `contracts/openapi` đã sinh lại theo đúng quy trình, chỉ thêm trường.
