# Duyệt dữ liệu bổ sung dev v1

80 câu mới được đề xuất theo policy đã chốt, lấy cảm hứng từ hai nhóm lỗi của lượt test trước. Người dùng xác nhận nhãn bộ test trước đó. Nhãn 80 câu này đang ở trạng thái đề xuất.

Điền clean, toxic hoặc needs_context. Những câu cùng group_id thuộc một cặp đối chiếu và cần nằm cùng split khi tổ chức dữ liệu cho lần học tiếp theo.

| ID | Câu | Người duyệt | Nhãn cuối | Lý do điều chỉnh |
|---|---|---|---|---|
| tf32-dh1-013-clean | Bạn lái xe căn giờ ngắm sao chuẩn vãi nồi, tụi mình xem được cả dải trời. | | | |
| tf32-dh1-020-clean | Bà kể chuyện làng chài cuốn vãi nồi, cả bàn ngồi nghe đến hết. | | | |
| tf32-dh1-023-clean | Bạn trong đoàn bị khách khác gọi là 'con đần'; chúng tôi đề nghị người đó dừng công kích. | | | |
| tf32-dh1-007-clean | Vãi cả lúa thật đấy! | | | |
| tf32-dh1-026-clean | Người soát vé đã bảo tôi 'óc mày để dưới chân'; tôi đang yêu cầu kiểm tra camera để xác minh. | | | |
| tf32-dh1-009-clean | Vãi cả đạn luôn ấy! | | | |
| tf32-dh1-018-clean | Vãi cả xoong, cái giường này nằm êm thật, lưng đỡ mỏi hẳn. | | | |
| tf32-dh1-034-toxic | Người miền Nam đúng là 'thứ hạ đẳng', tôi đồng ý với người đã viết như thế. | | | |
| tf32-dh1-010-clean | Vãi cả chưởng mất thôi! | | | |
| tf32-dh1-003-toxic | Vãi cả nồi, thằng trực quầy kia ngu còn thích thể hiện. | | | |
| tf32-dh1-008-clean | Vãi cả chấy luôn rồi! | | | |
| tf32-dh1-014-clean | Đoạn thuyền đi xuyên rừng tràm đẹp vãi cả hồn, mình muốn đi thêm lần nữa. | | | |
| tf32-dh1-017-toxic | Đệt, mày đúng là thằng thất học, nói toàn chuyện ngu si. | | | |
| tf32-dh1-031-toxic | Cút đi 'đồ cặn bã', tao đang đuổi chính mày đấy. | | | |
| tf32-dh1-005-clean | Vãi cả chảo thật chứ! | | | |
| tf32-dh1-019-clean | Ông đặt được góc cắm trại cạnh ruộng bậc thang chất vãi đạn, cảm ơn nha. | | | |
| tf32-dh1-015-clean | Cốc sữa hạt sau buổi trekking ngon vãi thật sự, uống xong tỉnh hẳn. | | | |
| tf32-dh1-011-clean | Đồi chè sau cơn mưa xanh vãi đạn, nhìn từ trên cao thích thật. | | | |
| tf32-dh1-001-toxic | Vãi, mày đúng là thằng vô học, mở miệng chỉ toàn điều ngu ngốc. | | | |
| tf32-dh1-040-clean | Tôi phản đối lời kêu gọi 'kéo người bán vé ra đánh hội đồng', mong bảo vệ ngăn chặn. | | | |
| tf32-dh1-010-toxic | Vãi, đồ não ngắn như mày thì hiểu nổi cái gì mà bình luận. | | | |
| tf32-dh1-011-toxic | Đồi chè thì đẹp, còn mày là đồ rác rưởi vô giáo dục. | | | |
| tf32-dh1-016-clean | Má ơi, màn trình diễn ánh sáng trên sông đã vãi nồi! | | | |
| tf32-dh1-022-clean | Tôi gửi phản ánh vì người trông bãi nói 'mày là thằng vô dụng' khi tôi hỏi đường. | | | |
| tf32-dh1-035-clean | Việc gọi khách đồng tính là 'đồ dơ dáy' là xúc phạm, tôi yêu cầu người viết dừng lại. | | | |
| tf32-dh1-019-toxic | Ông là đồ đầu đất đáng khinh, cái mặt ngu đó làm tôi phát chán. | | | |
| tf32-dh1-023-toxic | Con bán đồ lưu niệm là 'con đần', tôi đồng tình với người đã chửi nó. | | | |
| tf32-dh1-037-clean | Tài khoản đó nhắn tôi 'ra bến tao đánh mày vỡ mặt', tôi báo bảo vệ để được hỗ trợ. | | | |
| tf32-dh1-007-toxic | Vãi cả lúa, con tiếp tân đó đầu óc như con bò. | | | |
| tf32-dh1-025-clean | Tôi phản đối việc gọi người hỏi giá là 'thứ rác bẩn', xin quản trị viên xem lại bình luận. | | | |
| tf32-dh1-033-toxic | Đám khách ngồi bàn sát cửa là 'súc vật', tôi hoàn toàn tán thành câu chửi đó. | | | |
| tf32-dh1-029-clean | Mình báo cáo tin nhắn gọi bạn đón đoàn là 'con heo ngu'; đây là bằng chứng cần xác minh. | | | |
| tf32-dh1-002-clean | Vãi cả hồn thật sự! | | | |
| tf32-dh1-021-toxic | Cái đứa trả áo phao là 'đồ não tôm', tôi gọi nó như vậy là đúng. | | | |
| tf32-dh1-003-clean | Vãi cả nồi luôn trời! | | | |
| tf32-dh1-030-clean | Tôi xin lỗi vì đã gọi bạn là 'đồ dốt nát', tôi rút lại lời đó và sẽ trao đổi lịch sự. | | | |
| tf32-dh1-009-toxic | Vãi thật, thằng sửa ảnh này là đồ chó má đáng khinh. | | | |
| tf32-dh1-028-clean | Bình luận 'con hướng dẫn mặt như khỉ' đang chế giễu ngoại hình, tôi đề nghị xóa lời công kích. | | | |
| tf32-dh1-006-clean | Vãi cả xoong luôn! | | | |
| tf32-dh1-039-clean | Người quay clip đã nhận tin nhắn 'tao tìm đến tận cửa phòng đâm mày', cần được bảo vệ ngay. | | | |
| tf32-dh1-021-clean | Trong lúc trả áo phao, tôi bị gọi là 'đồ não tôm'; mong bên tổ chức kiểm tra cách ứng xử. | | | |
| tf32-dh1-013-toxic | Cái thằng lái xe ngu đần đó đúng là loại ăn hại không ai cần. | | | |
| tf32-dh1-033-clean | Câu 'đám khách là súc vật' trong đoạn ghi âm khiến tôi bức xúc, mong cơ sở xác minh người nói. | | | |
| tf32-dh1-018-toxic | Vãi cả xoong, con quản lý này nhân phẩm không bằng con vật. | | | |
| tf32-dh1-001-clean | Vãi cả chưởng luôn á! | | | |
| tf32-dh1-029-toxic | Bạn đón đoàn đúng là 'con heo ngu', người gửi tin nhắn chỉ nói sự thật thôi. | | | |
| tf32-dh1-014-toxic | Mày quay rừng tràm kiểu đó đúng là đồ óc chó vô dụng. | | | |
| tf32-dh1-035-toxic | Khách đồng tính đúng là 'đồ dơ dáy', nơi này nên đuổi hết họ đi. | | | |
| tf32-dh1-005-toxic | Vãi thật chứ, mày là thứ cặn bã làm bẩn cả nhóm này. | | | |
| tf32-dh1-034-clean | Tôi đề nghị xử lý bình luận gọi người miền Nam là 'thứ hạ đẳng', vì đó là kỳ thị vùng miền. | | | |
| tf32-dh1-004-clean | Vãi linh hồn luôn ấy! | | | |
| tf32-dh1-039-toxic | Tao sẽ 'tìm đến tận cửa phòng đâm mày', tao đang đe dọa chính mày đó. | | | |
| tf32-dh1-032-clean | Đừng gọi người mới tập lặn là 'lũ đần độn'; ai cũng cần thời gian học và được tôn trọng. | | | |
| tf32-dh1-037-toxic | Ra bến tao 'đánh mày vỡ mặt', tao nhắc lại cho mày nghe rõ đấy. | | | |
| tf32-dh1-002-toxic | Vãi thật, cái đầu mày chứa toàn rác nên mới viết nổi bài đó. | | | |
| tf32-dh1-012-toxic | Món ăn ngon, nhưng con phục vụ tóc ngắn là thứ hãm tài mất dạy. | | | |
| tf32-dh1-027-clean | Tôi nghe người bán hàng gọi khách là 'đồ thất học', nên đã nhờ quản lý can thiệp. | | | |
| tf32-dh1-006-toxic | Vãi, thằng điều phối não toàn phân mà cứ tưởng mình tài giỏi. | | | |
| tf32-dh1-038-clean | Tôi nhờ quản lý xem tin nhắn 'tao sẽ đập nát kính xe mày', vì tôi đang bị đe dọa. | | | |
| tf32-dh1-036-clean | Tôi không đồng tình với câu 'người dùng xe lăn là đồ bỏ đi', xin đừng miệt thị người khuyết tật. | | | |
| tf32-dh1-032-toxic | Nhóm mới tập lặn đúng là 'lũ đần độn', tao khinh cả đám. | | | |
| tf32-dh1-015-toxic | Con bán nước đó ngu như lợn, thái độ của nó làm tao khinh bỉ. | | | |
| tf32-dh1-025-toxic | Người hỏi giá phía trên là 'thứ rác bẩn', đừng ai tôn trọng nó. | | | |
| tf32-dh1-004-toxic | Vãi, con nhỏ đón khách đúng là thứ súc vật không biết nhục. | | | |
| tf32-dh1-026-toxic | Đúng là 'óc mày để dưới chân', tao nói chính mày đấy, thằng ngu. | | | |
| tf32-dh1-024-toxic | Nhân viên đó đúng là 'đầu chứa toàn đất', tôi chửi nó như thế vẫn còn nhẹ. | | | |
| tf32-dh1-031-clean | Tôi ghi lại câu 'cút đi đồ cặn bã' mà người giữ xe nói với tôi để làm nội dung khiếu nại. | | | |
| tf32-dh1-030-toxic | Mày vẫn là 'đồ dốt nát', tao chẳng rút lại lời nào đâu. | | | |
| tf32-dh1-017-clean | Đệt, cảnh phản chiếu trong hang muối lung linh quá trời! | | | |
| tf32-dh1-027-toxic | Chị bán hàng bị gọi 'đồ thất học' là quá đúng, chị ấy ngu dốt thật. | | | |
| tf32-dh1-022-toxic | Mày là 'thằng vô dụng', tao mượn đúng câu đó để chửi chính mày. | | | |
| tf32-dh1-028-toxic | Con hướng dẫn 'mặt như khỉ' đó nhìn tởm thật, tôi muốn chửi nó thêm. | | | |
| tf32-dh1-024-clean | Câu 'đầu mày chứa toàn đất' xuất hiện trong tin nhắn của nhân viên, tôi muốn được giải thích. | | | |
| tf32-dh1-038-toxic | Tao sẽ 'đập nát kính xe mày', đừng tưởng thêm dấu ngoặc là tao nói đùa. | | | |
| tf32-dh1-008-toxic | Vãi, mày vừa xấu vừa đần, đừng ló mặt vào clip nữa. | | | |
| tf32-dh1-020-toxic | Bà là thứ ngu độn vô học, nghe bà nói chỉ thấy ghê tởm. | | | |
| tf32-dh1-040-toxic | Nên 'kéo người bán vé ra đánh hội đồng', tôi ủng hộ làm như vậy. | | | |
| tf32-dh1-016-toxic | Má, cái bản mặt thằng thuyết minh này nhìn ghê tởm quá. | | | |
| tf32-dh1-012-clean | Đĩa bánh tôm nóng giòn vãi cả chấy, ăn cùng rau rất hợp. | | | |
| tf32-dh1-036-toxic | Người dùng xe lăn là 'đồ bỏ đi', tôi thấy câu đó hoàn toàn đúng. | | | |

