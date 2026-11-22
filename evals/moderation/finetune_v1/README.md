# TF32 — Fine-tune ViSoBERT vòng đầu

Ngày 11/11/2026. Người dùng xác nhận giữ nguyên nhãn 80 câu bổ sung. Bản reviewed-dev.jsonl gồm 320 câu đã duyệt, giữ snapshot đề xuất trong dev_hard_negatives_v1 để truy vết.

## Chạy trên Colab

1. Giải nén gói tf32-visobert-finetune-ready.zip.
2. Upload notebook tf32-visobert-finetune-colab.ipynb lên Google Colab.
3. Chọn Runtime → Change runtime type → T4 GPU.
4. Chạy các cell theo thứ tự. Khi hỏi file, upload đúng một finetune-input.zip trong gói.
5. Sau huấn luyện, tải tf32-visobert-finetune-results.zip và gửi lại để kiểm tra. Cell cuối tải riêng tf32-visobert-finetuned-model.zip chứa checkpoint để dùng lại.

Input ZIP có dữ liệu, mã tính điểm và mã mask PII được đóng gói cùng. Notebook tải checkpoint công khai, dùng PyTorch có sẵn trong Colab và các phiên bản Transformers/tokenizers tương thích với lần thử trước. Toàn bộ thí nghiệm chạy trên Colab, kết quả OpenAI/Core của bộ hồi quy được tái sử dụng từ pack đã chấm.

## Dữ liệu và cách chọn model

Train có 255 câu, 127 clean và 128 toxic. Validation có 65 câu, 35 clean và 30 toxic. Chia seed 42 theo group_id, có phân tầng theo focus hoặc kind. Các biến thể cùng group và cặp đối chiếu cùng nằm trong một split. Group cũ theo câu gốc, các họ template rộng hơn vẫn có thể chia sẻ cấu trúc giữa train và validation.

Nhãn binary hiện có được dùng trực tiếp bằng loss trên clean_logit và logsumexp(offensive_logit,hate_logit). Head ba nhãn giữ trọng số ban đầu. Sau thí nghiệm, ý nghĩa đã được giám sát là clean/toxic; điểm riêng offensive/hate chưa được kiểm chứng bằng dữ liệu ba nhãn.

Thử 3 epoch, learning rate 1e-5, batch 8, max_length 256. Chọn checkpoint bằng validation loss thấp nhất, gồm cả checkpoint ban đầu ở epoch 0. Nếu epoch 0 được chọn, notebook ghi rõ các epoch huấn luyện chưa cải thiện validation loss. Ngưỡng được chọn riêng trên validation, tối đa cùng số false positive với model gốc tại ngưỡng 0,97. Tiêu chí FP này áp dụng model riêng trên validation, còn bảng hồi quy so sánh hybrid cùng OpenAI/Core.

Mỗi lượt ghi checkpoint, seed, phiên bản thư viện, hash input, lịch sử loss, điểm theo ID và bảng trước/sau. Checkpoint/ngưỡng được lưu trước khi xem kết quả model mới trên 300 câu hồi quy.

## Kiểm chứng

Các test local kiểm tra chia nhóm tái lập, cặp đối chiếu đi chung split, nhãn đã duyệt, ngưỡng chỉ chọn trên validation và budget FP. Notebook có assert kiểm tra công thức loss nhị phân so với xác suất gộp, gradient hữu hạn, input hash và điểm checkpoint sau khi nạp lại.

Kiểm tra local xác nhận cấu trúc và logic chuẩn bị dữ liệu. Việc huấn luyện GPU và mức cải thiện thực tế được xác nhận sau khi chạy notebook và xem ZIP kết quả.

## Diễn giải kết quả

Bộ 300 câu đã dùng để phát hiện lỗi và xây thêm dữ liệu, nên kết quả trên đó là kiểm tra hồi quy. Validation cũng đã được dùng để chọn checkpoint/ngưỡng. Dataset nhỏ, tổng hợp và mới thử một seed. Điểm nghiệm thu cho mức cải thiện tổng quát cần test mới sau bước phát triển.

## Tài liệu API

Forward pass dùng outputs.logits và lưu checkpoint bằng save_pretrained theo tài liệu Transformers 4.51. [Fine-tuning](https://huggingface.co/docs/transformers/v4.51.3/training), [model outputs](https://huggingface.co/docs/transformers/v4.51.3/main_classes/output).
