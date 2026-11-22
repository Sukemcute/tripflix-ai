# TF32 — Bổ sung dev từ lỗi cảm thán và trích dẫn

Bổ sung 80 câu tổng hợp mới theo hai nhóm lỗi phát hiện ở lượt test 300 câu. Có 40 cặp đối chiếu, mỗi cặp gồm một câu clean và một câu toxic. Ngữ cảnh tích cực, khiếu nại, phản đối, công kích hoặc đe dọa đều nằm ngay trong văn bản được đưa vào model.

Người dùng xác nhận giữ nguyên 80 nhãn mới ngày 11/11/2026. Snapshot đề xuất trong thư mục này được giữ để truy vết. Bản 320 câu đã xác nhận và split huấn luyện nằm ở `../finetune_v1/reviewed-dev.jsonl`, `../finetune_v1/train.jsonl` và `../finetune_v1/validation.jsonl`.

## File sử dụng

- `dev-additions.jsonl` chứa riêng 80 câu mới, 40 clean và 40 toxic.
- `dev-expanded.jsonl` ghép 240 câu dev đã duyệt với 80 câu bổ sung, tổng 320 câu, 162 clean và 158 toxic.
- `REVIEW.md` có cột để ghi nhận người duyệt, nhãn cuối và lý do điều chỉnh của 80 câu mới.
- `manifest.json` lưu hash, phân bố nhãn, nguồn lỗi và kiểm tra dữ liệu.

80 nhãn mới được đề xuất theo ANNOTATION_POLICY.md đã chốt. Xác nhận của người dùng với bộ test 300 câu đã được lưu ở bộ test đó. Với bộ dev mở rộng, 240 câu đầu giữ nội dung và nhãn đã duyệt, 80 câu mới có label_status=proposed. Các metadata source, split và label_status được ghi tường minh.

## Tình huống bổ sung

| Nhóm | Clean | Toxic |
|---|---:|---:|
| Cảm thán hoặc lời khen có từ tục so với công kích có cùng kiểu từ | 20 | 20 |
| Thuật lại, phản đối hoặc rút lại lời xúc phạm so với dùng lời trích dẫn để công kích, kỳ thị, đe dọa hoặc cổ súy bạo lực | 20 | 20 |

Các cặp bao gồm trường hợp có dấu ngoặc kép, emoji, đại từ xưng hô, yêu cầu quản lý xác minh và lời công kích được ngụy trang thành nhắc lại lời người khác. Mỗi cặp giữ cùng group_id để phục vụ chia dữ liệu theo tình huống khi cần.

## Dùng cho lượt phát triển tiếp theo

`dev-expanded.jsonl` là dữ liệu thô cho vòng phát triển mới. Runner OpenAI hiện có nhận trực tiếp đường dẫn này qua tham số --data. Khi chạy ViSoBERT, đọc trường text để suy luận, dùng toxic/kind để tính điểm sau đó.

Bộ bổ sung chưa có dự đoán model hoặc cache OpenAI cho 80 câu mới. Để chọn ngưỡng với notebook calibration cần tạo dev pack có đủ dự đoán cho cả 320 câu. Model và báo cáo đã khóa của lượt trước vẫn là mốc đối chiếu của lượt đó.

Dữ liệu hiện có nhãn nhị phân toxic/clean. Nếu dùng để fine-tune checkpoint ba nhãn clean/offensive/hate, cần xác nhận ánh xạ nhãn tương ứng, đặc biệt các câu threat/violence. Việc thêm file dữ liệu chưa làm thay đổi trọng số model.

Bộ test 300 câu đã được phân tích để xây các tình huống này. Điểm trên bộ đó trong các lượt sau là kiểm tra hồi quy trên lỗi đã biết. Để đánh giá mức cải thiện tổng quát sau khi điều chỉnh, dùng tập test mới.

## Kiểm tra

Đã kiểm tra schema của 80 câu và bộ ghép 320 câu, ID và nội dung chuẩn hóa duy nhất, 40 group_id có đủ cặp clean/toxic. Chưa thấy trùng nội dung sau chuẩn hóa với bộ 3k, snapshot candidate, bộ 30 câu, dev 240 hoặc holdout 300. So sánh gần trùng chuỗi ở cutoff 0,90 cũng chưa phát hiện trường hợp nào. Kiểm tra này tập trung vào chuỗi ký tự, các nhóm ý nghĩa được cố ý xây từ lỗi đã quan sát.

Kiểm tra local ngày 11/11/2026 đạt 462 test passed, 6 skipped. Ruff lint/format và Pyright đều pass. Hai test mới đối chiếu cặp nhãn, hash, trùng dữ liệu và việc giữ nhãn đã duyệt của 240 câu dev cũ.

