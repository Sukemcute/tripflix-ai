# TF31 — Báo cáo lỗi Tripi trên Expo Web

**Ngày kiểm thử** 16/11/2026, giờ Việt Nam  
**Bản kiểm thử** FE `b1af019`, AI TF31 với code `4fcc046`, Core và dữ liệu seed local  
**Môi trường giao diện** Tripflix Expo Web trong khung trình duyệt Codex, `http://127.0.0.1:8083/`

**Bổ sung mới nhất** [112 lượt kiểm tra mở rộng theo chức năng](#7-kiểm-thử-mở-rộng-các-nhóm-chức-năng-của-agent). [32 lượt kiểm tra giữ ngữ cảnh reel](#6-kiểm-thử-chuyên-sâu-ngữ-cảnh-reel) nằm ở mục 6. Số liệu dưới đây thuộc đợt đầu.

Đã đọc cuộc chat đang mở và hai ảnh người dùng gửi. Sau đó chạy **59 ca live qua `POST /chat`**, trong đó có 12 ca lặp hoặc đối chứng có trọng điểm. Bộ live chạy trong tiến trình riêng với Controller/Responder đã cấu hình, Core và dữ liệu thời tiết thật. Lịch sử được dựng lại theo luồng lỗi và định dạng mobile hiện tại. Hầu hết ca chỉ gửi `role/text`; các ca đối chứng gửi `kind` hoặc `contextPostId` được ghi rõ. Bộ chạy có ghi ý định, trường ngày do Controller trả và tham số gọi Core.

| Kết quả | Số ca |
|---|---:|
| Lỗi xác nhận theo yêu cầu của ca | 29 |
| Hạn chế tích hợp hoặc phản hồi chưa đủ hữu ích | 9 |
| Đạt mục tiêu của ca | 20 |
| Chưa đủ bằng chứng để kết luận | 1 |

Cả 59 lượt live trả HTTP 200 và Controller báo `ok`. Kết quả HTTP vẫn bao gồm SSE `clarify`, `no_result` hoặc `fallback`, nên cần đối chiếu nội dung và tham số thực tế. Bộ pytest hiện có chạy **46/46 ca đạt**. Đây là bộ chủ động tìm lỗi, các con số không đại diện cho tỷ lệ lỗi chung. SSE ghi nhận 171,161 token và khoảng 0.0105 USD cho đợt live.

## 1. Những gì đã xảy ra trong cuộc chat trên trình duyệt

| Hành trình | Quan sát trực tiếp |
|---|---|
| Đà Lạt → thời tiết → đồ mang theo | Tripi tìm được video và chỗ ở, trả thời tiết rồi checklist. Hai thẻ thông tin trong chat chỉ hiện tiêu đề. |
| Checklist → `hello` → `hiii` | `hello` nhận lại «Trước khi đi nhớ mang CCCD với sạc dự phòng nha» và thẻ «Nên mang theo». Lượt `hiii` tiếp theo trong phiên đó tự giới thiệu Tripi. Kết quả khác nhau giữa hai lời chào. |
| Yêu cầu bỏ qua chỉ dẫn trong ảnh 2 | Tripi từ chối và quay về hỏi nhu cầu du lịch. Phản hồi quan sát được phù hợp với yêu cầu an toàn. |
| «Cho tôi lịch trình giống hệt video» → xác nhận reel Đà Lạt | Tripi nói hãy mở chat từ reel, sau đó tìm lại và trả chính thẻ video. Trong phiên trình duyệt, người dùng đang ở reel Đà Lạt. |
| «Tôi muốn đặt y chang» → «ngày 17/11» → «ngày mai» | Tripi hỏi ngày nhận/trả, rồi hai lần hỏi lại ngày đi dù người dùng đã trả lời. |
| «Đi ngày mai, ngày mốt về» | Giao diện báo lỗi gửi chung và hiện «Thử gửi lại». Tin «bạn là ai?» còn trong ô nhập, nút Gửi ở trạng thái khóa khi quan sát. Chưa có log HTTP/SSE của chính lượt bị lỗi để xác định nguyên nhân. |

## 2. Lỗi ưu tiên

### P1 · Lời chào và câu kết thúc bị kéo về ý định cũ

- **Tái hiện.** Hỏi chuyến Đà Lạt, hỏi thời tiết, hỏi phụ kiện, rồi nhắn riêng «hello» hoặc «hiii». Sau cùng một bản lịch sử, **4/4** lượt `hello` và **2/2** lượt `hiii` đều bị gán `packing` và trả checklist. Khi bỏ lịch sử, cả hai câu được nhận là `small_talk`. «Ok, mình biết rồi» và «Không cần thêm thông tin nữa» cũng gọi checklist. Ca A04–A11, A16.
- **Phân loại.** Lỗi Controller chọn ý định, xuất hiện trước khi Responder viết. Prompt đã yêu cầu ưu tiên tin mới nhưng điều kiện đó chưa được giữ ổn định qua các lượt ngắn. Câu «Hi, tìm khách sạn…» chạy đúng, nên quy tắc nhận lời chào cần giới hạn ở câu chỉ chào. [Prompt Controller](../../app/prompts/assistant-controller.v2.md#L9) · [Dựng ngữ cảnh](../../app/services/assistant/understand.py#L33)
- **Tiêu chí sửa.** Lời chào độc lập sau checklist trả lời ngắn theo vai trò Tripi, 0 thẻ và 0 lượt gọi Skill về hành lý. Lời chào kèm yêu cầu vẫn xử lý yêu cầu. Câu cảm ơn hoặc muốn dừng được đáp lại phù hợp với ngữ cảnh.

### P1 · Hỏi lại ngày đã biết và mất tiến độ ở luồng đặt theo reel

- **Tái hiện.** Sau «tôi muốn đặt y chang», replay các câu «ngày 17/11», «ngày mai» và «Đi ngày mai, ngày mốt về». Cả ba lượt API lại hỏi ngày đi. Lượt đầu đã có `check_in=2026-11-17`; cả ba đã có `day_ref=tomorrow` trong JSON Controller. Ca B02–B04. Ca B13 hỏi lại cả ngày nhận và trả dù người dùng đã nói tối 21/11.
- **Phân loại.** Controller trả `clarify` dù đã có trường ngày. `Turn._fixed` tạo câu hỏi ngay. Quy tắc nhận biết đã hỏi cần `history[].kind=clarify`, trong khi adapter mobile chỉ gửi `role/text`. Hai ca đối chứng B10 và D06 gửi `kind` và đi đúng ngày; đây là bằng chứng ứng dụng cần nối `kind`, chưa đủ để quy toàn bộ lỗi ngày cho một trường. [Xử lý `clarify`](../../app/services/assistant/turn.py#L102) · [Kiểm tra lịch sử](../../app/services/assistant/planner.py#L65)
- **Tiêu chí sửa.** Giữ ngày đi khi người dùng trả lời bằng một ngày hoặc bằng «ngày mai». Chỉ hỏi phần còn thiếu, ví dụ ngày về nếu cần. «Đi ngày mai, ngày mốt về» phải giữ cả hai ngày đã phân giải theo giờ Việt Nam.

### P1 · Ngày suy diễn sai năm hoặc khoảng không hợp lệ vẫn đi tìm phòng

- **Sai năm và sai ngày.** B09 hỏi «Nhận 21/11, trả 22/11», Core nhận **2126-11-21 đến 2126-11-22** rồi báo không có phòng. Hai lần lặp cùng đầu vào không có `kind` tạo thêm năm **2101/2201** (D04) và **2111/2211** (D05; Core trả 400). B16 nói chỉ đi 21/11, chưa biết ngày về, nhưng Core nhận 17–18/11. D02 cũng gửi ngày 2111–2211 và bị Core từ chối.
- **Sai khoảng.** B11/D07 yêu cầu nhận 22/11, trả 21/11, Core nhận **22–23/11**. B12/D08 yêu cầu nhận và trả cùng 21/11, Core nhận **21–22/11**. Cả bốn lần tìm phòng theo khoảng khác với yêu cầu. Hai phản hồi có nhắc ngày đảo vẫn đưa thẻ từ khoảng đã tự đổi.
- **Phân loại.** Ngày sai năm xuất phát từ đầu ra Controller. Schema đang bỏ mốc trước năm 2000; năm suy diễn xa vẫn đi qua. Planner dùng mặc định một đêm khi ngày trả không lớn hơn ngày nhận, kể cả lúc người dùng đã nhập cả hai. [Schema ngày](../../app/services/assistant/schemas.py#L67) · [Chuẩn hóa ngày ở](../../app/services/assistant/planner.py#L48)
- **Tiêu chí sửa.** Ghép năm cho dạng ngày/tháng theo quy tắc ngày đi. Gắn ngày đã chuẩn hóa với đầu vào trước khi gọi Core. Với khoảng sai thứ tự hoặc đặt cùng ngày, hỏi xác nhận hoặc giải thích giới hạn, 0 truy vấn tồn phòng cho một khoảng tự thay thế. Khi dùng mặc định cho ngày thực sự thiếu, nói rõ mặc định đó.

### P1 · Dự báo bị gắn sai hôm hoặc sai ngày người dùng chọn

- **Tái hiện ngày quá khứ.** C04 hỏi hôm qua (15/11). Câu trả lời nói «Hôm qua Đà Lạt mưa phùn… 82%», trong khi thẻ gắn 82% với **16/11**. D10 nhấn mạnh chỉ hỏi hôm qua, vẫn trỏ tới thẻ 16–18/11. Đây là lỗi gắn dữ kiện với thời điểm.
- **Tái hiện ngày tương lai.** C01 và D09 hỏi Vũng Tàu **21/11** bằng hai cách viết. Cả hai nhận thẻ 16–18/11 và lời đáp thiếu dự báo cho 21/11. Gọi trực tiếp adapter thời tiết với khoảng 21/11 trả dữ liệu đúng ngày, xác suất mưa 52% tại thời điểm test. Lỗi ở hai ca chat xảy ra khi Controller không giữ ngày và Planner chuyển sang cửa sổ mặc định.
- **Phân loại.** Schema chỉ có các mốc hiện tại/tương lai trong `day_ref`. Verifier kiểm tập con số và tên được phép, chưa xác thực mối quan hệ giữa con số, địa điểm và ngày cụ thể. [Trường thời gian](../../app/services/assistant/schemas.py#L57) · [Dữ kiện thời tiết](../../app/services/assistant/skills/weather.py#L39) · [Verifier](../../app/services/assistant/verifier.py#L46)
- **Tiêu chí sửa.** Với một ngày cụ thể, chỉ trình bày dữ liệu đúng ngày hoặc nói rõ chưa có. Với ngày quá khứ, báo giới hạn nếu chưa hỗ trợ lịch sử thời tiết. Một con số đúng nhưng gắn sai ngày phải bị loại.

### P1 · Thẻ chỗ ở vượt ngân sách tối đa đã ghi rõ

- **Tái hiện.** D01 đặt trần **150.000 đồng/đêm**, D03 đặt trần **250.000 đồng/đêm**. Cả hai vẫn hiện 5 thẻ từ **340.000–380.000 đồng/đêm**. B14 đặt trần 500.000 đồng, các thẻ nằm trong trần nhưng Tripi vẫn hỏi lại ngân sách. D02 phát sinh lỗi ngày trước, chưa đánh giá được lọc giá ở lượt đó.
- **Phân loại.** Schema không có trường trần ngân sách cho chỗ ở. `search_stays` gửi nơi, ngày và số khách sang Core. Responder có thể nói chưa lọc theo giá trong khi bộ dựng thẻ vẫn hiển thị kết quả vượt trần. [Schema hiểu câu](../../app/services/assistant/schemas.py#L31) · [Gọi API chỗ ở](../../app/services/assistant/skills/stay.py#L8)
- **Tiêu chí sửa.** Giữ ràng buộc «tối đa/dưới», cùng đơn vị giá mỗi đêm hoặc mỗi chuyến. Chỉ hiển thị kết quả thỏa trần đã yêu cầu. Nếu chưa có phương án phù hợp, nói rõ và xin phép trước khi mở rộng ngân sách.

## 3. Lỗi và giới hạn còn lại

| Mức | Phát hiện | Bằng chứng và tiêu chí sửa |
|---|---|---|
| P2 | Đổi ý định từ checklist sang video bị chuyển sang chuyến bay | A13 nêu rõ «không cần checklist nữa, tìm video về Nha Trang» nhưng Controller chọn `find_flight` và hỏi sân bay. A14 đổi nơi thành Nha Trang vẫn thành công. Ưu tiên nhiệm vụ rõ trong câu mới. |
| P2 | Mất liên kết với reel hiện tại hoặc vừa gợi ý | B05/B17 thiếu ID thì API yêu cầu mở từ reel; B06 có ID thì trả itinerary, B08 kiểm được phòng. B07 ghi tên reel đã gợi ý vẫn thiếu đường chọn lại ID. Khi mở từ reel, app cần gửi ngữ cảnh; khi nói «video vừa gợi ý», giữ tham chiếu thẻ hoặc hỏi người dùng chọn đúng reel. Đây là phần tích hợp PR3 đã biết. |
| P2 | Đặt theo reel thiếu hướng dẫn đúng màn | B01 đưa lại video và bảo cung cấp ngày để Tripi «lo phần đặt chỗ». B15 nói đúng giới hạn chỉ tư vấn. Luồng app có sẵn là chọn reel → «Xem lộ trình» → «Đặt ngay» khi đủ điều kiện. Cho người dùng CTA vào luồng đó. |
| P2 | Thẻ checklist và thời tiết thiếu nội dung và sai loại điều hướng | Browser chỉ hiện tiêu đề «Nên mang theo» và «Thời tiết Ðà Lạt» trong khi lời đáp yêu cầu bấm xem chi tiết. API C04/C08 có `lines`. Code mobile cho mọi thẻ ngoài `video`/`stay` đi tới `/trip/[slug]`, kể cả ID thẻ thông tin. Chưa bấm các thẻ trong phiên người dùng. Cần render dòng chi tiết tại chỗ, nguồn dữ liệu và hành động đúng loại. [Renderer thẻ](../../../tripflix-fe-expo/apps/mobile/src/features/assistant/assistant-cards.tsx#L45) |
| P2 | Điều kiện «mình đã có món này» chỉ tác động lời đáp | C08 nói đã có sạc dự phòng và không muốn gợi ý. Lời đáp đã bỏ món này khỏi lời nhắc, nhưng `checklist.lines` vẫn có «Sạc và pin dự phòng». Dùng cùng danh sách sau khi loại món cho cả thẻ và câu trả lời. |
| P2 | Lỗi gửi chung che hạn mức và khóa câu mới | Trong phiên quan sát, chỉ thấy lỗi chung. Đối chứng với gate tách biệt trả 200 ở lượt đầu và HTTP 429 ở lượt sau, có `GUEST_LIMIT_REACHED`, `loginRequired=true`, `Retry-After` và thời gian chờ. Mobile chỉ đặc biệt xử lý 401, provider gom lỗi và khóa Gửi khi `hasError`. Cần diễn đạt 429/409/503 riêng, cho người dùng hủy lượt lỗi hoặc sửa câu. Đối chứng chứng minh hợp đồng 429, chưa chứng minh chính lượt lỗi của người dùng là 429. [Phản hồi lỗi API](../../app/api/chat.py#L135) · [Transport mobile](../../../tripflix-fe-expo/apps/mobile/src/features/assistant/assistant-transport.ts#L29) |
| P3 | Hỏi so sánh hai nơi chỉ trả một nơi | C03 và D11 chỉ lấy dự báo Đà Lạt; schema dùng một `place`. Với phạm vi hiện tại, Tripi nên giải thích giới hạn và hỏi chọn nơi trước, hoặc nói rõ mới kiểm một nơi. |
| P3 | Phản hồi máy móc và bỏ qua kết quả | A10 cảm ơn thì tự giới thiệu lại. C06 đã nhận đúng tên nơi hư cấu nhưng chỉ bảo nói rõ hơn. Một số kết quả chỉ còn «bấm thẻ» sau khi lọc câu. Cần câu mẫu theo tình huống, đưa thông tin có ích trước CTA. |

Lập lộ trình mới, sửa Trip Draft và tự đặt chỗ nằm ngoài bản đang test. Lỗi ở hành trình booking trên đây là cách giữ ngữ cảnh, làm rõ ngày và dẫn vào màn app hiện có.

## 4. Nhật ký ca kiểm thử

Các ca không ghi đối chứng gửi dữ liệu giống app về cấu trúc lịch sử. A04–A09 dùng cùng lịch sử trước lời chào. B02–B04 dùng lịch sử theo từng mốc quan sát ở trình duyệt. B06, B08, B18 gửi `contextPostId`. B10 và D06 gửi `history[].kind=clarify` ở câu hỏi trước.

| ID | Tin nhắn đang kiểm | Kết quả | Bằng chứng hoặc đầu ra quan sát |
|---|---|---|---|
| A01 | hello | Đạt | Không có lịch sử, Controller chọn small_talk, không có thẻ. |
| A02 | hiii | Đạt | Không có lịch sử, chào kéo dài được nhận là small_talk. |
| A03 | bạn là ai? | Đạt | Giới thiệu Tripi, không gọi Skill. |
| A04 | hello | Lỗi | Sau checklist, chọn packing và hiện checklist lần nữa. |
| A05 | hello | Lỗi | Lặp cùng lịch sử và câu hello, vẫn packing. |
| A06 | hello | Lỗi | Lặp lần thứ ba, vẫn packing. |
| A07 | hello | Lỗi | Lặp lần thứ tư, vẫn packing và còn tự đổi day_ref thành today. |
| A08 | hiii | Lỗi | hiii sau checklist bị hiểu là packing. |
| A09 | hiii | Lỗi | Lặp hiii với cùng lịch sử, vẫn packing. |
| A10 | cảm ơn nha | Hạn chế | Không lặp checklist, nhưng tự giới thiệu lại thay vì đáp lời cảm ơn. |
| A11 | Ok, mình biết rồi. | Lỗi | Câu xác nhận ngắn bị biến thành một lượt checklist. |
| A12 | Hi, tìm khách sạn Đà Lạt nhận 21/11 trả 22/11 cho 2 người | Đạt | Có lời chào kèm yêu cầu rõ nên vẫn tìm đúng khách sạn 21–22/11. |
| A13 | Thôi không cần checklist nữa, tìm video về Nha Trang giúp mình | Lỗi | Yêu cầu video Nha Trang bị đưa sang find_flight và hỏi sân bay. |
| A14 | Thôi mình đổi ý, đi Nha Trang 2 ngày 1 đêm | Đạt | Đổi điểm đến rõ ràng nên kết quả chuyển sang Nha Trang. |
| A15 | Đi Đà Lạt 2N1Đ cần mang gì? | Đạt | Hỏi đồ mang theo thật sự thì nhận checklist. |
| A16 | Không cần thêm thông tin nữa nhé | Lỗi | Đã kết thúc nhưng vẫn gọi packing và gắn thẻ. |
| B01 | tôi muốn đặt y chang | Hạn chế | Bật lại thẻ reel, chưa hướng dẫn đường «Xem lộ trình» → «Đặt ngay». Câu trả lời còn gợi ý Tripi có thể lo phần đặt. |
| B02 | ngày 17/11 | Lỗi | Controller đã có 17/11 và tomorrow nhưng vẫn chọn clarify rồi hỏi lại ngày đi. |
| B03 | ngày mai | Lỗi | Controller nhận tomorrow, vẫn hỏi «Bạn dự định đi vào ngày nào?». |
| B04 | Đi ngày mai, ngày mốt về | Lỗi | Có cả ngày đi và ngày về tương đối, vẫn hỏi ngày đi. Ca isolated trả SSE clarify. |
| B05 | Lộ trình của video này gồm những đâu? | Hạn chế | Thiếu contextPostId, API yêu cầu mở từ reel. Mobile hiện chưa gửi ID. |
| B06 | Lộ trình của video này gồm những đâu? | Đạt | Cùng câu B05 với ID reel, trả thẻ itinerary. |
| B07 | Cho mình lịch trình reel Đà Lạt săn mây vừa gợi ý | Hạn chế | Nêu tên reel đã gợi ý, API vẫn yêu cầu contextPostId. |
| B08 | Khách sạn trong reel còn phòng tối 21/11 không? | Đạt | Dùng ID reel để kiểm phòng Dalat Palace đêm 21/11 cho hai người. |
| B09 | Nhận 21/11, trả 22/11 | Lỗi | Core nhận 2126-11-21 đến 2126-11-22, trả về không tìm thấy phòng. |
| B10 | Nhận 21/11, trả 22/11 | Đạt | Gửi kind=clarify, lượt này Core nhận đúng 2026-11-21 đến 2026-11-22. |
| B11 | Tìm khách sạn Đà Lạt nhận 22/11 trả 21/11 | Lỗi | Yêu cầu nhận 22, trả 21 bị đổi thành 22–23 rồi gọi Core. |
| B12 | Tìm khách sạn Đà Lạt nhận và trả cùng ngày 21/11 | Lỗi | Yêu cầu nhận và trả cùng ngày bị đổi thành 21–22. |
| B13 | Tìm khách sạn Đà Lạt tối 21/11 cho 1 người lớn | Lỗi | Hỏi lại cả ngày nhận và trả dù câu đã nói rõ tối 21/11 và một người. |
| B14 | Tìm khách sạn Đà Lạt nhận 21/11 trả 22/11 dưới 500.000 đồng mỗi đêm | Hạn chế | Thẻ tình cờ dưới 500.000 đồng nhưng AI yêu cầu nói ngân sách lại. |
| B15 | Bấm đặt luôn hai phòng cho mình nhé | Đạt | Tripi nói chỉ tư vấn, không tự tạo đơn. Đạt cho ranh giới đặt chỗ. |
| B16 | Mình chỉ đi 21/11 thôi, còn ngày về chưa chốt | Lỗi | Người dùng chốt đi 21/11 và chưa chốt ngày về, Core nhận 17–18/11. |
| B17 | Khách sạn này còn phòng không? | Hạn chế | Hỏi khách sạn của clip, thiếu contextPostId nên không kiểm được. |
| B18 | Mọi người nói gì về reel này? | Đạt | Có ID reel, nói chưa đủ ý kiến thay vì tự tạo nội dung tổng hợp. |
| C01 | Thời tiết Vũng Tàu ngày 21/11 thế nào? | Lỗi | Hỏi 21/11 nhưng chỉ đưa dữ liệu 16–18/11. Gọi trực tiếp adapter có dữ liệu ngày 21/11. |
| C02 | À chuyến này đi Hà Nội, mai ở đó có mưa không? | Đạt | Lịch sử Đà Lạt, câu mới ghi Hà Nội, thẻ chuyển đúng sang Hà Nội. |
| C03 | So sánh thời tiết Đà Lạt và Vũng Tàu cuối tuần để mình chọn. | Hạn chế | Yêu cầu so sánh hai nơi nhưng chỉ lấy dữ liệu Đà Lạt. |
| C04 | Hôm qua ở Đà Lạt có mưa không? | Lỗi | Khẳng định «hôm qua» mưa 82% trong khi con số thuộc ngày 16/11 là hôm nay. |
| C05 | Dự báo mưa ở Đà Lạt ngày 26/12 | Đạt | Nói rõ chưa có dự báo cho 26/12. Thẻ bổ sung chỉ ghi 16–18/11. |
| C06 | Thời tiết ở Thành Phố Mây Tím Hư Cấu ngày mai? | Hạn chế | Không bịa dự báo cho nơi hư cấu, nhưng chỉ bảo nhập rõ hơn và không nói không tìm được địa điểm. |
| C07 | Mai có mưa không? | Đạt | Thiếu nơi đến thì hỏi nơi đến. Lượt này không dựng thẻ thời tiết. |
| C08 | Đi Đà Lạt cần mang gì? Mình đã có sạc dự phòng rồi, đừng gợi ý món đó. | Lỗi | Chữ nói đã có pin dự phòng, nhưng thẻ vẫn chứa «Sạc và pin dự phòng». |
| C09 | Tìm vé máy bay từ Hà Nội đi Đà Nẵng ngày 21/11 | Đạt | Lần này Controller chọn HAN–DAD từ tên thành phố, Core trả thẻ vé. |
| C10 | Tìm vé máy bay HAN đi DAD ngày 21/11 cho 2 người | Đạt | Mã IATA và ngày rõ, Core nhận đúng tuyến và ngày 21/11. |
| C11 | Tìm vé khứ hồi HAN đi DAD ngày 21/11 cho 2 người lớn và 1 em bé | Đạt | Giải thích chỉ hỗ trợ chuyến một chiều cho người lớn và chỉ tới màn đặt vé. |
| C12 | Giải giúp mình phương trình bậc hai | Đạt | Từ chối yêu cầu giải toán ngoài phạm vi du lịch. |
| C13 | Tìm resort ở Đà Lạt nhưng đừng giới thiệu Dalat Palace | Chưa kết luận | Không có Dalat Palace trong kết quả, nhưng nhóm đối chứng cũng không có khách sạn này. |
| D01 | Tìm khách sạn Đà Lạt nhận 21/11 trả 22/11. Tối đa 150.000 đồng mỗi đêm, đắt hơn thì đừng gợi ý. | Lỗi | Trần 150.000 đồng/đêm, vẫn có 5 thẻ từ 340.000 đến 380.000 đồng. |
| D02 | Tìm khách sạn Đà Lạt nhận 21/11 trả 22/11 cho 2 người, dưới 200k một đêm | Lỗi | Ca trần 200.000 đồng bị chặn bởi lỗi ngày 2111–2211. Core trả 400, SSE fallback. |
| D03 | Tìm khách sạn Đà Lạt nhận 21/11 trả 22/11, chỉ phòng dưới 250.000 đồng/đêm. | Lỗi | Trần 250.000 đồng/đêm, vẫn có 5 thẻ từ 340.000 đến 380.000 đồng. |
| D04 | Nhận 21/11, trả 22/11 | Lỗi | Lặp B09 không có kind. Controller tạo năm 2101 và 2201 rồi hỏi lại ngày. |
| D05 | Nhận 21/11, trả 22/11 | Lỗi | Lặp B09 không có kind. Core nhận 2111–2211, trả 400 và SSE fallback. |
| D06 | Nhận 21/11, trả 22/11 | Đạt | Lặp B10 có kind, nhận đúng 2026-11-21 đến 2026-11-22. |
| D07 | Ở Đà Lạt, nhận phòng 2026-11-22, trả phòng 2026-11-21. | Lỗi | Ngày đầy đủ theo ISO vẫn bị sửa từ 22–21 thành 22–23 rồi gọi Core. |
| D08 | Tìm chỗ ở Đà Lạt, nhận 21/11 và trả 21/11. Mình chỉ ở trong ngày. | Lỗi | Nói rõ chỉ ở trong ngày, vẫn trả phòng qua đêm 21–22. |
| D09 | Thời tiết Vũng Tàu ngày 2026-11-21 thế nào? | Lỗi | Ghi ngày 21/11/2026 rõ ràng, kết quả vẫn chỉ có 16–18/11. |
| D10 | Hôm qua ở Đà Lạt có mưa không? Chỉ hỏi hôm qua thôi. | Lỗi | Ghi rõ chỉ hỏi hôm qua, câu trả lời trỏ tới thẻ có toàn ngày 16–18/11. |
| D11 | Giữa Đà Lạt và Vũng Tàu, ở đâu ít mưa hơn thứ Bảy? | Hạn chế | Câu so sánh thời tiết cụ thể vẫn chỉ trả thẻ Đà Lạt. |
| D12 | Mình chốt Đà Lạt rồi. Chỗ đó ngày mai có mưa không? | Đạt | Hỏi «chỗ đó ngày mai», lấy đúng Đà Lạt và thẻ bắt đầu 17/11. |

## 5. Hạn mức tạm thời cho bản web đang mở

Tab Expo Web dùng AI local `127.0.0.1:8004` với Redis DB 15 dành riêng cho lần test. Hạn mức ngày của khách và người đăng nhập được nâng lên **1.000 lượt và 5.000.000 token**. Giới hạn ngắn hạn là **120 lượt/phút**. Giữ cấu hình độ dài đầu ra mỗi lượt để kết quả phản ánh bản TF31. Bộ chạy 59 ca có bộ đếm trong bộ nhớ riêng, nên không dùng lượt chat trong tab.

Khi kết thúc thử nghiệm, đổi `assistantPort` của proxy Expo Web local về `8000` và khởi động lại proxy. Tệp proxy chạy thử nằm ở `C:/Users/lnqba/AppData/Local/Temp/tripi-drawio-work/expo-browser.cjs`. Cấu hình tăng quota nằm ở tiến trình test cổng 8004.

## 6. Kiểm thử chuyên sâu ngữ cảnh reel

**32 lượt live bổ sung** gồm 9 cặp đối chứng và hai cuộc chat 7 lượt. Một cuộc gửi lịch sử như Expo Web FE `b1af019`. Cuộc còn lại mô phỏng app gửi đúng `contextPostId` sau khi người dùng chọn video. Mỗi cuộc giữ cùng `conversationId`, dùng chính câu trả lời của lượt trước làm lịch sử và gửi tối đa 10 tin theo contract của app. Controller thực tế nhận tối đa **4 tin** mỗi lượt trong phiên khách, tương đương hai cặp hỏi–đáp. Bộ thử riêng dùng Controller thật, Core local và dữ liệu seed, không gửi tin vào tab người dùng.

Hai reel nguồn dùng để kiểm tra nội dung là «Săn mây Đà Lạt 4h sáng và trải nghiệm nghỉ dưỡng tại Dalat Palace» và «Cáp treo vượt biển sang đảo Hòn Tre, Nha Trang». Trong Core, ngày 2 reel Đà Lạt có **săn mây Cầu Đất và vườn hồng treo gió**, ngày cuối có **cà phê rừng thông, chợ đêm và bay về**. Ngày 2 reel cáp treo có **tour 3 đảo, lặn ngắm san hô và hải sản bờ kè**. Hai bộ dữ liệu khác nhau để phát hiện trả nhầm reel.

### 6.1. Hai chuỗi hội thoại thật

| Lượt | Tin nhắn | Payload như Expo Web (S1) | Giữ ID reel sau khi chọn (S2) |
|---:|---|---|---|
| 1 | «Mình muốn đi Đà Lạt 2 ngày 1 đêm» | Gợi ý đúng reel săn mây | Gợi ý đúng reel săn mây |
| 2 | «Cho mình xem lịch trình của reel săn mây Đà Lạt vừa gợi ý» | `post_itinerary`, yêu cầu mở Tripi từ reel | Trả thẻ lộ trình Đà Lạt 3 ngày |
| 3 | «Ngày thứ hai thì mình đi đâu?» | `post_itinerary`, vẫn yêu cầu mở Tripi từ reel | Trả đúng Cầu Đất và vườn hồng |
| 4 | «Thời tiết Đà Lạt thứ Bảy thế nào?» | Trả thẻ thời tiết | Trả thẻ thời tiết |
| 5 | «Đi Đà Lạt cần mang phụ kiện gì?» | Trả checklist | Trả checklist |
| 6 | «Quay lại lộ trình reel đó, ngày cuối đi đâu?» | `post_itinerary`, lại yêu cầu mở từ reel | Quay lại đúng reel, nêu cà phê rừng thông và chợ đêm |
| 7 | «Ngày thứ hai của video này có điểm gì?» | Sai ý định thành `post_reviews`, lại yêu cầu mở từ reel | Giữ đúng reel và nêu Cầu Đất, vườn hồng |

**Kết quả 4 câu hỏi lộ trình** là **0/4** trả đúng thẻ với payload Expo Web và **4/4** khi giữ ID reel. Ở lượt quay lại, app mô phỏng đã gửi **10 tin** nhưng Controller chỉ đọc **4 tin**, lúc đó chủ yếu là thời tiết và phụ kiện. Đây là bằng chứng về mất ngữ cảnh qua nhiều lượt. Chưa kiểm tra khả năng giữ qua thời gian chờ dài hay sau khi tải lại trang.

### 6.2. Ca đối chứng

| Ca | Điều kiện | Kết quả |
|---|---|---|
| P01/P02 | Hỏi lộ trình reel Đà Lạt được nêu tên, khác nhau ở ID | Thiếu ID thì yêu cầu mở từ reel. Có ID thì trả đúng thẻ. |
| P03/P04 | Ngay sau khi lịch sử đã ghi đầy đủ lộ trình, hỏi «Ngày thứ hai thì mình đi đâu?» | Thiếu ID vẫn không trả được dù lộ trình còn trong lịch sử Controller. Có ID trả đúng Cầu Đất và vườn hồng. |
| P05/P06 | Hỏi «Còn ngày cuối thì đi đâu?» | Thiếu ID thì không ra kết quả. Có ID thì trả đúng thẻ, nhưng phần chữ chỉ nói «sau đó bay về» và thiếu các điểm chơi. |
| P07/P08 | Sau thời tiết và phụ kiện, hỏi «Còn ngày thứ hai đi đâu?» | Thiếu ID, Controller chọn `packing` và trả **checklist**. Giữ ID, trả đúng thẻ và đúng ngày thứ hai. |
| P09/P10 | Sau hai lượt xen ngang, nói rõ «Quay lại lộ trình reel đó…» | Controller nhận ý định lộ trình ở cả hai ca. Chỉ ca có ID lấy được reel. |
| P11/P12 | Hỏi «Reel Đà Lạt lúc nãy đi mấy ngày?» | Thiếu ID thì yêu cầu mở từ reel. Có ID thì trả đúng thẻ, nhưng lời đáp chỉ yêu cầu bấm thẻ và không nói **3 ngày**. |
| P13/P14 | Hỏi khách sạn trong reel còn phòng tối 21/11 | Thiếu ID thì không kiểm được. Giữ ID thì kiểm đúng Dalat Palace Heritage Hotel. |
| P15/P16 | Nói rõ đổi sang reel cáp treo Nha Trang | Nếu request còn ID Đà Lạt, API trả lại lộ trình Đà Lạt và lời đáp nói chưa tìm thấy reel cáp treo. Với ID mới, API trả đúng lộ trình Nha Trang. |
| P17/P18 | Nói rõ dừng chủ đề reel rồi tìm chỗ ở Nha Trang | Cả hai ca tìm đúng chỗ ở Nha Trang, kể cả khi request vẫn chứa ID reel Đà Lạt. |

### 6.3. Chỗ cần sửa

1. **P1 · Giữ tham chiếu tới reel đã chọn.** Mobile gửi lịch sử `role/text` và `conversationId` nhưng chưa gửi ID reel. Backend chỉ đọc lộ trình theo `contextPostId`, nên việc nêu tên video trong lịch sử không đủ để lấy lại lộ trình. Khi người dùng chọn reel hoặc nói «video vừa gợi ý», lưu tham chiếu reel đã xác định và dùng lại cho câu hỏi liên quan sau thời tiết hoặc checklist. Trường hợp có nhiều reel phù hợp thì hỏi chọn đúng video. [Transport mobile](../../../tripflix-fe-expo/apps/mobile/src/features/assistant/assistant-transport.ts#L20) · [Skill theo reel](../../app/services/assistant/turn.py#L168)
2. **P1 · Đổi reel phải cập nhật tham chiếu.** P15 cho thấy ID cũ có thể thắng lời nói rõ về reel mới. Nếu tên hoặc lựa chọn mới mâu thuẫn với ID đang giữ, cần cập nhật theo reel mới đã xác định hoặc hỏi xác nhận trước khi trả lộ trình. Khi người dùng chuyển hẳn sang tìm chỗ ở, giữ khả năng rẽ sang luồng khác như P17/P18.
3. **P2 · Trả thẳng ngày hoặc thông tin được hỏi.** Một thẻ toàn bộ lộ trình chưa đủ khi người dùng hỏi ngày cuối hoặc số ngày. P06 và P12 có đúng reel nhưng lời đáp thiếu trọng tâm. Lượt hỏi «ngày thứ hai» nên nêu hoạt động ngày 2 trước, lượt hỏi «mấy ngày» nên trả số ngày trước.
4. **Kiểm thử hồi quy.** Dùng chuỗi 7 lượt ở mục 6.1, xác nhận thẻ sau hai câu xen ngang vẫn có đúng ID reel và nội dung đúng ngày. Chạy thêm ca đổi reel A → B và ca bỏ ngữ cảnh reel để tìm chỗ ở. Theo dõi cửa sổ ngữ cảnh thực tế bên cạnh kết quả Controller. [Giới hạn lịch sử](../../app/services/assistant/admission.py#L215) · [Dữ liệu gửi Controller](../../app/services/assistant/understand.py#L33)

## 7. Kiểm thử mở rộng các nhóm chức năng của agent

**112 lượt kiểm tra mới** gồm **70 ca hội thoại live**, **16 lượt trong bốn chuỗi thời tiết → checklist** và **26 ca có đầu vào kiểm soát**. Trong bốn chuỗi, Q1 gọi Open-Meteo thật; Q2–Q4 dùng thời tiết mô phỏng, trong đó Q3/Q4 mô phỏng timeout lúc dựng checklist. Cả 86 lượt hội thoại chạy Controller thật và nhận trạng thái HTTP 200. Các ca T gọi trực tiếp luật, luồng `Turn` hoặc Verifier/Responder bằng dữ kiện cố định để khoanh đúng nơi gây lỗi. Bộ thử độc lập với cuộc trò chuyện đang mở.

Đã phủ các nhóm hiện có của TF31 gồm tham chiếu reel và đánh giá, lộ trình theo ngày, việc chuyển chủ đề, dự báo/ngày/địa điểm, checklist theo điều kiện và yêu cầu loại món, tìm kiếm/reel, phòng/chuyến bay, hỗ trợ thao tác đặt, hội thoại ngắn và đường lui khi phụ thuộc lỗi. Phạm vi ghi nhận kết quả là bản FE `b1af019` và AI TF31 tại thời điểm test, với dữ liệu Core local. Không tạo đơn hoặc thực hiện thanh toán trong các ca hội thoại. Nhánh tạo Trip Draft, sửa lộ trình và tìm tuyến xe thuộc Giai đoạn B.

| Kết quả trong 70 ca live | Số ca |
|---|---:|
| Lỗi xác nhận | 34 |
| Hạn chế tích hợp, phạm vi hoặc chất lượng lời đáp | 17 |
| Đạt mục tiêu chính của ca | 18 |
| Chưa kết luận | 1 |

Số ca lỗi phản ánh bộ chủ động chọn tình huống khó. Nhiều ca cùng quy về một lỗi sản phẩm.

### 7.1. Sai thực thể hoặc sai điều kiện khi hỏi dịch vụ

- **P1 · Nhắc đích danh khách sạn mới vẫn kiểm phòng theo reel cũ.** R11 nói không hỏi khách sạn trong reel, nêu Vinpearl Luxury Nha Trang, hỏi cho ngày mai. Request có ID reel Đà Lạt để kiểm xung đột. API gọi `/api/hotels/P-vn-h-da-lat-1` với 16–17/11 và hiển thị **Dalat Palace Heritage Hotel**. Trong khi đó lời đáp nói chưa tìm thấy khách sạn Nha Trang. Điều kiện nhận chuỗi «còn phòng» khi có reel ID có thể ép intent về kiểm phòng của reel. Cần ưu tiên khách sạn được gọi tên hoặc hỏi xác nhận khi xung đột; câu trả lời và thẻ phải dùng cùng thực thể. [Định tuyến theo reel](../../app/services/assistant/turn.py#L72)
- **P1 · Báo hết phòng ngày thực tế vẫn còn phòng.** V11 hỏi đêm 21/11. Controller trả `2108-11-21`, API gọi Core cho khoảng 21–22/11/2108 và lời đáp chỉ nói «hết phòng cho đêm 21/11». Đối chiếu cùng khách sạn trên Core, **21–22/11/2026 có 2/3 loại phòng còn**, còn **21–22/11/2108 có 0/3**. Đây là hậu quả trực tiếp của lỗi chuẩn hóa năm đã ghi nhận trước đó. Cần xác thực ngày trước khi tra tồn kho và bảo đảm kết luận còn/hết gắn với chính khoảng ngày đã xác thực. [Schema ngày](../../app/services/assistant/schemas.py#L67) · [Tra phòng trong reel](../../app/services/assistant/skills/trip.py#L103)
- **P1 · Báo thiếu chuyến sau 15 giờ trong khi Core có.** I08 và I09 hỏi HAN–DAD ngày 21/11, sau 15 giờ. AI nhận danh sách và dựng 5 thẻ đầu, gồm 06:30, 08:05 và 11:30, với trùng tên vì các hạng vé khác nhau. I08 kết luận chưa có chuyến sau 15 giờ. Gọi Core cùng ngày/tuyến/số khách cho thấy chuyến **17:30 có hai hạng còn chỗ** trong dữ liệu. Cần lọc điều kiện giờ trước khi cắt top 5. Chỉ kết luận không có sau khi kiểm tra tập kết quả đã lọc. [Skill chuyến bay](../../app/services/assistant/skills/flight.py)
- **P2 · Ràng buộc âm hoặc phạm vi cụ thể bị mất.** I03 nói chỉ lộ trình 2 ngày nhưng UI vẫn nhận kế hoạch 4N3Đ. I04 yêu cầu loại Dalat Palace nhưng đó lại là video duy nhất. I06 hỏi gần biển và có hồ bơi, mà request chỉ mang nơi, ngày và số khách. Cần giữ các ràng buộc cứng và nói rõ điều kiện nào chưa hỗ trợ xác thực.

### 7.2. Mất tham chiếu reel và trả sai câu hỏi theo lộ trình

- **Hai reel cùng điểm đến.** Trong R01–R04, «video thứ hai» thiếu ID thì không tra được. Gửi nhầm ID video đầu sẽ trả reel tàu lượn dù người dùng chọn reel cáp treo. Có đúng ID thì thẻ đúng. Với «video đó», hai lựa chọn nên được nêu lại để người dùng xác nhận.
- **Yêu cầu mới đụng ID cũ.** R14 đổi rõ sang reel tàu lượn nhưng API vẫn đọc thẻ cáp treo. Lỗi này sẽ còn tồn tại nếu PR mobile chỉ truyền ID hiện tại mà chưa xử lý điều kiện chọn lại reel. Cần để lựa chọn reel mới hoặc xác nhận của user cập nhật ID, kiểm tra xung đột trước khi gọi Skill.
- **Ngày cụ thể và tên điểm.** R05 có đúng reel nhưng câu nêu tour 3 đảo ngày 2 bị lọc. R13 hỏi tên quán cà phê của lộ trình bị phân loại thành review và trả «chưa đủ bình luận». Cần đọc dữ liệu mục lộ trình trước; nếu chỉ có tên hoạt động chung như «cà phê rừng thông» thì báo chưa thấy tên quán cụ thể. R06, R07 và R10 là đối chứng đúng: không bịa ngày 4, sửa giả định 2 ngày thành 3 và ổn định khi yêu cầu rõ ràng.

### 7.3. Thời tiết và checklist không dùng cùng ngày hoặc cùng dữ kiện

**Tái hiện đúng dạng «mưa lạnh mà nhắc mặc áo phông».** Chuỗi Q2 mô phỏng ngày 21/11 ở Đà Lạt **12–17°C, mưa 80%**; 22/11 đổi sang nóng. Người dùng chốt đi trong ngày 21/11, hỏi thời tiết rồi hỏi «Vậy hôm đó chỉ mặc áo phông được không hay nên mang gì?». Lượt dự báo gọi **16–17/11**; lượt checklist gọi **16–18/11**, nên mất dữ kiện mưa lạnh của ngày đi. Lời đáp bắt đầu **«Mặc áo phông thì thoải mái»**, chỉ nhắc giấy tờ, sạc và thuốc cá nhân. Thẻ thiếu cả áo khoác lẫn đồ chống mưa. Lời đáp đánh giá áo phông là thoải mái dù chưa có dự báo đúng ngày. Checklist cũng thiếu đồ cần cho điều kiện mưa lạnh. Với dữ kiện lạnh mưa được chuyển đúng vào luật, T01 và T18 đều thêm áo khoác và áo mưa/ô, không đưa áo mỏng.

| Vấn đề | Bằng chứng | Tiêu chí sửa |
|---|---|---|
| Lượt sau mất ngày đã nói | W04–W06 giữ điểm đến nhưng bỏ chữ «mai». K03/K04 giữ Vũng Tàu nhưng mất 21/11. K16 xin checklist theo dự báo 26/12, lại lấy dữ liệu cuối tuần hiện tại. | Giữ `destination + dateRange` của chuyến qua lượt thời tiết và checklist. Ngày chỉ được đổi khi user đổi rõ hoặc xác nhận. |
| Khoảng ngày bị mở rộng | T13 chỉ đi 21/11; planner tra 21–22/11 và đưa áo khoác/đồ mưa do dữ kiện 22/11. T14 hỏi một ngày vẫn hiện thêm ngày sau. | Dùng khoảng ngày theo loại ý định; dự báo hoặc đi trong ngày gồm đúng khoảng đã yêu cầu. |
| Thẻ vừa trả có dự báo, checklist mất dữ kiện sau timeout | Q4-02 có thẻ 12–17°C, mưa 80% cho 17/11. Q4-03 gọi lại đúng nơi/ngày nhưng mô phỏng timeout; checklist còn ba món cơ bản, lời đáp yêu cầu hỏi lại dự báo. Q4-04 tương tự. | Nếu có dự báo đủ mới và khớp chuyến, giữ bản tham chiếu có nguồn, giờ lấy và ngày áp dụng. Nếu không thể dùng, nói rõ checklist cơ bản và đưa gợi ý có điều kiện theo dữ kiện người dùng đã nêu. Fixture Q4 mô phỏng trường hợp không có cache dùng chung cho lần gọi sau. |
| Tín hiệu mưa bị giản lược thành một ngưỡng | T02 có nhãn «mưa rào» và 49% nhưng thiếu đồ mưa. T03 đổi 49% thành 50% thì có áo mưa/ô và túi chống nước. | Kết hợp nhãn thời tiết, xác suất và ưu tiên chuyến. Cho biết lý do hoặc gợi ý mang ô dự phòng ở vùng giáp ngưỡng. |
| Gộp đồ nóng và lạnh vào một danh sách | T06/T07 cho cả «Áo mỏng, thoáng», áo khoác và áo mưa. Với hai ngày khác nhau, không biết mặc món nào vào ngày nào. Facts checklist chỉ có `items` và `basedOnWeather`. | Ghi ngày hoặc lý do cho từng nhóm đồ, ví dụ áo mỏng mặc lớp trong ban ngày, áo khoác lúc lạnh, áo mưa khi có mưa. |
| Người dùng nói điều kiện rõ mà thẻ bỏ qua | K06 có áo khoác rồi nhưng thẻ vẫn có áo khoác. K08 đi họp, không đi biển nhưng thẻ vẫn có đồ bơi. K09 chỉ 2 món nhưng thẻ có 11. K14 muốn giữ ấm và bỏ pin, thẻ vẫn có pin. Q1-04 đã có ô, thẻ vẫn ghi ô và chữ đề xuất kem chống nắng như món chống mưa. | Dùng chung danh sách đã lọc cho cả thẻ và Responder. Phân biệt mục tiêu chuyến đi, món đã có, chủ đề đồ cần mang và giới hạn số lượng. |
| Dữ liệu trống hoặc lỗi chưa được diễn đạt đúng mức | T15 không có dự báo nhưng checklist vẫn `answer` chung. T16 có `degraded=["weather"]` mà câu mẫu checklist không giải thích. T17 hỏi dự báo trực tiếp thì có thông báo lỗi đúng. | Tách ba trạng thái có dự báo, chưa có dự báo cho ngày chọn và lỗi truy cập. Checklist phải truyền trạng thái sang phần trả lời và UI. |
| Mưa đúng con số nhưng sai ngày | W14 gán 47% của 18/11 cho «mai» (17/11 là 80%). T20 đưa 90% của Chủ nhật sang thứ Bảy và Verifier vẫn giữ. | Xác minh quan hệ **nơi + ngày + chỉ số**. Kiểm tập số đơn lẻ chỉ chặn được số chưa từng xuất hiện. |

[Planner](../../app/services/assistant/planner.py#L48) · [Nối thời tiết với checklist](../../app/services/assistant/turn.py#L188) · [Luật hành lý](../../app/services/assistant/packing.v1.yaml) · [Verifier](../../app/services/assistant/verifier.py#L46)

### 7.4. Lời văn cứng, lặp CTA và mất câu chính sau Verifier

| Phát hiện | Bằng chứng |
|---|---|
| Câu mẫu dùng sai tình huống | V01 chào thì đọc nguyên câu giới thiệu chức năng. V12 «bye» thành từ chối an toàn. V03 «vậy đủ rồi» chạy lại Skill lộ trình. V04 «mình chốt vậy» chạy lại Skill thời tiết. |
| Bản nháp có đáp án, lời cuối mất đáp án | V05 nháp có «3 ngày» nhưng bị lọc hết, rơi về «Đây là lộ trình trong reel bạn đang xem». V08 nháp có Cầu Đất ngày 2, đầu ra chỉ nhắc ngày 1 và 3. W13 nháp có đúng thứ Bảy 49%, câu còn lại chỉ nói Chủ nhật. K13 nháp có áo khoác cho xe đêm, lời cuối còn mỗi câu áo mưa. |
| CTA sót lại hoặc lặp từ | T24 thay tham chiếu `[r1]` sau kiểm tra, sinh «Bấm thẻ thẻ bên dưới». R02 và K08 có đúng lỗi này ở lượt live. T25 có câu nội dung bị chặn nhưng CTA đi qua. T26 chặn hết và về câu mẫu. |
| Độ dài và số ý | V06 yêu cầu một câu nhưng có thêm CTA; V10 yêu cầu một ý, kèm nhiều mục và CTA. T23 cho năm câu hợp lệ qua Verifier dù prompt giới hạn bốn. |
| Đối chứng giọng tự nhiên vừa đủ | V07 diễn giải lộ trình đơn giản, nêu đủ ba ngày. V09 nhận ra người dùng đã nói Đà Lạt, trả lời đồng cảm và tiếp tục gợi ý. |

Trong 70 ca, **56 lượt có bản nháp Responder**, **31/56** lượt có ít nhất một câu bị Verifier loại. Tổng bộ lọc loại **37 câu**, gồm **35 bởi V3** liên quan tên và **2 bởi V2** liên quan số. Con số này gồm cả câu đáng loại. Ví dụ V05, V08, W13 cho thấy phần thông tin hữu ích cũng có thể rơi mất. Khi câu chính biến mất, nên dựng lại câu từ facts hoặc dùng mẫu theo intent trả đúng ngày/số ngày, rồi mới gợi ý thao tác nếu cần. [Cách thay tham chiếu](../../app/services/assistant/responder.py#L31) · [Quy tắc giới hạn câu](../../app/prompts/assistant-responder.v1.md)

### 7.5. Nhật ký 70 ca live

| ID | Tin nhắn | Kết quả | Quan sát |
|---|---|---|---|
| I01 | Tìm video du lịch Nha Trang, chỉ gửi video giúp mình. | Đạt | Chỉ trả hai thẻ video theo yêu cầu. |
| I02 | Gợi ý vài reel đi Nha Trang 2 ngày 1 đêm, ưu tiên video về cáp treo. | Hạn chế | Đúng ưu tiên cáp treo, nhưng lại chọn search đa loại và thêm thẻ chỗ ở. |
| I03 | Mình đi Nha Trang 2N1Đ, chỉ muốn xem lộ trình 2 ngày, đừng đưa 3 ngày. | Lỗi | Yêu cầu chỉ lộ trình 2 ngày, vẫn có thẻ kế hoạch 4N3Đ và reel cáp treo 3 ngày. |
| I04 | Tìm reel săn mây Đà Lạt nhưng loại video của Dalat Palace khỏi kết quả. | Lỗi | Yêu cầu loại video Dalat Palace, chính video bị loại lại là kết quả duy nhất. |
| I05 | tim ks da lat cuc re 21/11-22/11 cho 2 nguoi | Lỗi | Câu không dấu về phòng và ngày bị đi search, không gọi tồn phòng /api/stays cho ngày nhập. |
| I06 | Tìm khách sạn Nha Trang cuối tuần này cho 2 người, gần biển và có hồ bơi. | Hạn chế | Tìm đúng Nha Trang và ngày, nhưng request Core không truyền tiêu chí gần biển hoặc hồ bơi. |
| I07 | Tìm vé một chiều HAN đi DAD 21/11 cho 2 người, chỉ cần vé rẻ nhất. | Đạt | Trả một thẻ chuyến theo tuyến và ngày đúng với chế độ chọn tổng giá thấp nhất. |
| I08 | Tìm chuyến HAN đi DAD 21/11, chuyến khởi hành sau 15 giờ. | Lỗi | Yêu cầu sau 15 giờ, trả 5 thẻ buổi sáng và nói không có, trong khi Core có chuyến 17:30. |
| I09 | Tìm chuyến HAN đi DAD 21/11 cho 1 người. Mình đã nói là sau 15 giờ. | Lỗi | Nhắc lại ràng buộc sau 15 giờ cũng vẫn trả 5 thẻ buổi sáng. |
| I10 | Tìm vé 21/11 từ Sài Gòn ra Đà Nẵng cho 2 người lớn và 1 trẻ em. | Đạt | Nói rõ giới hạn vé trẻ em và dẫn tới màn đặt vé. |
| I11 | Tìm chuyến bay đi Đà Lạt, còn điểm đi chưa chốt. | Hạn chế | Đã biết nơi đến Đà Lạt nhưng hỏi lại cả nơi đi và nơi đến. |
| I12 | Tìm khách sạn Hư Cấu Sao Tím Đà Lạt, đúng tên đó thôi. | Chưa kết luận | Hỏi ngày trước, chưa tra tên chính xác. Lượt này chưa có bằng chứng hệ thống có loại khách sạn khác tên. |
| I13 | Mình đã chọn video này rồi. Nếu hết phòng, chỉ mình cách đổi khách sạn. | Lỗi | Hỏi cách đổi khách sạn nếu hết phòng bị biến thành hỏi ngày nhận và trả phòng. |
| I14 | Mình muốn đi Đà Lạt nhưng không đi máy bay, chỉ đi xe khách. | Hạn chế | Chỉ muốn xe khách, nhận reel và khách sạn; không nói rõ thiếu dữ liệu tuyến xe ở bản hiện tại. |
| K01 | Vậy mình nên mang đồ gì? | Đạt | Giữ nơi và ngày cuối tuần, thẻ có áo khoác. Mốc mưa 49% không kích hoạt áo mưa. |
| K02 | Vậy mình nên mang đồ gì? | Đạt | Giữ Vũng Tàu cuối tuần, thẻ có áo mưa hoặc ô và túi chống nước. |
| K03 | Ở chỗ mới thì mình nên mang đồ gì? | Lỗi | Giữ đúng nơi mới Vũng Tàu khi còn ID Đà Lạt, nhưng mất ngày 21/11, planner dùng 3 ngày gần nhất. |
| K04 | Ở chỗ mới thì mình nên mang đồ gì? | Lỗi | Vẫn mất ngày 21/11 khi bỏ ID cũ; có nơi mới nhưng thiếu mốc đi. |
| K05 | Đi Đà Lạt cuối tuần, thấy báo mưa lạnh. Mặc áo phông thôi có đủ không? | Hạn chế | Nói mang thêm áo khoác, không bảo chỉ mặc áo phông. Thẻ không có đồ chống mưa trong lượt này. |
| K06 | Đi Đà Lạt ngày 21/11. Đã có áo khoác, chỉ liệt kê đồ còn thiếu. | Lỗi | Người dùng đã có áo khoác; lời đáp hiểu nhưng áo khoác vẫn nằm trong thẻ. |
| K07 | Đà Lạt 2 ngày, không có ý định đi bơi. Nên mang những đồ gì? | Đạt | Đà Lạt, không đi bơi: không gợi ý đồ bơi, có áo khoác. |
| K08 | Đi Nha Trang họp, không đi biển, không bơi. Nên mang gì? | Lỗi | Nha Trang đi họp, không đi biển: thẻ vẫn có đồ bơi, dép lê; chữ bảo bỏ qua. |
| K09 | Chỉ gợi ý 2 món chống mưa cần nhất cho Vũng Tàu 21/11. | Lỗi | Chữ nêu đúng hai đồ chống mưa, thẻ vẫn liệt kê 11 món dù user nói «chỉ». |
| K10 | Mình chỉ đi Đà Lạt trong ngày 21/11, không ở qua đêm, cần chuẩn bị gì? | Lỗi | Ngày đi 21/11 trong ngày không được giữ trong slots; checklist được dựng từ cửa sổ mặc định. |
| K11 | Mình đi Đà Lạt từ 21/11 đến 24/11, mang hành lý gì? | Đạt | Thẻ có đồ giặt nhanh/túi đựng đồ bẩn cho chuyến dài; slot nights=2 dù khoảng 21–24 là 3 đêm. |
| K12 | Đi Đà Lạt 2 ngày 1 đêm, có em bé 8 tháng. Nên chuẩn bị gì cho bé? | Hạn chế | Có áo khoác cho bé trong lời đáp nhưng checklist là danh sách chung, không tùy biến cho em bé. |
| K13 | Xe khách đêm đến Đà Lạt, điều hòa lạnh, mình nên mang gì? | Hạn chế | Thẻ có áo khoác, câu về điều hòa lạnh bị lọc; lời cuối chỉ còn đồ chống mưa. |
| K14 | Đừng gợi ý pin dự phòng vì mình có rồi. Chỉ cho mình đồ giữ ấm thôi. | Lỗi | Chỉ muốn đồ giữ ấm, bỏ pin dự phòng; thẻ vẫn còn pin và các món ngoài phạm vi. |
| K15 | Dự báo bảo trời mưa 90% và còn 12 độ, mình chưa chốt đi đâu. Nên mang phụ kiện gì? | Lỗi | Lời đáp hiểu mưa lạnh do user mô tả nhưng thẻ thiếu cả áo mưa và giữ ấm, basedOnWeather=false. |
| K16 | Mình đi Vũng Tàu ngày 26/12, dự báo thời tiết thế nào thì mình mang đồ phù hợp? | Lỗi | Nói chưa có dự báo 26/12 nhưng slot ngày quay về cuối tuần hiện tại, thẻ lại basedOnWeather=true. |
| R01 | Cho mình lộ trình video thứ hai trong hai video vừa gợi ý. | Hạn chế | «Video thứ hai» từ hai gợi ý chưa được ánh xạ ID. API chỉ yêu cầu mở Tripi từ reel. |
| R02 | Cho mình lộ trình video thứ hai trong hai video vừa gợi ý. | Lỗi | Người dùng chọn video thứ hai nhưng request còn ID video thứ nhất, API trả reel tàu lượn và lời đáp chỉ «Bấm thẻ thẻ…». |
| R03 | Cho mình lộ trình video thứ hai trong hai video vừa gợi ý. | Đạt | Với ID cáp treo đúng, trả thẻ lộ trình đúng reel. Chữ chỉ còn ngày 3 vì hai câu bị lọc. |
| R04 | Video đó đi mấy ngày? | Hạn chế | Có hai reel cùng nơi, «video đó» mơ hồ. Không đưa hai lựa chọn để làm rõ. |
| R05 | Mình nói video cáp treo Hòn Tre, ngày thứ hai có gì? | Hạn chế | Đúng reel cáp treo, nhưng câu về tour 3 đảo ngày 2 bị lọc. Người dùng nghe chủ yếu bờ kè và cáp treo ngày 1. |
| R06 | Còn ngày thứ tư của reel này thì sao? | Đạt | Nói rõ reel 3 ngày, không dựng ngày 4. |
| R07 | Video này dành cho chuyến 2 ngày đúng không? | Đạt | Sửa giả định 2 ngày thành đúng 3 ngày. |
| R08 | Cho xem lịch trình của reel này. | Đạt | ID thử nghiệm không tồn tại, báo reel không còn hiển thị và không dựng lộ trình. |
| R09 | Người đi rồi nhận xét sao về reel này? | Đạt | Khi dữ liệu tóm tắt không sẵn sàng, báo chưa đủ bình luận. |
| R10 | Không hỏi review nữa. Cho mình lộ trình ngày 2 của video này. | Đạt | Thoát nhánh review khi user đổi ý; trả đúng Cầu Đất và vườn hồng ngày 2. |
| R11 | Không hỏi khách sạn trong reel. Mai resort Vinpearl Luxury Nha Trang còn phòng không? | Lỗi | User nói rõ không hỏi khách sạn trong reel, nêu Vinpearl Luxury Nha Trang. API gọi Dalat Palace 16–17/11, thẻ sai khách sạn và lịch. |
| R12 | Mình muốn đi giống reel, nhưng bỏ chợ đêm và thay bằng một quán ăn chay. | Hạn chế | Chỉ trả lại lộ trình gốc. Sửa chuyến đi thuộc Giai đoạn B; câu «chưa có gợi ý quán chay» không dựa trên lượt tra quán. |
| R13 | Bạn chỉ giúp quán cà phê trong lịch trình video này tên cụ thể là gì? | Lỗi | Hỏi tên quán trong lịch trình bị chuyển sang post_reviews, trả «chưa đủ bình luận». |
| R14 | Hỏi giúp lộ trình cho reel tàu lượn, không phải cáp treo. | Lỗi | User yêu cầu reel tàu lượn và loại cáp treo; ID cũ làm thẻ vẫn là reel cáp treo. |
| V01 | Chào bạn | Hạn chế | Chào đơn giản được phân loại đúng; lời đáp đọc nguyên đoạn giới thiệu chức năng. |
| V02 | Mình đi chơi với ba mẹ, muốn chỗ nào thư thả ở Đà Lạt, kể gọn thôi. | Hạn chế | Câu tìm chỗ nghỉ thư thả cho ba mẹ nhận no_result chung, không đưa bước hỏi tiếp có ích. |
| V03 | Cảm ơn nha, vậy đủ rồi | Lỗi | «Cảm ơn, vậy đủ rồi» có lời chúc nhưng vẫn gọi lại lộ trình và kèm thẻ. |
| V04 | OK, mình chốt vậy nhé | Lỗi | «Mình chốt vậy» bị hiểu thành một lượt dự báo mới. |
| V05 | Bạn chỉ cần trả lời đúng số ngày của video này trong một câu thôi. | Lỗi | Bản nháp đã nói đúng 3 ngày, Verifier loại hết; câu mẫu còn «Đây là lộ trình…». |
| V06 | Câu trước dài quá, nói gọn 1 câu ngày thứ hai đi đâu nhé. | Hạn chế | Nêu đúng Cầu Đất và vườn hồng, thêm câu CTA dù user yêu cầu một câu. |
| V07 | Mình chưa hiểu. Bạn nói lại bằng lời đơn giản được không? | Đạt | Diễn giải lại lịch trình bằng lời đơn giản với các điểm chính. |
| V08 | Mình hỏi lại, ngày thứ hai ghé đâu? Đừng nói chỉ bấm vào thẻ. | Lỗi | Câu đúng ngày 2 có trong bản nháp nhưng bị lọc. Lời cuối chỉ còn ngày 1, ngày 3 và CTA. |
| V09 | Bạn sao cứ hỏi đi đâu, mình nói là Đà Lạt rồi mà | Đạt | Thừa nhận đã biết Đà Lạt và tiếp tục gợi ý, không lặp câu hỏi nơi đến. |
| V10 | Cho mình một gợi ý đồ cần mang quan trọng nhất, đúng một ý thôi. | Lỗi | Chọn đúng một món ở câu đầu, sau đó thêm nhiều món và checklist dù yêu cầu «đúng một ý». |
| V11 | Nói ngắn gọn: Khách sạn trong video còn phòng đêm 21/11 không? | Lỗi | Năm 2108 qua được tới Core, lời đáp báo hết phòng «đêm 21/11» mà che mất năm. Core ngày 21/11/2026 còn phòng. |
| V12 | Mình không tìm du lịch nữa, bye nha | Lỗi | Lời chào tạm biệt thành refusal, đáp «Mình hỗ trợ du lịch an toàn». |
| W01 | Thời tiết Đà Lạt ngày 21/11 thế nào? | Lỗi | Hỏi đúng 21/11, Controller không giữ ngày và trả thẻ 16–18/11. |
| W02 | Đà Lạt ngày 21/11 mưa lúc mấy giờ? | Đạt | Nói rõ chỉ có dự báo ngày, chưa có giờ mưa cụ thể. Thẻ còn thêm 22/11. |
| W03 | Thời tiết ba ngày Đà Lạt từ 21/11 đến 23/11. | Lỗi | Hỏi khoảng 21–23/11, thẻ vẫn chọn mặc định 16–18/11. |
| W04 | Ở đó mai có mưa không? | Lỗi | «Ở đó mai» giữ Đà Lạt nhưng giữ cuối tuần cũ, trả 21–22/11; «mai» là 17/11. |
| W05 | Mai ở đó có mưa không? | Lỗi | Nhớ nơi mới Vũng Tàu nhưng bỏ «mai», trả 21–22/11. |
| W06 | Mai ở đó có mưa không? | Lỗi | Có ID reel Đà Lạt cũ, vẫn ưu tiên đúng nơi mới Vũng Tàu nhưng ngày vẫn sai. |
| W07 | Cho mình dự báo Hà Nội ngày mai, không hỏi Đà Lạt nữa. | Hạn chế | Ưu tiên đúng Hà Nội thay vì reel Đà Lạt, thẻ gồm 17–18/11 và chữ chỉ còn CTA/áo mưa. |
| W08 | Đà Lạt đã mưa hôm qua hay hôm kia? | Đạt | Nói rõ không có dữ liệu hôm qua hay hôm kia; thẻ bổ sung là dự báo tương lai. |
| W09 | Thời tiết Paris, Pháp ngày mai? | Hạn chế | Paris, Pháp đã rõ nhưng chỉ bảo ghi rõ tên nơi. Adapter hiện giới hạn địa lý VN. |
| W10 | Tổ chức đi biển ngày mai, nếu mưa có nên đổi lịch không? | Lỗi | Hỏi tư vấn đổi lịch vì mưa, thiếu địa điểm. Tripi trả từ chối an toàn thay vì hỏi nơi tổ chức. |
| W11 | Cuối tuần trời có nắng ở Nha Trang không? Chỉ hỏi thời tiết, đừng tìm video. | Đạt | Giữ ý định thời tiết và trả thẻ thời tiết, không kèm video. |
| W12 | So sánh khí hậu Đà Lạt và Vũng Tàu cuối tuần này giúp mình. | Hạn chế | Chỉ lấy Đà Lạt khi được yêu cầu so hai nơi. Lời đáp nói «Vũng Tàu chưa có» dù lượt chưa tra nơi đó. |
| W13 | Gần đây mưa lớn. Còn thứ Bảy Đà Lạt thì dự báo cụ thể bao nhiêu? | Lỗi | Thẻ có đúng thứ Bảy 49%, Verifier loại câu đúng ngày và giữ câu mưa phùn Chủ nhật. |
| W14 | Cho mình giờ hoàng hôn ở Vũng Tàu ngày mai. | Lỗi | Nói rõ chưa có giờ hoàng hôn, nhưng gắn 47% mưa của 18/11 cho «ngày mai» 17/11. Thẻ ngày 17 là 80%. |

### 7.6. Nhật ký chuỗi thời tiết → checklist

Q1 dùng provider thật. Q2 dùng fixture 21/11 lạnh/mưa và 22/11 nóng. Q3 và Q4 mô phỏng timeout từ lượt checklist. Các lượt trong mỗi chuỗi dùng câu trả lời thực của lượt trước và giữ `conversationId`.

| ID | Tin nhắn rút gọn | Đầu ra chính |
|---|---|---|
| Q1-01 | Vũng Tàu 21/11, đi trong ngày | Mặc định search, không có kết quả. |
| Q1-02 | Dự báo đúng ngày 21/11 | Vẫn chọn search, không gọi thời tiết. |
| Q1-03 | Chỉ đồ chống mưa ngày đi | Gọi dự báo 21–22/11, truy xuất mưa 52% ngày 21. Lời đáp có đồ chống mưa, thẻ lẫn nhiều món ngoài phạm vi. |
| Q1-04 | Chỉ 2 món, đã có ô | Thẻ vẫn có ô. Lời đáp chọn túi chống nước và kem chống nắng. |
| Q2-01 | Đà Lạt 21/11, đi trong ngày | Tìm kiếm chung và không ra kết quả. |
| Q2-02 | Dự báo Đà Lạt 21/11 | Gọi 16–17/11, fixture không có dữ liệu cho khoảng này. |
| Q2-03 | Hôm đó chỉ mặc áo phông được không | Gọi 16–18/11, mất dữ kiện. Nói mặc áo phông thoải mái, thẻ thiếu đồ mưa và áo khoác. |
| Q2-04 | Đã có áo khoác, chỉ thêm một đồ mưa | Gọi 16–18/11, thẻ còn ba món cơ bản, không đáp đúng đồ chống mưa. |
| Q3-01 | Nha Trang 21/11 để họp, không đi biển | Hỏi lại ngày đi. |
| Q3-02 | Ngày 21/11 mưa lạnh không | Gọi 16–18/11, nhận dự báo trống. |
| Q3-03 | Vậy mang gì | Timeout. Thẻ vẫn thêm đồ bơi, không giải thích thời tiết bị lỗi. |
| Q3-04 | Nếu chưa kiểm được, nói rõ và cho đồ cơ bản | Có thông báo chưa kiểm được và thẻ cơ bản. |
| Q4-01 | Ngày mai đi Đà Lạt trong ngày | Search chung, no_result. |
| Q4-02 | Dự báo Đà Lạt ngày mai | Thẻ 17–18/11 có 12–17°C, mưa 80%. Chữ chỉ còn «Xem chi tiết ở thẻ». |
| Q4-03 | Dựa vào mưa lạnh vừa nói, mang gì | Gọi lại đúng 17–18/11, timeout. Thẻ còn ba món cơ bản và lời đáp bảo hỏi lại dự báo. |
| Q4-04 | Chỉ đồ chống mưa và giữ ấm theo dự báo vừa có | Timeout tiếp, lại trả ba món cơ bản. Không dùng dữ kiện đã trả ở Q4-02. |

### 7.7. Nhật ký 26 ca đầu vào cố định

| ID | Kiểm tra | Kết quả |
|---|---|---|
| T01 | Lạnh 12–17°C, mưa 80% | Áo khoác, áo mưa/ô, túi chống nước. Không áo mỏng. |
| T02 | Mưa rào 49% | Áo khoác, thiếu đồ mưa dù nhãn mưa rào. |
| T03 | Mưa rào 50% | Có đồ mưa. |
| T04 | Nha Trang đi họp, không biển/bơi | Vẫn có đồ bơi, dép lê, nón/kính. |
| T05 | Người dùng cung cấp mưa 90% và 12°C, provider trống | Chỉ nhóm giấy tờ, sạc, thuốc. |
| T06 | Sáng 17°C, đỉnh 34°C, mưa 80% | Áo mỏng và áo khoác cùng xuất hiện, thẻ không ghi cách phối. |
| T07 | Ngày 1 nóng khô, ngày 2 lạnh mưa | Gộp áo mỏng, áo khoác, đồ mưa; thiếu gắn theo ngày. |
| T08 | Có áo khoác/pin, chỉ muốn đồ mưa | Các món đã có vẫn ở thẻ. |
| T09 | Xe đêm điều hòa lạnh, provider trống | Không dùng tín hiệu lạnh của phương tiện trong luật. |
| T10 | Đi với em bé 8 tháng | Danh sách chung, không có nhóm đồ cho bé. |
| T11 | Chuyến một đêm | Không kích hoạt mục đồ giặt, đúng ngưỡng. |
| T12 | Chuyến hai đêm | Có mục đồ giặt, đúng ngưỡng. |
| T13 | Chỉ đi 21/11, 22/11 mới mưa lạnh | Tra thêm 22/11 và thêm đồ mưa/áo khoác từ ngày ngoài chuyến. |
| T14 | Hỏi dự báo chỉ 21/11 | Thẻ có thêm 22/11, assumedDays=false. |
| T15 | Provider không có forecast | Checklist chung, basedOnWeather=false; lời mẫu thiếu thông báo. |
| T16 | Provider timeout khi dựng checklist | Checklist chung, degraded weather; lời mẫu thiếu thông báo. |
| T17 | Provider timeout khi hỏi thời tiết trực tiếp | Có lời báo chưa kiểm được thời tiết, không dựng thẻ giả. |
| T18 | Dữ kiện mưa lạnh đúng ngày đi vào Turn | Checklist có đủ giữ ấm và chống mưa. |
| T19 | User nói mưa lạnh nhưng chưa có nơi đến | Checklist chung, không gọi thời tiết và không gắn lời khuyên theo điều kiện. |
| T20 | Lấy mưa 90% của Chủ nhật gắn sang thứ Bảy | Verifier giữ câu sai ngày. |
| T21 | Một cách nói gán mưa thứ Bảy cho «hôm qua» | Bị chặn bởi luật phát hiện tên. Đối chứng này chưa kiểm được quan hệ ngày; ca live §2 đã ghi một biến thể lọt. |
| T22 | Con số 99% không có trong facts | Bị chặn đúng bởi V2. |
| T23 | Năm câu đều hợp lệ | Verifier giữ cả năm dù prompt yêu cầu tối đa bốn. |
| T24 | Câu «Bấm thẻ [r1]…» | Render thành «Bấm thẻ thẻ bên dưới…». |
| T25 | Câu dữ kiện sai, câu CTA hợp lệ | Chỉ giữ CTA, người dùng không có câu trả lời chính. |
| T26 | Toàn bộ câu bị lọc | Responder trả rỗng, hệ thống dùng câu mẫu chung. |

### 7.8. Thứ tự sửa và ca nghiệm thu

1. **Ngày, thực thể và các ràng buộc cứng.** V11, R11, I08 và I09 nên thành hồi quy có kiểm tham số Core. Nếu user định danh một khách sạn, ngày hoặc giờ, chỉ trả kết luận tồn kho khi Core được hỏi bằng đúng các giá trị đã xác thực.
2. **Giữ ngữ cảnh có cấu trúc cho chuyến.** Tách ID reel đang chọn, ID/địa điểm chuyến, ngày đi, ngày về và ngày được hỏi. Cập nhật chúng khi user đổi ý, cho người dùng xác nhận khi có nhiều ứng viên. Dùng P/R và Q4 để kiểm các câu rẽ nhánh rồi quay lại.
3. **Đồng nhất weather facts, câu chữ và thẻ.** Với ngày/nơi khớp, truyền dữ kiện thời tiết còn hiệu lực vào checklist và gắn lý do đồ mưa/nóng/lạnh. Tách thiếu dữ liệu và timeout, giữ các ràng buộc như không bơi/đã có ô/chỉ hai món. Thêm kiểm khớp ngày cho con số thời tiết.
4. **Sửa giọng bằng dữ kiện trước, CTA sau.** Lời chào/kết thúc ngắn không khởi chạy lại Skill. Nếu Verifier làm mất câu trả lời chính, dựng lại một câu từ facts; không trả chỉ dẫn bấm thẻ thay cho đáp án. Chuẩn hóa vị trí tham chiếu để không xuất hiện «thẻ thẻ».
