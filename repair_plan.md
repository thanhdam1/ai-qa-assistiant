# KẾ HOẠCH NÂNG CẤP & KHẮC PHỤC HỆ THỐNG SINH TEST CASE (ZERO-GAP REPAIR PLAN)

**Dự án:** `ai-qa-assistiant`  
**Mục tiêu cốt lõi:** Tối ưu hóa kiến trúc AI QA Assistant để sinh Test Case **chính xác 100%, đầy đủ 100% (Zero-Gap)**, bao phủ toàn bộ nghiệp vụ (SRS), hợp đồng giao tiếp (OpenAPI/Swagger), các nhánh rẽ mã nguồn (AST Control-Flow) và lỗ hổng bảo mật (OWASP).

---

## 1. PHẠM VI ÁP DỤNG (SCOPE OF WORK)

### 1.1. In-Scope (Trong phạm vi nâng cấp)
* **Tầng Ingestion & Parsing (`src/parsers/`):**
  * Phân rã tài liệu SRS/PRD thành các mệnh đề nguyên tử (`Atomic REQ_ID`).
  * Bóc tách hợp đồng giao tiếp từ OpenAPI/Swagger và DTO Validation Annotations thành ma trận biên tất định (`Deterministic Boundary Matrix`).
  * Trích xuất Cây luồng điều khiển (`Control-Flow Graph - CFG`) và độ phức tạp chu trình (`Cyclomatic Complexity` $V(G)$) từ mã nguồn bằng Tree-sitter.
* **Tầng 對 chiếu & Phát hiện Gap (`src/engine/gap_detector.py`):**
  * Kiểm toán chéo 3 chiều (`3-Way Cross-Verification`): **SRS $\leftrightarrow$ OpenAPI $\leftrightarrow$ AST Codebase**.
* **Tầng Multi-Agent & Agent Skills (`.claude/skills/` hoặc `skills/`):**
  * Thiết lập và điều phối 3 Agent Skills chuyên biệt:
    1. `qa-ast-contract-extractor`
    2. `qa-rag-assistant`
    3. `qa-coverage-critic`
* **Tầng Kiểm chứng Đóng (`src/engine/rtm_coverage_gate.py`):**
  * Chấm điểm độ phủ toán học và tự động kích hoạt vòng lặp sinh bù (`Delta Self-Healing Loop`) nếu độ phủ $< 100\%$.

### 1.2. Out-of-Scope (Ngoài phạm vi giai đoạn này)
* Kiểm thử hiệu năng chịu tải quy mô lớn (Distributed Load Testing với JMeter/Locust).
* Kiểm thử giao diện đồ họa mức điểm ảnh (Visual Regression Pixel-by-Pixel).

---

## 2. BỘ QUY TẮC BẮT BUỘC CHỐNG SÓT TEST CASE (ZERO-GAP STRICT RULES)

Mọi Agent, Prompt và Pipeline trong hệ thống bắt buộc phải tuân thủ 6 quy tắc bất biến sau:

* **RULE-01 (Atomic Requirement Rule):** Cấm gộp nhiều điều kiện nghiệp vụ vào một yêu cầu. Mỗi mệnh đề logic (`AND`, `OR`, `UNLESS`, `WHEN`) trong SRS phải được tách thành một `REQ_ID` nguyên tử độc lập.
* **RULE-02 (Deterministic BVA Rule):** Cấm để LLM tự suy diễn giá trị biên bằng xác suất. Mọi trường dữ liệu đầu vào phải được thuật toán sinh sẵn 8 phân vùng chuẩn: `[min - 1, min, min + 1, nominal, max - 1, max, max + 1, null/empty/wrong_type]`.
* **RULE-03 (AST Branch Parity Rule):** Số lượng kịch bản kiểm thử luồng điều khiển cho một hàm/endpoint bắt buộc phải $\ge$ chỉ số Cyclomatic Complexity $V(G)$ của hàm đó:
  $$V(G) = E - N + 2P \quad \text{hoặc} \quad V(G) = \text{Số điểm quyết định } (\text{if, else, switch, catch, ? :}) + 1$$
  Mỗi `AST_BRANCH_ID` phải có ít nhất một `Test_Case_ID` ánh xạ trực tiếp.
