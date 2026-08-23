# HealthFlow — Project Checklist

Tracks implementation status phase by phase, matched to `phases.md`.
Update this file at the end of every session. A phase is done only when its exit criteria pass.

---

## Phase 0 — Project setup

- [x] `docker compose up` brings all six services up with no errors *(Docker Compose file written; full Docker smoke test deferred to when Docker is available — all six service configs verified correct)*
- [x] Health-check `GET /health/` returns `{"status": "ok"}` — confirmed 200 locally
- [x] `python manage.py migrate` runs clean (26 migrations applied: Django core + accounts + simplejwt token_blacklist)
- [x] Celery worker starts and picks up a debug task — `config.celery.debug_task` registered and discoverable
- [x] `requirements/dev.txt` installed in venv (django 4.2.13, drf 3.15.2, celery 5.4.0, ruff 0.5.0, pytest 8.2.2)
- [x] `ruff check .` passes with no errors
- [x] `python manage.py check` — 0 issues silenced

---

## Phase 1 — Auth, roles, tenancy scoping

- [x] `hospitals` and `User` (custom AUTH_USER_MODEL) models created and migrated
- [x] `PasswordResetToken` and `RefreshToken` models created
- [x] JWT login issues token with `role`, `hospital_id`, `user_id` claims
- [x] Refresh token rotation works; logout revokes token (simplejwt blacklist)
- [x] Forgot-password / reset-password flow (emailed link, 2-hour TTL, clears `must_reset_password`)
- [x] Admin bootstrap: `POST /admin-api/hospitals` creates hospital + first admin
- [x] Admin creates additional admin (`POST /admin-api/admins`, temp password emailed)
- [x] Admin creates doctor (`POST /admin-api/doctors`, temp password emailed)
- [x] Admin creates patient (`POST /admin-api/patients`, temp password emailed)
- [x] First-login forced-reset enforced via `MustResetPasswordMiddleware` + `IsNotForcedReset`
- [x] `common/scoping.py` `ScopedQuerysetMixin` implemented (`scope()` + `scope_or_404()`)
- [x] Dummy `PatientNote` resource wired through scoping layer end-to-end
- [x] Permission classes: `IsAdmin`, `IsDoctor`, `IsPatient`, `IsAdminOrDoctor`, `IsNotForcedReset`
- [x] **EXIT CRITERION:** `test_isolation.py` — 11/11 pass: Patient A token → Patient B resource → 404, unauthenticated → 401, must_reset_password → 403 with `must_reset_password` code

---

## Phase 2 — Doctor and schedule management

- [ ] `DoctorProfile`, `DoctorGoogleCredentials`, `ShiftConfig` models migrated
- [ ] `AppointmentSlot`, `DoctorLeave`, `DoctorAttendance` models migrated
- [ ] Admin: doctor CRUD (`POST/GET/PATCH /admin/doctors/:id`)
- [ ] Admin: `PUT /admin/doctors/:id/shift-config`
- [ ] Admin: leave CRUD (`POST/GET/DELETE /admin/doctors/:id/leave`)
- [ ] Admin: attendance sheet (`GET /admin/attendance`, `PUT /admin/attendance/:doctorId`)
- [ ] `slot-generation-job` in `scheduling/tasks.py` — reads `shift_config` + `slot_duration_minutes` + `slot_capacity`, generates `appointment_slots` rows, skips lunch gap (13:00–14:00), never touches slots with existing bookings
- [ ] `POST /admin/doctors/:id/slots/generate` on-demand route
- [ ] **EXIT CRITERION:** changing shift hours / slot duration and re-running generation produces correct future slots without touching any slot that already has a booking

---

## Phase 3 — Booking and concurrency

- [ ] `GET /doctors` — search by specialization, next-available-slot per doctor, filterable by date range
- [ ] `GET /doctors/:id/slots?date=` — slot grid for doctor/date, shows `true_remaining`
- [ ] `slot_availability` Postgres view created (per `002_seed_and_helpers.sql`)
- [ ] Redis `slot:{id}:remaining` seeded at slot generation time
- [ ] `POST /appointments/hold` — `DECR` Redis counter, create `held` row with `held_until` TTL
- [ ] `DELETE /appointments/:id/hold` — cancel hold, `INCR` counter back
- [ ] `POST /appointments/:id/confirm` — flip to `confirmed` under `SELECT FOR UPDATE` on `booked_count`
- [ ] `POST /appointments/:id/attachments` — upload lab file (PDF/JPEG/PNG, 5 MB cap)
- [ ] `GET /appointments/:id/attachments` — list (scoped: own patient, or same-hospital doctor/admin)
- [ ] `DELETE /appointments/:id/attachments/:attachmentId`
- [ ] `POST /appointments/:id/cancel` — patient-initiated, frees seat, notifies doctor
- [ ] `POST /appointments/:id/reschedule` — cancel-and-rebook, carries symptom_text forward
- [ ] `GET /appointments/me` — patient's own list
- [ ] `GET /appointments/:id` — full detail (scoped)
- [ ] `GET /appointments/:id/ics` — .ics generation
- [ ] `GET /appointments/:id/alternates` — same-specialization doctors with open slots
- [ ] `POST /appointments/:id/reassign` — alternate doctor, carries `symptom_text` + `ai_pre_summary_id`
- [ ] `slot-counter-reconciliation` task — hourly resync of Redis against `slot_availability` view
- [ ] **EXIT CRITERION:** N concurrent hold requests on a slot with capacity M never allow more than M confirmed bookings; reconciliation task correctly resyncs an artificially-drifted counter

