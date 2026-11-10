# TF31 — Trợ lý yêu cầu đăng nhập, bản triển khai bước đầu

- Jira https://tripflix.atlassian.net/browse/SCRUM-35
- Nhánh `bao/TF31-tro-ly-goi-y`, người phụ trách Bảo, có dùng AI, ngày 2026-11-10.
- Người dùng duyệt kế hoạch và chốt bắt buộc đăng nhập. Mã nằm trong checkout tripflix-ai.

## Đã làm

- POST /chat trả SSE, kiểm ES256 qua JWKS, issuer/audience, claim người dùng, từ chối service token. Kiểm thêm /api/auth/me để Core quyết định phiên còn hiệu lực.
- Phân loại yêu cầu bằng DeepSeek khi bật CHAT_LLM_ENABLED, mặc định tắt và dùng tìm kiếm dự phòng.
- Tìm khám phá qua /api/search, chỉ lấy kết quả chính, bỏ gợi ý nới điều kiện.
- Tìm phòng theo ngày qua /api/suggest và /api/stays, hỏi lại khi thiếu ngày hoặc nơi chưa rõ.
- Thẻ lấy ID và giá từ Core. Câu trả lời dùng mẫu cố định. Đây là baseline một lần gọi LLM, chưa phải workflow hai bước hoàn chỉnh trong kiến trúc.
- Deadline, lỗi SSE, che PII theo helper có sẵn, thống kê token và chi phí ước tính trong done. Usage hiện ghi structured log.
- Sinh OpenAPI bằng scripts.export_openapi.

## Kiểm tra

- 14 test chat kiểm đăng nhập, claims, SSE, lỗi Core, giới hạn truy vấn và giá phòng theo ngày.
- Pyright qua trước lần sửa cuối thay ZoneInfo bằng UTC+7 để chạy trên Windows.
- Ruff check và format check các file thay đổi qua.
- Eval summary fake trong worktree ban đầu trả status_accuracy 0.267 và all_gates_pass false. Chưa đối chiếu baseline sạch, chưa dùng làm bằng chứng chất lượng chatbot.

## Còn phải triển khai trước nghiệm thu

- Endpoint chi tiết bài, kiểm phòng khách sạn cụ thể, tìm chuyến bay và tham chiếu thẻ lượt trước.
- Client Core sinh tự động, workflow viết câu có kiểm bằng chứng, phương án tool-calling để so sánh.
- Hạn mức Redis, sự kiện usage được analytics tiếp nhận, xác minh giá mô hình trước benchmark.
- Khung chat web/mobile và gateway. Chưa kiểm end-to-end với Core/LLM thật.
- Bộ 100 câu và benchmark hai cách trên hai mô hình. Đang chờ lựa chọn mô hình thứ hai và ngân sách API thật.
- Chưa đạt tiêu chí nghiệm thu TF31/TF14/TF40. Chưa push hoặc mở PR.
