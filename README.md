# AI QA Assistant

MVP noi bo gom hai workflow co human-in-the-loop:

1. **Requirement Review Agent** phan tich user story va tao ban nhap co cau truc.
2. QA chinh sua, phe duyet ban review.
3. **Test Case Generation Agent** tao test case positive, negative, boundary va integration tu story + review da duyet.

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

