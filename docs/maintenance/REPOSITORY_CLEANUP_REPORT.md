# Báo cáo dọn dẹp kho mã AI Tripflix

Thực hiện ngày 22/11/2026 trên nhánh `chore/repository-deep-cleanup`. Mốc đối chiếu là `1a2183e02204087e72bb1b237d5ae5a5adb2bca3` của `origin/develop`.

## Kết quả

| Hạng mục | Tệp đã xóa | Byte đã xóa |
| --- | ---: | ---: |
| Bản sao của gói ViSoBERT đã rà soát | 4 | 735.165 |
| Minh chứng cũ | 5 | 12.404 |
| **Tổng** | **9** | **747.569** |

Mốc xóa minh chứng là hết ngày 15/11/2026 theo giờ UTC+7, tính bằng ngày tác giả của commit không phải commit merge sửa tệp lần cuối. Giữ đủ **26 tệp từ 16–22/11** và **14 tệp cũ** cần cho đánh giá, tái lập kết quả, bảo mật hoặc vận hành. Tổng cộng còn 40 tệp trong `docs/evidence`.

Giữ nguyên toàn bộ `evals`, bộ notebook, kết quả và các tệp gốc ngoài bốn bản sao được duyệt, cùng mã nguồn và cấu hình chạy dịch vụ. Tệp `notebooks/tf32-round2-test-upload.zip` của lần đánh giá trước vẫn được giữ vì chứa bản `test-pack.json` riêng.

## Đo dung lượng

| Chỉ số | Trước | Sau |
| --- | ---: | ---: |
| Đường dẫn tại mốc đối chiếu còn trong bản làm việc | 354 | 345 |
| Byte của các tệp tại mốc đối chiếu còn trong bản làm việc | 8.931.407 | 8.183.838 |
| Đối tượng Git đã đóng gói | 1.667 KiB | 1.667 KiB |
| Đối tượng Git rời | 5.743 KiB | 5.743 KiB |

Mức giảm 747.569 byte chỉ tính các tệp được Git theo dõi ở mốc đối chiếu. Hai tài liệu bảo trì mới chưa được Git theo dõi nên được để ngoài phép tính. Lịch sử Git, cấu hình phụ thuộc và hợp đồng API được giữ nguyên. Môi trường ảo và đầu ra build nằm ngoài phép đo.

## Xác minh

- `uv sync --locked` thành công. Ruff, kiểm tra định dạng, Pyright và pytest đều đạt trước và sau khi xóa. Pytest có **1.264 bài đạt, 7 bài bỏ qua** ở cả hai lượt.
- Eval trợ lý ở chế độ CI đạt **171/171** ca trước và sau khi dọn. Phép chấm ViSoBERT với đầu vào và cấu hình đã khóa tạo báo cáo JSON trùng với `notebooks/tf32-round2-test-results-reviewed/test-report.json` ở cả hai lượt.
- Eval tóm tắt với LLM giả chạy đủ 15 ca. Kết quả đối chiếu trạng thái là **4/15 (26,7%)** và bộ tiêu chí kiểm tra chung chưa đạt ở cả hai lượt.
- Sinh OpenAPI vào thư mục tạm và đối chiếu với hợp đồng đã lưu. Đã kiểm tra `git diff --check`, các đường dẫn eval được giữ và dữ liệu trong gói trùng trước khi xóa.
- Chưa chạy eval gọi mô hình trực tiếp hoặc build ảnh Docker. Docker Engine chưa hoạt động trong môi trường này.

## Tệp gốc để tái lập

Nếu cần tạo lại gói tải lên đã rà soát, nén ba tệp dưới đây ở cấp gốc của ZIP và giữ nguyên tên tệp. Nội dung từng tệp sẽ trùng với gói đã xóa. Metadata của ZIP có thể khác.

- `notebooks/tf32-round2-dev-results/dev-complete.json`
- `notebooks/tf32-round2-dev-results/frozen-config.json`
- `notebooks/tf32-round2-test-results-reviewed/test-pack.json`

