# TF32 — Bổ sung dữ liệu dev sau phân tích lỗi

Ngày 11/11/2026, trên nhánh trang/TF32-visobert-calibration. Phần AI do Bảo phụ trách, thực hiện theo yêu cầu bổ sung dữ liệu của người dùng.

## Đã làm

- Thêm 80 câu tổng hợp theo hai nhóm lỗi cảm thán có từ tục và thuật lại lời xúc phạm.
- Tổ chức 40 cặp có nhãn đối lập, giữ cùng group_id trong mỗi cặp.
- Xuất dev-additions.jsonl, bộ ghép dev-expanded.jsonl có 320 câu, bảng duyệt và manifest.
- Ghi 80 nhãn mới ở trạng thái proposed. 240 câu dev cũ giữ nguyên ID, nội dung và nhãn đã duyệt.

## Kiểm tra

- Ruff lint và format toàn repo pass. Pyright đạt 0 errors.
- Pytest đạt 462 passed, 6 skipped, gồm 2 test mới cho dữ liệu bổ sung.
- Kiểm tra chuỗi chuẩn hóa có 0 trùng với dữ liệu cũ và holdout. Kiểm tra gần trùng tại cutoff 0,90 có 0 kết quả.

## Cách kiểm lại

Chạy `uv run pytest tests/test_moderation_dev_additions.py`. Các file dữ liệu và hướng dẫn nằm trong evals/moderation/dev_hard_negatives_v1.

## Giới hạn

80 câu mới được xây từ lỗi đã quan sát trên holdout 300 câu, dùng làm dữ liệu phát triển. Bước này chưa huấn luyện lại model hoặc sinh dự đoán mới. Lượt đánh giá mức cải thiện sau điều chỉnh cần dữ liệu test mới.
