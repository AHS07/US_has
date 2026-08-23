# HealthFlow

A full-stack clinic appointment platform with separate portals for patients, doctors, and admins. An LLM assists clinical communication through AI pre-visit summaries and doctor-approved post-visit summaries — it never makes clinical decisions.

---

## Features

**Patient portal**
- Search doctors by specialization with live slot availability
- Redis-backed slot hold with 10-minute TTL, confirmed under Postgres `SELECT FOR UPDATE`
- Symptom form with file attachments (PDF, JPEG, PNG)
- Booking confirmation with `.ics` calendar invite
- Post-visit summary (doctor-approved, patient-friendly language)
- Reassignment flow when doctor is marked absent — symptoms carry forward

**Doctor portal**
- Day view: slot grid with expandable patient cards, urgency badges, AI summary status
- AI pre-visit briefing (chief complaint, suggested questions, red flags)
- Consultation screen: clinical notes + prescription builder with medicine autocomplete and fuzzy matching
- Side-by-side summary review with inline editing and approval gate
- Google Calendar OAuth integration

**Admin portal**
- Doctor management: shift config, slot generation, leave CRUD, attendance sheet
- Hospital dashboard: today's bookings, active doctors, pending medicines, unread alerts
- Patient accounts: all hospital patients with appointment history
- Medicine catalog: approve/reject/merge entries added during consultations

**System**
- Multi-tenant: every query scoped by `hospital_id`; patients isolated by `patient_id`
- Celery beat: no-show sweep (30 min), slot reconciliation (hourly), follow-up reminders (daily)
- Doctor absence cascade: marks absent → cancels affected bookings → finds same-specialization alternate → offers reassignment
- LLM audit log in MongoDB: every prompt+response pair stored immutably; medication injection guard prevents hallucination of unprescribed drugs

---

## Tech stack

| Layer | Stack |
|---|---|
| Backend | Django 4.2, DRF, SimpleJWT, Celery, PostgreSQL 18, Redis, MongoDB |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4, react-router-dom v7, animejs |
| AI | HuggingFace Inference API (configurable; OpenAI/Azure stub ready) |
| Calendar | Google Calendar API v3, OAuth2 |
| Auth | JWT with custom claims (`role`, `hospital_id`, `user_id`), refresh rotation, token blacklist |

---

## Quick start (Docker)

```bash
# 1. Clone and configure
git clone <repo-url> && cd US_has
cp healthflow/.env.example healthflow/.env
# Edit healthflow/.env — fill in DJANGO_SECRET_KEY, POSTGRES_PASSWORD, ENCRYPTION_KEY

# 2. Start all services
docker compose up --build

# 3. Apply migrations and seed demo data
docker compose exec api python manage.py migrate
docker compose exec api python manage.py seed_demo_data
```

Frontend: `http://localhost:3000` — Backend: `http://localhost:8000`

See **[SETUP.md](SETUP.md)** for local dev (without Docker), environment variable reference, and CI configuration.

See **[WALKTHROUGH.md](WALKTHROUGH.md)** for the step-by-step demo script.

---

## Test suite

```bash
cd healthflow
pytest apps/
# 271 tests, 0 failures
```

> The full test suite requires a live PostgreSQL instance. `django.contrib.postgres` extensions (`ArrayField`, `pg_trgm`) are not supported on SQLite.

---

## Documentation

| File | Contents |
|---|---|
| `about/architecture.md` | System architecture, tenancy model, data flow |
| `about/HealthFlow_System_Design__1_.md` | Detailed system design |
| `about/HealthFlow_API_Routes.md` | Full API route reference |
| `about/prd.md` | Product requirements |
| `about/phases.md` | Build phases and exit criteria |
| `healthflow/docs/memory.md` | Session-by-session implementation log |
