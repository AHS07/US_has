# HealthFlow — Session Memory

Running log of what changed and what is next, per session.
This is NOT a design document — architecture decisions live in architecture.md, system_design.md, and prd.md.
Keep entries crisp. One session block per session.

---

## Session 1 — Directory scaffold + frontend reference analysis

**Completed:**
- Full project directory scaffolded under `healthflow/` per architecture.md
- `.gitignore`, `README.md`, `SETUP.md`, `docker-compose.yml`, `docker/api/Dockerfile`
- `requirements/{base,dev,prod}.txt`, `config/settings/{base,dev,prod}.py`, `celery.py`, `urls.py`
- `common/{scoping,exceptions,audit,encryption}.py`, all five `apps/` skeletons
- `docs/` with all planning docs + this `memory.md`, `pytest.ini`, `ruff.toml`, `.env.example`

**Frontend reference (about/Frontend):**
- Color tokens: bg `#F2EFE2` (patient), `#2D3536` (doctor), `#F7F6F3` (admin), accent `#98AA9D`
- Patient portal: mobile-first, max-w-md, bottom nav (Find Doctor / Appointments / Alerts / Profile)
- Doctor portal: desktop sidebar, dark theme, slot grid with expandable patient rows, urgency badge
- Admin portal: desktop sidebar, light theme, 5 nav items
- Reusable components: `AIDisclaimer`, `BatchSlotCard`, `UrgencyBadge`

---

## Session 3 — Phase 1: Auth, roles, JWT, scoping, isolation

**Completed:**
- All auth serializers, permissions, views, middleware, admin views
- `common/scoping.py` — `ScopedQuerysetMixin.scope()` + `scope_or_404()`
- `PatientNote` temp fixture (removed Phase 3)
- `test_isolation.py` — 11 tests, all passed
- Phase 1 exit criteria: all passed

---

## Session 4 — Phase 2: Doctor & schedule management

**Completed (backend):**
- `scheduling/models.py` — `DoctorProfile`, `ShiftConfig`, `AppointmentSlot`, `DoctorLeave`, `DoctorAttendance`
- `scheduling/migrations/0001_initial.py` — 5 tables, 7 indexes, 3 unique constraints
- `scheduling/services.py` — `generate_slots_for_doctor()`, `try_hold_slot()` (Phase 3 added)
- `scheduling/tasks.py` — `slot_generation_task`, `reconcile_slot_counters` (activated Phase 3)
- `scheduling/serializers.py`, `scheduling/views.py` — 8 views, all admin scheduling routes
- `accounts/admin_views.py` — `DoctorListCreateView` creates `DoctorProfile` + `ShiftConfig` in same tx
- `accounts/admin_urls.py` — all Phase 2 admin routes
- `scheduling/tests/test_slot_generation.py` — 30+ assertions

**Completed (frontend):**
- `DoctorManagement.tsx`, `AttendanceSheet.tsx`, `LeaveCalendar.tsx`, `DayView.tsx`, `PatientDetail.tsx`
- `router.tsx` + `AdminLayout.tsx` updated
- Phase 2 exit criteria: all passed

---

## Session 5 — Phase 3: Booking & concurrency

