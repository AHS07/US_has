-- HealthFlow — Migration 001: Core schema
-- Matches HealthFlow_System_Design.md as of this round

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS citext;

-- ─────────────────────────────────────────────
-- Enums
-- ─────────────────────────────────────────────
CREATE TYPE user_role AS ENUM ('admin', 'doctor', 'patient');
CREATE TYPE appointment_status AS ENUM ('held', 'confirmed', 'completed', 'cancelled', 'no_show', 'reassigned');
CREATE TYPE cancel_reason AS ENUM ('patient_initiated', 'affected_by_leave');
CREATE TYPE urgency_level AS ENUM ('Low', 'Medium', 'High');
CREATE TYPE attendance_shift AS ENUM ('morning', 'afternoon');
CREATE TYPE attendance_status AS ENUM ('present', 'absent');
CREATE TYPE notification_channel AS ENUM ('email', 'in_app');
CREATE TYPE notification_type AS ENUM (
  'booking_confirmed', 'reminder', 'cancellation',
  'doctor_absent', 'reschedule_offer', 'running_late', 'follow_up_available'
);
CREATE TYPE catalog_status AS ENUM ('pending_review', 'active');

-- ─────────────────────────────────────────────
-- Hospitals & Users
-- ─────────────────────────────────────────────
CREATE TABLE hospitals (
  id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name          TEXT NOT NULL,
  address       TEXT,
  contact_email TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  hospital_id     UUID REFERENCES hospitals(id),      -- NULL only ever disallowed for admin/doctor; enforced in app layer
  role            user_role NOT NULL,
  name            TEXT NOT NULL,
  email           CITEXT NOT NULL UNIQUE,
  phone           TEXT,
  password_hash   TEXT NOT NULL,
  must_reset_password BOOLEAN NOT NULL DEFAULT true,   -- true on admin-created accounts until first reset
  created_by      UUID REFERENCES users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_users_hospital ON users(hospital_id);
CREATE INDEX idx_users_role ON users(role);

-- password_reset_tokens: forgot-password flow
CREATE TABLE password_reset_tokens (
  id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash  TEXT NOT NULL,
  expires_at  TIMESTAMPTZ NOT NULL,
  used_at     TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_reset_tokens_user ON password_reset_tokens(user_id);

-- refresh_tokens: session lifecycle
CREATE TABLE refresh_tokens (
  id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash  TEXT NOT NULL,
  expires_at  TIMESTAMPTZ NOT NULL,
  revoked_at  TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_refresh_tokens_user ON refresh_tokens(user_id);

-- ─────────────────────────────────────────────
-- Doctors, shifts, slots, leave, attendance
-- ─────────────────────────────────────────────
CREATE TABLE doctor_profiles (
  user_id        UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  specialization TEXT NOT NULL,
  is_active      BOOLEAN NOT NULL DEFAULT true,
  google_oauth_connected BOOLEAN NOT NULL DEFAULT false,
  slot_duration_minutes INT NOT NULL DEFAULT 60,   -- admin-configurable per doctor; slot generation reads this
  slot_capacity          INT NOT NULL DEFAULT 5     -- admin-configurable per doctor; batch size per slot
);
CREATE INDEX idx_doctor_specialization ON doctor_profiles(specialization);

-- doctor_google_credentials: OAuth token storage, one row per doctor once connected.
-- Tokens are encrypted at rest at the application layer (envelope encryption via a KMS key,
-- not plain-text columns) — this table stores ciphertext + the metadata needed to refresh.
CREATE TABLE doctor_google_credentials (
  doctor_id             UUID PRIMARY KEY REFERENCES doctor_profiles(user_id) ON DELETE CASCADE,
  access_token_encrypted  TEXT NOT NULL,
  refresh_token_encrypted TEXT NOT NULL,
  token_expires_at        TIMESTAMPTZ NOT NULL,
  scope                   TEXT NOT NULL DEFAULT 'https://www.googleapis.com/auth/calendar.events',
  connected_by            UUID REFERENCES users(id),   -- admin who ran the connect flow
  connected_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_refreshed_at       TIMESTAMPTZ
);

CREATE TABLE shift_config (
  id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  doctor_id      UUID NOT NULL REFERENCES doctor_profiles(user_id) ON DELETE CASCADE,
  shift_1_start  TIME NOT NULL DEFAULT '09:00',
  shift_1_end    TIME NOT NULL DEFAULT '13:00',
  shift_2_start  TIME NOT NULL DEFAULT '14:00',
  shift_2_end    TIME NOT NULL DEFAULT '17:00',
  working_days   INT[] NOT NULL DEFAULT '{1,2,3,4,5}', -- 0=Sun..6=Sat
  UNIQUE(doctor_id)
);

-- Rows here are produced by the slot-generation job (see API routes doc, Background Jobs),
-- which reads doctor_profiles.slot_duration_minutes / slot_capacity + shift_config at generation
-- time. Editing shift_config or slot_duration_minutes does NOT retroactively change already-
-- generated future slots — the admin must explicitly re-run generation for the affected range
-- (see POST /admin/doctors/:id/slots/generate), so in-flight bookings are never silently altered.
CREATE TABLE appointment_slots (
  id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  doctor_id    UUID NOT NULL REFERENCES doctor_profiles(user_id) ON DELETE CASCADE,
  date         DATE NOT NULL,
  slot_start   TIME NOT NULL,
  slot_end     TIME NOT NULL,
  capacity     INT NOT NULL DEFAULT 5,
  booked_count INT NOT NULL DEFAULT 0,
  CHECK (booked_count <= capacity),
  UNIQUE (doctor_id, date, slot_start)
);
CREATE INDEX idx_slots_doctor_date ON appointment_slots(doctor_id, date);

CREATE TABLE doctor_leave (
  id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  doctor_id UUID NOT NULL REFERENCES doctor_profiles(user_id) ON DELETE CASCADE,
  date      DATE NOT NULL,
  reason    TEXT,
  UNIQUE (doctor_id, date)
);

CREATE TABLE doctor_attendance (
  id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  doctor_id  UUID NOT NULL REFERENCES doctor_profiles(user_id) ON DELETE CASCADE,
  date       DATE NOT NULL,
  shift      attendance_shift NOT NULL,
  status     attendance_status NOT NULL DEFAULT 'present',
  marked_by  UUID REFERENCES users(id),
  marked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (doctor_id, date, shift)
);
CREATE INDEX idx_attendance_doctor_date ON doctor_attendance(doctor_id, date);

-- ─────────────────────────────────────────────
-- Medicine catalog (app-wide, name-only)
-- ─────────────────────────────────────────────
CREATE TABLE medicine_catalog (
  id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name         TEXT NOT NULL,
  status       catalog_status NOT NULL DEFAULT 'active',
  added_by     UUID REFERENCES users(id),   -- NULL for the initial Kaggle seed
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX idx_medicine_name_unique ON medicine_catalog (lower(name));
CREATE INDEX idx_medicine_name_trgm ON medicine_catalog USING gin (name gin_trgm_ops);

-- ─────────────────────────────────────────────
-- Appointments & clinical records
-- ─────────────────────────────────────────────
CREATE TABLE appointments (
  id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  patient_id          UUID NOT NULL REFERENCES users(id),
  doctor_id           UUID NOT NULL REFERENCES doctor_profiles(user_id),
  hospital_id         UUID NOT NULL REFERENCES hospitals(id),
  slot_id             UUID NOT NULL REFERENCES appointment_slots(id),
  status              appointment_status NOT NULL DEFAULT 'held',
  cancel_reason       cancel_reason,
  symptom_text        TEXT,
  urgency_level       urgency_level,
  ai_pre_summary_id   TEXT,      -- Mongo doc reference
  pre_summary_status  TEXT NOT NULL DEFAULT 'pending'
                        CHECK (pre_summary_status IN ('pending','ready','unavailable')),
  original_request_id UUID REFERENCES appointments(id),
  google_calendar_event_id TEXT,        -- doctor-side calendar event
  patient_ics_generated_at TIMESTAMPTZ, -- last .ics regeneration for patient
  held_until          TIMESTAMPTZ,      -- Redis TTL mirror for held rows
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_appt_patient ON appointments(patient_id);
CREATE INDEX idx_appt_doctor ON appointments(doctor_id);
CREATE INDEX idx_appt_hospital ON appointments(hospital_id);
CREATE INDEX idx_appt_slot ON appointments(slot_id);
CREATE INDEX idx_appt_status ON appointments(status);

CREATE TABLE prescriptions (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  appointment_id  UUID NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
  line_no         INT NOT NULL,
  medicine_id     UUID NOT NULL REFERENCES medicine_catalog(id),
  dosage          TEXT NOT NULL,
  frequency_text  TEXT NOT NULL,
  reminder_times  TIME[] NOT NULL DEFAULT '{}',
  duration_days   INT NOT NULL,
  instructions    TEXT,
  UNIQUE (appointment_id, line_no)
);
CREATE INDEX idx_prescriptions_appt ON prescriptions(appointment_id);

CREATE TABLE visit_notes (
  id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  appointment_id       UUID NOT NULL UNIQUE REFERENCES appointments(id) ON DELETE CASCADE,
  doctor_raw_notes     TEXT NOT NULL,
  follow_up_days       INT,
  ai_patient_summary_id TEXT,           -- Mongo doc reference
  summary_status       TEXT NOT NULL DEFAULT 'pending_doctor_approval'
                        CHECK (summary_status IN ('pending_doctor_approval','approved','unavailable')),
  approved_by          UUID REFERENCES users(id),
  approved_at          TIMESTAMPTZ
);

CREATE TABLE llm_audit_log (
  id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  appointment_id UUID NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
  stage          TEXT NOT NULL CHECK (stage IN ('pre_visit','post_visit')),
  raw_input      TEXT NOT NULL,
  llm_output     TEXT NOT NULL,
  approved_by    UUID REFERENCES users(id),
  approved_at    TIMESTAMPTZ,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_llm_audit_appt ON llm_audit_log(appointment_id);

CREATE TABLE pre_visit_attachments (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  appointment_id  UUID NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
  file_url        TEXT NOT NULL,
  file_type       TEXT NOT NULL CHECK (file_type IN ('application/pdf','image/jpeg','image/png')),
  file_size_bytes INT NOT NULL,
  uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_attachments_appt ON pre_visit_attachments(appointment_id);

-- ─────────────────────────────────────────────
-- Reminders & notifications
-- ─────────────────────────────────────────────
CREATE TABLE medication_reminders (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  prescription_id UUID NOT NULL REFERENCES prescriptions(id) ON DELETE CASCADE,
  scheduled_at    TIMESTAMPTZ NOT NULL,
  sent_at         TIMESTAMPTZ,
  channel         notification_channel NOT NULL DEFAULT 'in_app',
  status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed'))
);
CREATE INDEX idx_reminders_scheduled ON medication_reminders(scheduled_at) WHERE status = 'pending';

CREATE TABLE notifications (
  id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type       notification_type NOT NULL,
  payload    JSONB NOT NULL DEFAULT '{}',
  channel    notification_channel NOT NULL,
  read_at    TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_notifications_user ON notifications(user_id, read_at);

CREATE TABLE email_jobs (
  id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  notification_id UUID REFERENCES notifications(id) ON DELETE CASCADE,
  status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed')),
  attempts     INT NOT NULL DEFAULT 0,
  last_error   TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
