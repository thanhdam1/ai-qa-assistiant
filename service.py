"""
Service xử lý nghiệp vụ rút tiền từ ví điện tử về tài khoản ngân hàng liên kết.
Tương thích hoàn toàn với OpenAPI Spec và User Story AC-01 -> AC-05.
"""
from datetime import date
from typing import Dict, Any


class BusinessException(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class WithdrawalService:
    DAILY_LIMIT_MAX = 100_000_000  # Hạn mức ngày 100.000.000 VND
    WITHDRAW_FEE_RATE = 0.001      # Phí rút 0.1%
    MIN_FEE = 3_300               # Mức phí tối thiểu 3.300 VND

    def __init__(self, wallet_repo, bank_gateway, auth_service, audit_repo):
        self.wallet_repo = wallet_repo
        self.bank_gateway = bank_gateway
        self.auth_service = auth_service
        self.audit_repo = audit_repo

    def calculate_fee(self, amount: int) -> int:
        fee = int(amount * self.WITHDRAW_FEE_RATE)
        return max(fee, self.MIN_FEE)

    def process_withdrawal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        wallet_id = payload.get("wallet_id")
        amount = payload.get("amount", 0)
        bank_code = payload.get("bank_code")
        account_no = payload.get("bank_account_number")
        auth_token = payload.get("auth_token")

        # 1. Kiểm tra tồn tại và trạng thái ví (AC-04)
        wallet = self.wallet_repo.find_by_id(wallet_id)
        if not wallet:
            raise BusinessException(403, "Tài khoản ví không tồn tại.")
        if wallet.status != "ACTIVE":
            raise BusinessException(403, f"Ví đang ở trạng thái {wallet.status}, không thể rút tiền.")

        # 2. Xác thực mã OTP / Sinh trắc học (AC-05)
        if not self.auth_service.verify_token(wallet_id, auth_token):
            raise BusinessException(422, "Mã xác thực không hợp lệ hoặc đã hết hạn.")

        # 3. Kiểm tra hạn mức giao dịch đơn lẻ (AC-03)
        if amount < 50_000:
            raise BusinessException(400, "Số tiền rút tối thiểu là 50,000 VND.")
        if amount > 50_000_000:
            raise BusinessException(400, "Số tiền rút tối đa là 50,000,000 VND / lần.")

        # 4. Kiểm tra tổng hạn mức rút trong ngày (Business Rule)
        today_total = self.wallet_repo.get_today_withdrawn_amount(wallet_id, date.today())
        if today_total + amount > self.DAILY_LIMIT_MAX:
            raise BusinessException(400, "Vượt quá hạn mức rút tiền tối đa 100,000,000 VND trong ngày.")

        # 5. Tính phí và kiểm tra số dư khả dụng (AC-01, AC-02)
        fee = self.calculate_fee(amount)
        total_deduct = amount + fee
        if wallet.available_balance < total_deduct:
            raise BusinessException(402, "Số dư khả dụng không đủ để thanh toán số tiền và phí rút.")

        # 6. Kiểm tra quy định KYC Level 2 cho giao dịch lớn (Business Rule AML)
        if amount >= 30_000_000 and wallet.kyc_level < 2:
            return {
                "transaction_id": "HOLD_COMPLIANCE_REVIEW",
                "status": "MANUAL_HOLD",
                "amount": amount,
                "fee": fee,
                "message": "Giao dịch giá trị lớn đang chờ duyệt tuân thủ AML do chưa đạt KYC Level 2."
            }

        # 7. Trừ tiền ví và gọi lệnh chuyển khoản ngân hàng (AC-01)
        new_balance = wallet.available_balance - total_deduct
        self.wallet_repo.update_balance(wallet_id, new_balance)

        transfer_result = self.bank_gateway.transfer(
            bank_code=bank_code,
            account_number=account_no,
            amount=amount
        )

        txn_id = self.audit_repo.log_transaction(
            wallet_id=wallet_id,
            amount=amount,
            fee=fee,
            status="SUCCESS",
            bank_ref=transfer_result.reference_id
        )

        return {
            "transaction_id": txn_id,
            "status": "SUCCESS",
            "amount": amount,
            "fee": fee,
            "remaining_balance": new_balance
        }
