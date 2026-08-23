# HealthFlow — Setup Guide

## Prerequisites

| Tool | Version | Required for |
|---|---|---|
| Docker & Docker Compose v2 | Any recent | Docker path |
| Python | 3.12+ | Local dev path |
| Node.js | 20+ | Frontend dev |
| pnpm | 8+ | Frontend dev |
| PostgreSQL | 16+ | Local dev + CI |
| Redis | 7+ | Local dev |
| MongoDB | 7+ | LLM audit log |

---

## Path A — Docker Compose (recommended)

Everything runs in containers. No local database setup needed.

### 1. Clone and configure

```bash
git clone <repo-url>
cd US_has
cp healthflow/.env.example healthflow/.env
```

Edit `healthflow/.env` and fill in at minimum:

```env
DJANGO_SECRET_KEY=<generate below>
POSTGRES_PASSWORD=<choose a password>
ENCRYPTION_KEY=<generate below>
```

Generate values:
```bash
# Secret key
python -c "import secrets; print(secrets.token_urlsafe(50))"

# Fernet encryption key (for Google OAuth token storage)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

LLM and Google OAuth keys are optional — the system runs without them; AI features show a graceful "unavailable" state.

### 2. Start all services

```bash
docker compose up --build
```

Six services start: `api` (port 8000), `worker`, `postgres`, `redis`, `mongo`, `frontend` (port 3000).

### 3. Apply migrations

```bash
docker compose exec api python manage.py migrate
```

### 4. Seed demo data

```bash
docker compose exec api python manage.py seed_demo_data
```

Creates: City General Hospital, 1 admin, 4 specialist doctors with shift configs and 7 days of slots, 2 patients, 15 medicines.

See [WALKTHROUGH.md](WALKTHROUGH.md) for demo credentials and the full demo script.

### 5. Verify

```bash
curl http://localhost:8000/health/
# {"status": "ok"}
```

---

## Path B — Local development (without Docker)

Use this when you want faster iteration without container overhead.

### 1. Database setup

Start PostgreSQL 16+, Redis 7+, and MongoDB 7+ locally. Then create the database:

```bash
psql -U postgres -c "CREATE USER healthflow WITH PASSWORD 'your-password';"
psql -U postgres -c "CREATE DATABASE healthflow OWNER healthflow;"
psql -U healthflow healthflow -c "CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"; CREATE EXTENSION IF NOT EXISTS citext;"
```

### 2. Backend setup

```bash
cd healthflow
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements/dev.txt
cp .env.example .env
# Edit .env — set POSTGRES_HOST=localhost, POSTGRES_PASSWORD, DJANGO_SECRET_KEY, ENCRYPTION_KEY
python manage.py migrate
python manage.py seed_demo_data
python manage.py runserver
```

Backend is at `http://localhost:8000`.

### 3. Frontend setup

```bash
cd healthflow-ui
pnpm install
pnpm dev
```

Frontend is at `http://localhost:5173`. The Vite dev server proxies all API calls to port 8000.

### 4. Celery worker (optional — needed for background jobs and LLM tasks)

```bash
cd healthflow
celery -A config.celery worker --loglevel=info
```

### 5. Celery beat (optional — needed for scheduled tasks)

```bash
cd healthflow
celery -A config.celery beat --loglevel=info
```

---

## Environment variables reference

| Variable | Required | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | Yes | Django secret key — generate with `secrets.token_urlsafe(50)` |
| `DJANGO_SETTINGS_MODULE` | Yes | `config.settings.dev` or `config.settings.prod` |
| `DJANGO_ALLOWED_HOSTS` | Yes | Comma-separated hostnames |
| `POSTGRES_DB` | Yes | Database name (default: `healthflow`) |
| `POSTGRES_USER` | Yes | Database user (default: `healthflow`) |
| `POSTGRES_PASSWORD` | Yes | Database password |
| `POSTGRES_HOST` | Yes | `postgres` in Docker, `localhost` in local dev |
| `POSTGRES_PORT` | No | Default: `5432` |
| `REDIS_HOST` | Yes | `redis` in Docker, `localhost` in local dev |
| `REDIS_PORT` | No | Default: `6379` |
| `MONGO_URI` | No | `mongodb://mongo:27017` in Docker, `mongodb://localhost:27017` in local dev |
| `MONGO_DB_NAME` | No | Default: `healthflow` |
| `EMAIL_HOST` | No | SMTP host (default: SendGrid) |
| `EMAIL_PORT` | No | Default: `587` |
| `EMAIL_HOST_USER` | No | SMTP username (`apikey` for SendGrid) |
| `SENDGRID_API_KEY` | No | SendGrid API key |
| `DEFAULT_FROM_EMAIL` | No | Sender address |
| `LLM_API_BASE` | No | HuggingFace inference endpoint or Azure OpenAI base URL |
| `LLM_API_KEY` | No | HuggingFace or Azure OpenAI API key |
| `LLM_MODEL` | No | Model name (e.g. `mistralai/Mistral-7B-Instruct-v0.2`) |
| `LLM_BACKEND` | No | `huggingface` (default) or `openai` |
| `GOOGLE_OAUTH_CLIENT_ID` | No | Google Cloud OAuth2 client ID |
| `GOOGLE_OAUTH_CLIENT_SECRET` | No | Google Cloud OAuth2 client secret |
| `GOOGLE_OAUTH_REDIRECT_URI` | No | OAuth2 redirect URI |
| `ENCRYPTION_KEY` | Yes | Fernet key for Google OAuth token storage at rest |
| `SLOT_HOLD_TTL_SECONDS` | No | Slot hold TTL in seconds (default: `600`) |
| `USE_SQLITE` | No | `True` to force SQLite in dev (not recommended — see CI note below) |

---

## Running tests

```bash
cd healthflow
pytest apps/
```

The full suite requires a live PostgreSQL instance. `django.contrib.postgres` features used in this project (`ArrayField`, `pg_trgm` trigram indexes) are not available on SQLite and will cause test collection errors.

**For CI environments**, provision a PostgreSQL service container and set the standard `POSTGRES_*` environment variables. Example GitHub Actions setup:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    env:
      POSTGRES_USER: healthflow
      POSTGRES_PASSWORD: testpass
      POSTGRES_DB: healthflow
    ports:
      - 5432:5432
    options: >-
      --health-cmd pg_isready
      --health-interval 5s
      --health-timeout 5s
      --health-retries 10
```

Then run:
```bash
POSTGRES_HOST=localhost POSTGRES_PASSWORD=testpass pytest apps/
```

**SQLite fallback**: set `USE_SQLITE=True` in `.env` for simple unit tests that don't touch `ArrayField` or trigram lookups. The isolation, booking, LLM pipeline, and cascade tests all require Postgres.

---

## Rotating the encryption key

The `ENCRYPTION_KEY` (Fernet) encrypts Google Calendar OAuth tokens at rest. Rotating it invalidates all stored credentials — doctors will need to reconnect their calendars.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Update the key in `.env` and redeploy.

---

## Swapping the LLM backend

The LLM client is behind `apps/integrations/llm/client.py`. To switch from HuggingFace to OpenAI/Azure OpenAI:

1. Set `LLM_BACKEND=openai` in `.env`
2. Set `LLM_API_BASE`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_API_VERSION`
3. The `_call_openai()` stub in `client.py` is ready to uncomment and wire — no view or task changes needed
