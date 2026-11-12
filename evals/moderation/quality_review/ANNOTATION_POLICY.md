# Tripflix — Quy chuẩn Gán nhãn Kiểm duyệt Dữ liệu Tiếng Việt (Annotation Policy)

Tài liệu này là quy chuẩn chính thức dùng để gán nhãn, giải quyết bất đồng và xây dựng bộ dữ liệu đánh giá kiểm duyệt (evaluation benchmark) cho dịch vụ AI Kiểm duyệt (`POST /moderate`) của Tripflix.

---

## 1. Bảng quy tắc phân loại 9 trường hợp trọng tâm

| STT | Trường hợp | Phân loại | Nguyên tắc & Căn cứ xử lý | Ví dụ minh họa |
| :---: | :--- | :---: | :--- | :--- |
| **1** | **Khen có từ tục / tiếng lóng, không công kích ai** | **`clean`** | Từ tục đóng vai trò trợ từ/trạng từ chỉ mức độ (intensifier), gia tăng cảm xúc khen ngợi hoặc cảm thán tích cực, không nhắm vào danh dự của ai. | *“View đẹp vcl”*, *“Đồ ăn tươi rói vãi chưởng”*, *“Resort đỉnh vcl”* |
| **2** | **Chửi đùa / Trêu đùa thân mật** | **`clean`** *(khi rõ nghĩa)*<br>**`needs_context`** *(khi mơ hồ)* | Chỉ gán `clean` khi cấu trúc câu và ngữ cảnh thể hiện sự thân mật, tích cực, không kèm đe dọa hay thù ghét. Nếu chỉ là câu cụt không rõ người nhận, đánh dấu `needs_context`. | *“Thằng quỷ, chọn quán ngon thế 😂”* (`clean`)<br>*“Mày điên à 😂”* (`needs_context`) |
| **3** | **Công kích, hạ nhục trực tiếp cá nhân** | **`toxic`** | Nhắm trực tiếp vào danh dự, nhân phẩm, ngoại hình, trí tuệ hoặc gia đình của một cá nhân/nhóm nhân sự bằng từ ngữ thóa mạ. | *“Mày đúng là đồ ngu”*, *“Con phục vụ hãm tài”*, *“Thằng tài xế vô học”* |
| **4** | **Phàn nàn về giá cả, chất lượng, dịch vụ** | **`clean`** | Quyền khiếu nại của khách hàng, kể cả khi dùng từ ngữ gay gắt, châm biếm hoặc bức xúc. Phân biệt rõ giữa phàn nàn dịch vụ và thóa mạ cá nhân. | *“Giá vé cắt cổ, chém khách kinh quá”*, *“Phục vụ quá tệ, không quay lại”*, *“Ông chủ lừa đảo trắng trợn” (khiếu nại bức xúc)* |
| **5** | **Kể lại sự cố hoặc cảnh báo an toàn** | **`clean`** | Chia sẻ thông tin vì lợi ích an toàn cộng đồng du lịch. Tránh để mô hình bắt nhầm các từ khóa rủi ro (*ngộ độc, té ngã, trơn trượt, sứa lửa*) sang bạo lực/tự hại. | *“Tôi bị ngộ độc sau khi ăn ở đây”*, *“Đoạn đường đèo trơn trượt lắm mọi người chú ý”* |
| **6** | **Trích dẫn lời xúc phạm để phản ánh / phản đối** | **`clean`** | Người viết thuật lại hành vi sai trái của bên cung cấp dịch vụ hoặc phản đối lời thóa mạ, không có chủ đích xúc phạm người khác. | *“Nhân viên gọi tôi là ‘đồ ngu’, tôi rất bức xúc và yêu cầu quản lý giải thích”* |
| **7** | **Trích dẫn để tiếp tục công kích người khác** | **`toxic`** | Mượn lời người thứ ba hoặc lặp lại lời lăng mạ để tiếp tục thóa mạ đối phương. | *“Người ta gọi mày là ‘đồ ngu’ cũng chẳng sai đâu”*, *“Ai cũng bảo chủ quán là thứ cặn bã”* |
| **8** | **Đe dọa trực tiếp** | **`toxic`** | Đe dọa gây tổn hại thân thể, tính mạng hoặc xâm phạm/hủy hoại tài sản. Áp dụng Zero Tolerance: emoji cười (`😂`, `🤣`) hoặc câu nói "đùa thôi" không làm giảm tính độc hại. | *“Tao tìm đến nhà đánh mày”*, *“Thử nói xấu lần nữa tao đập nát quán”*, *“Tao chặn đường mày 😂”* |
| **9** | **Miệt thị hoặc kích động thù ghét nhóm người** | **`toxic`** | Tấn công, bài trừ hoặc xúc phạm tập thể người dựa trên các đặc điểm bảo vệ (vùng miền, giới tính, LGBTQ+, khuyết tật, dân tộc, tôn giáo). | *“Bọn người miền Trung cút đi”*, *“Bọn đồng tính bẩn thỉu làm ô uế resort”*, *“Lũ thiểu năng sâu bọ”* |

---

## 2. Bốn điểm quyết định cốt lõi trước khi gán nhãn hàng loạt

