# TF32 — Hiệu chỉnh ViSoBERT vòng hai

Nhánh `trang/TF32-visobert-calibration`. Phần AI thuộc Bảo. Quy ước và nhãn đầu vào là các file người dùng đã duyệt cùng Bảo trong workspace. Pipeline đọc CSV làm nguồn nhãn cuối và giữ hash của policy, CSV, model, rules trong kết quả.

## Dữ liệu đã chuẩn bị

- 240 câu dev đã duyệt, 118 toxic và 122 clean, 2 nhãn được sửa.
- ID của review pack thuộc snapshot khác với ID của bộ 3k đã chạy. Ghép theo nguyên văn tìm được 235 câu có kết quả cũ. 5 câu cần chạy lại cả OpenAI và ViSoBERT.
- `colab-input.zip` chứa dev pack và Python source cần cho notebook, được tạo trong thư mục Downloads. `openai-dev-cache.json` chứa 235 kết quả OpenAI đã ánh xạ sang ID review. `dev.jsonl` chứa đủ 240 nhãn cuối.
- Gói giao ngày 11/11/2026 đã được bổ sung 5 kết quả OpenAI qua runner local. Cache giao kèm có đủ 240 câu. Còn 5 dự đoán ViSoBERT để notebook chạy trên Colab.
- Các câu đã xem và thảo luận dùng làm dev. Tập test mới cần được duyệt theo cùng policy và có group_id nhất quán giữa các biến thể cùng gốc/template.

## Chạy vòng dev

Với gói đã chuẩn bị, mở notebook và upload hai file khi được yêu cầu. Nếu tự tái tạo input pack, từ PowerShell trong repo `tripflix-ai`, chạy lệnh sau để bổ sung cache. Runner dùng OPENAI_API_KEY trong môi trường local, bổ sung kết quả còn thiếu và lưu vào cache riêng. Cache chứa văn bản dev. Giữ cache ở máy và chỉ upload dữ liệu đã khử thông tin cá nhân khi dùng dữ liệu thật.

```powershell
$evalDir = 'C:\Users\ADMIN\Downloads\tf32-visobert-round2'
$env:PYTHONIOENCODING = 'utf-8'
uv run python -m evals.run_moderation_eval --data "$evalDir\dev.jsonl" --cache "$evalDir\openai-dev-cache.json"
```

Mở `notebooks/tf32-visobert-calibration-colab.ipynb` trên Colab, chọn T4 và chạy lần lượt đến phần khóa ngưỡng. Upload `colab-input.zip`, sau đó upload cache OpenAI vừa hoàn thành. Notebook chỉ suy luận ViSoBERT cho 5 câu còn thiếu, chọn ngưỡng trên 240 câu dev và tải `tf32-round2-dev-results.zip`.

Giải nén kết quả, giữ `dev-complete.json` và `frozen-config.json`. Lượt test sẽ dùng nguyên các file này. Nếu thay nhãn, policy hoặc cấu hình model, tạo một lượt dev mới để có manifest và cấu hình tương ứng.

## Baseline và tiêu chí lựa chọn

Baseline gắn cờ khi OpenAI flagged hoặc có bất kỳ rule Core khớp. Luật được chạy trực tiếp từ file TypeScript của BE bằng Node 24. Danh sách allowedDomains trong thí nghiệm là rỗng và được ghi vào manifest. Đây là phép đo tín hiệu nghi vấn. Quyết định auto-hide, report count và hàng chờ chưa được chấm trong báo cáo này.

Thử điểm gộp `offensive + hate` và hai ngưỡng riêng. Chọn recall trên toxic harassment/hate cao nhất với FPR tăng tối đa 1 điểm phần trăm so với baseline. Khi hòa điểm ưu tiên ít FP rồi F1 cao hơn. Giá trị ngưỡng 1,01 dùng để tắt nhánh, baseline cũng là một ứng viên. Với 122 câu sạch, budget này cho phép thêm tối đa 1 FP. Đây là budget thử nghiệm người dùng có thể điều chỉnh.

Ngưỡng được chọn chỉ nhìn điểm model, tuyệt đối không dùng kind thật để quyết định từng câu. Kind chỉ phục vụ đo lường. Mốc đề xuất trên test là recall harassment/hate tăng ít nhất 10 điểm phần trăm và FPR tăng tối đa budget đã khóa.

