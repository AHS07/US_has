# HealthFlow — Setup Guide

## Prerequisites

- Docker and Docker Compose (v2+)
- Python 3.12+ and the project venv (for running management commands outside Docker)
- A zero-retention LLM endpoint (Azure OpenAI, AWS Bedrock, or local equivalent)
- A Google Cloud project with the Calendar API enabled (for doctor calendar integration)

## Local development (Docker Compose)

### 1. Clone and configure environment

```
git clone <repo-url>
cd US_has
cp healthflow/.env.example healthflow/.env
```

Edit `healthflow/.env` and fill in all `change-me` values. At minimum:

- `DJANGO_SECRET_KEY` — generate with `python -c "import secrets; print(secrets.token_urlsafe(50))"`
- `POSTGRES_PASSWORD`
- `ENCRYPTION_KEY` — generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

LLM and Google OAuth keys are not required to start the server but are required for those
features to function.

### 2. Start all services

```
docker compose up --build
```

All six services start: `api`, `worker`, `postgres`, `redis`, `mongo`, `frontend`.
Only `api` (port 8000) and `frontend` (port 3000) are exposed to the host.

### 3. Verify the stack is running

```
curl http://localhost:8000/health/
# expected: {"status": "ok"}
```

### 4. Run database migrations

```
docker compose exec api python manage.py migrate
```

### 5. Bootstrap the first admin account

```
docker compose exec api python manage.py createsuperuser
```

Or use the hospital bootstrap route once Phase 1 is implemented:
`POST /admin/hospitals` — creates the first hospital and its first admin account.

### 6. Seed the medicine catalog (after Phase 5)

Download the Kaggle "A-Z Medicine Dataset of India" CSV and run:

```
docker compose exec -T postgres psql -U healthflow healthflow \
  -c "\copy medicine_catalog(name) FROM STDIN WITH (FORMAT csv, HEADER true)" \
  < az_medicine_dataset_india_names_deduped.csv
```

See `healthflow/migrations/002_seed_and_helpers.sql` for dedup instructions.

## Running tests

```
docker compose exec api pytest
```

Or outside Docker with the venv active:

```
cd healthflow
pytest
```

## Running lint / formatting checks

```
cd healthflow
ruff check .
black --check .
```

## Environment differences

| Setting | Dev | Prod |
|---|---|---|
| `DEBUG` | `True` | `False` |
| Email backend | Console (stdout) | SendGrid SMTP |
| `DJANGO_SETTINGS_MODULE` | `config.settings.dev` | `config.settings.prod` |

## Generating a new Fernet encryption key

```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store the output in `ENCRYPTION_KEY`. Rotating this key invalidates all stored
Google OAuth tokens — doctors will need to reconnect their calendars.