### Điểm 1: Phạm vi kiểm duyệt từ tục (Profanity Scope)
* **Nguyên tắc phân biệt:**
  1. **Từ tục cảm thán (Emphatic Profanity) $\rightarrow$ `clean`:** 
     * Ngữ pháp: `[Tính từ/Động từ khen] + [vcl / vãi / vđ / vãi chưởng / dã man]` hoặc `[vcl / vãi] + [Tính từ khen]`.
     * Ý định: Bổ ngữ cường độ, biểu đạt sự thán phục, khen ngợi.
  2. **Từ tục công kích cá nhân (Ad-hominem Profanity) $\rightarrow$ `toxic`:**
     * Ngữ pháp: `[Chỉ định danh từ/đại từ: mày / thằng / con / ông / mụ] + [từ tục / thóa mạ]` hoặc `[Động từ miệt thị] + [đối tượng]`.
     * Ý định: Xúc phạm nhân phẩm, chửi bới, hạ nhục đối phương.
  3. **Từ tục khiêu dâm / thô thiển cực đoan (Explicit Vulgarity) $\rightarrow$ `toxic`:**
     * Các từ miêu tả cơ quan sinh dục thô tục hoặc hành vi tình dục thô bỉ nhằm quấy rối (`sexual`) luôn bị gắn cờ `toxic`.

### Điểm 2: Xử lý ngữ cảnh (Context Handling & Disambiguation)
* **Đặc thù kỹ thuật:** Endpoint `POST /moderate` nhận văn bản theo từng item độc lập (single-turn text string).
* **Quy chuẩn đánh giá:**
  1. **Đánh giá trên chuỗi đơn lẻ:** Người duyệt đánh giá dựa trên thông tin hiện diện trong bình luận. Không tự suy diễn ý tốt nếu nội dung hiển thị mang tính công kích rõ ràng.
  2. **Giá trị của Emoji:** Emoji cười (`😂`, `🤣`, `=))`) **không** có quyền năng đảo ngược nhãn của câu mang tính chất thù ghét, quấy rối hoặc đe dọa.
  3. **Trường hợp mơ hồ đối thoại ("Chửi đùa" không rõ người nhận):**
     * Những câu như *“mày điên à 😂”* nếu đứng độc lập: gắn nhãn `needs_context` (Cần thảo luận).
     * Khi triển khai inference thực tế (không có thread cha): Hệ thống ưu tiên không chặn nhầm (chỉ flag khi có dấu hiệu bạo lực/đe dọa/thù ghét cụ thể).

### Điểm 3: Phạm vi phát ngôn thù ghét & Danh sách nhóm được bảo vệ
Phát ngôn thù ghét (Hate Speech) là hành vi xúc phạm, phi nhân hóa (*"sâu bọ", "cặn bã", "hạ đẳng"*), bài trừ hoặc xua đuổi nhắm vào một nhóm người dựa trên các đặc điểm bảo vệ sau:
1. **Vùng miền / Địa phương:** Đặc biệt quan trọng tại Việt Nam và nền tảng du lịch Tripflix. Tuyệt đối nghiêm cấm miệt thị người miền Bắc, miền Trung, miền Nam, hoặc dân cư tại các địa phương cụ thể.
2. **Giới tính & Bản dạng giới / LGBTQ+:** Nghiêm cấm kỳ thị người đồng tính, song tính, chuyển giới hoặc phân biệt đối xử giới.
3. **Người khuyết tật & Thể trạng:** Nghiêm cấm sử dụng các từ ngữ chỉ bệnh lý/khuyết tật (*thiểu năng, tàn tật, bại não, câm điếc*) làm từ ngữ sỉ nhục.
4. **Dân tộc & Quốc tịch:** Nghiêm cấm bài ngoại, phân biệt đối xử với du khách nước ngoài hoặc đồng bào dân tộc thiểu số.
5. **Tôn giáo & Tín ngưỡng.**

> **Lưu ý tách biệt:** Chê bai, kêu gọi tẩy chay một cửa hàng/doanh nghiệp cụ thể vì dịch vụ kém (*“quán này lừa đảo, tẩy chay đi”*) là **phàn nàn dịch vụ (`clean`)**, hoàn toàn khác với việc quy chụp xấu cho cả một cộng đồng người (*“dân vùng X toàn lũ lừa đảo”* $\rightarrow$ **Hate Speech `toxic`**).

### Điểm 4: Quy trình xử lý câu mơ hồ & Xây dựng bộ Benchmark chuẩn
1. **Gán nhãn đa trạng thái trong rà soát:**
   * Sử dụng 3 trạng thái khi audit: `toxic`, `clean`, và `needs_context` (hoặc `Cần thảo luận`).
2. **Xử lý tập `needs_context`:**
   * Cố gắng bổ sung ngữ cảnh (bình luận cha, bài viết gốc).
   * Nếu sau khi bổ sung vẫn không đạt được đồng thuận (Inter-Annotator Agreement < 80%): **Loại bỏ khỏi bộ Gold Benchmark chấm điểm chính thức**.
3. **Phân tách bộ dữ liệu đánh giá:**
   * **Core Gold Benchmark (100% Đồng thuận):** Dùng để tính toán Accuracy, Precision, Recall, F1 chính thức cho model.
   * **Challenge Set (Tập thử thách biên):** Dùng riêng cho nghiên cứu chuyên sâu về khả năng hiểu ngữ cảnh đa tầng của LLM.
