# Kế hoạch dọn dẹp kho mã AI Tripflix

> Kế hoạch dưới đây ghi lại kết quả kiểm kê trước khi dọn. Ngày 22/11/2026, người dùng duyệt xóa bốn tệp trùng và dọn minh chứng AI đến hết 15/11, đồng thời yêu cầu giữ đủ dữ liệu để chạy lại eval. Xem [Báo cáo thực hiện](REPOSITORY_CLEANUP_REPORT.md) để đối chiếu các tệp đã xóa và kết quả kiểm tra.

## Mốc đối chiếu và kiểm kê

Nhánh `chore/repository-deep-cleanup` bắt đầu tại `1a2183e02204087e72bb1b237d5ae5a5adb2bca3` sau khi đồng bộ bằng chế độ fast-forward với `origin/develop`.

- `app` chứa dịch vụ FastAPI chạy trên Python 3.13 và các worker Redis. `app/main.py` đăng ký các nhóm tuyến kiểm tra trạng thái, trò chuyện, kiểm duyệt và embedding. Dockerfile có các giai đoạn riêng để xuất mô hình, cài phụ thuộc, chạy phát triển và chạy môi trường chính thức. Workflow phát hành tải bộ phân loại từ bản phát hành rồi build ảnh Docker.
- `tests` có các bài kiểm thử pytest cho API và worker. `evals` và `notebooks` chứa quy trình đánh giá trợ lý và kiểm duyệt, dữ liệu đầu vào, cấu hình và kết quả thực nghiệm. `scripts` chứa công cụ xuất OpenAPI, sự kiện và mô hình, cùng công cụ đóng gói bộ phân loại. CI dùng uv với lockfile, Ruff, Pyright, pytest và bước sinh lại OpenAPI.
- `docs` chứa tài liệu kiến trúc, minh chứng mô hình và đánh giá, cùng hồ sơ đầu việc theo quy định lưu minh chứng của kho mã.
- Mốc ban đầu gồm **354 đường dẫn và 8.931.407 byte** được Git theo dõi. Tổng kích thước tệp trên đĩa bằng tổng kích thước blob Git theo từng đường dẫn tại commit đối chiếu. Kết quả `git count-objects -v` ghi nhận kho đối tượng Git cục bộ có 1.667 KiB đã đóng gói và 5.743 KiB đối tượng rời.

## Có thể xóa sau khi được phê duyệt

Gói tải lên của bộ dữ liệu đã rà soát được thêm tại `c62d36f`. Cả ba tệp bên trong ZIP đều trùng từng byte với các tệp gốc được giữ lại. Các bản sao trong thư mục chuẩn bị tải lên cũng trùng với những tệp đó. Tìm kiếm theo đường dẫn trong cả ba kho mã không thấy nơi sử dụng thư mục chuẩn bị hoặc ZIP của bộ đã rà soát trong phần được Git theo dõi. README của tập đánh giá riêng và minh chứng tinh chỉnh mô hình dùng gói kiểm thử đã rà soát ở đường dẫn gốc. Giữ các đường dẫn gốc, báo cáo của chúng và tệp ZIP tải lên phiên bản trước.

| Đường dẫn | Byte | Hạng mục | Lý do và bằng chứng | Rủi ro có thể phát sinh | Độ tin cậy |
| --- | ---: | --- | --- | --- | --- |
| `notebooks/tf32-round2-test-upload-reviewed.zip` | 195,002 | Gói tải lên sinh tự động bị trùng | Cả ba tệp trong ZIP trùng với các tệp gốc liệt kê bên dưới. | Bản bàn giao qua Colab có thể dẫn trực tiếp đến ZIP. Phiên bản Git ban đầu vẫn lưu nguyên từng byte của ZIP. | Cao đối với khả năng tái lập |
| `notebooks/tf32-round2-test-upload-reviewed/dev-complete.json` | 323,829 | Bản sao chuẩn bị tải lên | Cùng blob Git với `notebooks/tf32-round2-dev-results/dev-complete.json`. | Workspace thao tác thủ công có thể dùng đường dẫn bản sao. | Cao |
| `notebooks/tf32-round2-test-upload-reviewed/frozen-config.json` | 18,266 | Bản sao chuẩn bị tải lên | Cùng blob Git với `notebooks/tf32-round2-dev-results/frozen-config.json`. | Quy trình tải lên notebook thủ công có thể dùng đường dẫn bản sao. | Cao |
| `notebooks/tf32-round2-test-upload-reviewed/test-pack.json` | 198,068 | Bản sao chuẩn bị tải lên | Cùng blob Git với `notebooks/tf32-round2-test-results-reviewed/test-pack.json`. | Quy trình tải lên notebook thủ công có thể dùng đường dẫn bản sao. | Cao |