Hướng dẫn chấm và cách chạy Colab vẫn có trong `docs/evidence/TF32-visobert-calibration.md`, `docs/evidence/TF32-visobert-finetune.md` và `evals/moderation/holdout_v1/README.md`.

## Minh chứng cũ được giữ

| Tệp | Lý do |
| --- | --- |
| `docs/evidence/TF14-ai-summary.md` | Quy trình chạy eval tóm tắt, kết quả đối chiếu và minh chứng che thông tin cá nhân |
| `docs/evidence/TF14-canh-bao-cho-duyet.md` | Luồng kiểm tra cảnh báo an toàn và kiểm duyệt của Core |
| `docs/evidence/TF14-tai-model-khi-build.md` | Vận hành bộ phân loại và quy tắc giữ dữ liệu nghiên cứu ngoài ảnh Docker |
| `docs/evidence/TF32-dev-hard-negatives.md` | Nguồn gốc dữ liệu phát triển và các mẫu dùng để đối chiếu lỗi |
| `docs/evidence/TF32-eval-moderation-vi-3k.md` | Phương pháp đánh giá kiểm duyệt tiếng Việt và số liệu mốc |
| `docs/evidence/TF32-moderate-endpoint.md` | Hướng dẫn kiểm tra đầu cuối API kiểm duyệt |
| `docs/evidence/TF32-plan-eval-visobert.md` | Thiết kế đánh giá ViSoBERT và phương án so sánh |
| `docs/evidence/TF32-visobert-calibration.md` | Lệnh tái lập hiệu chỉnh và đánh giá với cấu hình đã khóa |
| `docs/evidence/TF32-visobert-finetune.md` | Quy trình Colab và đường dẫn gói đối chiếu hồi quy |
| `docs/evidence/TF32-visobert-runtime.md` | Cách đối chiếu đầu ra mô hình và kiểm tra khi chạy dịch vụ |
| `docs/evidence/TF33-an-binh-luan-tom-tat-lai.md` | Minh chứng bảo vệ nội dung đã bị ẩn khỏi tóm tắt |
| `docs/evidence/TF33-mau-binh-luan-va-doi-soat.md` | Quy trình tái lập eval trực tiếp và số liệu cho kiểm tra hồi quy |
| `docs/evidence/TF44-sua-mau-thuan-logic.md` | Mốc đánh giá trước/sau và điều kiện tái lập hồi quy tóm tắt |
| `docs/evidence/TF44-summary-ben-vung.md` | Hướng dẫn kiểm tra worker và xử lý sự cố khi dịch vụ phụ thuộc lỗi |

## Tệp đã xóa

| Tệp | Phân loại | Byte |
| --- | --- | ---: |
| `notebooks/tf32-round2-test-upload-reviewed.zip` | Bản sao trùng từng byte | 195.002 |
| `notebooks/tf32-round2-test-upload-reviewed/dev-complete.json` | Bản sao trùng từng byte | 323.829 |
| `notebooks/tf32-round2-test-upload-reviewed/frozen-config.json` | Bản sao trùng từng byte | 18.266 |
| `notebooks/tf32-round2-test-upload-reviewed/test-pack.json` | Bản sao trùng từng byte | 198.068 |
| `docs/evidence/TF31-sua-phan-hoi-tripi.md` | Minh chứng cập nhật ngày 10/11/2026 | 1.918 |
| `docs/evidence/TF31-tro-ly-goi-y.md` | Minh chứng cập nhật ngày 10/11/2026 | 2.469 |
| `docs/evidence/TF44-cong-truoc-phan-loai.md` | Minh chứng cập nhật ngày 13/11/2026 | 4.129 |
| `docs/evidence/TF44-ten-consumer-co-dinh.md` | Minh chứng cập nhật ngày 11/11/2026 | 2.198 |
| `docs/evidence/TF68-sua-ci-cd.md` | Minh chứng cập nhật ngày 07/11/2026 | 1.690 |
