# TF31 — Đo tải Tripi (`POST /chat`) bằng LLM thật

- Notion: (Bảo dán link task) · Nhánh: `bao/TF31-tripi-do-tai` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-26

## Đã làm
- `evals/load/run.py`: công cụ đo tải dùng `httpx` có sẵn, không thêm thư viện.
  - **Mô hình mở:** hội thoại bắt đầu theo phân phối Poisson với tốc độ đặt trước, nên không bị coordinated omission.
  - **Kịch bản:** mỗi hội thoại chạy một chain của `evals/assistant`, mang `history` và `trip` qua các lượt như app.
  - **Kết quả mỗi giai đoạn:**
    - số lượt/giây thật, số lượt chạy cùng lúc cao nhất;
    - `done%`, `full%`;
    - p50/p95/p99;
    - lỗi theo loại, Controller không `ok` theo loại;
    - chi phí.
  - **Chặn chi phí:** dừng gửi lượt mới khi chạm `--budget-usd`.
- `evals/load/compose.load.yaml`: ghép sau compose của tripflix-be.
  - ai-service chạy bản `prod` như staging.
  - Tin `X-Forwarded-For` để mỗi hội thoại là một khách riêng.
  - Key và model LLM lấy từ `.env` của tripflix-ai.
- `evals/load/README.md`: cách chạy và đọc kết quả.
- `tests/test_load_run.py`: 7 test (đọc SSE, mang `trip`/`history` sang lượt sau, percentile, đếm lượt chạy cùng lúc, tổng hợp).

## Kết quả đo (máy local, 26/11, gpt-5-nano + DeepSeek thật)
Một instance ai-service (bản `prod`, 1 process) và core-api local. Tổng 1.242 lượt, tốn **0,52 USD**, trung bình **0,00047 USD/lượt**. Lệnh: `--stages 0.5:120,1:120,2:120,4:90,6:60 --budget-usd 1.5`.

| Mục tiêu (lượt/s) | Thật (lượt/s) | Cùng lúc tối đa | done% | full% | p50 / p95 / p99 (giây) | CPU ai-service |
|---|---|---|---|---|---|---|
| 0,5 | 0,48 | 5 | 100 | 100 | 3,45 / 5,27 / 8,78 | ~1% |
| 1 | 1,02 | 9 | 100 | 100 | 3,57 / 4,41 / 4,77 | ~2% |
| 2 | 1,65 | 13 | 100 | 99,0 | 3,27 / 4,45 / 5,80 | ~3% |
| 4 | 4,01 | 21 | 100 | 99,2 | 3,15 / 3,96 / 5,03 | ~6% |
| **6** | **7,13** | **31** | **95,6** | **66,8** | 3,04 / 3,89 / 5,03 | ~9% |

- `full%` là lượt `done` mà Controller trả lời được và không bị giảm chất lượng.
- Responder không stream, nên thời gian tới chữ đầu tiên gần bằng cả lượt.
- RAM ai-service ~108 MB suốt bài đo.

### Đọc kết quả
- **Tới 4 lượt/giây ổn định:** p95 dưới 4,5 giây, gần 100% lượt đủ chất lượng, CPU ai-service dưới 10%. Lỗi lẻ tẻ là `connection_error` tới OpenAI (mạng).
- **Gãy ở khoảng 6–7 lượt/giây**, do hai giới hạn bên ngoài code xử lý chứ không do CPU:
  1. **`CHAT_MAX_INFLIGHT=30`:** từ giây 471, khi lượt tới dồn lên 7,5 lượt/giây, số lượt chạy cùng lúc chạm 30 và server trả 503 `CHAT_BUSY` (19 lượt, 4,4%). Đây là trần đặt có chủ ý.
  2. **OpenAI trả 429** (giới hạn của tài khoản) từ giây 482, lúc lượt tới khoảng 9 lượt/giây trong 15 giây:
     - Trong giai đoạn này, 88 lượt Controller bị 429 và 32 lượt gặp breaker đang mở, nên khoảng 1/3 số lượt **mất LLM**.
     - Các lượt này trả lời bằng code trong ~0,35 giây thay vì ~3,2 giây, nên p95 **trông tốt hơn** dù chất lượng tụt. Vì vậy phải đọc `full%`, không chỉ đọc độ trễ.
- **Breaker đóng mở liên tục khi tải cao:** log có 34 lần "breaker chat-controller open for 300s".
  - Nguyên nhân: các lượt đang bay mà thành công thì `record_success` đặt lại bộ đếm, nên breaker đóng sau vài giây chứ không giữ 300 giây như cấu hình.
  - Breaker cũng coi 429 (bị giới hạn tốc độ) giống như nhà cung cấp sập.
  - Chưa sửa ở task này, xem mục việc còn lại.
- **Quy đổi:** 4 lượt/giây ứng với khoảng **160 người đang chat cùng lúc** trên một instance, nếu mỗi người gửi một tin khoảng 40 giây một lần (giả định, chưa đo trên app thật).

