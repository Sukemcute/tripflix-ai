# TF31 — Tìm sân bay theo tên thành phố qua core, Controller v4

- Notion: TF31 · Nhánh: `bao/TF31-san-bay-theo-ten` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-16
- Kế hoạch: bước A2 (T8 trong `tripi-agent-v3-de-xuat.md`).

## Đã làm
- **Controller v4** (`assistant-controller.v4.md`; v3 giữ nguyên):
  - ghi `from_city`, `to_city` đúng như người dùng nói ("sg", "hn", "đà nẵng");
  - chỉ điền mã IATA khi người dùng tự viết mã.
- **Skill bay tự tìm mã sân bay** qua `GET /api/suggest?types=airport` của core (core biết cả tên gọi khác như "hcm").
  - Thành phố không có sân bay (Vũng Tàu): nói rõ, **không gọi `/api/flights`**.
  - Một tên khớp nhiều sân bay: hỏi lại.
- **Thẻ chuyến bay nào cũng có số khách**, để app mở màn chọn vé đúng số người (FE #170).
- **Guard mới sau Controller** (eval live của v4 bắt được):
  - "ks đà nẵng t7 này" (có chữ chỉ chỗ ở, không có chữ chỉ bay; "thứ bảy" không tính là "bay") → tìm chỗ ở;
  - "sau 3h chiều" → `depart_after` 15:00, lấy từ tin nhắn chứ không theo model;
  - "reel này đi mấy ngày" → `asks_days_count`;
  - câu chốt ngắn ("mình chốt vậy") → `ack`;
  - "có áo khoác rồi" → món đã có; "2 món" → giới hạn số món.

## Đối chiếu "Xong khi"
| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Tên thành phố thành mã sân bay qua core | Đạt | `test_city_names_become_airport_codes_through_core` (SGN → HAN) |
| Không có sân bay thì nói rõ, không tìm | Đạt | `test_a_city_without_an_airport_is_said_not_searched` |
| Nhiều sân bay thì hỏi lại | Đạt | `test_two_airports_for_one_name_are_asked_about` |
| Không tụt chất lượng Controller | Đạt | Eval live dưới đây |

## Kết quả kiểm tra
- ruff, pyright sạch.
- `pytest`: **670 passed, 6 skipped** + 17/17 `tests/test_chat.py` đã commit.
- Eval ci: **70/70**.
- **Eval live** (70 ca × 3 lần, `gpt-5-nano`) và **chain** (5 chuỗi × 3 lần):

| Prompt | Intent + thông tin | pass^3 | Chain (lượt đúng) | Chi phí live |
|---|---|---|---|---|
| v3 (đang dùng trên develop) | 95,2% | 90,0% | 91,7%, 2/5 chuỗi | 0,020 USD |
| v4 trước khi thêm guard | 92,9% | 90,0% | 91,7%, 3/5 chuỗi | 0,021 USD |
| **v4 + guard** | **99,5%** | **98,6%** | **100%, 5/5 chuỗi** | khoảng 0,021 USD |

- Lần trượt duy nhất của bản cuối là timeout mạng (`room-02`, 1/3 lần).
- Độ trễ Controller p50 2,17 giây, p95 2,72 giây.

## Cách kiểm lại
1. `uv run pytest tests/assistant -q`
2. `PYTHONIOENCODING=utf-8 uv run python -m evals.assistant.run --mode live --runs 3` và `--mode chain` (cần khoá OpenAI).
3. Chạy ai-service với core local, hỏi "bay sg ra hn t7 này 2 người": core nhận `from=SGN&to=HAN&passengers=2`. Hỏi "có chuyến bay sài gòn đi vũng tàu không": Tripi nói chưa có chuyến bay tới Vũng Tàu.

## Ảnh / video
- Không đổi giao diện trong repo này.

## Ảnh hưởng tới phần của người khác
- Không. Tripi gọi thêm `GET /api/suggest?types=airport` có sẵn của discovery (Duy).