* **RULE-04 (3-Way Cross-Verification Rule):** Trước khi sinh Test Case, hệ thống phải đối chiếu `SRS <-> OpenAPI <-> AST`. Mọi sự lệch pha (Code có nhánh xử lý nhưng SRS không mô tả, hoặc SRS yêu cầu nhưng Code thiếu validation) đều phải gắn cờ `GAP_DETECTED` và sinh Test Case bắt lỗi tương ứng.
* **RULE-05 (Two-Phase Batch Generation Rule):** Cấm sinh toàn bộ chi tiết Test Case trong 1 lần gọi LLM (tránh lỗi *Output Token Truncation* làm mất các Test Case cuối). Bắt buộc chạy **Pha 1 (Skeleton Matrix)** để liệt kê 100% danh sách ID, sau đó chạy **Pha 2 (Batch Expansion)** với kích thước $\le 8$ Test Cases/batch.
* **RULE-06 (100% Mathematical Coverage Gate):** Pipeline chỉ được phép kết thúc khi thỏa mãn phương trình:
  $$\text{Coverage}_{\text{Total}} = \min\left(\frac{|\text{REQ}_{\text{covered}}|}{|\text{REQ}_{\text{total}}|}, \frac{|\text{BRANCH}_{\text{covered}}|}{|\text{BRANCH}_{\text{total}}|}, \frac{|\text{BVA}_{\text{covered}}|}{|\text{BVA}_{\text{total}}|}\right) = 1.0 \ (100\%)$$

---

## 3. KIẾN TRÚC PHỐI HỢP 3 AGENT SKILLS (AGENT SKILL ARCHITECTURE)

```
[SRS Docs + OpenAPI + Source Code]
               │
               ▼
┌──────────────────────────────────────────┐
│ SKILL 1: qa-ast-contract-extractor       │ ──► Xuất `canonical_test_contract.json`
│ (Bóc tách REQ, BVA Matrix, AST CFG, Gap) │     (Định nghĩa mẫu số 100% cần phủ)
└──────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ SKILL 2: qa-rag-assistant                │ ──► Pha 1: Sinh Full Test Skeleton + Decision Table
│ (Hybrid GraphRAG + Two-Phase Generator)  │ ──► Pha 2: Mở rộng chi tiết theo Batch (<= 8 TC/lần)
└──────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ SKILL 3: qa-coverage-critic              │ ──► Tính điểm Coverage Gate & lập Bi-directional RTM
│ (Kiểm toán toán học & Self-Healing Loop) │ ──► Nếu < 100%: Trích xuất phần thiếu ──► Gọi lại Skill 2
└──────────────────────────────────────────┘
```

---

## 4. CẤU TRÚC THƯ MỤC DỰ ÁN NÂNG CẤP

```text
ai-qa-assistiant/
├── repair-plan.md
├── skills/
│   ├── qa-ast-contract-extractor/
│   │   └── SKILL.md
│   ├── qa-rag-assistant/
│   │   └── SKILL.md
│   └── qa-coverage-critic/
│       └── SKILL.md
└── src/
    ├── schemas/
    │   └── test_contract_schema.py      # Pydantic Strict Schemas cho CTC, Test Case & RTM
    ├── parsers/
    │   ├── srs_atomic_decomposer.py     # Tách REQ nguyên tử (RULE-01)
    │   ├── openapi_bva_generator.py     # Sinh ma trận BVA tất định (RULE-02)
    │   └── ast_cfg_extractor.py         # Tree-sitter trích xuất nhánh CFG & V(G) (RULE-03)
    └── engine/
        ├── gap_detector.py              # Kiểm toán 3 chiều SRS-Swagger-AST (RULE-04)
        ├── batch_test_generator.py      # Điều phối sinh Test 2 pha (RULE-05)
        └── rtm_coverage_gate.py         # Chốt chặn Coverage 100% & Delta Loop (RULE-06)
```

---

## 5. LỘ TRÌNH TRIỂN KHAI & TIÊU CHÍ NGHIỆM THU (ACCEPTANCE CRITERIA)

| Giai đoạn | Hạng mục công việc | Tiêu chí nghiệm thu (DoD) |
| :--- | :--- | :--- |
| **Phase 1** | Triển khai `qa-ast-contract-extractor` | Xuất được file `canonical_test_contract.json` chứa đủ 100% nhánh `if/else/switch/catch` trong code và 100% trường DTO. |
| **Phase 2** | Triển khai `qa-rag-assistant` | Sinh Test Case qua 2 pha, 0% trường hợp bị cắt cụt JSON hoặc dùng từ ngữ chung chung ("v.v.", "tương tự"). |
| **Phase 3** | Triển khai `qa-coverage-critic` | Tự động phát hiện mọi `REQ_ID` hoặc `AST_BRANCH_ID` bị bỏ sót và ép hệ thống sinh bù cho đến khi đạt 100.0% trên bảng RTM. |