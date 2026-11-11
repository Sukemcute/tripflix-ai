# TF32 — Tích hợp ViSoBERT vào API kiểm duyệt

## Cập nhật INT8 ngày 12/11/2026

Bản Docker hiện xuất ONNX FP32 để đối chiếu với PyTorch, rồi lượng tử hóa động QInt8 theo kênh cho MatMul, Gemm và Gather. Bước build kiểm tra dung lượng và hai quyết định mẫu trước khi đóng gói riêng bản INT8. Runtime dùng một CPU thread và mặc định tắt ViSoBERT. Đặt `IS_VISOBERT_ENABLED=true` trong môi trường của container để thử.

- Model giảm từ 390.535.756 byte xuống khoảng 99 MB. Model INT8 do Docker xuất có SHA256 `b272ff140981d893c4223eb83c9f1630ab15ecaca9fe519f18e103dd7575adb1`.
- Với 0,5 CPU và 384 MiB, FP32 bị OOM lúc nạp. Image INT8 nạp được, `/health` và `/moderate` trả HTTP 200 với OpenAI và xác thực giả lập. Một batch 20 câu ngắn mất khoảng 0,32 giây. Batch 20 văn bản dài chạm timeout, trả fallback sau khoảng 1,62 giây rồi phục hồi ở request tiếp theo. Đỉnh RAM của container trong thử nghiệm API khoảng 289 MiB.
- Trên 300 câu hồi quy, có 3 quyết định ViSoBERT đổi ở ngưỡng 0,97. Với OpenAI và Core snapshot trong test pack, TP tăng 125 → 126, FP giữ 21 và số harassment/hate bắt đúng giữ 49/50. Đây là phép đo tác động của quantization trên dữ liệu đã xem.
- Lint, format và Pyright đạt. Test local đạt 549 passed, 6 skipped. Chưa có phép đo lưu lượng staging hoặc production.

Các số liệu FP32 bên dưới ghi nhận kết quả của bản tích hợp ban đầu.

Ngày 11/11/2026. Nhánh trang/TF32-visobert-runtime. Phần AI thuộc Bảo, thực hiện theo yêu cầu tích hợp model đã eval vào hệ thống. Nhánh đã merge origin/develop tại 51449ea và giữ các thay đổi summary mới của Bảo.

## Hành vi runtime

POST /moderate chạy OpenAI và một lượt ViSoBERT theo batch đồng thời. Văn bản được mask PII trước cả hai nhánh. ViSoBERT dùng tổng P(offensive)+P(hate), ngưỡng mặc định 0,97. flagged được gộp OR. Scores/categories mới có prefix visobert/, giữ nguyên các category và score OpenAI.

Core hiện chấp nhận dictionary category/score mở rộng. Tín hiệu visobert/toxic làm suspicious=true và tạo case duyệt. Regex category nguy hiểm dùng để auto-hide của Core không khớp prefix visobert/. Nhánh image-only dùng OpenAI.

Model được nạp và kiểm hash khi API startup, trước khi nhận request. Mặc định IS_VISOBERT_ENABLED=true. Nếu bật model mà bundle thiếu/hỏng, service báo chưa sẵn sàng. IS_VISOBERT_ENABLED=false là nút tắt để trở về nhánh OpenAI hiện có.

ViSoBERT dùng một worker suy luận, 2 CPU threads, batch nội bộ 4, max length 256. Timeout riêng mặc định 1,5 giây và bị chặn ở tối đa 80% deadline toàn request. Khi bận, lỗi hoặc timeout, request giữ kết quả OpenAI, ghi log degradation. RunOptions.terminate dừng job ONNX khi hết hạn/cancel. Worker bị giới hạn để tránh dồn hàng đợi CPU. Lỗi OpenAI vẫn dùng cơ chế 502/504 và Core fallback regex hiện có.

## Checkpoint và Docker

- Model nd-khoa/vihsd-uit-visobert-v2, revision 5e8e892f45bf3d52bc3d4c780b6235b65714f07b.
- ONNX fp32, labels clean/offensive/hate, pad_id=1, max_length=256.
- model.onnx SHA256 05ee34344f1e18612b2948fe29723862a2a24d0c014df2e4596fb54e8dbb812a.
- tokenizer.json SHA256 54f841c392dcaafa2816078b67c39d3d289944ef4f7427bf6dc91244960e9ab8.
- Docker có stage Python 3.12 xuất ONNX từ checkpoint cố định bằng torch CPU 2.5.1, Transformers 4.51.0, tokenizers 0.21.2, ONNX 1.17.0 và accelerate 1.6.0. Runtime Python 3.13 chỉ dùng các dependency hiện có, không chứa torch.
- Bundle được COPY vào base image nên có trong target dev/prod và pipeline publish hiện tại. Weights nằm trong gitignore/dockerignore ở máy local và không được commit.