Đề xuất giảm **735.165 byte được Git theo dõi trên bốn đường dẫn**, tương đương 8,23% dung lượng ban đầu. Ước tính còn 8.196.242 byte trước khi tính tài liệu bảo trì. Nếu cần gói tải lên của bộ đã rà soát, nén lại ba tệp gốc ở cấp gốc của ZIP và giữ nguyên tên hiện tại. Metadata nén của gói mới có thể khác.

## Cần xem xét

| Đường dẫn | Byte | Hạng mục | Bằng chứng và lý do giữ lại để xem xét | Rủi ro có thể phát sinh | Độ tin cậy khi xóa |
| --- | ---: | --- | --- | --- | --- |
| `notebooks/tf32-round2-test-upload.zip` | 194,861 | Gói tải lên của lần thực nghiệm trước | Hai tệp trong ZIP trùng với các đầu vào hiệu chỉnh đang giữ. Tệp `test-pack.json` 202.991 byte trong gói chưa có bản trùng từng byte được lưu trong Git. | Mất đầu vào của lần thực nghiệm gốc hoặc ảnh hưởng đến khả năng tái lập. | Thấp |

## Phải giữ và kết quả rà soát phụ thuộc

- Giữ tệp hiệu chỉnh trên tập phát triển, bộ kết quả đã rà soát và bộ kết quả gốc, báo cáo, notebook, manifest, dữ liệu kiểm thử kiểm duyệt và tập đánh giá riêng. README của tập đánh giá riêng chủ động lưu một bản kết quả suy luận cũ cùng mã băm. Các tệp gần giống nhau có thể ghi lại trạng thái đánh giá khác nhau.
- Giữ mô hình và script xuất mô hình dùng trong Dockerfile và workflow phát hành, kể cả quy trình tải bộ phân loại đã được biên dịch. Mã embedding, kiểm duyệt và tóm tắt import ONNX Runtime khi cần. Giữ minh chứng bảo mật và kiểm duyệt, tài liệu kiến trúc hiện tại, cấu hình CI/triển khai và các hợp đồng được sinh.
- Cả chín phụ thuộc của dự án đều có nơi dùng trong ứng dụng, script, phần đánh giá hoặc kiểm thử. CI dùng nhóm phụ thuộc phát triển, còn CI và Docker đều cần lockfile. Chưa đề xuất xóa phụ thuộc, script hoặc mã nguồn chạy dịch vụ.
- Bộ nhớ đệm Python, bộ nhớ đệm đánh giá cục bộ, môi trường ảo và checkpoint mô hình cục bộ đã được bỏ qua. Không thấy thư mục cache hoặc build phổ biến nào chứa tệp được Git theo dõi. Giữ nguyên các hiện vật cục bộ đang có.

## Xác minh sau khi được phê duyệt

1. Đối chiếu lại các tệp trong ZIP, các đường dẫn gốc và mã băm với mốc ban đầu. Xác nhận ZIP lịch sử vẫn chứa gói kiểm thử riêng ban đầu. Rà soát diff để kiểm tra dữ liệu đầu vào đánh giá và tài nguyên mô hình.
2. Chạy `uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest` và `uv run python -m scripts.export_openapi`. So sánh hợp đồng được sinh với mốc ban đầu và tìm nguyên nhân nếu lỗi đã tồn tại trước thay đổi.
3. Kiểm tra đăng ký tuyến API, điểm khởi chạy worker và quy trình build Docker. Chạy các bài đánh giá không cần thông tin xác thực với dữ liệu kiểm thử có sẵn nếu phù hợp. Ghi kết quả vào `docs/maintenance/REPOSITORY_CLEANUP_REPORT.md` và ghi riêng dung lượng phụ thuộc, đầu ra build, nội dung được theo dõi và lịch sử Git.