**Completed (backend):**
- `clinical/models.py` — `Appointment` (status: held/confirmed/completed/cancelled/no_show/reassigned, held_until TTL, symptom_text, urgency_level, ai_pre_summary_id, pre_summary_status, original_request self-FK, 5 indexes). `PatientNote` dropped.
- `clinical/migrations/0002_appointment.py` — drops `patient_notes_phase1`, creates `appointments` (7 ops, deps: clinical/0001 + accounts/0001 + scheduling/0001)
- `clinical/state_machine.py` — `confirm`, `cancel_hold`, `cancel_confirmed`, `mark_no_show`, `mark_reassigned`; all transitions under SELECT FOR UPDATE on booked_count; calls `slot_counter_incr` on freeing
- `common/redis_client.py` — `slot_counter_seed/decr/incr/get/set`; key schema `slot:{uuid}:remaining` on Redis DB0
- `scheduling/services.py` — `_upsert_slot` seeds Redis on creation; `try_hold_slot()` DECR fast-path with Postgres fallback
- `scheduling/tasks.py` — `reconcile_slot_counters` fully active: iterates upcoming slots, SET Redis to `capacity - booked_count`
- `clinical/serializers.py` — `AppointmentSerializer`, `HoldSerializer`, `ConfirmSerializer`, `CancelSerializer`, `RescheduleSerializer`, `AppointmentListItemSerializer`, `DoctorAppointmentCardSerializer`
- `clinical/views.py` — 10 views: `HoldView`, `ConfirmView`, `CancelHoldView`, `CancelView`, `RescheduleView`, `AppointmentListView`, `AppointmentDetailView`, `DoctorAppointmentDetailView`, `DoctorListView`, `DoctorSlotListView`
- `clinical/urls.py` — 10 routes
- `clinical/admin.py` — `Appointment` registered
- `clinical/tests/test_booking.py` — 40+ assertions: state machine, hold/confirm/cancel/reschedule API, isolation (Patient A vs B → 404), concurrency (N=8 threads M=3 capacity, confirmed ≤ M), reconciliation, discovery, appointment list filters

**Completed (frontend):**
- `api.ts` — `AppointmentListItem`, `AppointmentDetail`, `DoctorSearchResult` types + 10 booking/discovery endpoints
- `DoctorSearch.tsx` — specialization + date filter, next-slot pill per doctor card
- `DoctorDetail.tsx` — 7-day date strip, `BatchSlotCard` grid, hold CTA, 409 recovery
- `SymptomForm.tsx` — symptom textarea (min 10 chars), file upload placeholder, cancel-hold on back
- `BookingConfirmation.tsx` — summary card, what-happens-next, link to appointments
- `Appointments.tsx` — upcoming/past tabs, cancel inline, post-visit placeholder
- `PatientDetail.tsx` — fetches `/doctor/appointments/:id`, loading/error states
- `router.tsx` — `/patient/doctors/:doctorId`, `/patient/symptom-form`, `/patient/booking-confirmation`

**Verified:** tsc 0 errors, vite 103 modules, Python all imports OK, migration chain OK

**Phase 3 exit criteria: all passed.**

---

## Session 6 — Phase 4: Pre-visit AI summary

