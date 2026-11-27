# Đo tải Tripi (`POST /chat`)

Đo xem một instance ai-service chịu được bao nhiêu **lượt chat mỗi giây** mà độ trễ và tỉ lệ lỗi còn chấp nhận được. Chạy bằng LLM thật nên **tốn tiền**: mỗi lượt khoảng 0,001 USD (khoảng 15k token đầu vào).

## Cách đo
- **Mô hình mở:** hội thoại mới bắt đầu theo phân phối Poisson với tốc độ đặt trước, không phụ thuộc server nhanh hay chậm. Server chậm thì vẫn bị dồn tải đúng mức, nên p95 không đẹp giả (coordinated omission).
- **Kịch bản:** mỗi hội thoại chạy một chain trong `evals/assistant/chains.v*.jsonl` (bỏ chain cần reel). Lượt sau mang `history` và `trip` của lượt trước như app thật, nghỉ 2–6 giây giữa hai lượt.
- **Danh tính:** mỗi hội thoại gửi `X-Forwarded-For` riêng nên server coi là một khách riêng. Cách này chỉ dùng được khi ai-service tin header đó (`compose.load.yaml`), không dùng được qua Traefik.
- **Giai đoạn:** `--stages 0.5:120,1:120` nghĩa là 0,5 lượt/giây trong 120 giây, rồi 1 lượt/giây trong 120 giây. Lượt bắt đầu sau giai đoạn cuối (hội thoại đang dở) được tính vào dòng `tail`.

## Chạy
```bash
# 1. Stack local: core-api + ai-service bản prod; key LLM lấy từ .env của tripflix-ai
docker compose --env-file ../tripflix-be/deploy/.env --env-file .env \
  -f ../tripflix-be/deploy/compose.yaml -f evals/load/compose.load.yaml \
  --profile be --profile ai up -d --build core-api ai-service

# 2. Smoke, rồi tăng dần
uv run python -m evals.load.run --stages 0.1:60 --budget-usd 0.1
uv run python -m evals.load.run --stages 0.5:120,1:120,2:120,4:90,6:60 --budget-usd 1.5 --out /tmp/load.jsonl
```
Khi tổng chi phí chạm `--budget-usd`, script thôi gửi lượt mới.

Chạy xong, `pnpm stack:ai` bên tripflix-be dựng lại ai-service bản dev như cũ.

## Đọc kết quả
| Cột | Nghĩa |
|---|---|
| `rate` | Số lượt/giây thật sự đã gửi trong giai đoạn |
| `inflight` | Số lượt cao nhất đang chạy cùng lúc. Server từ chối (503 `CHAT_BUSY`) khi vượt `CHAT_MAX_INFLIGHT` (30) |
| `done%` | Lượt kết thúc bằng `done` |
| `full%` | Lượt `done` mà Controller trả lời được (`llm=ok`) và không bị giảm chất lượng (`degraded` rỗng) |
| `text p50/p95` | Giây tới khi có chữ đầu tiên. Responder không stream nên gần bằng `total` |
| `total` | Giây cho cả lượt, chỉ tính lượt `done` |
| `failures` | `http_503` đông quá, `http_429` vượt giới hạn, `timeout`, `DEPENDENCY_UNAVAILABLE`… |
| `llm` | Controller không `ok`: `http_429` là nhà cung cấp LLM giới hạn, `breaker_open`, `connection_error` |

Điểm gãy là giai đoạn mà `full%` tụt hoặc `total p95` vượt khoảng 8 giây. Muốn đổi ra số người đang chat: số người ≈ lượt/giây × khoảng cách giữa hai tin của một người (ví dụ 40 giây).
