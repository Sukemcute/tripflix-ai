# Cách người dùng Việt hỏi, lọc, sắp xếp, so sánh chỗ ở và chuyến bay nội địa với trợ lý du lịch hội thoại

Ghi chú nghiên cứu: web search chỉ trả về snippet, không mở được trang bộ lọc của OTA. Phần "Cited Findings" chỉ chứa điều có nguồn. Danh mục câu mẫu (utterance) tiếng Việt là do tác giả tự dựng từ kiến thức ngôn ngữ chung, KHÔNG phải trích từ log thật; nằm ở "Inferences" và cần kiểm chứng bằng log Tripi.

## 1. Các OTA Việt Nam / khu vực đưa ra chiều lọc, sắp xếp nào và chiều nào dùng nhiều nhất?

### Takeaway
Nguồn công khai cho thấy các OTA lớn đều có lọc giá, sao, điểm đánh giá, tiện ích, và sắp xếp (giá thấp nhất, đánh giá cao nhất); với vé bay là giá, giờ đi/đến, hãng. Không tìm được trang trợ giúp liệt kê đầy đủ bộ lọc của Agoda, Mytour, iVIVU, Vietjet; số liệu dùng nhiều nhất chỉ có một nguồn thứ cấp.

### Cited Findings
- Agoda quảng bá bộ lọc, ảnh, chế độ bản đồ, thông tin địa phương; một đánh giá bên thứ ba nói có nhiều tùy chọn lọc — [Agoda about](https://www.agoda.com/vi-vn/about-agoda/what-exactly-does-agoda-offer), [TopTenReviews](https://www.toptenreviews.com/hotel-booking-services-agoda-review)
- Nguồn thứ cấp (chưa đối chiếu gốc): loại hình lưu trú chiếm 31% lượt dùng bộ lọc của du khách Việt (2026); bữa sáng đứng thứ hai ở châu Á (12%); hồ bơi 3%, ban công 2%, máy lạnh 1% — [leisure-travel.vn](https://leisure-travel.vn/?p=39944)
- Trang danh sách khách sạn Trip.com có lọc theo số sao, điểm khách đánh giá và sắp xếp (giá thấp nhất, đánh giá cao nhất) — [vn.trip.com](https://vn.trip.com/hotels/bentong-hotels-list-61213/star3)
- Traveloka vé bay: mỗi chuyến hiển thị giá, ghế còn, giờ bay, hãng, hành lý ký gửi, chính sách hủy/đổi; lọc theo khoảng giá ở thanh bên; chọn theo giá, giờ đi, giờ đến; có thông báo giá vé — [Traveloka app](https://apps.apple.com/vn/app/traveloka-kh%C3%A1ch-s%E1%BA%A1n-v%C3%A9-m%C3%A1y-bay/id898244857?l=vi), [PLO](https://plo.vn/meo-vang-giup-san-ve-may-bay-tet-binh-ngo-2026-gia-hoi-tu-traveloka-post866580.html), [VNTravelLive](https://vntravellive.com/en/tinh-nang-thong-bao-gia-ve-cua-traveloka-d32551.html)
- Vietjet có các hạng ECO, Deluxe, Skyboss, Business; Deluxe kèm 20 kg ký gửi nội địa; hướng dẫn của hãng khuyên giờ rạng sáng/đêm muộn (23h–5h) rẻ hơn — [Vietjet hybrid](https://www.vietjetair.com/vi/diem-den/kinh-nghiem/hang-khong-hybrid-la-gi-hanh-khach-duoc-loi-gi-tu-mo-hinh-nay), [Vietjet Tết](https://www.vietjetair.com/vi/diem-den/kinh-nghiem/nen-mua-ve-may-bay-tet-khi-nao-cach-mua-ve-tet-gia-re)
- Xách tay Vietjet theo Kayak: tối đa 56x36x23 cm — [Kayak](https://www.vn.kayak.com/VietJet-Air.VJ.airline.en.html)

### Inferences
- Chiều lọc phổ biến cần hỗ trợ tối thiểu cho chỗ ở: giá/đêm, hạng sao, điểm đánh giá, loại hình (khách sạn/homestay/villa/resort), tiện nghi (bữa sáng, hồ bơi, ban công/view, máy lạnh, đỗ xe, thú cưng), chính sách hủy miễn phí, khu vực/khoảng cách, số khách/phòng/giường. Vé bay: giá, giờ đi/đến, hãng, số điểm dừng, hành lý, hạng vé, khứ hồi.
- Sắp xếp: giá tăng/giảm, đánh giá, khoảng cách, "phù hợp nhất"; vé bay: rẻ nhất, sớm nhất, nhanh nhất.

### Gaps
- Danh sách bộ lọc chính thức của Agoda, Booking.com, Mytour, iVIVU, Vietnam Airlines, Vietjet: không lấy được (snippet không đủ; Mytour/iVIVU không có kết quả). Cần mở app/web thủ công.
- Xác nhận Traveloka có lọc hành lý và sort giá tăng dần: không tìm thấy.
- Con số 31%/12% chưa xác thực.

## 2. Người dùng tinh chỉnh kết quả qua hội thoại thế nào (so sánh tương đối, phủ định, ghép ràng buộc)?

### Takeaway
Không tìm được nghiên cứu công khai đo trực tiếp hành vi tinh chỉnh tiếng Việt. Nghiên cứu agent chung chỉ ra các lỗi lặp lại: theo dõi ràng buộc kém, chốt sớm, bỏ qua ràng buộc cứng. Danh mục dưới đây là suy luận.

### Cited Findings
- UserBench: mô hình hỏi sơ sài, chọn phương án quá sớm, lặp lại chọn trên cùng một khía cạnh (theo dõi trạng thái yếu) — [UserBench](https://arxiv.org/pdf/2507.22034)
- ReSpAct: mẫu làm rõ chuẩn: thu hẹp khi quá nhiều kết quả, nới khi không có kết quả, hỏi thêm khi không liên quan — [ReSpAct](https://arxiv.org/pdf/2411.00927)
- PIVOT: baseline chọn khách sạn thiếu tính năng người dùng bắt buộc (screen mirroring) — [PIVOT](https://arxiv.org/pdf/2605.11225)
- TravelEval: mô hình báo đạt ngân sách dù tổng chi tiết vượt xa — [TravelEval](https://arxiv.org/pdf/2606.01046)

### Inferences (danh mục câu mẫu, tự dựng, chưa kiểm chứng bằng log thật)
Quy ước: mỗi mẫu gồm cả dạng có dấu và không dấu/teencode.

**A. Chỗ ở: giá**
- "khách sạn đà lạt dưới 500k/đêm" / "ks da lat duoi 500k"
- "tầm 1tr2 một đêm", "1 củ rưỡi", "không quá 2 triệu", "từ 800k đến 1tr5"
- "dưới 1 triệu/người" (chia theo đầu người, cần nhân số khách), "cả nhóm 6 người tổng 3 củ"
- "rẻ nhất", "giá sinh viên", "bình dân", "xịn xịn tí", "sang chảnh"
- Quy đổi tiền: k = nghìn; tr/triệu/m = triệu; "1tr2" = 1.200.000; "củ" = triệu (cần xác nhận, nguồn chỉ nói "lít" = trăm nghìn, "xị" = 10 nghìn, "tỏi" = tỷ — [FPT Shop](https://fptshop.com.vn/tin-tuc/danh-gia/1-lit-la-bao-nhieu-tien-167587)). "Củ" trong fptshop có bài riêng nhưng snippet không ghi giá trị; hiểu thông dụng là 1 triệu.

**B. Chỗ ở: tinh chỉnh tương đối (cần giữ trạng thái lượt trước)**
- "đắt hơn tí", "rẻ hơn nữa", "có cái nào xịn hơn không", "gần biển hơn", "gần trung tâm hơn", "yên tĩnh hơn", "mới hơn", "nhiều review hơn"
- "giống cái đầu nhưng rẻ hơn", "tương tự cái thứ 2 mà có hồ bơi"
- Tham chiếu thứ tự: "cái thứ 2", "cái cuối", "cái rẻ nhất trong đó", "cái vừa rồi"
- Tham chiếu kết quả: "cái thứ 2 có gì?", "cái đó có ăn sáng không", "cho xem ảnh cái số 3"

**C. Lọc sao/đánh giá/loại phòng**
- "4 sao trở lên", "trên 8 điểm", "tối thiểu 4.5", "homestay thôi", "villa nguyên căn", "căn hộ có bếp"
- "phòng đôi/2 giường đơn", "phòng family", "giường phụ", "3 người lớn 1 trẻ em 5 tuổi", "2 phòng liền kề"

**D. Tiện nghi/vị trí**
- "có hồ bơi", "view biển", "cho mang thú cưng/chó mèo", "gần chợ đêm", "gần sân bay", "đi bộ ra biển", "có đỗ xe ô tô", "bếp nấu ăn", "bồn tắm", "bao ăn sáng"
- Phủ định: "không cần hồ bơi", "đừng homestay", "bỏ mấy chỗ trên đồi", "không cần ăn sáng"
- Kết hợp: "villa Vũng Tàu cho 10 người có hồ bơi, dưới 5tr, cuối tuần này"

**E. Chính sách hủy và thanh toán**
- "huỷ miễn phí không", "có hoàn tiền không", "trả tại khách sạn được không", "đổi ngày được không", "cọc bao nhiêu"

**F. So sánh hai phương án**
- "so sánh cái 1 với cái 3", "cái nào gần biển hơn", "khác gì nhau", "chọn giúp mình", "đáng tiền hơn cái nào", "tổng 3 đêm hết bao nhiêu"
- Chia tiền: "chia đầu người bao nhiêu", "4 người chia đều", "mỗi người ra bao nhiêu"

**G. Vé bay nội địa**
- "vé HN đi SGN thứ 6 này", "bay sáng sớm", "sau 6h tối", "trước 10h", "bay đêm cho rẻ"
- Hãng: "chỉ Vietjet/Bamboo/VNA", "không bay Vietjet", "tránh Pacific"
- Hành lý: "có 20kg ký gửi không", "chỉ xách tay thôi", "thêm 15kg bao nhiêu"
- Giá: "rẻ nhất tuần sau", "ngày nào rẻ nhất trong tháng 12", "dưới 1tr/người", "khứ hồi", "đi thứ 6 về chủ nhật", "bay thẳng", "đổi ngày được không", "huỷ hoàn không"
- Tinh chỉnh: "sớm hơn", "muộn hơn", "rẻ hơn", "hãng khác", "chuyến thứ 2 mấy giờ hạ cánh"

**H. Dạng viết không dấu/teencode (cần chuẩn hoá đầu vào)**
- "kh san", "ks", "hs" (không rõ), "k cần", "ko", "dc/đc", "vs", "j", "ntn", "bn" (bao nhiêu), "r" (rồi), "mik/mk", "ok k", "tp.hcm/sg/hcm/sgn", "hn/hanoi", "dl/dalat", "pq/phu quoc", "nt/nha trang"
- Cần xác nhận bằng log thật; không đủ nguồn để khẳng định tần suất.

### Gaps
- Không có corpus/log hoặc nghiên cứu học thuật về cách người Việt hỏi lọc chỗ ở bằng chat. Cần lấy từ log Tripi, nhóm Facebook/Reddit r/VietNam (không truy cập được trong đợt này).
- Không có số liệu tần suất từng loại câu.

## 3. Trợ lý AI du lịch (Booking.com, Agoda, Trip.com, Traveloka, Expedia) hỗ trợ tinh chỉnh tiếp theo thế nào và thất bại ở đâu?

### Takeaway
Các nhà cung cấp quảng bá tinh chỉnh theo thời gian thực và bộ lọc tự áp dụng từ ngôn ngữ tự nhiên; đánh giá độc lập cho thấy lọc chưa hoàn hảo và AI đôi khi lỗi thời/bịa. Agoda mới mở rộng trợ lý AI sang 21 thị trường gồm Việt Nam (11/2026).

### Cited Findings
- Booking.com AI Trip Planner: trò chuyện, hỏi đáp, tinh chỉnh thời gian thực; Smart Filter tự áp dụng bộ lọc từ câu tự nhiên; Property Q&A — [Hospitality Net](https://hospitalitynet.org/news/4124415.html), [Booking news](https://news.booking.com/how-bookingcoms-ai-trip-planner-can-inspire-travelers-to-plan-that-last-minute-summer-vacation/)
- Skift: bộ lọc AI "không như phép màu" khi hỏi chi tiết từng khách sạn — [Skift](https://skift.com/2024/10/30/booking-coms-ai-trip-planner-got-a-big-update-heres-how-it-works)
- Lodgify: AI Trip Planner bổ sung chứ không thay tìm kiếm chuẩn — [Lodgify](https://encyclopedia.lodgify.com/booking-com-ai-trip-planner)
- Afar: ứng dụng lập kế hoạch AI hay lỗi thời và "hallucinate" (nhận định chung) — [Afar](https://www.afar.com/magazine/we-tested-ai-travel-planning-apps-here-are-the-3-that-actually-worked?country=85)
- Agoda AI Assistant mở rộng 21 thị trường gồm Việt Nam, so sánh khu vực, tìm chỗ ở và vé theo ngày, tích hợp web search, chạy trên mô hình OpenAI — [Viet Nam News](https://vietnamnews.vn/life-style/1803525/agoda-expands-ai-travel-assistant-to-21-markets.html), [Agoda press](https://www.agoda.com/press/1509063/)
- Trip.com TripGenie: ra mắt 2023, có đặt trong app; công ty báo đơn hàng hỗ trợ AI tăng ~400% (số liệu công ty) — [Trip.com](https://www.trip.com/newsroom/introducing-tripgenie-groundbreaking-ai-travel-assistant), [AAP 2026](https://www.aap.com.au/aapreleases/cision20260315ae09481)

### Inferences
- Điểm yếu cần tránh trong Tripi: giữ ràng buộc qua nhiều lượt, kiểm ràng buộc cứng (ngân sách, thú cưng), xử lý 0 kết quả/quá nhiều kết quả bằng nới/thu hẹp, trả lời dữ kiện từng khách sạn từ dữ liệu có thật thay vì bịa.

### Gaps
- Không tìm thấy nguồn về chatbot AI của Traveloka, Mytour, iVIVU; không có đánh giá độc lập về tinh chỉnh tiếng Việt của Agoda AI; Expedia Romie/ChatGPT plugin chưa tìm được.

## 4. Cách viết tắt tiền tiếng Việt phổ biến

### Takeaway
Nguồn tìm được chỉ xác nhận một phần tiếng lóng; "500k", "1tr2" là cách viết thông dụng không cần nguồn, "củ" cần xác minh.

### Cited Findings
- "Xị" (miền Nam) = 10.000đ; "lít" = 100.000đ; "tỏi" = 1 tỷ — [FPT Shop](https://fptshop.com.vn/tin-tuc/danh-gia/1-lit-la-bao-nhieu-tien-167587)
- Tiếng lóng tiền dùng trong nhóm nhất định, tránh chú ý khi nhắc số lớn — cùng nguồn.

### Inferences
- Bảng chuẩn hoá đề xuất: `500k`=500.000; `1tr2`/`1m2`=1.200.000; `1tr`=1.000.000; `3 củ`=3.000.000 (thường hiểu, chưa có nguồn); `1 lít`=100.000 (dễ nhầm, nên hỏi lại nếu ngữ cảnh mơ hồ); `1 chai` = 100.000 (cách dùng vùng miền, chưa xác nhận); `nửa củ`=500.000; `rưỡi` = +0,5 đơn vị liền trước.
- Mơ hồ "đơn vị": /đêm vs /người vs tổng; "dưới 1 triệu/người" cho nhóm cần nhân số khách; phải ghi lại giả định khi trả lời.

### Gaps
- Giá trị "củ", "chai", "lít" vùng miền chưa có nguồn đầy đủ; cần xác nhận bởi người bản ngữ.