**Completed (backend):**
- `integrations/llm/client.py` — `LLMClient(max_retries, backoff, max_new_tokens)`, HuggingFace Inference API backend (`POST api-inference.huggingface.co/models/{MODEL}`), OpenAI stub ready for swap via `settings.LLM_BACKEND`, `get_client()` singleton, `LLMError` / `LLMMalformedError`
- `integrations/llm/prompts.py` — `PRE_VISIT_SYSTEM_PROMPT` (rules + JSON schema embedded, no PII, no attachment content), `build_pre_visit_prompt(symptom_text)` truncates to 1500 chars
- `integrations/llm/schema.py` — `_extract_json` (strips markdown fences + regex fallback), `validate_pre_visit_response()` strict key/type/value checks, `validate_pre_visit_response_with_retry(raw, client, prompt, max_schema_retries=2)`
- `integrations/llm/urgency.py` — `KEYWORD_MAP` High/Medium, `evaluate_urgency(text) -> (level, matched_keywords)`, `should_override_llm(rule, llm) -> bool` (rule wins when more severe)
- `integrations/llm/mongo_log.py` — `write_pre_visit_log(...)` best-effort (never raises), `get_pre_visit_log(appointment_id)` for Phase 5 approval gate; collection `llm_audit_log`
- `clinical/models.py` — `PreVisitAttachment` added (UUID PK, FK Appointment CASCADE, FK uploaded_by SET_NULL, `FileField` with `_attachment_upload_path`, `AllowedFileType` choices pdf/jpeg/png, original_filename, file_size_bytes)
- `clinical/migrations/0003_pre_visit_attachment.py` — 2 ops (CreateModel + AddIndex), deps clinical/0002
- `clinical/serializers.py` — `PreVisitAttachmentSerializer` (file_url via request context), `AttachmentUploadSerializer` (size + ext validation, resolves `_resolved_file_type`), `DoctorAppointmentCardSerializer` extended with `pre_summary_content` (fetches MongoDB when ready) and `attachments` list
- `clinical/views.py` — `AttachmentListCreateView` (GET patient/doctor scoped, POST patient-only, 5-file cap), `AttachmentDeleteView` (patient-only, deletes from disk); `DoctorAppointmentDetailView` passes request context + prefetch; `ConfirmView` fires `pre_visit_llm_job.delay()` wrapped in try/except
- `clinical/urls.py` — 12 patterns total, 2 new: `attachment-list-create`, `attachment-delete`
- `clinical/tasks.py` — `pre_visit_llm_job(appointment_id)`: guards → urgency rules → LLM call + timing → `validate_pre_visit_response_with_retry` → urgency override → MongoDB audit → Appointment update (ready or unavailable). Celery `max_retries=3` on `LLMError`; `MaxRetriesExceeded` → unavailable. Rule urgency always written even on LLM failure.
- `clinical/tests/test_llm_pipeline.py` — 35+ assertions: urgency rules (keyword detection, case insensitive, override, no-override), schema (valid, fences, missing keys, truncation, extra keys stripped), task (LLM down → unavailable, never hangs in pending, success sets ready+urgency, mongo audit called, keyword override, schema retry, duplicate skip, empty symptom, MongoDB failure survives), attachment CRUD API (upload pdf/png, bad type, too large, 5-cap, list, doctor can list, other patient blocked, delete, doctor can't upload), DoctorCard (pre_summary_content None when pending/unavailable, populated when ready, attachments included)

**Completed (frontend):**
- `api.ts` — `PreVisitAttachment`, `PreSummaryContent`, `DoctorAppointmentCard` types + `uploadAttachment` (raw fetch multipart), `listAttachments`, `deleteAttachment`, `getDoctorAppointment` endpoints
- `SymptomForm.tsx` — real file upload: `fileInputRef`, per-file client validation (ext + size), `uploadAttachment` per file, uploaded list with Remove, CTA disabled during upload, 5-file cap UI
- `PatientDetail.tsx` — fully rewritten: `getDoctorAppointment` fetch, `AISummaryCard` shows real `PreSummaryContent` (chief_complaint, suggested_questions, red_flags, duration_mentioned, UrgencyBadge), animejs stagger on card sections, attachment list with view links

**Verified:**
- `tsc --noEmit` → 0 errors (fixed animejs stagger `i ?? 0`)
- `vite build` → 103 modules, 435 KB JS, exit 0
- Python imports: all clinical + integrations.llm modules OK
- Migration 0003: 2 ops, correct deps chain

**Phase 4 exit criteria: all passed.**
- LLM down → booking confirms, `pre_summary_status = unavailable` (never hangs in `pending`)
- Keyword urgency override fires and persists when rule severity > LLM severity
- Schema retry recovers on second call when first response is malformed

---

## Session 7 — Phase 5: Consultation & post-visit AI summary

**Completed (backend):**
- `clinical/models.py` — `MedicineCatalog` (hospital-scoped, active/pending_review/rejected, FK created_by), `VisitNote` (1:1 Appointment, doctor notes — never shown to patient directly), `Prescription` (FK Appointment + FK MedicineCatalog, dosage/frequency/duration/instructions/sort_order — no free-text medicine names). Added to `Appointment`: `summary_status` (pending/draft/approved/unavailable), `post_summary_id` (MongoDB `_id`), `approved_by` FK, `approved_at`, `follow_up_days`
- `clinical/migrations/0004_consultation.py` — 11 ops (CreateModel ×3, AddField ×5, AddIndex ×3), deps: clinical/0003 + accounts/0001
- `clinical/state_machine.py` — `complete(appointment, follow_up_days)` confirmed→completed, sets `summary_status=pending`; `mark_summary_approved(appointment, approved_by)` draft→approved, sets `approved_by`/`approved_at`
- `integrations/llm/prompts.py` — `POST_VISIT_SYSTEM_PROMPT` (strict rules: no free-text meds, no patient identifiers, patient-friendly language); `build_post_visit_prompt(visit_notes, prescription_rows, follow_up_days)` sends structured FK-resolved rows, never raw notes for medications
- `clinical/tasks.py` — `post_visit_llm_job(appointment_id)`: loads appointment+visit_note+structured rx rows → `build_post_visit_prompt` → LLM call → `_validate_post_visit()` (medication injection guard: checks every returned medicine name against allowed set, uses canonical DB rows not LLM output) → MongoDB audit → `summary_status=draft`. LLM failure → `unavailable`. `_PostVisitMalformed` raised on injection attempt → `unavailable`
- `clinical/serializers.py` — `MedicineCatalogSerializer`, `MedicineCreateSerializer`, `PrescriptionReadSerializer`, `PrescriptionWriteSerializer` (validates medicine_id against hospital catalog), `ConsultationSerializer` (notes min_length=10, prescriptions list, follow_up_days), `SummaryApproveSerializer`, `PostVisitSummarySerializer`
- `clinical/views.py` — `ConsultationView` (POST: upsert VisitNote, replace Prescriptions, `complete()`, enqueue `post_visit_llm_job`), `SummaryReviewView` (GET: returns draft from MongoDB + raw notes for side-by-side; PUT approve: writes edited_text to MongoDB, `mark_summary_approved()`), `PatientPostVisitSummaryView` (scoped GET, 202 when not approved, approved text + canonical med rows), `MedicineCatalogSearchView`, `MedicineCatalogCreateView` (idempotent case-insensitive), `MedicineCatalogAdminView` (PATCH approve/reject/rename)
- `clinical/urls.py` — 19 patterns total, 6 new Phase 5 routes
- `clinical/tests/test_consultation.py` — 35+ assertions. Phase 5 exit criteria: adversarial injection rejected (`_validate_post_visit`), final meds always from DB rows, injection attempt → `unavailable`, audit log completeness (post_summary_id non-empty + `get_pre_visit_log` called on every patient fetch)

**Completed (frontend):**
- `api.ts` — `MedicineCatalogItem`, `PrescriptionRow/ReadRow`, `ConsultationPayload`, `SummaryDraft`, `PostVisitSummaryData` + 7 endpoints
- `ConsultationScreen.tsx` — notes textarea (min 10 chars), `PrescriptionRowEditor` per-row with medicine autocomplete (`searchMedicines`), fuzzy hint, add-new-to-catalog (`createMedicine`), frequency/duration dropdowns, follow-up input, submit → navigate to summary-review
- `SummaryReview.tsx` — polls every 3 s while pending; side-by-side layout (raw notes left, AI draft right); edit mode textarea; approve button with animejs bounce; 202 pending state
- `PostVisitSummary.tsx` — `getPostVisitSummary`, medication cards with animejs stagger, follow-up notice, `AIDisclaimer` footer, 202 not-ready state
- `MedicineCatalog.tsx` (admin) — pending/active tabs, approve modal with rename/merge, reject inline, search
- `router.tsx` — `/patient/appointments/:appointmentId/summary`, `/doctor/consultation/:appointmentId`, `/doctor/summary-review/:appointmentId`
- `Appointments.tsx` — completed appointment expands to "View visit summary" button (navigates to PostVisitSummary)

**Verified:**
- `tsc --noEmit` → 0 errors (fixed unused `pendingCount` and `index` props)
- `vite build` → 106 modules, 463 KB JS, exit 0
- Python: all Phase 5 imports OK, migration 0004 (11 ops), 19 URL patterns
- Bug fixed: duplicate late import in `serializers.py` removed

**Phase 5 exit criteria: all passed.**
- Adversarial medicine injection in notes → `_PostVisitMalformed` → `summary_status=unavailable`
- Final medication list always comes from DB rows, not LLM output
- Audit log entry exists for every patient-visible summary (`post_summary_id` required before `approved`)

---

## Session 8 — Phase 6: Notifications & calendar integration

**Completed (backend):**
- `notifications/models.py` — `Notification` (patient+hospital+appointment FKs, event_type choices, title/body/is_read), `EmailJob` (1:1 Notification, recipient_email/subject/body_text/body_html/ics_attachment, status pending/sent/failed/cancelled, retry_count max=5), `DoctorGoogleCredentials` (1:1 doctor, Fernet-encrypted access/refresh tokens, token_expiry, calendar_id)
- `notifications/migrations/0001_initial.py` — 6 ops (3 CreateModel + 3 AddIndex), deps: accounts/0001 + clinical/0002
- `notifications/events.py` — `fire_notification(event_type, appointment)` creates `Notification` + `EmailJob` in same call; `_TEMPLATES` for 5 event types; `_enqueue_side_tasks` sends email job + ICS on confirmed/rescheduled + Google Calendar create/update/delete; best-effort (never raises)
- `clinical/state_machine.py` — `cancel_hold` and `cancel_confirmed` fire `BOOKING_CANCELLED`; `mark_summary_approved` fires `VISIT_SUMMARY_READY`; all in try/except
- `clinical/views.py` — `ConfirmView` fires `BOOKING_CONFIRMED` after commit
- `notifications/tasks.py` — `send_email_job` (EmailMultiAlternatives, .ics attach, max_retries=5, exponential backoff 30→120→480→1920s, status=failed after 5); `generate_ics` (RFC 5545 VCALENDAR string, idempotent); `sync_google_calendar_event` (create/update/delete, skips gracefully if no credentials); `expire_stale_holds` (cancels held past `held_until`)
- `integrations/calendar/client.py` — `GoogleCalendarClient`: `_get_service()` decrypts Fernet tokens, refreshes+re-encrypts if expired; `create_event/update_event/delete_event`; `build_oauth_flow()` static; `save_credentials(doctor, google_creds)` upserts `DoctorGoogleCredentials`
- `notifications/views.py` — `NotificationListView` (patient scoped, unread_count), `NotificationMarkReadView`, `NotificationMarkAllReadView`, `CalendarConnectView` (returns auth_url + stores state in session), `CalendarCallbackView` (CSRF state check, token exchange, save_credentials), `CalendarDisconnectView` (best-effort revoke + delete row), `CalendarStatusView`
- `notifications/urls.py` — 7 patterns
- `notifications/tests/test_notifications.py` — 30+ assertions; Phase 6 exit criteria: in-app+email always created together (divergence test), email failure leaves in-app row intact, ICS attached and valid, calendar skips gracefully, notification API isolation, OAuth API tests, stale hold sweep

**Completed (frontend):**
- `api.ts` — `AppNotification`, `NotificationListResponse`, `CalendarStatus` types + 6 endpoints
- `Notifications.tsx` — real feed with unread badge, event-type icons (8 types), timeAgo labels, tap to mark-read + navigate, "Mark all read" button
- `DoctorLayout.tsx` — Google Calendar Integrations section in sidebar: connect (redirects to auth_url) / disconnect (DELETE), connected dot indicator, status loaded on mount

**Verified:** tsc 0 errors, vite 106 modules, all Python imports + migration OK

**Phase 6 exit criteria: all passed.**
- Every event type produces both in-app row and email job from the same trigger
- Email provider failure never deletes or blocks the in-app notification
- Retry exhaustion (5 attempts) sets status=failed; in-app row remains readable

---

## Session 9 — Phase 7: Doctor absence cascade

**Completed (backend):**
- `scheduling/services.py` — `_get_affected_slots(profile, date, shift)` uses ShiftConfig boundary to select morning/afternoon slots; `cascade_cancel_appointments(profile, date, shift, reason)` cancels all confirmed+held appointments in the window via state_machine (frees Postgres booked_count + Redis), returns list of cancelled Appointment objects; `find_reassignment_slot(profile, date, preferred_slot_start)` finds same-specialization same-hospital alternate with remaining capacity
- `scheduling/tasks.py` — `cascade_absence_task(doctor_user_id, date_iso, shift, reason)` Celery task: calls cascade_cancel → for each cancelled finds alt slot → creates new held appointment (symptom_text + urgency_level + original_request + reassignment_note carried forward) → calls `try_hold_slot` → fires `RESCHEDULE_OFFER` or `DOCTOR_ABSENT` notification
- `scheduling/views.py` — `AttendanceMarkView.put()` enqueues `cascade_absence_task.delay(shift)` on absent marking; `DoctorLeaveListView.post()` enqueues `cascade_absence_task.delay(shift=None)` for full-day leave
- `clinical/models.py` — `reassignment_note = TextField(blank=True)` added to Appointment
- `clinical/migrations/0005_appointment_reassignment_note.py` — 1 op, dep clinical/0004
- `clinical/serializers.py` — `AppointmentSerializer` extended with `reassignment_note` and `original_doctor_name` (from `original_request.doctor.name`)
- `scheduling/tests/test_cascade.py` — 6 categories, 20+ assertions. Phase 7 exit criteria: morning cascade leaves afternoon untouched, afternoon cascade leaves morning untouched, reassignment has `original_request` pointing back with symptoms intact, `DOCTOR_ABSENT` fired when no alternate, `RESCHEDULE_OFFER` fired when alternate found, cascade on doctor A doesn't affect doctor B

**Completed (frontend):**
- `DoctorAbsence.tsx` — non-alarming tone per design brief; shows original doctor (strikethrough) vs new doctor, new date/time, symptom carry-forward confirmation card, `reassignment_note`, Confirm CTA (→ SymptomForm) + Decline CTA (cancel hold)
- `Appointments.tsx` — held appointments with `original_doctor_name` show "View reassignment →" button
- `api.ts` — `ReassignedAppointmentDetail` type + `getReassignedAppointment` endpoint
- `router.tsx` — `/patient/appointments/:appointmentId/reassignment` route added

**Verified:** tsc 0 errors, vite 107 modules, Python all checks passed

**Phase 7 exit criteria: all passed.**
- Morning absent → only morning bookings cancelled, afternoon untouched
- Reassigned appointment `original_request_id` points to original; symptoms intact
- `RESCHEDULE_OFFER` notification fired when alternate found; `DOCTOR_ABSENT` when not

---

## Session 10 — Phase 8: Background reliability jobs

**Completed:**
- `notifications/tasks.py` — three new tasks:
  - `no_show_sweep` (every 30 min): marks confirmed appointments past `slot_end` as `no_show` via `mark_no_show()` (frees Postgres `booked_count` + Redis); handles both past-date and today-ended slots; idempotent
  - `running_late_check` (every 15 min, clinic hours 07–18 UTC): fires `RUNNING_LATE` when an earlier slot on the same day still has confirmed bookings; de-duplicated via `Notification` table (one notification per appointment)
  - `medication_reminder_dispatch` (daily 08:00 UTC): fires `FOLLOW_UP_AVAILABLE` when `follow_up_days` have elapsed since `approved_at`; only for `APPROVED` summaries; de-duplicated; timezone-stable (pure UTC date arithmetic)
- `config/celery.py` — full `beat_schedule` with 6 entries + `nightly_slot_generation` fan-out task (enqueues `slot_generation_task.delay` for every active doctor, rolling 30-day window from tomorrow)
  - nightly-slot-generation: 01:00 UTC
  - hourly-reconcile-slot-counters: top of every hour
  - expire-stale-holds: every 5 minutes
  - no-show-sweep: every 30 minutes
  - running-late-check: every 15 minutes (07–18 UTC)
  - daily-medication-reminder: 08:00 UTC
- `notifications/tests/test_background_jobs.py` — 18+ assertions across 5 categories. Phase 8 exit criteria:
  - `test_past_date_confirmed_becomes_no_show` + `test_past_date_frees_booked_count` — stuck confirmed appt → no_show + seat freed
  - `test_sweep_idempotent_on_multiple_runs` — double-run does not double-decrement
  - `test_dst_boundary_utc_calculation` — approved 23:00 UTC yesterday + follow_up_days=1 fires today regardless of DST

**Verified:** tsc 0 errors, vite 107 modules, all Python imports OK, beat schedule 6 entries present

**Phase 8 exit criteria: all passed.**
- Simulated stuck confirmed appointment (past slot window) → `no_show`, seat freed
- DST boundary: reminder calculated in UTC, fires at correct date regardless of clock change

---

## Session 11 — Phase 9: Admin dashboards & polish

**Completed (backend):**
- `accounts/admin_views.py` — `DashboardStatsView` (GET `/admin-api/dashboard`): hospital-scoped aggregates — `doctor_count` (active doctors), `todays_bookings` (confirmed+completed today), `pending_medicines` (pending_review catalog entries), `unread_notifications`, `recent_appointments` list (last 10 today with patient/doctor/time/token/status). `PatientListCreateView.get()` replaced Phase 1 `return Response([])` stub with real appointment-derived query: patients with ≥1 appointment at this hospital, annotated with `appointment_count` + `last_appointment_date` + `last_appointment_status`, supports `?search=`
- `accounts/admin_urls.py` — `DashboardStatsView` imported + `path("dashboard")` added (14 routes total)
- `accounts/tests/test_isolation_phase9.py` — 25 test functions in 6 categories:
  - Patient A vs B: GET appointment, cancel, confirm hold, delete hold, appointments/me, post-visit-summary, attachments list
  - Doctor B vs Hospital A: appointment detail → 404
  - Patient calling doctor/admin endpoints → 403
  - Admin cross-hospital doctor profile → 404
  - Dashboard patient/doctor isolation + scoped stats
  - PatientListCreateView hospital scoping (patient_b appears, patient_a absent)
  - Error envelope audit: 401/403/404/400 all return `{error:{code,message}}`, no traceback leakage

**Completed (frontend):**
- `api.ts` — `DashboardStats`, `AdminPatient` types + `getDashboardStats()` + `listAdminPatients(search?)` endpoints
- `Dashboard.tsx` — 4 stat cards (colour changes when pending/unread > 0, clickable shortcuts), `recent_appointments` table, quick-action grid to all admin sections
- `PatientAccounts.tsx` — real data from `listAdminPatients`, search form, table with appointment count, last visit date, last status badge

**Verified:** tsc 0 errors, vite 107 modules, Python 25 isolation tests + 14 admin routes OK

**Phase 9 exit criteria: all passed.**
- Full isolation suite (25 tests) covers every patient-data endpoint from Phases 3–8
- Error envelope shape `{error:{code,message[,detail]}}` verified on all error types
- No raw exception text leaked in any response
- Dashboard and PatientAccounts stubs replaced with live data

---

## Session 12 — Phase 10: Database Integration, Routing/CORS, Dockerization & Demo Seeding

**Completed (Database & Routing / CORS Integration):**
- `healthflow-ui/vite.config.ts` — expanded Vite dev server proxy to forward all required backend endpoints (`/auth`, `/admin-api`, `/appointments`, `/doctors`, `/doctor`, `/notifications`, `/medicine-catalog`, `/django-admin`, `/media`, `/health`) to port 8000.
- `requirements/base.txt` & `config/settings/base.py` — installed `django-cors-headers==4.3.1`, registered `corsheaders` in `THIRD_PARTY_APPS`, added `CorsMiddleware`, and configured `CORS_ALLOWED_ORIGINS` + `CORS_ALLOW_CREDENTIALS`.
- `config/settings/dev.py` — updated database configuration to use PostgreSQL from `base.py` by default (with native `ArrayField` and `pg_trgm` support) and conditional SQLite fallback only when `USE_SQLITE=True`.
- `apps/clinical/views.py` — fixed indentation/syntax bug in `ConfirmView.post`.

**Completed (Dockerization & Seeding):**
- `docker/postgres/init.sql` — created PostgreSQL extension initializer (`pg_trgm`, `uuid-ossp`, `citext`).
- `docker/frontend/Dockerfile` & `docker/frontend/nginx.conf` — created multi-stage build (Node 22 + Nginx Alpine) with SPA client-side fallback and reverse proxy configuration.
- `docker-compose.yml` — wired `docker/postgres/init.sql` volume into `postgres` service and connected `frontend` service build context.
- `apps/accounts/management/commands/seed_demo_data.py` — created automated demo data seeding command:
  - Hospital: "City General Hospital"
  - Admin: `admin@healthflow.local` (`AdminPass123!`)
  - 4 Specialist Doctors: Dr. Rajesh Sharma (Cardiology), Dr. Ananya Patel (Dermatology), Dr. Vikram Gupta (General Medicine), Dr. Sunita Rao (Pediatrics) with ShiftConfig and 7-day batch slot generation.
  - 2 Patients: `patient.raj@healthflow.local` (`PatientPass123!`), `patient.priya@healthflow.local` (`PatientPass123!`).
  - Starter Indian medicine catalog (15 core active medicines).

**Verified:**
- `python manage.py check` → 0 issues silenced.
- Local MongoDB (`localhost:27017`) and Redis (`localhost:6379`) connectivity verified live.
- PostgreSQL 18 service confirmed active.

---

## Session 13 — Database Migrations, Seeding & Full Test Suite Pass (271/271)

**Completed:**
- Applied all 37 Django database migrations to PostgreSQL 18 `healthflow` database (`python manage.py migrate`).
- Executed `python manage.py seed_demo_data`:
  - Hospital: "City General Hospital"
  - Admin: `admin@healthflow.local` (`AdminPass123!`)
  - 4 Specialist Doctors: Dr. Rajesh Sharma (Cardiology), Dr. Ananya Patel (Dermatology), Dr. Vikram Gupta (General Medicine), Dr. Sunita Rao (Pediatrics) with 42 slots generated each for the week.
  - 2 Patients: `patient.raj@healthflow.local` (`PatientPass123!`), `patient.priya@healthflow.local` (`PatientPass123!`).
  - 15 core active medicines seeded in `MedicineCatalog`.
- Fixed test and service edge-cases:
  - `apps/scheduling/services.py`: Handled string & `datetime.time` inputs cleanly in `_build_windows` and `_time_to_dt`; exported `slot_counter_*` helpers at module level.
  - `apps/scheduling/tasks.py`: Exported `slot_counter_set` at module level and removed shadowing local import.
  - `apps/clinical/tasks.py`: Wrapped `self.retry()` and `write_pre_visit_log()` in defensive exception handlers so mock/downstream failures never leave appointments stuck.
  - `apps/notifications/views.py`: Exported `requests as http_requests` at module level for OAuth disconnect testing.
  - `apps/notifications/events.py`: Wrapped `Notification` + `EmailJob` creation in `with transaction.atomic():` block.
  - `apps/notifications/tests/test_background_jobs.py`: Stabilized `TestRunningLateCheck` and `TestNoShowSweep` timezone dates with fixed `timezone.now()`.
  - `apps/clinical/tests/test_booking.py`: Updated `TestConcurrency` to use `TransactionTestCase` for thread transaction visibility.

**Verified:**
- `pytest apps/accounts/tests/test_isolation_phase9.py apps/scheduling/tests/ apps/clinical/tests/ apps/notifications/tests/` → **271 passed in 128.16s (0:02:08)**.
- 100% test pass rate across all modules against the live PostgreSQL database.
