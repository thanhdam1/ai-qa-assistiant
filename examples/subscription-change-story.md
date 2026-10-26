# Story mẫu: Đổi gói thuê bao và tính phí theo chu kỳ

## Tiêu đề

Đổi gói thuê bao có hiệu lực theo chu kỳ thanh toán

## User story

Là người đang sử dụng dịch vụ thuê bao, tôi muốn đổi gói hiện tại sang gói khác để điều chỉnh dịch vụ phù hợp với nhu cầu của mình.

## Acceptance criteria

1. Người dùng chỉ được đổi gói thuê bao đang ở trạng thái `active`.
2. Khi đổi sang gói có giá cao hơn, gói mới có hiệu lực ngay sau khi thao tác đổi được xác nhận thành công.
3. Khi đổi sang gói có giá thấp hơn, gói mới có hiệu lực từ đầu chu kỳ thanh toán kế tiếp; người dùng vẫn dùng gói hiện tại đến hết chu kỳ.
4. Nếu thao tác đổi gói thất bại, gói đang dùng và ngày kết thúc chu kỳ hiện tại không thay đổi.
5. Sau khi đổi gói thành công, màn hình chi tiết thuê bao hiển thị tên gói đang có hiệu lực và ngày hiệu lực của gói mới.
6. Không cho phép đổi sang chính gói đang có hiệu lực.

## Business context

- Mỗi thuê bao thuộc về một tài khoản người dùng.
- Chu kỳ thanh toán của thuê bao có ngày bắt đầu và ngày kết thúc.
- Giá gói được cấu hình theo tháng. Story chưa quy định cách xử lý khi chu kỳ không đủ một tháng.
- Đổi lên gói giá cao hơn có thể phát sinh khoản thu bổ sung, nhưng cách tính số tiền, thuế, phí và thời điểm thu chưa được xác định.
- Đổi xuống gói giá thấp hơn không hoàn lại khoản tiền đã thanh toán cho chu kỳ hiện tại.
- Nếu ngày hiệu lực dự kiến rơi vào thời điểm gói đích không còn được bán, hành vi cần được xác nhận.
- Người dùng có thể gửi lại yêu cầu do mạng chậm. Story chưa xác định hệ thống có bảo đảm không xử lý trùng yêu cầu hay không.
- Việc cập nhật thuê bao và thu tiền có thể phụ thuộc vào dịch vụ thanh toán bên ngoài. Story không xác nhận giao thức, cơ chế retry hoặc thứ tự gọi dịch vụ.

## Dependencies

- Danh mục gói thuê bao và giá hiện hành.
- Dịch vụ thanh toán để xử lý khoản thu bổ sung khi đổi lên gói cao hơn; hành vi lỗi và kết quả không xác định chưa được mô tả.
- Màn hình chi tiết thuê bao để người dùng xem gói và ngày hiệu lực.

## Các câu hỏi cần PO/BA xác nhận

- Đổi lên gói giá cao hơn có hiệu lực ngay khi yêu cầu được chấp nhận hay chỉ sau khi khoản thu bổ sung thành công?
- Khoản thu bổ sung được tính theo phần thời gian còn lại, toàn bộ tháng hay theo quy tắc khác?
- Nếu thanh toán bị từ chối hoặc timeout, thuê bao giữ gói cũ hay có trạng thái chờ?
- Người dùng có được đổi gói nhiều lần trong cùng một chu kỳ không? Nếu có, quy tắc gộp hoặc thay thế yêu cầu trước là gì?
- Điều gì xảy ra nếu gói đích bị ngừng bán trước ngày hiệu lực dự kiến?
- Hai yêu cầu đổi gói được gửi gần như đồng thời thì kết quả nào được áp dụng?

## Hướng dẫn nhập vào QA Compass

- **Title:** dùng nội dung trong mục “Tiêu đề”.
- **Description:** dùng phần “User story”.
- **Acceptance criteria:** nhập sáu mục AC thành sáu dòng riêng.
- **Business context:** nhập toàn bộ mục “Business context”.
- **Dependencies:** nhập ba dependency thành ba dòng riêng.
- **Language:** chọn tự nhận diện hoặc tiếng Việt.

Story này cố ý có cả quy tắc đã xác nhận và câu hỏi còn mở. Khi thử agent, kiểm tra rằng các câu hỏi về proration, thanh toán, retry và xử lý đồng thời được gắn cần làm rõ, không biến thành business rule hoặc integration architecture do AI tự suy đoán.
