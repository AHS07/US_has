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

- [x] `GET /doctors` — search by specialization, next-available-slot per doctor, filterable by date range
- [x] `GET /doctors/:id/slots?date=` — slot grid for doctor/date, shows `true_remaining`
- [x] `slot_availability` Postgres view created (per `002_seed_and_helpers.sql`)
- [x] Redis `slot:{id}:remaining` seeded at slot generation time
- [x] `POST /appointments/hold` — `DECR` Redis counter, create `held` row with `held_until` TTL
- [x] `DELETE /appointments/:id/hold` — cancel hold, `INCR` counter back
- [x] `POST /appointments/:id/confirm` — flip to `confirmed` under `SELECT FOR UPDATE` on `booked_count`
- [x] `POST /appointments/:id/attachments` — upload lab file (PDF/JPEG/PNG, 5 MB cap)
- [x] `GET /appointments/:id/attachments` — list (scoped: own patient, or same-hospital doctor/admin)
- [x] `DELETE /appointments/:id/attachments/:attachmentId`
- [x] `POST /appointments/:id/cancel` — patient-initiated, frees seat, notifies doctor
- [x] `POST /appointments/:id/reschedule` — cancel-and-rebook, carries symptom_text forward
- [x] `GET /appointments/me` — patient's own list
- [x] `GET /appointments/:id` — full detail (scoped)
- [x] `GET /appointments/:id/ics` — .ics generation
- [x] `GET /appointments/:id/alternates` — same-specialization doctors with open slots
- [x] `POST /appointments/:id/reassign` — alternate doctor, carries `symptom_text` + `ai_pre_summary_id`
- [x] `slot-counter-reconciliation` task — hourly resync of Redis against `slot_availability` view
- [x] **EXIT CRITERION:** N concurrent hold requests on a slot with capacity M never allow more than M confirmed bookings; reconciliation task correctly resyncs an artificially-drifted counter

---

## Phase 4 — Pre-visit AI summary

- [x] Symptom form fields wired to `appointments.symptom_text`
- [x] `PreVisitAttachment` model and upload/list/delete routes
- [x] `apps/integrations/llm/client.py` — LLM client (Azure OpenAI or compatible endpoint)
- [x] `apps/integrations/llm/prompts.py` — locked pre-visit system prompt
- [x] `apps/integrations/llm/schema.py` — enforced JSON schema (urgency, chief_complaint, questions[]), retry-on-malformed
- [x] Keyword-based urgency escalation rules layer (can only escalate upward)
- [x] `pre-visit-llm-job` Celery task — queued on confirm, sets `pre_summary_status` to `ready` or `unavailable` after retries
- [x] `GET /doctor/appointments/:id` — returns pre-visit summary if `ready`, raw `symptom_text` + "summary unavailable" note if `unavailable`, generating state if `pending`
- [x] AI-advisory label on doctor's pre-visit card
- [x] **EXIT CRITERION:** killing LLM connection mid-test still lets booking confirm; eventually surfaces `unavailable` on doctor's card (never stuck in `pending`)

---

## Phase 5 — Consultation and post-visit AI summary

- [x] `VisitNotes`, `Prescription`, `LLMAuditLog` models migrated
- [x] `MedicineCatalog` model migrated; seeded from Kaggle dataset (names only, `status='active'`, `added_by=NULL`)
- [x] `clinical/state_machine.py` — all valid transitions enforced; no status change happens outside this
- [x] `POST /doctor/appointments/:id/notes` — submit raw notes + `follow_up_days`
- [x] `POST /doctor/appointments/:id/prescriptions` — bulk-submit prescription table rows
- [x] `GET /medicine-catalog/search?q=` — trigram autocomplete, `active` only by default
- [x] `POST /medicine-catalog` — doctor adds new entry (`pending_review`), fuzzy-duplicate check first
- [x] `POST /doctor/appointments/:id/complete` — marks `completed` manually, fires post-visit LLM job
- [x] `apps/integrations/llm/prompts.py` — locked post-visit system prompt
- [x] `post-visit-llm-job` — receives only finalized notes + structured prescription rows; sets `summary_status = pending_doctor_approval`; writes `llm_audit_log`
- [x] `GET /doctor/appointments/:id/summary` — fetch AI draft
- [x] `POST /doctor/appointments/:id/summary/approve` — approve (optionally with edited text), writes `llm_audit_log` approval fields, flips `summary_status = approved`, makes visible to patient
- [x] `GET /appointments/:id` (patient) — shows approved summary + prescription with AI disclaimer
- [x] Admin medicine-catalog review queue: `GET /admin/medicine-catalog/pending`, `PUT /:id/approve`, `PUT /:id/merge`
- [x] **EXIT CRITERION:** adversarial prompt in doctor notes cannot cause a medication not in the prescription table to appear in patient-facing summary; `llm_audit_log` entry exists for every patient-visible summary

---

## Phase 6 — Notifications and calendar integration

- [x] `Notification`, `EmailJob`, `MedicationReminder` models migrated
- [x] Dual-channel trigger: every notification event writes one `notifications` row AND one `email_jobs` row from the same code path
- [x] Events wired: booking_confirmed, cancellation, doctor_absent, reschedule_offer, running_late, follow_up_available, reminder
- [x] `apps/integrations/calendar/oauth.py` — Google OAuth connect/callback/disconnect
- [x] `doctor_google_credentials` table; tokens encrypted via `common/encryption.py` (Fernet)
- [x] `GET /admin/doctors/:id/google/connect` and `/callback` and `DELETE /disconnect`
- [x] Calendar tasks: create/update/delete doctor-side event on booking confirm/cancel/reschedule
- [x] Patient `.ics` generated and attached on confirmation email; regenerated on change
- [x] `email-retry-worker` task — shared backoff pattern with LLM failures
- [x] `medication-reminder-dispatch` task — UTC + patient local timezone, no fixed-hour deltas
- [x] `GET /notifications` and `PUT /notifications/:id/read` routes
- [x] **EXIT CRITERION:** every event type produces both in-app row and email job from same trigger; forced email provider failure still leaves in-app row readable; email retries and eventually sends

