# AI QA Assistant

MVP noi bo gom hai workflow co human-in-the-loop:

1. **Requirement Review Agent** phan tich user story va tao ban nhap co cau truc.
2. QA chinh sua, phe duyet ban review.
3. QA co the tai OpenAPI JSON/YAML; **API Contract Agent** dung AI provider dang cau hinh (Gemini hoac OpenAI) de phan tich endpoint, request, response va schema.
4. QA chinh sua, phe duyet API contract review.
5. **Test Case Generation Agent** tao test case tu story + requirement review da duyet, va API contract review da duyet neu duoc chon.
6. QA duyet noi dung suite, xac nhan assertion cho tung coverage target hoac ghi quyet dinh gap, sau do chap nhan pham vi coverage. Danh gia dieu kien chay cua tung case la buoc doc lap.

## Danh gia suite

- `review_status` cho biet QA da duyet noi dung test; khong tu dong chap nhan coverage.
- `coverage_status` dem muc tieu co assertion duoc lien ket trong thiet ke (`complete`, `partial`, `unsubstantiated`). `candidate_coverage_count` va `qa_confirmed_target_count` tach de xuat AI khoi xac nhan cua QA. Day khong phai ket qua thuc thi.
- Moi requirement obligation, risk va API finding trong coverage matrix can QA xac nhan mot assertion cu the, hoac ghi gap decision (`accepted_risk`, `deferred`, `blocked`, `not_applicable`) co ly do; `deferred` can owner. Gap khong duoc tinh la covered.
- `coverage_acceptance_status` chi la `accepted` sau khi noi dung duoc duyet va moi target co quyet dinh. Quy trinh nay chap nhan pham vi da khai bao, khong ket luan release an toan.
- `execution_readiness` dua tren danh gia rieng ve moi truong, du lieu va cach xac minh cua tung case. Case con `needs_clarification` khong the danh dau san sang chay.
- MVP khong co dang nhap: ten QA la tu khai. `accepted_risk` va `not_applicable` cho risk high/critical bi tu choi cho den khi co xac minh quyen. Doi story, review, contract hoac noi dung suite se vo hieu hoa quyet dinh cu.

API danh gia suite: `PUT /api/test-case-sets/{id}/coverage-decisions`, `POST /api/test-case-sets/{id}/coverage-accept`, `PUT /api/test-case-sets/{id}/cases/{case_id}/readiness`.

## API Contract Agent

- Ho tro OpenAPI 3.0.x/3.1.x dang JSON, YAML hoac YML; dung luong upload toi da 1 MB.
- Ho tro `$ref` noi bo trong tai lieu. External `$ref` bi tu choi va khong duoc tu dong fetch.
- Gioi han phan tich: toi da 200,000 ky tu operations da chuan hoa cho AI.
- Phat hien/request checks, negative, boundary, schema, security va khoang trong contract; moi phat hien co operation va JSON Pointer tham chieu.
- Hanh vi khong duoc OpenAPI khai bao duoc danh dau can xac nhan; agent khong tu dat endpoint, status code hay business rule.
- QA phai duyet API contract review truoc khi no duoc dua vao test generation. Sua spec tao version moi va danh dau review/test cu stale.
- Test generation co the nhan `api_contract_review_id` tuy chon; khi co, test case va coverage map truy vet den API finding IDs.
- Khong tu chay request den API dich. Agent chi tao phan tich va test case ban nhap.
- OpenAPI 3.1 giu dong thoi constraint cua `$ref` va schema sibling; parser khong ghi de constraint trung ten.

API endpoints bo sung:

- `POST /api/stories/{story_id}/api-specifications` (multipart field `file`)
- `POST /api/api-specifications/{specification_id}/contract-reviews`
- `PATCH /api/api-contract-reviews/{review_id}`
- `POST /api/api-contract-reviews/{review_id}/approve`
- `GET /api/api-contract-reviews/{review_id}/export?format=json|csv`

## Scope guardrails

In-scope agents are Requirement Review, API Contract, and Test Case Generation. MVP inputs are manually entered user stories and manually uploaded OpenAPI 3.x documents. Outputs are analysis drafts, reviewed test cases, and JSON/CSV exports.

- Every AI result remains a draft until QA explicitly approves it. AI does not approve requirements, run tests, create defects, or call the target API.
- Story is the source for business behavior; OpenAPI is the source for the API contract. Conflicts are raised for QA/PO confirmation without selecting a winner.
- Unknown behavior is marked `needs_clarification`; recommendations are labeled separately from source-backed requirements.
- API tests require a current approved API contract review. Uploading a new spec or editing the story/review makes dependent work stale.
- API keys stay on the backend. Story text and OpenAPI content are untrusted data, and embedded instructions are ignored.
- Moi AC goc duoc gan source ID; QA phai doi chieu va bo sung AC bi AI bo sot truoc khi duyet review. Moi dong coverage duoc danh dau covered phai tro den assertion cu the cua test case; QA van can kiem tra assertion co chung minh dung hanh vi nghiep vu hay khong.
- Jira/CI integrations, authentication/roles, DOCX/PDF ingestion, failure/flaky triage, defect drafting, regression selection, release summaries, and automation code review are outside this MVP.

## Chay bang Docker

1. Sao chep `.env.example` thanh `.env` va dien `OPENAI_API_KEY`.
2. Chay `docker compose up --build`.
3. Mo http://localhost:5173. API docs o http://localhost:8000/docs.

## Phat trien local

Backend:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\alembic upgrade head
.venv\Scripts\uvicorn app.main:app --reload
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

## Kiem thu

```powershell
cd backend
pytest
cd ..\frontend
npm run test
npm run build
```

Migration `0003_requirement_identity` them source ID va revision vao review cu. Neu ID thay doi, test suite phu thuoc duoc danh dau `stale`; neu review cu bo sot AC goc, review chuyen ve draft de QA duyet lai. `ai_original` duoc giu nguyen.
Migration `0004_suite_assessment` them decision va readiness; suite cu giu trang thai duyet noi dung nhung coverage acceptance bat dau la `pending`.

Bo tinh huong danh gia API Contract Agent nam trong `backend/evals`. Chay thu co chu dich bang `python -m evals.api_contract_regressions --output api-contract-eval-results.json` khi da cau hinh AI provider; QA cham ket qua theo `qa_check` trong file xuat. Lenh nay goi API cua provider va co the phat sinh chi phi.

Khong dua OpenAI API key vao frontend. Noi dung story duoc coi la du lieu khong tin cay; prompt cua he thong yeu cau model khong lam theo chi dan nam trong story.

## AI provider

Backend ho tro chuyen provider bang `.env`:

```dotenv
AI_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-6-astra
```

Hoac Gemini:

```dotenv
AI_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.5-flash-lite
```

API key chi duoc doc boi backend. Khoi dong lai backend sau khi thay provider.