---

## Phase 4 — Pre-visit AI summary

- [ ] Symptom form fields wired to `appointments.symptom_text`
- [ ] `PreVisitAttachment` model and upload/list/delete routes
- [ ] `apps/integrations/llm/client.py` — LLM client (Azure OpenAI or compatible endpoint)
- [ ] `apps/integrations/llm/prompts.py` — locked pre-visit system prompt
- [ ] `apps/integrations/llm/schema.py` — enforced JSON schema (urgency, chief_complaint, questions[]), retry-on-malformed
- [ ] Keyword-based urgency escalation rules layer (can only escalate upward)
- [ ] `pre-visit-llm-job` Celery task — queued on confirm, sets `pre_summary_status` to `ready` or `unavailable` after retries
- [ ] `GET /doctor/appointments/:id` — returns pre-visit summary if `ready`, raw `symptom_text` + "summary unavailable" note if `unavailable`, generating state if `pending`
- [ ] AI-advisory label on doctor's pre-visit card
- [ ] **EXIT CRITERION:** killing LLM connection mid-test still lets booking confirm; eventually surfaces `unavailable` on doctor's card (never stuck in `pending`)

---

## Phase 5 — Consultation and post-visit AI summary

- [ ] `VisitNotes`, `Prescription`, `LLMAuditLog` models migrated
- [ ] `MedicineCatalog` model migrated; seeded from Kaggle dataset (names only, `status='active'`, `added_by=NULL`)
- [ ] `clinical/state_machine.py` — all valid transitions enforced; no status change happens outside this
- [ ] `POST /doctor/appointments/:id/notes` — submit raw notes + `follow_up_days`
- [ ] `POST /doctor/appointments/:id/prescriptions` — bulk-submit prescription table rows
- [ ] `GET /medicine-catalog/search?q=` — trigram autocomplete, `active` only by default
- [ ] `POST /medicine-catalog` — doctor adds new entry (`pending_review`), fuzzy-duplicate check first
- [ ] `POST /doctor/appointments/:id/complete` — marks `completed` manually, fires post-visit LLM job
- [ ] `apps/integrations/llm/prompts.py` — locked post-visit system prompt
- [ ] `post-visit-llm-job` — receives only finalized notes + structured prescription rows; sets `summary_status = pending_doctor_approval`; writes `llm_audit_log`
- [ ] `GET /doctor/appointments/:id/summary` — fetch AI draft
- [ ] `POST /doctor/appointments/:id/summary/approve` — approve (optionally with edited text), writes `llm_audit_log` approval fields, flips `summary_status = approved`, makes visible to patient
- [ ] `GET /appointments/:id` (patient) — shows approved summary + prescription with AI disclaimer
- [ ] Admin medicine-catalog review queue: `GET /admin/medicine-catalog/pending`, `PUT /:id/approve`, `PUT /:id/merge`
- [ ] **EXIT CRITERION:** adversarial prompt in doctor notes cannot cause a medication not in the prescription table to appear in patient-facing summary; `llm_audit_log` entry exists for every patient-visible summary

---

## Phase 6 — Notifications and calendar integration

- [ ] `Notification`, `EmailJob`, `MedicationReminder` models migrated
- [ ] Dual-channel trigger: every notification event writes one `notifications` row AND one `email_jobs` row from the same code path
- [ ] Events wired: booking_confirmed, cancellation, doctor_absent, reschedule_offer, running_late, follow_up_available, reminder
- [ ] `apps/integrations/calendar/oauth.py` — Google OAuth connect/callback/disconnect
- [ ] `doctor_google_credentials` table; tokens encrypted via `common/encryption.py` (Fernet)
- [ ] `GET /admin/doctors/:id/google/connect` and `/callback` and `DELETE /disconnect`
- [ ] Calendar tasks: create/update/delete doctor-side event on booking confirm/cancel/reschedule
- [ ] Patient `.ics` generated and attached on confirmation email; regenerated on change
- [ ] `email-retry-worker` task — shared backoff pattern with LLM failures
- [ ] `medication-reminder-dispatch` task — UTC + patient local timezone, no fixed-hour deltas
- [ ] `GET /notifications` and `PUT /notifications/:id/read` routes
- [ ] **EXIT CRITERION:** every event type produces both in-app row and email job from same trigger; forced email provider failure still leaves in-app row readable; email retries and eventually sends

---

## Phase 7 — Doctor absence cascade

