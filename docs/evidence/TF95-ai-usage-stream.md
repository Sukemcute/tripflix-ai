# TF95 — Ghi nhận mức sử dụng AI qua Redis Streams

- [SCRUM-123](https://tripflix.atlassian.net/browse/SCRUM-123) · Nhánh `bao/TF95-ai-usage-stream` · Người làm Bảo (dùng AI)

## Đã làm

- Phát `ai.usage.recorded` v1 vào `stream:ai`, theo định dạng `event` chứa JSON như các stream hiện có. Giới hạn stream gần đúng 100.000 bản ghi theo kiến trúc MVP.
- Envelope có `eventId`, `type`, `version`, `occurredAt` theo UTC, `producer`, `userId` và `payload`. `userId` là UUID của người dùng đã đăng nhập nếu ai-service có thông tin đó, hoặc `null`.
- Payload dùng camelCase ở cả ba luồng. Chat có một sự kiện cho mỗi kết quả Controller hoặc Responder, kèm `conversationId` và `step`. Tóm tắt có một sự kiện cho mỗi kết quả LLM, kèm `estimatedCommentTokens`. Hai luồng ghi token kể cả khi đã nhận kết quả tính phí nhưng JSON sinh ra không dùng được.
- Kiểm duyệt có một sự kiện cho mỗi batch thành công, kèm số mục và số ảnh. Provider kiểm duyệt miễn phí nên `costUsd` bằng 0. Hai trường token là `null` vì provider không trả số token. `estimated` đánh dấu chi phí ước tính ở chat và tóm tắt.
- Khi Redis không ghi được, ai-service ghi chính envelope vào log `ai.usage.publish_failed` để có dữ liệu đối soát. ACK của Redis có thể thất lạc sau khi đã ghi, nên cùng một envelope luôn giữ nguyên `eventId` khi gửi lại. Phần log dự phòng chưa có cơ chế tự phát lại.

## Đối chiếu tiêu chí SCRUM-123

| Tiêu chí | Trạng thái phía AI | Bằng chứng |
|---|---|---|
| Hợp đồng chung trong `contracts/` | Đã sinh schema v1 từ model Python | `contracts/events/ai.usage.recorded.v1.schema.json` và test so sánh schema |
| Ghi đúng token và chi phí | Đã có producer cho ba luồng | Test ở entry point chat, kiểm duyệt và worker tóm tắt. Còn xác nhận số liệu Admin sau khi có consumer |
| Sự kiện gửi trùng không bị cộng hai lần | Producer giữ `eventId` nếu ghi lại cùng envelope | Test Redis thật xác nhận hai entry nhận cùng ID. Consumer dùng ID làm khoá chống cộng trùng |

## Kết quả kiểm tra

- Ruff lint, Ruff format và Pyright đều đạt.
- Pytest với Redis 8.8 riêng cho test có **677 pass, 1 skip**.
- Eval Tripi có **70/70** ca đạt theo loại phản hồi, thẻ và lời gọi Core.
- Sinh lại schema sự kiện và OpenAPI cho kết quả khớp với các file đã commit.

## Cách kiểm lại

1. Chạy `uv run python -m scripts.export_usage_events`, rồi kiểm tra diff của file schema.
2. Chạy suite pytest với `REDIS_TEST_URL` trỏ tới Redis dành riêng cho test. Fixture của worker dọn database đó.
3. Sau khi ghép consumer TF60, gọi Tripi một lượt và đối chiếu token, chi phí theo ngày và model. Phát lại cùng envelope và kiểm tra tổng không tăng thêm.

## Phạm vi

Phần producer và hợp đồng trong `tripflix-ai`. Sự kiện chỉ chứa số liệu sử dụng và định danh nêu trong schema. Nội dung chat, bình luận, URL ảnh và hash IP không nằm trong payload. Consumer và API số liệu thuộc [TF60/SCRUM-64](https://tripflix.atlassian.net/browse/SCRUM-64) và phần analytics của [SCRUM-123](https://tripflix.atlassian.net/browse/SCRUM-123).
