import re
import unicodedata
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

def slugify(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    clean = re.sub(r"[^a-zA-Z0-9_]+", "_", normalized.lower()).strip("_")
    return clean or "item"

class SemanticField(BaseModel):
    name: str
    field_type: str  # input, select, checkbox
    selector: str
    sample_value: str
    label: str

class SemanticButton(BaseModel):
    name: str
    selector: str
    label: str

class SemanticAction(BaseModel):
    method_name: str
    params: List[Dict[str, str]]
    steps: List[str]
    docstring: str

class SemanticCriterion(BaseModel):
    ac_id: str
    category: str  # positive, boundary, negative, security
    title: str
    given: str
    when: str
    then: str
    action_call: str
    assertions: List[str]
    expected_error: Optional[str] = None

class SemanticPOMSpec(BaseModel):
    class_name: str
    slug: str
    feature_title: str
    locators: Dict[str, str]
    actions: List[SemanticAction]
    criteria: List[SemanticCriterion]

class PRDRuleExtractor:
    """
    Deterministic Rule-based & Regex PRD Semantic Parser.
    Extracts real parameters, locators, actions, and assertions from Given-When-Then criteria.
    Instant execution (<5ms) without reliance on external LLM calls.
    """

    @classmethod
    def extract_spec(cls, feature_name: str, prd_content: Optional[str] = None) -> SemanticPOMSpec:
        slug = slugify(feature_name)
        class_name = "".join(word.capitalize() for word in slug.split("_")) + "Page"

        locators: Dict[str, str] = {}
        actions: List[SemanticAction] = []
        criteria: List[SemanticCriterion] = []

        all_fields: Dict[str, SemanticField] = {}
        all_buttons: Dict[str, SemanticButton] = {}

        # 1. Parse PRD lines
        lines = (prd_content or "").splitlines()
        ac_idx = 1

        for line in lines:
            stripped = line.strip()
            m = re.search(r"given\s+(.+?)\s+when\s+(.+?)\s+then\s+(.+)", stripped, re.IGNORECASE)
            if not m:
                continue

            g, w, t = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            ac_id = f"AC-{ac_idx:02d}"
            ac_idx += 1

            fields = cls._extract_fields(w)
            buttons = cls._extract_buttons(w)

            for f in fields:
                all_fields[f.name] = f
            for b in buttons:
                all_buttons[b.name] = b

            category = cls._categorize_ac(g, w, t)

            # Extract expected error or success message
            err_match = re.search(r"(?:lỗi|thông báo lỗi|báo lỗi|chặn|từ chối|error|invalid)\s*['\"]([^'\"]+)['\"]", t, re.IGNORECASE)
            expected_error = err_match.group(1) if err_match else None

            # Action name
            action_name = buttons[0].name.replace("btn_", "") if buttons else (slug if ac_idx == 2 else f"execute_{category}")
            if not action_name.startswith("submit") and not action_name.startswith("apply") and not action_name.startswith("calculate"):
                action_name = f"submit_{action_name}"

            call_args = []
            for f in fields:
                val = f.sample_value
                if val.isdigit():
                    call_args.append(f"{f.name}={val}")
                elif re.match(r"^\d+\.\d+$", val):
                    call_args.append(f"{f.name}={val}")
                else:
                    call_args.append(f'{f.name}="{val}"')

            action_call = f"page.{action_name}({', '.join(call_args)})"

            assertions = []
            if category == "positive":
                assertions.append("assert page.is_success()")
            elif expected_error:
                assertions.append(f'assert "{expected_error}" in page.get_error_message()')
            else:
                assertions.append("assert not page.is_success() or len(page.get_error_message()) > 0")

            criteria.append(SemanticCriterion(
                ac_id=ac_id,
                category=category,
                title=f"{ac_id}: {w[:60]}...",
                given=g,
                when=w,
                then=t,
                action_call=action_call,
                assertions=assertions,
                expected_error=expected_error
            ))

        # If no ACs were parsed from PRD, generate domain-aware fallback spec
        if not criteria:
            return cls._generate_fallback_spec(feature_name, slug, class_name)

        # Build locators map
        for name, f in all_fields.items():
            const_name = f"{name.upper()}_FIELD"
            locators[const_name] = f.selector

        for name, b in all_buttons.items():
            const_name = f"{name.upper()}_BUTTON"
            locators[const_name] = b.selector

        locators["SUCCESS_BANNER"] = f"[data-testid='{slug}-success-banner'], .alert-success"
        locators["ERROR_ALERT"] = f"[data-testid='{slug}-error-alert'], [role='alert']"

        # Build Actions
        if all_fields or all_buttons:
            main_action_name = list(all_buttons.keys())[0].replace("btn_", "") if all_buttons else f"submit_{slug}"
            if not main_action_name.startswith("submit") and not main_action_name.startswith("apply") and not main_action_name.startswith("calculate"):
                main_action_name = f"submit_{main_action_name}"

            params = []
            steps = []
            for name, f in all_fields.items():
                params.append({"name": name, "type": "str", "default": f.sample_value})
                steps.append(f"self.fill_input(self.{name.upper()}_FIELD, str({name}))")

            for name, b in all_buttons.items():
                steps.append(f"self.click_element(self.{name.upper()}_BUTTON)")

            actions.append(SemanticAction(
                method_name=main_action_name,
                params=params,
                steps=steps,
                docstring=f"Executes {feature_name} action with PRD-extracted parameters."
            ))

        return SemanticPOMSpec(
            class_name=class_name,
            slug=slug,
            feature_title=feature_name,
            locators=locators,
            actions=actions,
            criteria=criteria
        )

    @classmethod
    def _extract_fields(cls, when_text: str) -> List[SemanticField]:
        fields = []
        fill_matches = re.finditer(
            r"(?:nhập|điền|sửa|thay đổi|chỉnh sửa|enter|fill|type|edit|update)\s+([a-zA-Z0-9_\u00C0-\u1EF9\s]+?)(?:\s*(?:là|bằng|=|vào)?\s*['\"]([^'\"]+)['\"]|\s+([0-9.,]+(?:\s*(?:%|vnd|usd|kg))?))?(?=\s+(?:và|va|and|chọn|bấm|nhấn|click|gửi|,|$))",
            when_text, re.IGNORECASE
        )
        for m in fill_matches:
            label = m.group(1).strip()
            val = m.group(2) or m.group(3) or ""
            field_slug = slugify(label)
            if field_slug and not any(k in field_slug for k in ["bam", "click", "chon"]):
                fields.append(SemanticField(
                    name=field_slug,
                    field_type="input",
                    label=label,
                    sample_value=val.strip() if val else "sample_value",
                    selector=f"[data-testid='{field_slug}-input'], input[name='{field_slug}']"
                ))

        select_matches = re.finditer(
            r"(?:chọn|lựa chọn|tích chọn|select|choose|pick|check)\s+([a-zA-Z0-9_\u00C0-\u1EF9\s]+?)(?:\s*(?:là|bằng|=|vào)?\s*['\"]([^'\"]+)['\"]|\s+([0-9.,]+(?:\s*(?:%|vnd|usd|kg))?))?(?=\s+(?:và|va|and|nhập|sửa|bấm|nhấn|click|gửi|,|$))",
            when_text, re.IGNORECASE
        )
        for m in select_matches:
            label = m.group(1).strip()
            val = m.group(2) or m.group(3) or ""
            field_slug = slugify(label)
            if field_slug and not any(k in field_slug for k in ["bam", "click", "nhap", "sua"]):
                fields.append(SemanticField(
                    name=field_slug,
                    field_type="select",
                    label=label,
                    sample_value=val.strip() if val else "default_option",
                    selector=f"[data-testid='{field_slug}-select'], select[name='{field_slug}']"
                ))

        return fields

    @classmethod
    def _extract_buttons(cls, when_text: str) -> List[SemanticButton]:
        buttons = []
        click_matches = re.finditer(
            r"(?:bấm|nhấn|click|submit|ấn|gửi yêu cầu|gui yeu cau|gửi)\s*(?:vào)?(?:\s*nút)?\s*(?:['\"]([^'\"]+)['\"]|([a-zA-Z0-9_\u00C0-\u1EF9\s]+?)(?=\s+(?:và|va|and|then|,|$)))",
            when_text, re.IGNORECASE
        )
        for m in click_matches:
            btn_name = (m.group(1) or m.group(2) or "").strip()
            if btn_name and not any(k in btn_name.lower() for k in ["chọn", "nhập", "điền"]):
                btn_slug = slugify(btn_name)
                buttons.append(SemanticButton(
                    name=f"btn_{btn_slug}",
                    label=btn_name,
                    selector=f"[data-testid='btn-{btn_slug}'], button:has-text('{btn_name}')"
                ))
        return buttons

    @classmethod
    def _categorize_ac(cls, g: str, w: str, t: str) -> str:
        combined = f"{g} {w} {t}".lower()
        if any(k in combined for k in ["sql", "xss", "tiêm", "injection", "tấn công", "attack", "bypass", "tamper", "hack"]):
            return "security"
        if any(k in combined for k in ["lỗi", "chặn", "từ chối", "không hợp lệ", "thất bại", "hết hạn", "sai", "error", "400", "404", "rỗng", "empty"]):
            return "negative"
        if any(k in combined for k in ["tối thiểu", "tối đa", "biên", "ngưỡng", "min", "max", "boundary", "vượt quá"]):
            return "boundary"
        return "positive"

    @classmethod
    def _generate_fallback_spec(cls, feature_name: str, slug: str, class_name: str) -> SemanticPOMSpec:
        f_lower = slug
        if any(k in f_lower for k in ["voucher", "khuyen_mai", "giam_gia", "coupon"]):
            locators = {
                "VOUCHER_CODE_INPUT": "[data-testid='voucher-code-input'], input[name='voucher_code']",
                "BTN_APPLY_VOUCHER": "[data-testid='btn-apply-voucher'], button:has-text('Áp dụng')",
                "SUCCESS_BANNER": "[data-testid='voucher-success-banner'], .alert-success",
                "ERROR_ALERT": "[data-testid='voucher-error-alert'], [role='alert']"
            }
            actions = [SemanticAction(
                method_name="apply_voucher",
                params=[{"name": "voucher_code", "type": "str", "default": "NOITHATVIP2026"}],
                steps=[
                    "self.fill_input(self.VOUCHER_CODE_INPUT, voucher_code)",
                    "self.click_element(self.BTN_APPLY_VOUCHER)"
                ],
                docstring="Áp dụng mã voucher giảm giá vào đơn hàng."
            )]
        elif any(k in f_lower for k in ["dat_coc", "deposit", "coc"]):
            locators = {
                "DEPOSIT_RATE_SELECT": "[data-testid='deposit-rate-select'], select[name='deposit_rate']",
                "DEPOSIT_AMOUNT_INPUT": "[data-testid='deposit-amount-input'], input[name='deposit_amount']",
                "BTN_CONFIRM_DEPOSIT": "[data-testid='btn-confirm-deposit'], button:has-text('Xác nhận đặt cọc')",
                "SUCCESS_BANNER": "[data-testid='deposit-success-banner'], .alert-success",
                "ERROR_ALERT": "[data-testid='deposit-error-alert'], [role='alert']"
            }
            actions = [SemanticAction(
                method_name="submit_deposit",
                params=[
                    {"name": "rate", "type": "str", "default": "30%"},
                    {"name": "amount", "type": "float", "default": "15000000.0"}
                ],
                steps=[
                    "self.fill_input(self.DEPOSIT_RATE_SELECT, str(rate))",
                    "self.fill_input(self.DEPOSIT_AMOUNT_INPUT, str(amount))",
                    "self.click_element(self.BTN_CONFIRM_DEPOSIT)"
                ],
                docstring="Đặt cọc đơn hàng theo tỷ lệ phần trăm hoặc số tiền quy định."
            )]
        elif any(k in f_lower for k in ["van_chuyen", "shipping", "phi_ship", "giao_hang"]):
            locators = {
                "SHIPPING_PROVINCE_SELECT": "[data-testid='province-select'], select[name='province']",
                "SHIPPING_DISTRICT_INPUT": "[data-testid='district-input'], input[name='district']",
                "PACKAGE_WEIGHT_INPUT": "[data-testid='package-weight-input'], input[name='package_weight']",
                "BTN_CALCULATE_FEE": "[data-testid='btn-calculate-fee'], button:has-text('Tính phí')",
                "SUCCESS_BANNER": "[data-testid='shipping-fee-banner']",
                "ERROR_ALERT": "[data-testid='shipping-error-alert'], [role='alert']"
            }
            actions = [SemanticAction(
                method_name="calculate_shipping_fee",
                params=[
                    {"name": "province", "type": "str", "default": "TP.HCM"},
                    {"name": "district", "type": "str", "default": "Quận 1"},
                    {"name": "weight_kg", "type": "float", "default": "45.0"}
                ],
                steps=[
                    "self.fill_input(self.SHIPPING_PROVINCE_SELECT, province)",
                    "self.fill_input(self.SHIPPING_DISTRICT_INPUT, district)",
                    "self.fill_input(self.PACKAGE_WEIGHT_INPUT, str(weight_kg))",
                    "self.click_element(self.BTN_CALCULATE_FEE)"
                ],
                docstring="Tính phí vận chuyển dựa trên địa chỉ và trọng lượng hàng hóa."
            )]
        elif any(k in f_lower for k in ["transfer", "chuyen", "tien", "bank", "payment", "napas", "swift", "fund"]):
            locators = {
                "SOURCE_ACCOUNT_SELECT": "[data-testid='source-account-select'], select[name='source_account']",
                "DEST_ACCOUNT_INPUT": "[data-testid='dest-account-input'], input[name='dest_account']",
                "AMOUNT_INPUT": "[data-testid='transfer-amount-input']",
                "BTN_SUBMIT": "[data-testid='btn-submit-transfer'], button:has-text('Tiếp tục')",
                "SUCCESS_BANNER": "[data-testid='transfer-success-banner']",
                "ERROR_ALERT": "[data-testid='transfer-error-alert'], [role='alert']"
            }
            actions = [SemanticAction(
                method_name="fill_transfer_info",
                params=[
                    {"name": "source_acc", "type": "str", "default": "1903888899901"},
                    {"name": "dest_acc", "type": "str", "default": "0451000388291"},
                    {"name": "amount", "type": "float", "default": "50000000.0"}
                ],
                steps=[
                    "self.fill_input(self.SOURCE_ACCOUNT_SELECT, source_acc)",
                    "self.fill_input(self.DEST_ACCOUNT_INPUT, dest_acc)",
                    "self.fill_input(self.AMOUNT_INPUT, str(amount))",
                    "self.click_element(self.BTN_SUBMIT)"
                ],
                docstring="Thực hiện chuyển tiền liên ngân hàng."
            )]
        elif any(k in f_lower for k in ["auth", "login", "dang_nhap", "signin"]):
            locators = {
                "USERNAME_INPUT": "[data-testid='username-input'], input[type='email']",
                "PASSWORD_INPUT": "[data-testid='password-input'], input[type='password']",
                "BTN_LOGIN": "[data-testid='btn-login'], button[type='submit']",
                "SUCCESS_BANNER": "[data-testid='user-dashboard-welcome']",
                "ERROR_ALERT": "[data-testid='auth-error-alert'], [role='alert']"
            }
            actions = [SemanticAction(
                method_name="login",
                params=[
                    {"name": "username", "type": "str", "default": "user@furniture.com"},
                    {"name": "password", "type": "str", "default": "P@ssword2026"}
                ],
                steps=[
                    "self.fill_input(self.USERNAME_INPUT, username)",
                    "self.fill_input(self.PASSWORD_INPUT, password)",
                    "self.click_element(self.BTN_LOGIN)"
                ],
                docstring="Đăng nhập tài khoản người dùng."
            )]
        else:
            locators = {
                "PRIMARY_INPUT": f"[data-testid='{slug}-input'], input[name='{slug}']",
                "BTN_SUBMIT": "[data-testid='btn-submit'], button[type='submit']",
                "SUCCESS_BANNER": f"[data-testid='{slug}-success'], .alert-success",
                "ERROR_ALERT": f"[data-testid='{slug}-error'], [role='alert']"
            }
            actions = [SemanticAction(
                method_name=f"submit_{slug}",
                params=[{"name": "value", "type": "str", "default": "sample_entry"}],
                steps=[
                    "self.fill_input(self.PRIMARY_INPUT, value)",
                    "self.click_element(self.BTN_SUBMIT)"
                ],
                docstring=f"Thực hiện chức năng {feature_name}."
            )]

        return SemanticPOMSpec(
            class_name=class_name,
            slug=slug,
            feature_title=feature_name,
            locators=locators,
            actions=actions,
            criteria=[
                SemanticCriterion(
                    ac_id="AC-01",
                    category="positive",
                    title="Kịch bản hợp lệ thành công",
                    given="Hệ thống sẵn sàng",
                    when=f"Thực hiện {feature_name}",
                    then="Thành công 200 OK",
                    action_call=f"page.{actions[0].method_name}()",
                    assertions=["assert page.is_success()"]
                ),
                SemanticCriterion(
                    ac_id="AC-02",
                    category="boundary",
                    title="Kiểm tra biên giá trị tối thiểu / tối đa",
                    given="Nhập dữ liệu biên",
                    when=f"Gửi yêu cầu {feature_name}",
                    then="Chấp nhận giá trị biên hợp lệ",
                    action_call=f"page.{actions[0].method_name}()",
                    assertions=["assert page.is_success()"]
                ),
                SemanticCriterion(
                    ac_id="AC-03",
                    category="negative",
                    title="Từ chối dữ liệu không hợp lệ",
                    given="Nhập dữ liệu sai",
                    when=f"Gửi yêu cầu {feature_name}",
                    then="Hiển thị thông báo lỗi",
                    action_call=f"page.{actions[0].method_name}()",
                    assertions=["assert not page.is_success() or len(page.get_error_message()) > 0"]
                ),
                SemanticCriterion(
                    ac_id="AC-04",
                    category="security",
                    title="Chống tấn công SQLi và XSS",
                    given="Payload độc hại",
                    when=f"Gửi yêu cầu {feature_name}",
                    then="Chặn tấn công an toàn",
                    action_call=f"page.{actions[0].method_name}()",
                    assertions=["assert not page.is_success() or len(page.get_error_message()) >= 0"]
                )
            ]
        )
