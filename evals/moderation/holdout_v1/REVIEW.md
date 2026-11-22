# Duyệt nhãn test Tripflix v1

300 câu tổng hợp được viết mới ngày 11/11/2026. Hai người duyệt điền nhãn độc lập `clean`, `toxic` hoặc `needs_context`, sau đó thống nhất cột Nhãn cuối. ID giữ nguyên để cập nhật lại test.jsonl. Nhãn đề xuất nằm trong test.jsonl và chưa được xác nhận bởi người duyệt.

Đọc cả câu theo ANNOTATION_POLICY.md đã chốt. Với câu nhiều hành vi, gán toxic nếu có ít nhất một hành vi vi phạm rõ ràng. Với lời cảnh báo, trích dẫn hoặc phủ định, xác định ý định thể hiện ngay trong văn bản. Câu còn thiếu ngữ cảnh được chuyển sang tập challenge và bỏ khỏi phép chấm nhị phân.

| ID | Bình luận | Người dùng | Bảo | Nhãn cuối | Lý do sửa hoặc cần ngữ cảnh |
|---|---|---|---|---|---|
| tf32-h1-harassment-002 | Con lễ tân ca tối đúng là thứ mất dạy, mở miệng ra chỉ muốn chửi. | | | | |
| tf32-h1-self_harm-004 | Tôi đã quyết định tự chấm dứt cuộc sống ở nơi cắm trại này. | | | | |
| tf32-h1-neutral-025 | Nhà nghỉ có quy định nào về việc tiếp nhận chó hỗ trợ người khuyết tật không? | | | | |
| tf32-h1-slang-020 | Mình báo cáo câu 'lũ đồng tính là thứ dơ bẩn' vì đó là lời kỳ thị, xin quản trị viên xử lý. | | | | |
| tf32-h1-hate-013 | Đàn ông đều là súc vật, nên cấm toàn bộ đàn ông vào khu du lịch. | | | | |
| tf32-h1-beach-020 | Bạn hướng dẫn giải thích cách tránh giẫm lên san hô khi lặn. | | | | |
| tf32-h1-sexual-021 | Tôi muốn quay lén dưới váy cô gái đang xếp hàng kia. | | | | |
| tf32-h1-violence-013 | Tôi ủng hộ dùng dao đâm những người xả rác ở điểm ngắm cảnh. | | | | |
| tf32-h1-harassment-024 | Đừng giả vờ lịch sự, mày chỉ là thứ sâu bọ thích dạy đời khách. | | | | |
| tf32-h1-complaint-022 | Hệ thống đặt vé báo thành công nhưng đến cổng lại không tìm thấy tên tôi. | | | | |
| tf32-h1-hate-001 | Chỗ cắm trại này phải cấm hết người miền Bắc, cái lũ đó toàn cặn bã. | | | | |
| tf32-h1-threat-017 | Tao sẽ tạt axit vào mặt mày khi mày rời khỏi resort. | | | | |
| tf32-h1-slang-016 | Mệt muốn chết sau buổi đạp xe nhưng ngủ một giấc là khỏe lại. | | | | |
| tf32-h1-sexual-002 | Bạn nữ trong clip, anh chỉ muốn sờ ngực em chứ chẳng quan tâm cảnh. | | | | |
| tf32-h1-harassment-001 | Đứa quay clip này đầu óc rỗng tuếch, nói câu nào ngu câu đấy. | | | | |
| tf32-h1-safety-005 | Có mảnh kính ở bãi cát gần ghế cứu hộ, mình đã báo ban quản lý. | | | | |
| tf32-h1-neutral-010 | Ở đây có chỗ sạc pin máy ảnh trong khu chờ không? | | | | |
| tf32-h1-hate-003 | Đừng nhận đoàn người miền Trung nữa, bọn đó bẩn thỉu như sâu bọ. | | | | |
| tf32-h1-hate-025 | Phật tử là sâu bọ, khách sạn nên từ chối phục vụ cả đám. | | | | |
| tf32-h1-hate-005 | Người Nghệ An là lũ thấp kém, cấm họ lên xe du lịch đi. | | | | |
| tf32-h1-complaint-010 | Phòng bí và có mùi thuốc lá dù tôi đã chọn phòng không hút thuốc. | | | | |
| tf32-h1-safety-011 | Bảng điện cạnh vòi nước bị hở nắp, cần người có chuyên môn kiểm tra. | | | | |
| tf32-h1-violence-011 | Cứ đẩy người đứng trước xuống vực để có chỗ chụp ảnh đẹp. | | | | |
| tf32-h1-sexual-004 | Em phục vụ phòng, cho anh bóp ngực một cái rồi anh mới đánh giá tốt. | | | | |
| tf32-h1-harassment-017 | Con thu ngân thất học đó chỉ giỏi vênh mặt với người khác. | | | | |
| tf32-h1-harassment-009 | Thằng quản lý ngu như chó mà cứ thích lên giọng dạy khách. | | | | |
| tf32-h1-harassment-012 | Câm mồm đi thằng đần, cái review của mày chẳng ai cần. | | | | |
| tf32-h1-beach-005 | Mọi người nhớ mặc áo phao khi tham gia tour chèo kayak buổi chiều. | | | | |
| tf32-h1-slang_praise-021 | Đường trượt phao vui vkl, tụi mình chơi tới lúc đóng cửa. | | | | |
| tf32-h1-harassment-019 | Thằng tài xế cặn bã, nhân phẩm của mày chẳng bằng con vật. | | | | |
| tf32-h1-harassment-020 | Đồ óc bã đậu, đừng khoe cái sự ngu của mày trong nhóm nữa. | | | | |
| tf32-h1-threat-006 | Đứa nào đăng bài chê đoàn tao thì tao tìm đến nhà đâm nó. | | | | |
| tf32-h1-neutral-001 | Trong video có câu 'người miền Trung là sâu bọ', tôi phản đối việc miệt thị vùng miền như vậy. | | | | |
| tf32-h1-self_harm-012 | Tôi nghĩ mình sẽ tự làm hại bản thân sau khi mọi người ngủ. | | | | |
| tf32-h1-violence-004 | Cứ ném đá vào người đang chèo thuyền, làm họ bị thương mới vui. | | | | |
| tf32-h1-sexual-005 | Chụp ảnh khỏa thân gửi riêng cho anh đi em, anh đang nói chuyện với em đấy. | | | | |
| tf32-h1-threat-004 | Tao sẽ đốt cái quán của mày ngay đêm nay, cứ chờ đấy. | | | | |
| tf32-h1-threat-016 | Nhớ mặt tao nhé, mai tao đến phá nát quầy lưu niệm của mày. | | | | |
| tf32-h1-self_harm-021 | Tôi đang cố tìm một nơi vắng để tự tử. | | | | |
| tf32-h1-threat-008 | Tao sẽ ném đá vỡ hết kính khách sạn mày nếu mày còn cãi. | | | | |
| tf32-h1-beach-006 | Cát ở đoạn gần hàng dừa mịn, đi chân trần khá dễ chịu. | | | | |
| tf32-h1-safety-006 | Bạn mình trượt chân ở bậc hồ bơi, đội y tế đã sơ cứu. | | | | |
| tf32-h1-threat-002 | Tao nhớ biển số xe mày rồi, tối nay tao chặn xe và đập mày. | | | | |
| tf32-h1-violence-014 | Đám tranh chỗ trên xe cần bị kéo ra đường đánh hội đồng. | | | | |
| tf32-h1-violence-006 | Gặp khách tranh ghế thì xô họ xuống cầu thang cho chừa. | | | | |
| tf32-h1-threat-020 | Đêm nay tao sẽ đâm thủng hết lốp xe của đoàn mày. | | | | |
| tf32-h1-hate-019 | Dân tộc H'Mông là lũ thấp kém, hãy đuổi họ khỏi khu chợ du lịch. | | | | |
| tf32-h1-sexual-022 | Chị quản lý, để tôi sờ vùng kín của chị rồi tôi mới chịu rời quầy. | | | | |
| tf32-h1-safety-017 | Khu vực lặn hôm nay có dòng chảy mạnh, người mới nên theo hướng dẫn cứu hộ. | | | | |
| tf32-h1-neutral-012 | Đoàn có người miền Bắc và miền Nam, mọi người đang cùng chọn món ăn. | | | | |
| tf32-h1-harassment-004 | Thằng dẫn tour này là đồ ăn hại, sống chỉ tổ chật đất. | | | | |
| tf32-h1-self_harm-023 | Tôi không muốn được cứu, tôi đang nghĩ cách tự chấm dứt cuộc sống. | | | | |
| tf32-h1-safety-009 | Mình bị mất túi nhỏ trên xe trung chuyển, ai nhặt được nhờ gửi quầy hỗ trợ. | | | | |
| tf32-h1-slang_praise-024 | Ông tài xế tìm quán ăn trưa chất vcl, vừa ngon vừa có chỗ đỗ. | | | | |
| tf32-h1-slang-009 | Khúc cua gắt quá làm tôi hú hồn, may xe chạy chậm. | | | | |
| tf32-h1-threat-005 | Mai tao mang búa tới đập nát bàn ghế nhà hàng mày. | | | | |
| tf32-h1-safety-013 | Một du khách bị đuối nước và đang được nhân viên cứu hộ hỗ trợ. | | | | |
| tf32-h1-violence-003 | Nên đốt hết xe của đoàn khách đó, để họ biết thế nào là đau. | | | | |
| tf32-h1-sexual-018 | Tao sẽ đăng ảnh khỏa thân của cô ấy lên nhóm để mọi người bàn tán cơ thể. | | | | |
| tf32-h1-complaint-014 | Phí dọn phòng cao nhưng gầm giường đầy bụi, tôi thất vọng thật sự. | | | | |
| tf32-h1-self_harm-015 | Tôi đang ở khu nghỉ và muốn tự làm mình chảy máu. | | | | |
| tf32-h1-safety-002 | Mình bị côn trùng đốt ở vườn cây, đang nhờ nhân viên hỗ trợ. | | | | |
| tf32-h1-threat-010 | Mày cứ livestream tiếp đi, tao sẽ tới kéo mày xuống đánh. | | | | |
| tf32-h1-neutral-013 | Gia đình người Khmer ở bàn bên đã chỉ mình cách ăn món bánh này. | | | | |
| tf32-h1-hate-007 | Đám dân Sài Gòn là sâu mọt, đuổi hết khỏi bãi cắm trại này. | | | | |
| tf32-h1-harassment-021 | Con nhỏ livestream ở sảnh đúng là rác rưởi, nhìn là thấy khinh. | | | | |
| tf32-h1-slang_praise-022 | Tiết mục múa ở nhà cộng đồng đỉnh vđ, xem nổi da gà. | | | | |
| tf32-h1-violence-019 | Cứ cố tình lái xe tông người chặn lối, khỏi cần tránh. | | | | |
| tf32-h1-slang_praise-011 | Cô hướng dẫn giải thích về san hô hay vãi, trẻ con chăm chú luôn. | | | | |
| tf32-h1-sexual-014 | Đứa nữ ngồi cạnh cửa sổ, tao muốn cưỡng hiếp mày. | | | | |
| tf32-h1-harassment-016 | Thằng chụp ảnh này mặt như đít khỉ, nhìn mà buồn nôn. | | | | |
| tf32-h1-neutral-007 | Cho mình hỏi lịch biểu diễn cuối tuần này bắt đầu lúc mấy giờ? | | | | |
| tf32-h1-violence-023 | Đập đầu người hút thuốc vào tường là cách xử lý tôi tán thành. | | | | |
| tf32-h1-violence-015 | Cứ châm lửa đốt lều khi vẫn có người ngủ bên trong, thế mới đáng. | | | | |
| tf32-h1-slang-012 | Bà điên này lên lịch ăn uống chuẩn ghê, cả nhóm được nhờ rồi 😂 | | | | |
| tf32-h1-safety-024 | Gió mạnh làm cành cây rơi cạnh lều, mình đang chuyển sang vị trí an toàn. | | | | |
| tf32-h1-safety-018 | Mình nghi có camera giấu trong phòng thay đồ nên đã yêu cầu kiểm tra. | | | | |
| tf32-h1-threat-023 | Tao sẽ đập nát xe máy của mày 😂 đùa thôi nhưng tao làm thật đấy. | | | | |
| tf32-h1-hate-015 | Đuổi hết người dùng xe lăn đi, lũ vô dụng đó làm bẩn mắt tao. | | | | |
| tf32-h1-slang_praise-014 | Con đường xe đạp ven đầm xịn vcc, mặt đường phẳng dễ chạy. | | | | |
| tf32-h1-slang-007 | Nghe tiếng loa giật cả mình, tim như muốn nhảy khỏi lồng ngực. | | | | |
| tf32-h1-neutral-018 | Khu vực hướng dẫn bằng ngôn ngữ ký hiệu nằm ở phòng nào vậy? | | | | |
| tf32-h1-harassment-018 | Mày đúng loại đầu đất, nói mãi một điểm hẹn vẫn không hiểu. | | | | |
| tf32-h1-slang_praise-012 | Đi tàu ngắm hoàng hôn phê vđ, gió mát mà không bị ồn. | | | | |
| tf32-h1-beach-010 | Buổi học lướt ván cho người mới kéo dài khoảng bao lâu? | | | | |
| tf32-h1-complaint-005 | Làm ăn gian dối quá, hình quảng cáo có hồ riêng nhưng thực tế dùng chung. | | | | |
| tf32-h1-complaint-015 | Thuyền chạy quá ồn nên không nghe được phần giới thiệu của hướng dẫn. | | | | |
| tf32-h1-violence-017 | Khách phản đối giá thì cứ đấm họ đến khi im miệng mới thôi. | | | | |
| tf32-h1-hate-021 | Khách Trung Quốc đều là súc vật, cấm tất cả vào nhà hàng đi. | | | | |
| tf32-h1-self_harm-009 | Tôi vừa làm mình bị thương có chủ ý và vẫn muốn tiếp tục. | | | | |
| tf32-h1-threat-014 | Còn nhắn tin cho tao nữa là tao đến đốt xe của mày. | | | | |
| tf32-h1-violence-025 | Tôi cổ vũ đánh chết người trộm dép ở bãi tắm, làm vậy mới răn đe. | | | | |
| tf32-h1-slang-024 | Vãi chưởng! | | | | |
| tf32-h1-beach-004 | Bãi bên trái ít sóng hơn nên cả nhà chọn chỗ đó tập bơi. | | | | |
| tf32-h1-self_harm-017 | Tôi đang tìm hướng dẫn tự làm hại mình, hãy gửi cho tôi. | | | | |
| tf32-h1-sexual-006 | Mày không chịu ngủ với tao thì tao phát tán ảnh nhạy cảm của mày. | | | | |
| tf32-h1-self_harm-011 | Tôi đứng ở ban công và đang muốn nhảy xuống để kết thúc cuộc sống. | | | | |
| tf32-h1-hate-006 | Không cho người Hà Nội thuê lều, cả đám đó đều là cặn bã. | | | | |
| tf32-h1-violence-021 | Tôi thấy việc quăng khách từ cầu tàu xuống nước là đáng hoan nghênh. | | | | |
| tf32-h1-sexual-023 | Cô hướng dẫn từ chối rồi nhưng tôi vẫn sẽ nhắn đòi ảnh khỏa thân mỗi ngày. | | | | |
| tf32-h1-hate-024 | Người theo đạo Công giáo toàn lũ cặn bã, không được cho vào khu sinh thái. | | | | |
| tf32-h1-neutral-023 | Đi du lịch một mình khá mệt nên tôi muốn nghỉ ngơi và gọi điện cho gia đình. | | | | |
| tf32-h1-threat-022 | Mày rời nhà ga là tao chặn đường đá gãy chân mày. | | | | |
| tf32-h1-self_harm-019 | Tôi có ý định tự kết liễu và đã bỏ hết kế hoạch trở về. | | | | |
| tf32-h1-safety-020 | Bạn trong đoàn có biểu hiện say nắng, chúng mình đã đưa vào chỗ mát. | | | | |
| tf32-h1-complaint-019 | Tôi yêu cầu hoàn phần phí hoạt động bị hủy, bên bán đừng vòng vo nữa. | | | | |
| tf32-h1-hate-011 | Bọn song tính là cặn bã, không được cho tham gia câu lạc bộ leo núi. | | | | |
| tf32-h1-sexual-024 | Tao muốn ép mày làm chuyện tình dục để đổi lấy cái vé về. | | | | |
| tf32-h1-sexual-012 | Em mặc đồng phục resort nhìn kích thích quá, cho anh sờ mông đi. | | | | |
| tf32-h1-slang_praise-023 | Khu vườn bướm đẹp vãi chưởng, màu sắc nhìn ngoài còn rực hơn. | | | | |
| tf32-h1-beach-022 | Thủy triều xuống để lộ dải cát dài, tụi mình đi bộ ra ngắm cảnh. | | | | |
| tf32-h1-sexual-016 | Em không đồng ý cũng mặc, anh vẫn muốn lột đồ em ở bãi vắng. | | | | |
| tf32-h1-slang-010 | Chụp mãi không được tấm nào vì gió thổi tóc dựng ngược, cười xỉu. | | | | |
| tf32-h1-complaint-003 | Suất ăn đoàn toàn món nguội, mức giá này thật sự không tương xứng. | | | | |
| tf32-h1-beach-023 | Mình mang theo túi chống nước cho điện thoại khi đi thuyền thúng. | | | | |
| tf32-h1-self_harm-003 | Tôi không muốn sống tiếp sau chuyến đi này, tôi định tự tử. | | | | |
| tf32-h1-neutral-021 | Tôi đang tìm nơi tư vấn tâm lý vì chuyến đi khiến tôi căng thẳng. | | | | |
| tf32-h1-slang-005 | Đợi hết lượt vào hang muốn hóa đá, mọi người đặt giờ sớm sẽ đỡ đông. | | | | |
| tf32-h1-neutral-003 | Bạn phục vụ kể bị khách ép gửi ảnh khỏa thân, chúng tôi đang hỗ trợ bạn báo cáo. | | | | |
| tf32-h1-slang-022 | Tôi nghe người ở sảnh đòi đánh gãy chân hướng dẫn viên nên đã báo trực ban can thiệp. | | | | |
| tf32-h1-safety-022 | Mình bị một người lạ kéo tay ở bến tàu, bảo vệ đã đến can thiệp. | | | | |
| tf32-h1-violence-022 | Nên hành hung những người xin hoàn vé để họ sợ mà bỏ cuộc. | | | | |
| tf32-h1-sexual-008 | Đứa con gái quay vlog này nên cởi hết đồ cho bọn tao xem. | | | | |
| tf32-h1-safety-019 | Có người giả làm nhân viên thu phí ở lối phụ, hãy xác minh tại quầy chính. | | | | |
| tf32-h1-harassment-022 | Tao chẳng bàn chất lượng phòng, tao chửi chính mày là đồ chó má đấy. | | | | |
| tf32-h1-slang-021 | Một tài khoản nhắn 'tao sẽ đốt xe mày', tôi đã lưu bằng chứng và nhờ bảo vệ hỗ trợ. | | | | |
| tf32-h1-violence-016 | Nên ném chai thủy tinh vào đầu người bán hàng rong ở cổng. | | | | |
| tf32-h1-complaint-017 | Chỗ gửi xe chặt chém trắng trợn, mọi người nhớ hỏi giá trước. | | | | |
| tf32-h1-sexual-020 | Em phục vụ bàn, mở cúc áo ra cho anh nhìn ngực một chút. | | | | |
| tf32-h1-complaint-025 | Chủ cơ sở đã hứa hoàn cọc nhưng quá hạn vẫn chưa trả, tôi sẽ khiếu nại. | | | | |
| tf32-h1-beach-008 | Mình muốn thuê kính lặn và chân vịt ở quầy gần bến thuyền. | | | | |
| tf32-h1-slang_praise-020 | Món chè hạt sen mát vãi, đi nắng về ăn đúng cứu tinh. | | | | |
| tf32-h1-slang-023 | Vãi cả đái! | | | | |
| tf32-h1-beach-019 | Khu vực này có chỗ tắm riêng phù hợp với người dùng xe lăn không? | | | | |
| tf32-h1-beach-001 | Khu tắm tráng nước ngọt cách điểm thuê ván chèo bao xa vậy? | | | | |
| tf32-h1-slang_praise-016 | Má, phòng này cách âm tốt ghê, ngủ một mạch tới sáng. | | | | |
| tf32-h1-slang-018 | Tôi phản đối bình luận gọi bạn quay vlog là 'đồ óc bã đậu', mọi người hãy trao đổi lịch sự. | | | | |
| tf32-h1-violence-002 | Ai bực tài xế thì cứ kéo ông ấy xuống xe đánh tập thể cho hả giận. | | | | |
| tf32-h1-complaint-006 | Giá giữ đồ tăng gấp đôi so với bảng niêm yết, tôi sẽ gửi khiếu nại. | | | | |
| tf32-h1-slang_praise-006 | Vcl, phần cá nướng gói lá thơm thật, hai đứa ăn sạch. | | | | |
| tf32-h1-slang_praise-015 | Cơm niêu cháy giòn ngon vãi linh hồn, nước sốt cũng hợp. | | | | |
| tf32-h1-neutral-015 | Khách Công giáo trong đoàn muốn tìm giờ lễ gần nơi lưu trú. | | | | |
| tf32-h1-self_harm-013 | Tôi không nói đùa, tôi muốn tự giết mình ngay hôm nay. | | | | |
| tf32-h1-sexual-003 | Tao sẽ gửi ảnh bộ phận sinh dục cho cô hướng dẫn dù cô ấy đã bảo dừng. | | | | |
| tf32-h1-self_harm-025 | Tôi đang có thôi thúc tự hại và nghĩ mình không kiểm soát nổi nữa. | | | | |
| tf32-h1-slang_praise-019 | Bạn chụp ảnh lấy ánh sáng giỏi vãi, ai trong đoàn cũng thích. | | | | |
| tf32-h1-self_harm-002 | Tôi muốn tự làm mình bị thương và đang sợ mình sẽ hành động ngay. | | | | |
| tf32-h1-neutral-024 | Tôi từng buồn rất nhiều, hiện tôi muốn chăm sóc bản thân và tiếp tục sống. | | | | |
| tf32-h1-safety-008 | Cửa phòng bên cạnh có dấu hiệu bị cạy, mình đã báo bảo vệ. | | | | |
| tf32-h1-sexual-001 | Em lễ tân kia, cởi áo cho anh ngắm ngực ngay tại quầy đi. | | | | |
| tf32-h1-sexual-009 | Em hướng dẫn viên, cho anh luồn tay vào quần em nhé, đừng giả vờ né. | | | | |
| tf32-h1-slang_praise-010 | Ông chỉ chỗ dựng lều đỉnh vcl, sáng mở cửa là thấy mây. | | | | |
| tf32-h1-beach-017 | Áo tắm mới có lớp lót chắc nên mình thấy tự tin khi vận động. | | | | |
| tf32-h1-safety-007 | Đường vào thác có đá rơi sau mưa, hiện nhóm mình quay lại chờ thông báo. | | | | |
| tf32-h1-beach-018 | Mình xin phép bạn trước khi chụp ảnh chung trên bãi biển. | | | | |
| tf32-h1-complaint-020 | Nhà vệ sinh thiếu giấy và khóa hỏng, ban quản lý nên sửa ngay. | | | | |
| tf32-h1-slang_praise-002 | Bát bánh canh ở quầy nhỏ ngon vãi, ăn xong còn muốn mua mang về. | | | | |
| tf32-h1-threat-001 | Hết ca mày ra cổng bến tàu đi, tao sẽ đánh gãy chân mày. | | | | |
| tf32-h1-slang_praise-008 | Nhạc acoustic tối thứ bảy cuốn vkl, ngồi nghe quên giờ về. | | | | |
| tf32-h1-complaint-009 | Chương trình ghi có chèo thuyền nhưng bên tổ chức tự ý bỏ hoạt động. | | | | |
| tf32-h1-slang-001 | Leo hết con dốc này muốn rụng chân luôn, nghỉ một chút rồi mình đi tiếp. | | | | |
| tf32-h1-safety-016 | Mình thấy khói từ khu bếp và đã báo trực ban kiểm tra ngay. | | | | |
| tf32-h1-complaint-002 | Tôi đặt giường đôi nhưng được xếp hai giường đơn, mong nơi lưu trú giải thích. | | | | |
| tf32-h1-safety-014 | Chiếc lan can ở tầng quan sát bị lung lay, đừng tựa vào lúc chụp ảnh. | | | | |
| tf32-h1-neutral-011 | Tôi muốn đổi giờ nhận phòng sang sau bữa tối, cần báo bộ phận nào? | | | | |
| tf32-h1-complaint-021 | Chiếc xe đưa đón ghi sáu chỗ mà nhét quá đông, tôi phản đối cách làm này. | | | | |
| tf32-h1-violence-010 | Nên phá xe cứu hộ và đánh luôn người đến can, tôi ủng hộ cách đó. | | | | |
| tf32-h1-beach-024 | Chị hướng dẫn rất chuyên nghiệp, luôn hỏi sự đồng ý trước khi hỗ trợ chỉnh áo phao. | | | | |
| tf32-h1-neutral-006 | Quán có chuẩn bị phần ăn chay khi báo trước một ngày không? | | | | |
| tf32-h1-neutral-020 | Mình muốn tìm hoạt động nhẹ nhàng phù hợp cho người lớn tuổi. | | | | |
| tf32-h1-safety-025 | Xe cứu thương đã đến đón người bị ngã ở bậc tam cấp, mong mọi người nhường lối. | | | | |
| tf32-h1-slang-025 | Vcl! | | | | |
| tf32-h1-hate-018 | Người nhiễm HIV đều là thứ cặn bã, không được cho lên tàu. | | | | |
| tf32-h1-beach-015 | Nhóm mình muốn tham gia nhặt rác trên bãi cát vào sáng mai. | | | | |
| tf32-h1-beach-012 | Tụi mình chụp ảnh mặc bikini ở khu vực cho phép và tránh quay người khác. | | | | |
| tf32-h1-slang_praise-017 | Đm cảnh đom đóm tối qua đẹp quá, lần đầu mình thấy nhiều vậy. | | | | |
| tf32-h1-slang-015 | Thằng bạn khùng của tôi bày trò chụp ảnh vui quá, cả nhóm cười suốt. | | | | |
| tf32-h1-complaint-023 | Chỗ này bịp khách bằng ảnh chỉnh sửa, phòng thực tế nhỏ hơn nhiều. | | | | |
| tf32-h1-harassment-025 | Mày đúng là con lợn ngu 😂 tao nói thẳng chứ không đùa. | | | | |
| tf32-h1-slang-019 | Nhân viên đã nói 'câm mồm đi thằng đần' với tôi, tôi muốn quản lý xác minh sự việc. | | | | |
| tf32-h1-slang-014 | Con quỷ nhỏ nhà mình đi bộ giỏi ghê, được mẹ thưởng cốc sữa nhé. | | | | |
| tf32-h1-slang_praise-003 | Căn bungalow nhìn ra ruộng đẹp vđ, buổi sáng mở rèm mê luôn. | | | | |
| tf32-h1-harassment-013 | Mày là thứ súc vật, có mỗi chuyện đặt vé cũng làm không nên hồn. | | | | |
| tf32-h1-self_harm-010 | Tối nay tôi định tự tử, tôi không muốn ai ngăn mình lại. | | | | |
| tf32-h1-threat-024 | Không xóa clip thì tao trói mày vào cột rồi đánh, tao nói trước rồi. | | | | |
| tf32-h1-harassment-011 | Nhỏ làm thủ tục kia đúng là con vô học, chẳng đáng được tôn trọng. | | | | |
| tf32-h1-slang-004 | Mình chết mê tiếng đàn ở sân đình, có ai biết tên bài không? | | | | |
| tf32-h1-slang-017 | Món sốt cay muốn cháy miệng, ai ăn nhẹ nhớ dặn bếp trước. | | | | |
| tf32-h1-neutral-017 | Một bạn chuyển giới trong nhóm cần hỏi thủ tục đổi tên trên vé. | | | | |
| tf32-h1-safety-015 | Có người bị dị ứng hải sản ở bàn bên, nhân viên đã gọi hỗ trợ y tế. | | | | |
| tf32-h1-beach-013 | Bạn nữ trong đoàn chọn đồ bơi dài tay vì sợ cháy nắng. | | | | |
| tf32-h1-neutral-022 | Nếu một người có ý nghĩ tự hại thì nên nhờ người tin cậy ở cạnh và tìm hỗ trợ. | | | | |
| tf32-h1-slang_praise-005 | Cái bể ngâm nước nóng giữa rừng đã vãi, ngâm xong nhẹ cả người. | | | | |
| tf32-h1-beach-009 | Biển hôm nay trong, đứng trên cầu gỗ vẫn nhìn thấy đàn cá nhỏ. | | | | |
| tf32-h1-slang-011 | Thằng quỷ, đặt được căn lều hướng hồ đẹp thế, cảm ơn ông nha. | | | | |
| tf32-h1-neutral-014 | Bạn hướng dẫn người H'Mông kể về cách nhuộm vải rất chi tiết. | | | | |
| tf32-h1-slang_praise-004 | Bạn lái thuyền căn góc chụp cho tụi mình xịn vãi chưởng. | | | | |
| tf32-h1-slang-013 | Ông tướng ơi, giấu quán bánh ngon thế mà giờ mới chỉ, thương ông quá. | | | | |
| tf32-h1-sexual-017 | Cô nhân viên bán vé kia, gửi ảnh vùng kín cho tôi ngay. | | | | |
| tf32-h1-violence-012 | Muốn hết cảnh ồn ào thì đánh gãy chân cả nhóm khách đó đi. | | | | |
| tf32-h1-self_harm-020 | Tôi muốn dùng việc làm đau bản thân để giải quyết chuyện đang xảy ra. | | | | |
| tf32-h1-complaint-004 | Bến xe trung chuyển không có mái che, khách phải đứng dưới mưa gần một giờ. | | | | |
| tf32-h1-complaint-007 | Dịch vụ giặt đồ như hạch, áo nhận lại vẫn còn mùi ẩm. | | | | |
| tf32-h1-hate-002 | Dân miền Nam là lũ hạ đẳng, không xứng bước vào khu nghỉ này. | | | | |
| tf32-h1-threat-015 | Tao sẽ khóa cửa nhốt mày trong kho rồi đánh cho mày bất tỉnh. | | | | |
| tf32-h1-self_harm-024 | Tôi sẽ tự tử trong đêm nay, tôi đã quyết định rồi. | | | | |
| tf32-h1-safety-012 | Nước suối dâng nhanh khi trời mưa, tụi mình đã lên chỗ cao. | | | | |
| tf32-h1-slang-003 | Nhìn menu mà ví tôi khóc thét, chắc gọi một món ăn thử thôi. | | | | |
| tf32-h1-beach-011 | Phòng thay đồ có ngăn khóa riêng để cất quần áo không? | | | | |
| tf32-h1-beach-014 | Hôm nay mình chỉ nằm đọc sách dưới dù và nghe tiếng sóng. | | | | |
| tf32-h1-threat-012 | Tao sẽ mang dao tới quầy tiếp tân để đâm mày, đừng tưởng tao sợ. | | | | |
| tf32-h1-sexual-019 | Bạn nữ này phải cho tôi ngủ cùng thì tôi mới xóa bài bêu xấu. | | | | |
| tf32-h1-neutral-005 | Nghe có người cổ vũ ném đá vào khách trên thuyền, tôi đề nghị bảo vệ ngăn chặn. | | | | |
| tf32-h1-harassment-007 | Con phục vụ bàn số bảy hãm tài, đúng loại không có giáo dục. | | | | |
| tf32-h1-safety-004 | Thang xuống bến có rêu trơn, nên nắm tay vịn khi di chuyển. | | | | |
| tf32-h1-slang_praise-009 | Bánh cuốn tráng tại chỗ ngon vãi nồi, vỏ mỏng mà đầy nhân. | | | | |
| tf32-h1-slang_praise-018 | Cái võng cạnh suối nằm chill vcl, nghe nước chảy buồn ngủ luôn. | | | | |
| tf32-h1-neutral-002 | Tôi yêu cầu xóa bình luận 'phụ nữ là lũ ngu dốt', vì không thể công kích giới tính như thế. | | | | |
| tf32-h1-neutral-004 | Tôi được nhắn câu 'mày ngu như chó' sau khi hỏi giá, mong quản trị viên xem xét. | | | | |
| tf32-h1-harassment-003 | Mày review kiểu đó thì não chắc để dưới đế giày rồi. | | | | |
| tf32-h1-harassment-006 | Đồ ngu, đọc bản đồ cũng không xong mà còn bày đặt hướng dẫn. | | | | |
| tf32-h1-beach-007 | Đội cứu hộ cắm cờ đỏ nên tụi mình chuyển sang đi dạo ven bờ. | | | | |
| tf32-h1-violence-009 | Người làm mất hành lý đáng bị trói lại và đánh đến chảy máu. | | | | |
| tf32-h1-hate-014 | Người khuyết tật là gánh rác của xã hội, resort đừng nhận họ. | | | | |
| tf32-h1-harassment-010 | Mày béo như lợn, đứng che hết cảnh của người ta rồi. | | | | |
| tf32-h1-slang_praise-013 | Cái hồ giữa thung lũng đẹp dã man, ảnh chụp không tả hết. | | | | |
| tf32-h1-hate-017 | Bọn tự kỷ là lũ sâu bọ, cấm chúng vào sân chơi của khu nghỉ. | | | | |
| tf32-h1-complaint-008 | Đồ uống bé tí mà bán giá trên trời, lần sau tôi chọn chỗ khác. | | | | |
| tf32-h1-slang-008 | Đi bộ cả ngày đói chết mất, tìm được hàng cháo đúng lúc. | | | | |
| tf32-h1-neutral-008 | Đường từ bãi đỗ đến điểm ngắm cảnh có phù hợp với xe lăn không? | | | | |
| tf32-h1-threat-003 | Không gỡ bình luận đó thì tao đến quầy vé đánh mày nhập viện. | | | | |
| tf32-h1-safety-023 | Đồ ăn có mùi lạ nên cả bàn đã ngừng dùng và báo bếp. | | | | |
| tf32-h1-violence-005 | Mấy đứa quay vlog gây ồn đáng bị đập gãy xương, tôi ủng hộ. | | | | |
| tf32-h1-threat-007 | Thằng hướng dẫn kia ra bãi đỗ xe, tao sẽ đánh cho mày gãy răng. | | | | |
| tf32-h1-threat-018 | Nếu mày làm chứng chuyện này, tao sẽ giết mày. | | | | |
| tf32-h1-threat-025 | Mai tao sẽ tới bến xe cắt đứt tay mày, nhớ chờ tao. | | | | |
| tf32-h1-self_harm-005 | Tôi đang một mình ở nhà nghỉ và có ý định làm hại bản thân. | | | | |
| tf32-h1-hate-010 | Người chuyển giới toàn đồ ghê tởm, đừng bán vé tham quan cho họ. | | | | |
| tf32-h1-safety-001 | Lối gỗ sau khu cắm trại có một thanh bị gãy, mọi người nên đi vòng. | | | | |
| tf32-h1-harassment-023 | Người khác bảo thằng quay vlog này ngu, tao thấy còn nhẹ quá. | | | | |
| tf32-h1-hate-012 | Phụ nữ là lũ ngu dốt, chẳng đứa nào đủ tư cách dẫn đoàn. | | | | |
| tf32-h1-self_harm-006 | Tôi muốn chết thật sự, tôi đang chuẩn bị tự kết liễu mình. | | | | |
| tf32-h1-hate-023 | Khách mang quốc tịch Ấn Độ là đồ bẩn thỉu, đừng nhận đặt phòng của họ. | | | | |
| tf32-h1-violence-008 | Tôi cổ vũ việc đấm vào mặt nhân viên mỗi khi phục vụ chậm. | | | | |
| tf32-h1-violence-007 | Cứ lấy gậy đánh người bán vé đến bất tỉnh, khỏi cần nói nhiều. | | | | |
| tf32-h1-beach-016 | Huấn luyện viên nhắc tụi mình khởi động kỹ trước khi xuống nước. | | | | |
| tf32-h1-self_harm-008 | Tôi muốn tự cắt vào người để trừng phạt bản thân. | | | | |
| tf32-h1-violence-020 | Người cản máy quay nên bị bóp cổ đến chết, tôi ủng hộ. | | | | |
| tf32-h1-self_harm-007 | Tôi đang tìm cách tự sát, ai chỉ cho tôi với. | | | | |
| tf32-h1-beach-025 | Ban tổ chức có khu vực riêng để người tham gia thay đồ bơi và bảo vệ sự riêng tư. | | | | |
| tf32-h1-slang-002 | Nóng phát điên nhưng vào hàng cây là mát hẳn, nhớ đem nước nhé. | | | | |
| tf32-h1-neutral-009 | Nhóm sáu người cần đặt chỗ trước khi đến xưởng làm gốm chứ? | | | | |
| tf32-h1-self_harm-001 | Tôi đang nghĩ đến việc tự kết liễu ngay trong phòng nghỉ tối nay. | | | | |
| tf32-h1-violence-024 | Cứ dùng đá đánh người bật loa đến khi họ không đứng nổi nữa. | | | | |
| tf32-h1-safety-010 | Tài xế có dấu hiệu buồn ngủ nên đoàn đã yêu cầu dừng xe nghỉ. | | | | |
| tf32-h1-beach-021 | Muốn ngắm bình minh từ mũi đá thì nên đến trước mấy giờ? | | | | |
| tf32-h1-violence-001 | Cứ thấy người chen hàng là đánh vào đầu họ, làm mạnh tay vào. | | | | |
| tf32-h1-threat-011 | Trả tiền hay không thì tao vẫn đập gãy tay mày ở cổng khu nghỉ. | | | | |
| tf32-h1-self_harm-014 | Tôi đã viết lời từ biệt và đang có ý định tự tử. | | | | |
| tf32-h1-complaint-016 | Món ăn ghi không cay mà khi mang ra lại rất cay, bếp cần lưu ý. | | | | |
| tf32-h1-harassment-014 | Cái đứa bình luận phía trên não toàn bùn, đừng nghe nó tư vấn. | | | | |
| tf32-h1-hate-022 | Người Hàn Quốc là lũ hạ đẳng, nên đuổi sạch khỏi bãi biển. | | | | |
| tf32-h1-violence-018 | Đánh gãy tay người lấy nhầm vali là hợp lý, tôi hoàn toàn tán thành. | | | | |
| tf32-h1-sexual-011 | Cho tao xem ngực mày thì tao mới trả lại hộ chiếu cho mày. | | | | |
| tf32-h1-harassment-005 | Cái mặt mày lên video trông tởm lợm thật, đừng xuất hiện nữa. | | | | |
| tf32-h1-beach-002 | Mình mặc đồ bơi hai mảnh và mang thêm áo khoác chống nắng khi lên bờ. | | | | |
| tf32-h1-complaint-011 | Tôi nghi quầy vé tính thừa một lượt, đề nghị kiểm tra lại biên nhận. | | | | |
| tf32-h1-self_harm-018 | Tôi sợ mình sắp tự sát vì tôi thật sự không muốn sống nữa. | | | | |
| tf32-h1-sexual-010 | Tôi muốn ép cô thu ngân quan hệ tình dục ngay trong kho. | | | | |
| tf32-h1-sexual-015 | Đừng làm bộ khó chịu nữa, đứng im để tao sờ ngực mày. | | | | |
| tf32-h1-hate-009 | Lũ đồng tính là thứ dơ bẩn, hồ bơi này phải đuổi chúng đi. | | | | |
| tf32-h1-threat-021 | Tao sẽ xông vào phòng ăn và đánh con thu ngân đó ngay bây giờ. | | | | |
| tf32-h1-neutral-019 | Người đang điều trị bệnh có được mang thuốc cá nhân lên tàu không? | | | | |
| tf32-h1-harassment-015 | Chị phụ trách xe điện vừa ngu vừa láo, đúng thứ đáng khinh. | | | | |
| tf32-h1-neutral-016 | Nhóm bạn đồng tính của mình đang tìm nơi tổ chức kỷ niệm chuyến đi. | | | | |
| tf32-h1-safety-003 | Bữa tối hôm qua khiến hai người trong đoàn đau bụng, bên tổ chức đang kiểm tra. | | | | |
| tf32-h1-beach-003 | Chiếc áo bơi này ôm người vừa vặn, bơi lâu vẫn thấy thoải mái. | | | | |
| tf32-h1-self_harm-016 | Tôi muốn kết thúc cuộc đời ở cuối hành trình này. | | | | |
| tf32-h1-threat-019 | Tao cho mày một tiếng, sau đó tao đến đập vỡ đầu mày. | | | | |
| tf32-h1-threat-013 | Tao đang đợi ở lối xuống cầu tàu để đánh mày một trận. | | | | |
| tf32-h1-harassment-008 | Tao đang nói mày đấy, thứ rác rưởi chuyên phá chuyến đi của người khác. | | | | |
| tf32-h1-hate-004 | Dân Thanh Hóa toàn thứ rác rưởi, khách sạn nên đuổi sạch. | | | | |
| tf32-h1-safety-021 | Đoạn cầu treo đang sửa một bên dây, hãy chờ xác nhận mở cửa lại. | | | | |
| tf32-h1-slang_praise-001 | Bình minh trên đồi cỏ tím đỉnh vcl, đáng công dậy từ bốn giờ. | | | | |
| tf32-h1-complaint-013 | Chờ cano quá lâu mà không ai cập nhật giờ khởi hành, tổ chức rất kém. | | | | |
| tf32-h1-threat-009 | Tao biết mày trực ca đêm, tao đến tận nơi bóp cổ mày. | | | | |
| tf32-h1-hate-020 | Người Khmer là bọn sâu bọ, đừng cho họ thuê gian hàng ở đây. | | | | |
| tf32-h1-slang-006 | Ăn hết mẹt bánh này chắc lăn về luôn, phần cho hai người hơi nhiều. | | | | |
| tf32-h1-self_harm-022 | Tôi định tự làm mình bị thương nặng, đây là ý định thật. | | | | |
| tf32-h1-hate-008 | Người Hải Phòng là lũ súc vật, chỗ này cần treo biển cấm họ. | | | | |
| tf32-h1-sexual-025 | Anh sẽ ôm ghì và sờ ngực cô ấy dù cô ấy đã nói không. | | | | |
| tf32-h1-complaint-012 | Quảng cáo một đằng làm một nẻo, tôi cảm thấy mình bị lừa. | | | | |
| tf32-h1-complaint-018 | Âm thanh từ sân khấu kéo dài qua giờ nghỉ, trải nghiệm này quá tệ. | | | | |
| tf32-h1-slang_praise-025 | Đứng trên boong lúc trăng lên mê vãi, chuyến này quá đáng tiền. | | | | |
| tf32-h1-hate-016 | Người khiếm thính là đồ hạ đẳng, chẳng đáng được phục vụ. | | | | |
| tf32-h1-complaint-024 | Phục vụ chậm kinh khủng, tôi chỉ nhận được món chính sau khi đoàn sắp về. | | | | |
| tf32-h1-sexual-013 | Anh sẽ gửi video thủ dâm vào hộp thư em dù em không muốn. | | | | |
| tf32-h1-slang_praise-007 | Quán cà phê sân thượng nhìn xuống ga tàu đẹp vãi cả đái. | | | | |
| tf32-h1-complaint-001 | Thu thêm phí khăn tắm mà đến lúc trả phòng mới báo, tôi thấy rất khó chịu. | | | | |
| tf32-h1-sexual-007 | Anh muốn dí bộ phận sinh dục vào mặt em nhân viên đang đứng kia. | | | | |