### Giới hạn của bài đo
- Chạy trên laptop, core-api bản dev, dữ liệu Core local. Nút thắt nằm ở LLM nên kết luận vẫn dùng được, nhưng chưa thay được bài đo trên VM staging.
- Chain viết cho ngày 16/11, server chạy ngày 26/11, nên vài lượt có ngày ra câu hỏi lại thay vì tìm kiếm.
- Không biết hạng giới hạn RPM/TPM của tài khoản OpenAI. Xem lần đo sau khi sửa bên dưới: trần thật vào khoảng 3–4 lượt/giây kéo dài.
- Mỗi giai đoạn chỉ 1–2 phút. Chưa chạy bài kéo dài (soak).

## Sửa 429 và breaker (commit `3f06109`)
- **Breaker** (`app/core/breaker.py`): khi breaker đang mở, một cuộc gọi gửi *trước* lúc mở mà trả về thành công không còn đóng breaker lại. Breaker giữ mở đúng `open_seconds`; hết giờ thì cuộc gọi đầu tiên thành công mới đóng.
- **429 ở đường chat** (`GuardedLlmClient.agenerate`):
  - 429 do bị giới hạn tốc độ thì không tính là lỗi của breaker.
  - Nếu `retry-after-ms` / `retry-after` ≤ 2 giây (không có header thì chờ 1 giây), chờ rồi thử lại **một** lần. Lâu hơn thì bỏ ngay, lượt đó dùng câu dự phòng như cũ, vì cả lượt chỉ có 12 giây.
  - 429 `insufficient_quota` (hết tiền ở OpenAI) vẫn tính là lỗi, vì đó là sự cố thật.
  - Đường sync của worker tóm tắt giữ nguyên: adapter đã tự thử lại 429.
- 7 test mới trong `tests/test_breaker.py`.

### Đo lại sau khi sửa
Lệnh: `--stages 4:60,6:120,8:60 --budget-usd 0.8`. Tổng 1.406 lượt, 0,46 USD.

| Mục tiêu (lượt/s) | Thật | Cùng lúc tối đa | done% | full% | Controller 429 | 503 | Breaker mở |
|---|---|---|---|---|---|---|---|
| 4 | 3,0 | 19 | 100 | 99,4 | 0 | 0 | 0 |
| 6 | 5,8 | 24 | 100 | 78,1 | 148 | 0 | 0 |
| 8 | 7,4 | 24 | 100 | 42,7 | 253 | 0 | 0 |

So với lần đầu (mức 6 lượt/giây: 19 lượt bị 503, breaker mở 34 lần, full 66,8%):
- **Breaker không mở lần nào.** Lượt bị 429 chỉ ảnh hưởng chính lượt đó, không kéo người khác mất LLM theo.
- **Không còn 503:** lượt bị 429 kết thúc nhanh nên số lượt chạy cùng lúc dừng ở 24.
- **Trần thật là hạn mức tài khoản OpenAI.** Chia theo cửa sổ 15 giây, số lượt Controller `ok` đứng yên ở khoảng **47 mỗi 15 giây (~3,1 lượt/giây)** khi tải vượt mức đó. 429 bắt đầu sau khoảng 2 phút ở 5–6 lượt/giây, giống giới hạn token theo phút (TPM).
  - Thử lại một lần không vượt được trần này. Script đo phía client nên không đếm được bao nhiêu lượt được cứu nhờ thử lại.
  - Vì vậy sức chịu bền vững của **cả hệ thống** (mọi instance dùng chung key) khoảng **3–4 lượt/giây**, tức ~120–160 người đang chat với giả định 40 giây một tin.

## Việc còn lại (đề xuất, chưa làm)
1. **Xem hạn mức RPM/TPM của key OpenAI** trên dashboard, đối chiếu với ~3 lượt/giây ở trên. Muốn hơn thì nâng hạng. Thêm instance không giúp được, vì cùng một key.
2. **Giảm token mỗi lượt Controller** (khoảng 15k đầu vào/lượt): kéo dài trần TPM trực tiếp. Cần đo lại eval nếu đổi prompt.
3. Chạy lại bài này trên VM giống staging (cần anh Phong).

## Kết quả kiểm tra
- `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q`: sạch, pyright 0 lỗi, **1423 pass, 7 skip**.
- `uv run python -m evals.assistant.run` (ci): **194/194**.
- Không đổi prompt, eval case.

## Cách kiểm lại
Xem `evals/load/README.md`. Smoke: `uv run python -m evals.load.run --stages 0.1:60 --budget-usd 0.1`.

## Ảnh / video
- Không đổi giao diện.

## Ảnh hưởng tới phần của người khác
- Không sửa file của người khác. `compose.load.yaml` nằm trong tripflix-ai và chỉ ghép thêm khi chạy tay; `tripflix-be/deploy/` (anh Phong) không đổi.
- Lệnh build ở README ghi đè image local `tripflix-ai-service:latest` bằng bản `prod`; `pnpm stack:ai` dựng lại bản dev.