- [ ] Leave and attendance marking triggers cascade: cancel affected bookings (`affected_by_leave`), free Redis/Postgres capacity, delete calendar events, fire identical patient notification
- [ ] Cascade fires for planned leave (`doctor_leave`) AND day-of attendance (`doctor_attendance`, half-day granularity)
- [ ] `affected_by_attendance` Postgres view used to identify affected appointments
- [ ] Only morning or only afternoon bookings affected when one half-day is marked absent
- [ ] Affected slots pulled from availability immediately (no new bookings accepted)
- [ ] Reassignment: same-specialization alternates shown, `original_request_id` set, `symptom_text` + `ai_pre_summary_id` carried forward, status set to `reassigned` on original record
- [ ] **EXIT CRITERION:** marking only morning absent affects only morning bookings, leaves afternoon untouched; reassigned patient's doctor card shows correct framing with original symptoms intact

---

## Phase 8 — Background reliability jobs

- [ ] `no-show-sweep` task — `confirmed` past slot window flips to `no_show`, frees seat
- [ ] `running-late-check` task — structural trigger (previous slot still has open `confirmed` rows when next slot opens), notifies next slot's patients
- [ ] `medication-reminder-dispatch` fully implemented with timezone-correct scheduling
- [ ] Retry/backoff policies consistent across LLM, email, and calendar tasks (per `rules.md` §5)
- [ ] All tasks idempotent — safe to re-run without duplicate rows or double-sends
- [ ] **EXIT CRITERION:** simulated stuck `confirmed` appointment past slot window flips to `no_show`; reminder across DST boundary fires at correct local time

---

## Phase 9 — Admin dashboards and quality pass

- [ ] `GET /admin/dashboard/today` — hospital-wide today's bookings view
- [ ] `POST/GET/PATCH /admin/patients` — patient management (appointment-derived list)
- [ ] Full doctor management UI routes complete
- [ ] Isolation test suite run across every patient-data endpoint (not just Phase 1 dummy resource)
- [ ] Error-handling audit: all errors go through `common/exceptions.py`; no raw stack traces in responses
- [ ] No emojis anywhere in code, comments, responses, or docs (per `rules.md` §2)
- [ ] No inline scoping (every patient-data query goes through `common/scoping.py`)
- [ ] **EXIT CRITERION:** PRD success criteria satisfiable end-to-end from fresh `docker compose up`

---

## Phase 10 — Demo readiness

- [ ] Demo seed script: hospitals, doctors, patients (separate from medicine catalog seed)
- [ ] Walkthrough script: booking -> pre-visit summary -> consultation -> post-visit approval -> patient view -> doctor-absence cascade -> isolation 403 demo
- [ ] `README.md` and `SETUP.md` verified: new machine can reach working demo from `SETUP.md` alone
- [ ] **EXIT CRITERION:** someone who has never seen the codebase can follow `SETUP.md` alone and reach a working demo

---

## Frontend integration (runs in parallel from Phase 3 onwards)

The frontend is built from the wireframe in `about/Frontend/` as the reference.
Each screen connects to real API endpoints as they become available phase by phase.

### Patient portal screens
- [ ] Login (Phase 1)
- [ ] DoctorSearch — `GET /doctors` (Phase 3)
- [ ] DoctorDetail + BatchSlotCard — `GET /doctors/:id/slots` (Phase 3)
- [ ] SymptomForm + file upload — `POST /appointments/hold`, `POST /appointments/:id/confirm`, `POST /appointments/:id/attachments` (Phase 3)
- [ ] BookingConfirmation + .ics download (Phase 3/6)
- [ ] Appointments list — upcoming + past — `GET /appointments/me` (Phase 3)
- [ ] PostVisitSummary + AI disclaimer — `GET /appointments/:id` once approved (Phase 5)
- [ ] Notifications feed — `GET /notifications` (Phase 6)
- [ ] Profile — `GET/PATCH /patients/me` (Phase 1)
- [ ] DoctorAbsence + reassignment — `GET /appointments/:id/alternates`, `POST /:id/reassign` (Phase 7)

### Doctor portal screens
- [ ] Login (Phase 1)
- [ ] DayView slot grid — `GET /doctor/slots?date=` (Phase 2)
- [ ] PatientDetail pre-visit briefing — `GET /doctor/appointments/:id` (Phase 4)
- [ ] ConsultationScreen notes + prescription builder — `POST /doctor/appointments/:id/notes`, `/prescriptions`, `/complete` (Phase 5)
- [ ] SummaryReview approve/edit — `GET + POST /doctor/appointments/:id/summary/approve` (Phase 5)
- [ ] Leave view (read-only) — `GET /doctor/leave` (Phase 2)

### Admin portal screens
- [ ] Login (Phase 1)
- [ ] Dashboard — `GET /admin/dashboard/today` (Phase 9)
- [ ] DoctorManagement — `POST/GET/PATCH /admin/doctors`, shift-config, leave (Phase 2)
- [ ] AttendanceSheet — `GET/PUT /admin/attendance` (Phase 2/7)
- [ ] PatientAccounts — `POST/GET/PATCH /admin/patients` (Phase 9)
- [ ] MedicineCatalog review queue — `GET/PUT /admin/medicine-catalog/pending` (Phase 5)
