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
- Không biết hạng giới hạn RPM/TPM của tài khoản OpenAI. 429 cho thấy trần thật đang ở quanh 6–9 lượt/giây.
- Mỗi giai đoạn chỉ 1–2 phút. Chưa chạy bài kéo dài (soak).

## Việc còn lại (đề xuất, chưa làm)
1. **Xử lý 429 riêng:** đọc `Retry-After`, thử lại một lần có chờ, hoặc giới hạn số cuộc gọi Controller cùng lúc để không vượt giới hạn của nhà cung cấp, thay vì đẩy cả lượt sang câu dự phòng.
2. **Breaker giữ trạng thái mở cho đúng** khi có nhiều cuộc gọi đang bay (bỏ qua `record_success` của cuộc gọi bắt đầu trước lúc mở). Cân nhắc không đếm 429 như lỗi sập.
3. **Xem hạng giới hạn tài khoản OpenAI** trên dashboard. Nếu dự kiến vượt khoảng 4 lượt/giây thì nâng hạng trước khi mở rộng số instance, vì nhiều instance vẫn dùng chung một hạn mức key.
4. Chạy lại bài này trên VM giống staging (cần anh Phong).

## Kết quả kiểm tra
- `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q`: sạch, pyright 0 lỗi, **1416 pass, 7 skip**.
- Không đổi code của app, prompt, eval case. Không cần chạy lại eval ci.

## Cách kiểm lại
Xem `evals/load/README.md`. Smoke: `uv run python -m evals.load.run --stages 0.1:60 --budget-usd 0.1`.

## Ảnh / video
- Không đổi giao diện.

## Ảnh hưởng tới phần của người khác
- Không sửa file của người khác. `compose.load.yaml` nằm trong tripflix-ai và chỉ ghép thêm khi chạy tay; `tripflix-be/deploy/` (anh Phong) không đổi.
- Lệnh build ở README ghi đè image local `tripflix-ai-service:latest` bằng bản `prod`; `pnpm stack:ai` dựng lại bản dev.
