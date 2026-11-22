# TF32 — Chuẩn bị fine-tune ViSoBERT trên Colab

Ngày 11/11/2026, nhánh trang/TF32-visobert-calibration. Phạm vi AI do Bảo phụ trách. Người dùng đã xác nhận 80 nhãn bổ sung và yêu cầu tiếp tục bước fine-tune.

## Đã làm

- Tạo snapshot 320 câu có label_status=reviewed và manifest lưu xác nhận của người dùng.
- Chia cố định 255 câu train và 65 câu validation theo group_id, seed 42. Kiểm tra cặp đối chiếu và biến thể cùng group đi chung split.
- Thêm helper chia dữ liệu, chọn ngưỡng trên validation và đóng gói input Colab.
- Tạo notebook huấn luyện 3 epoch, learning rate 1e-5, batch 8, max_length 256. Dùng nhãn binary với loss trên clean so với logsumexp(offensive,hate), giữ trọng số head gốc khi bắt đầu.
- Chọn checkpoint theo validation loss, gồm cả epoch 0, chọn ngưỡng trên validation rồi chấm bộ hồi quy 300 câu đã xem.
- Xuất ZIP kết quả nhỏ và ZIP trọng số model riêng. Input ZIP đóng gói source nên notebook có thể chạy với các thay đổi local chưa push.

## Kiểm tra

- Ruff lint toàn repo pass, format đạt 125 files already formatted.
- Pyright đạt 0 errors, 0 warnings.
- Pytest đạt 466 passed, 6 skipped. Có 4 test mới cho split tái lập, cặp đối chiếu, nhãn duyệt, hash, tách regression và ngưỡng validation.
- Đã chạy lệnh tạo bundle thực tế, kiểm tra toàn vẹn hai ZIP, hash train/validation/regression pack, cú pháp 8 cell Python và import helper/PII từ ZIP.
- Notebook có self-check công thức loss, gradient hữu hạn và điểm validation sau khi nạp lại checkpoint. Các check phụ thuộc PyTorch/GPU chạy trong Colab.

## Chạy lại

```powershell
uv run python -m evals.moderation.finetune_visobert --regression-pack notebooks/tf32-round2-test-results-reviewed/test-pack.json --output 'C:\Users\ADMIN\Downloads\tf32-visobert-finetune-v1-new'
```

Output phải là thư mục mới. Gói đã tạo trong Downloads/tf32-visobert-finetune-v1, gồm notebook, finetune-input.zip và hướng dẫn. Mở notebook trên Colab, chọn T4 và chạy lần lượt các cell.

## Giới hạn

Chưa chạy huấn luyện GPU ở máy local. Chất lượng model được xác nhận sau lượt Colab. Nhãn binary chỉ giám sát điểm toxic gộp. Bộ hồi quy đã được dùng phân tích lỗi, validation dùng để chọn model/ngưỡng, nên cần test mới để đo mức cải thiện tổng quát. Group cũ theo câu gốc, chưa bảo đảm các template rộng hơn hoàn toàn độc lập.