## Khi có tập test mới

Mỗi dòng `test.jsonl` theo schema sau. Ví dụ minh họa này chỉ mô tả định dạng, bộ test cần có cả hai nhãn.

```json
{"id":"new-0001","text":"Bình luận đã khử thông tin cá nhân","toxic":false,"kind":"complaint","group_id":"tripflix-situation-0001"}
```

Các câu cùng tình huống hoặc cùng template dùng chung group_id. Tập test cần cả toxic và clean, có toxic harassment/hate để chấm mốc tăng recall. Nhóm câu phụ thuộc ngữ cảnh được lưu và đánh giá riêng.

1. Chạy phần tạo dự đoán test trong notebook, upload đúng `test.jsonl` và tải `visobert-test.json`.
2. Lưu hai file vào `$evalDir`, chạy các lệnh sau trên máy local để lấy OpenAI cache và chạy luật Core hiện tại.

```powershell
uv run python -m evals.run_moderation_eval --data "$evalDir\test.jsonl" --cache "$evalDir\openai-test-cache.json"
uv run python -m evals.moderation.calibrate_visobert prepare-test --data "$evalDir\test.jsonl" --predictions "$evalDir\visobert-test.json" --cache "$evalDir\openai-test-cache.json" --core-repo '..\tripflix-be' --dev "$evalDir\dev-complete.json" --output "$evalDir\test-pack.json"
uv run python -m evals.moderation.calibrate_visobert test --dev "$evalDir\dev-complete.json" --test "$evalDir\test-pack.json" --lock "$evalDir\frozen-config.json" --output "$evalDir\test-report.json"
```

Cũng có thể upload `dev-complete.json`, `frozen-config.json` và `test-pack.json` ở cell cuối của Colab để chấm cùng một thuật toán.

Test kiểm tra hash dev, model/revision, model OpenAI, hash rules, allowedDomains, policy và trùng ID/group_id/văn bản chuẩn hóa. Biến thể viết lại khác chữ hoặc group_id khai sai vẫn cần con người rà soát. Bí danh `omni-moderation-latest` có thể thay đổi theo thời gian, do đó lưu thời điểm chạy và diễn giải mức cải thiện theo đúng lượt đo.

## Tái tạo input pack

Lệnh prepare tạo thư mục mới và từ chối ghi đè output đã có. Đổi tên output khi tái tạo.

```powershell
uv run python -m evals.moderation.calibrate_visobert prepare --review evals/moderation/quality_review/review_240.csv --results-zip 'C:\Users\ADMIN\Downloads\tf32-visobert-eval-results.zip' --cache evals/moderation/.eval_cache.json --core-repo '..\tripflix-be' --output 'C:\Users\ADMIN\Downloads\tf32-visobert-round2-new'
```

## Kiểm tra và giới hạn

Các test bao phủ chọn ngưỡng trong budget, baseline Core, chống ghép sai nội dung, dev/test trùng ID/group/văn bản, thay đổi rules và dev sau khi khóa. Notebook được kiểm tra cú pháp và định dạng tại máy local. Kết quả GPU, 5 dự đoán mới và điểm test độc lập được ghi sau khi chạy Colab và có dữ liệu test mới.

- `uv run pytest` đạt 458 passed, 6 skipped, trong đó 9 test mới cho calibration.
- `uv run pyright` đạt 0 errors.
- `uv run ruff check .` và `uv run ruff format --check .` đều pass. Đã kiểm tra AST của cả hai notebook và import thực tế Python source/PII từ input ZIP.
- Đã chạy thực tế luật Core bằng Node trên 240 câu. Baseline OpenAI + Core có TP 45, FP 3, FN 73, TN 119. Recall 38,14%, FPR 2,46%. Đây là số trên dev đã chọn có chủ đích.
- Đã bổ sung đúng 5 request OpenAI. Lượt chạy lại xác nhận 240 cached, 0 pending. Lần đầu vướng encoding console sau khi đã lưu cache, chạy lại với PYTHONIOENCODING=utf-8 thành công.

Bộ dev có mẫu chọn có chủ đích và nhiều biến thể câu, nên tỷ lệ lỗi trên dev chưa đại diện lưu lượng Tripflix. Cần xem cả số lượng TP/FP và kết quả từng nhóm trong báo cáo test.
