# Story mẫu: Đổi điểm lấy voucher

## Title

Đổi điểm thưởng lấy voucher của chiến dịch

## Description

Là khách hàng đã đăng nhập, tôi muốn dùng điểm thưởng của tài khoản mình để đổi voucher từ một chiến dịch, nhằm sử dụng voucher cho lần mua hàng sau.

## Acceptance criteria

Nhập **mỗi dòng dưới đây thành một acceptance criterion riêng** trong form:

1. Chỉ khách hàng đã đăng nhập mới được đổi điểm; điểm bị trừ từ tài khoản của chính khách hàng đó.
2. Chỉ có thể đổi voucher khi chiến dịch ở trạng thái `active` và thời điểm yêu cầu (UTC) nhỏ hơn `expires_at`. Đúng tại `expires_at`, chiến dịch đã hết hạn.
3. `quantity` phải là số nguyên từ 1 đến 5, tính cả hai đầu mút.
4. Số điểm cần trừ bằng `points_per_voucher × quantity`. Khách hàng phải có số dư điểm lớn hơn hoặc bằng số điểm này.
5. Chiến dịch phải còn ít nhất `quantity` voucher khả dụng trước khi yêu cầu đổi được chấp nhận.
6. Khi đổi thành công, hệ thống trả về mã redemption, đúng `quantity` mã voucher và số dư điểm sau khi trừ. Điểm chỉ bị trừ một lần theo công thức ở tiêu chí 4.
7. Hệ thống yêu cầu nhà cung cấp Voucher Inventory cấp mã voucher trước khi hoàn tất redemption. Nếu nhà cung cấp từ chối cấp mã, hệ thống không trừ điểm, không tạo redemption thành công và trả lỗi `503`.
8. Khách hàng có thể xem redemption đã tạo bằng mã redemption. Khách hàng khác không được xem redemption đó.

## Business context

- Mỗi khách hàng có một tài khoản điểm và các redemption thuộc tài khoản đó.
- `points_per_voucher` và `expires_at` được cấu hình cho từng chiến dịch. Tất cả thời điểm trong story dùng UTC.
- Nếu thiếu điểm hoặc thiếu voucher khả dụng, yêu cầu bị từ chối bằng `409` và không trừ điểm.
- Nếu chiến dịch không tồn tại, yêu cầu bị từ chối bằng `404`.
- Nếu chiến dịch không `active` hoặc đã hết hạn, yêu cầu bị từ chối bằng `422`.
- Chưa xác định hệ thống phải xử lý thế nào khi nhà cung cấp Voucher Inventory timeout sau khi có thể đã cấp mã.
- Chưa xác định hai yêu cầu đổi gần như đồng thời được điều phối ra sao khi cùng tranh số điểm hoặc quota cuối cùng.
- OpenAPI yêu cầu header `Idempotency-Key`, nhưng chưa có quy tắc nghiệp vụ xác nhận replay cùng key phải trả kết quả cũ hay chặn xử lý trùng.

## Dependencies

- Voucher Inventory là hệ thống bên ngoài cấp mã voucher cho redemption. Story chỉ xác nhận tương tác cấp mã và kết quả thành công hoặc từ chối; chưa xác nhận giao thức hay cơ chế retry.
- Tài khoản điểm cung cấp số dư hiện tại của khách hàng.

## Cách thử trong QA Compass

1. Tạo story mới; điền Title, Description, từng AC, Business context và Dependencies từ các mục trên. Chọn tiếng Việt hoặc tự nhận diện.
2. Sinh Requirement Review và kiểm tra AI có trích cả quy tắc `409/404/422` trong Business context, cùng điều kiện hết hạn đúng tại `expires_at`.
3. Tải lên file `voucher-redemption.openapi.yaml` của cặp mẫu này, sinh rồi duyệt API Contract Review.
4. Duyệt Requirement Review, sinh test case, xem coverage cho mỗi obligation và assertion cụ thể. Kiểm tra có positive, negative, boundary và integration.
5. Kiểm tra các trường hợp timeout, tranh chấp đồng thời và replay `Idempotency-Key` được đánh dấu cần làm rõ, không bị AI biến thành quy tắc đã xác nhận.

Đây là dữ liệu mẫu để **sinh kịch bản**, không phải địa chỉ API đang chạy để gửi request.