## Kiểm tra thực tế

1. Export so sánh logits PyTorch và ONNX trên batch/độ dài khác nhau, atol/rtol 1e-4, pass. Phải giữ wrapper ở eval khi export để tránh dropout làm sai phép đối chiếu.
2. ONNX Windows so với 300 kết quả Colab có max drift xác suất 2,01e-6 và 0 quyết định khác ở ngưỡng 0,97. Lượt suy luận 300 câu hết 7,59 giây.
3. Gọi HTTP POST /moderate có JWT service đã ký trên 300 câu, dùng ONNX thật và cache OpenAI để đối chiếu. HTTP 200 toàn bộ, batch 20 câu tối đa 0,564 giây trên máy thử, 0 khác biệt quyết định so với OR OpenAI/ViSoBERT đã eval. Verifier sử dụng public key thử nghiệm, đúng issuer/audience/caller của Core.
4. Batch 20 văn bản dài chạm timeout, API vẫn HTTP 200 bằng OpenAI sau 1,579 giây. Lần gọi tiếp theo lại có ViSoBERT. Bài thử này dùng OpenAI cache/stub để đo nhánh local.
5. Một request HTTP local gọi OpenAI thật và ONNX thật trả HTTP 200 sau 1,557 giây, model=omni-moderation-latest+visobert-vihsd@5e8e892f45bf, flagged=true và visobert/toxic=0,9998734. JWT verifier vẫn dùng public key test; chưa kiểm thử mạng từ server Core staging.
6. Docker target prod build thành công, image local a939b227603e. Container chạy non-root, 300 câu Linux đạt 0 quyết định khác Colab, 7,50 giây; torch_in_runtime=false. Một lượt process suy luận batch 4 văn bản dài có peak RSS khoảng 639,5 MiB, cần cộng headroom ứng dụng khi sizing server.
7. Gọi AiModerationClient và evaluateSeverity thực tế phía BE với response stub có visobert/toxic và visobert/hate cao. Core parse thành công, suspicious=true, severity=60, shouldAutoHide=false khi reportCount=0.
8. Lint, format và Pyright pass. Full suite cuối đạt 549 passed, 6 skipped; bộ test moderation sau bổ sung đạt 29 passed. Local gồm cả các test eval chưa commit từ công việc trước; CI trên commit PR chỉ chạy các test đã đưa lên repo.
9. scripts.export_openapi chạy thành công và contracts/ không có thay đổi.

## Cách chạy

```powershell
docker build --target prod -t tripflix-ai:visobert .
```

Dùng image với cấu hình OpenAI và service JWT/JWKS hiện có. Body /moderate giữ schema cũ. Response model có thêm +visobert-vihsd@5e8e892f45bf khi suy luận local hoàn thành và scores có visobert/toxic. Khi nhánh local bận/timeout, model phản ánh OpenAI và log moderation.visobert unavailable nêu lý do.

Chạy bare Python cần export bundle trước bằng môi trường build có torch/transformers/onnx, hoặc dùng Docker để stage export tự thực hiện. Các biến cấu hình nằm trong .env.example.

## Giới hạn và bàn giao

Đây là tích hợp checkpoint đã thử, không thay trọng số bằng fine-tune. Batch dài hoặc tải đồng thời có thể fallback OpenAI để giữ SLA 3 giây của Core. 300 câu được dùng để kiểm chứng tương đương runtime, chưa phải phép đo tổng quát mới. Staging/production cần review PR và triển khai image mới theo quy trình repo. Các file eval/notebook chưa commit từ công việc trước được giữ nguyên ngoài phạm vi commit này.

Tham khảo API RunOptions.terminate và SessionOptions của [ONNX Runtime](https://onnxruntime.ai/docs/api/python/api_summary.html), checkpoint ở [Hugging Face](https://huggingface.co/nd-khoa/vihsd-uit-visobert-v2/tree/5e8e892f45bf3d52bc3d4c780b6235b65714f07b).