**Chờ phê duyệt.** Kế hoạch này là thay đổi duy nhất trong bản làm việc. Việc dọn dẹp, kiểm thử và build sẽ thực hiện sau khi được phê duyệt.

## Kiểm kê tài liệu và minh chứng

Kiểm kê 89 đường dẫn được Git theo dõi tại mốc đối chiếu, gồm các tệp trong `docs/` và tệp Markdown ở những thư mục khác. Minh chứng đầu việc được giữ theo quy định của kho mã. Các dòng cần xem xét phải được người phụ trách xác nhận hoặc có quyết định về lưu trữ trước khi xóa.

<details>
<summary>Phân loại từng tệp</summary>

| Đường dẫn | Byte | Phân loại | Căn cứ |
| --- | ---: | --- | --- |
| `.github/pull_request_template.md` | 389 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `ARCHITECTURE.md` | 1,846 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `CLAUDE.md` | 10 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `README.md` | 1,345 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `RULES.md` | 16,777 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/assistant-controller.v1.md` | 4,064 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/assistant-controller.v10.md` | 21,053 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/assistant-controller.v2.md` | 4,980 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/assistant-controller.v3.md` | 11,581 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/assistant-controller.v4.md` | 11,870 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/assistant-controller.v5.md` | 14,392 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/assistant-controller.v6.md` | 14,651 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/assistant-controller.v7.md` | 17,219 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/assistant-controller.v8.md` | 17,864 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/assistant-controller.v9.md` | 19,612 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/assistant-responder.v1.md` | 3,434 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/assistant-responder.v2.md` | 4,306 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/assistant-responder.v3.md` | 8,161 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/assistant-responder.v4.md` | 9,380 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/assistant-understand.v1.md` | 1,331 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/assistant-understand.v2.md` | 2,487 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/summary.v1.md` | 4,319 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/summary.v2.md` | 5,142 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `app/prompts/summary.v3.md` | 6,259 | PHẢI GIỮ | Hướng dẫn cài đặt, quy định kho mã hoặc tài liệu tham chiếu triển khai |
| `docs/architecture/06-kien-truc-lop.drawio` | 33,556 | PHẢI GIỮ | Kiến trúc hoặc lịch sử thiết kế |
| `docs/architecture/06-kien-truc-lop.png` | 521,413 | PHẢI GIỮ | Kiến trúc hoặc lịch sử thiết kế |
| `docs/architecture/06-kien-truc-tong-quan.drawio` | 39,570 | PHẢI GIỮ | Kiến trúc hoặc lịch sử thiết kế |
| `docs/architecture/06-kien-truc-tong-quan.png` | 549,765 | PHẢI GIỮ | Kiến trúc hoặc lịch sử thiết kế |
| `docs/architecture/10-de-xuat-kien-truc-va-repo.md` | 44,206 | PHẢI GIỮ | Kiến trúc hoặc lịch sử thiết kế |
| `docs/architecture/11-de-xuat-cau-truc-repo.md` | 45,977 | PHẢI GIỮ | Kiến trúc hoặc lịch sử thiết kế |
| `docs/architecture/README.md` | 869 | PHẢI GIỮ | Kiến trúc hoặc lịch sử thiết kế |
| `docs/architecture/tripflix-travel-agent-architecture.md` | 37,213 | PHẢI GIỮ | Kiến trúc hoặc lịch sử thiết kế |
| `docs/architecture/tripi-agent-kien-truc-chi-tiet.drawio` | 236,380 | PHẢI GIỮ | Kiến trúc hoặc lịch sử thiết kế |
| `docs/architecture/tripi-agent-kien-truc-chi-tiet.md` | 44,576 | PHẢI GIỮ | Kiến trúc hoặc lịch sử thiết kế |
| `docs/architecture/tripi-agent-thuyet-trinh.drawio` | 56,445 | PHẢI GIỮ | Kiến trúc hoặc lịch sử thiết kế |
| `docs/architecture/tripi-agent-v3-de-xuat.md` | 87,897 | PHẢI GIỮ | Kiến trúc hoặc lịch sử thiết kế |
| `docs/architecture/tripi-agent-v3-use-cases.drawio` | 43,919 | PHẢI GIỮ | Kiến trúc hoặc lịch sử thiết kế |
| `docs/evidence/SCRUM-177-su-kien-luot-chat.md` | 4,703 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/SCRUM-179-turn-id-latency.md` | 3,759 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF14-ai-summary.md` | 6,516 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF14-canh-bao-cho-duyet.md` | 3,112 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF14-tai-model-khi-build.md` | 1,830 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF28-embed-caption.md` | 5,110 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-bao-cao-loi-tripi-expo-web.md` | 64,239 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-chat-env-empty.md` | 1,976 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-chui-tuc-khong-tim.md` | 7,069 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-co-tat-va-injection.md` | 4,818 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-doi-thu-tu-diem.md` | 3,935 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-eval-du-pham-vi.md` | 3,220 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-lo-trinh-kem-dich-vu.md` | 7,259 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-ngu-canh-tu-nhien.md` | 11,891 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-nut-dat-cho.md` | 6,524 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-san-bay-theo-ten.md` | 3,279 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-sua-hoi-quy-eval.md` | 14,776 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-sua-phan-hoi-tripi.md` | 1,918 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-tin-nhan-lien-quan.md` | 8,213 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-tom-tat-204.md` | 1,631 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-tra-loi-ngoai-le.md` | 9,366 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-tripi-controller-v6.md` | 4,215 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-tripi-demo-regression.md` | 3,481 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-tripi-v3-hai-agent.md` | 9,387 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-tripi-v3-nen.md` | 6,902 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-tripi-v3-ngu-canh.md` | 9,184 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-tro-ly-giai-doan-b.md` | 9,717 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF31-tro-ly-goi-y.md` | 2,469 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF32-BE09-video-frame-proof.md` | 930 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF32-be09-dot1-20261119.md` | 1,890 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF32-dev-hard-negatives.md` | 1,459 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF32-eval-moderation-vi-3k.md` | 6,031 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF32-moderate-endpoint.md` | 4,095 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF32-plan-eval-visobert.md` | 10,742 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF32-visobert-calibration.md` | 7,651 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF32-visobert-finetune.md` | 2,687 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF32-visobert-runtime.md` | 7,669 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF33-an-binh-luan-tom-tat-lai.md` | 10,206 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF33-mau-binh-luan-va-doi-soat.md` | 8,780 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF44-cong-truoc-phan-loai.md` | 4,129 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF44-sua-mau-thuan-logic.md` | 13,890 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF44-summary-ben-vung.md` | 12,816 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF44-ten-consumer-co-dinh.md` | 2,198 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF68-sua-ci-cd.md` | 1,690 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `docs/evidence/TF95-ai-usage-stream.md` | 3,499 | PHẢI GIỮ | Minh chứng đầu việc, nghiệm thu hoặc kiểm thử hồi quy |
| `evals/moderation/dev_hard_negatives_v1/README.md` | 4,115 | PHẢI GIỮ | Hướng dẫn vận hành, đo hiệu năng hoặc đánh giá |
| `evals/moderation/dev_hard_negatives_v1/REVIEW.md` | 9,923 | PHẢI GIỮ | Hướng dẫn vận hành, đo hiệu năng hoặc đánh giá |
| `evals/moderation/finetune_v1/README.md` | 3,898 | PHẢI GIỮ | Hướng dẫn vận hành, đo hiệu năng hoặc đánh giá |
| `evals/moderation/holdout_v1/README.md` | 4,851 | PHẢI GIỮ | Hướng dẫn vận hành, đo hiệu năng hoặc đánh giá |
| `evals/moderation/holdout_v1/REVIEW.md` | 36,297 | PHẢI GIỮ | Hướng dẫn vận hành, đo hiệu năng hoặc đánh giá |
| `evals/moderation/quality_review/ANNOTATION_POLICY.md` | 8,878 | PHẢI GIỮ | Hướng dẫn vận hành, đo hiệu năng hoặc đánh giá |
| `evals/moderation/quality_review/QUALITY_REVIEW.md` | 3,848 | PHẢI GIỮ | Hướng dẫn vận hành, đo hiệu năng hoặc đánh giá |

</details>