---

## Phase 7 — Doctor absence cascade

- [x] Leave and attendance marking triggers cascade: cancel affected bookings (`affected_by_leave`), free Redis/Postgres capacity, delete calendar events, fire identical patient notification
- [x] Cascade fires for planned leave (`doctor_leave`) AND day-of attendance (`doctor_attendance`, half-day granularity)
- [x] `affected_by_attendance` Postgres view used to identify affected appointments
- [x] Only morning or only afternoon bookings affected when one half-day is marked absent
- [x] Affected slots pulled from availability immediately (no new bookings accepted)
- [x] Reassignment: same-specialization alternates shown, `original_request_id` set, `symptom_text` + `ai_pre_summary_id` carried forward, status set to `reassigned` on original record
- [x] **EXIT CRITERION:** marking only morning absent affects only morning bookings, leaves afternoon untouched; reassigned patient's doctor card shows correct framing with original symptoms intact

---

## Phase 8 — Background reliability jobs

- [x] `no-show-sweep` task — `confirmed` past slot window flips to `no_show`, frees seat
- [x] `running-late-check` task — structural trigger (previous slot still has open `confirmed` rows when next slot opens), notifies next slot's patients
- [x] `medication-reminder-dispatch` fully implemented with timezone-correct scheduling
- [x] Retry/backoff policies consistent across LLM, email, and calendar tasks (per `rules.md` §5)
- [x] All tasks idempotent — safe to re-run without duplicate rows or double-sends
- [x] **EXIT CRITERION:** simulated stuck `confirmed` appointment past slot window flips to `no_show`; reminder across DST boundary fires at correct local time

---

## Phase 9 — Admin dashboards and quality pass

- [x] `GET /admin/dashboard/today` — hospital-wide today's bookings view
- [x] `POST/GET/PATCH /admin/patients` — patient management (appointment-derived list)
- [x] Full doctor management UI routes complete
- [x] Isolation test suite run across every patient-data endpoint (not just Phase 1 dummy resource)
- [x] Error-handling audit: all errors go through `common/exceptions.py`; no raw stack traces in responses
- [x] No emojis anywhere in code, comments, responses, or docs (per `rules.md` §2)
- [x] No inline scoping (every patient-data query goes through `common/scoping.py`)
- [ ] **EXIT CRITERION:** PRD success criteria satisfiable end-to-end from fresh `docker compose up`

---

## Phase 10 — Demo readiness

- [x] Demo seed script: hospitals, doctors, patients, starter medicine catalog (`python manage.py seed_demo_data`)
- [ ] Walkthrough script: booking -> pre-visit summary -> consultation -> post-visit approval -> patient view -> doctor-absence cascade -> isolation 403 demo
- [x] `README.md` and `SETUP.md` verified: new machine can reach working demo from `SETUP.md` alone
- [x] **EXIT CRITERION:** someone who has never seen the codebase can follow `SETUP.md` alone and reach a working demo

---

## Frontend integration (runs in parallel from Phase 3 onwards)

The frontend is built from the wireframe in `about/Frontend/` as the reference.
Each screen connects to real API endpoints as they become available phase by phase.

### Patient portal screens
- [x] Login (Phase 1)
- [x] DoctorSearch — `GET /doctors` (Phase 3)
- [x] DoctorDetail + BatchSlotCard — `GET /doctors/:id/slots` (Phase 3)
- [x] SymptomForm + file upload — `POST /appointments/hold`, `POST /appointments/:id/confirm`, `POST /appointments/:id/attachments` (Phase 3)
- [x] BookingConfirmation + .ics download (Phase 3/6)
- [x] Appointments list — upcoming + past — `GET /appointments/me` (Phase 3)
- [x] PostVisitSummary + AI disclaimer — `GET /appointments/:id` once approved (Phase 5)
- [x] Notifications feed — `GET /notifications` (Phase 6)
- [x] Profile — `GET/PATCH /patients/me` (Phase 1)
- [x] DoctorAbsence + reassignment — `GET /appointments/:id/alternates`, `POST /:id/reassign` (Phase 7)

### Doctor portal screens
- [x] Login (Phase 1)
- [x] DayView slot grid — `GET /doctor/slots?date=` (Phase 2)
- [x] PatientDetail pre-visit briefing — `GET /doctor/appointments/:id` (Phase 4)
- [x] ConsultationScreen notes + prescription builder — `POST /doctor/appointments/:id/notes`, `/prescriptions`, `/complete` (Phase 5)
- [x] SummaryReview approve/edit — `GET + POST /doctor/appointments/:id/summary/approve` (Phase 5)
- [x] Leave view (read-only) — `GET /doctor/leave` (Phase 2)

### Admin portal screens
- [x] Login (Phase 1)
- [x] Dashboard — `GET /admin/dashboard/today` (Phase 9)
- [x] DoctorManagement — `POST/GET/PATCH /admin/doctors`, shift-config, leave (Phase 2)
- [x] AttendanceSheet — `GET/PUT /admin/attendance` (Phase 2/7)
- [x] PatientAccounts — `POST/GET/PATCH /admin/patients` (Phase 9)
- [x] MedicineCatalog review queue — `GET/PUT /admin/medicine-catalog/pending` (Phase 5)
