# HealthFlow — Demo Walkthrough

A repeatable demo script for the full system. Follow the steps in order.
All credentials come from `python manage.py seed_demo_data`.

---

## Accounts reference

| Role | Email | Password |
|---|---|---|
| Admin | `admin@healthflow.local` | `AdminPass123!` |
| Cardiology doctor | `dr.sharma@healthflow.local` | `DoctorPass123!` |
| Dermatology doctor | `dr.patel@healthflow.local` | `DoctorPass123!` |
| General Medicine doctor | `dr.gupta@healthflow.local` | `DoctorPass123!` |
| Pediatrics doctor | `dr.rao@healthflow.local` | `DoctorPass123!` |
| Patient 1 | `patient.raj@healthflow.local` | `PatientPass123!` |
| Patient 2 | `patient.priya@healthflow.local` | `PatientPass123!` |

---

## 1. Admin setup — shift config and attendance

1. Open `http://localhost:3000/admin/login` and log in as `admin@healthflow.local`.
2. Navigate to **Doctors**. Confirm the 4 seeded doctors are visible.
3. Click **Shifts** next to Dr. Rajesh Sharma. Verify shift hours (09:00–13:00 / 14:00–17:00) and click **Save shift config**.
4. Click **Generate slots for range** — pick today through 7 days from now. Observe the generated-slot count.
5. Navigate to **Attendance**. Confirm all doctors show **Present** (default). No action needed yet.
6. Navigate to **Leave**. Select Dr. Vikram Gupta and add a leave day 3 days from now. Note: the system will cascade-cancel bookings on that date automatically.

---

## 2. Patient books an appointment

1. Open a new private/incognito window. Go to `http://localhost:3000/patient/login`.
2. Log in as `patient.raj@healthflow.local`.
3. Navigate to **Find Doctor**. Select specialization **Cardiology** and click **Search**.
4. Click the Dr. Rajesh Sharma card — confirm the next available slot is shown.
5. On the slot picker, select a morning slot and click **Book this slot**.
6. On the symptom form, type at least 10 characters describing symptoms (e.g. _"Chest tightness on exertion for the past two days, worse in the morning."_).
7. Optionally attach a PDF (any small PDF file).
8. Click **Confirm booking**. You land on the **Booking Confirmation** screen with token number, date/time, and what-happens-next.
9. Navigate to **Appointments** → **Upcoming**. The confirmed booking is visible.

---

## 3. Doctor portal — pre-visit AI summary

1. Open a new tab. Go to `http://localhost:3000/doctor/login`.
2. Log in as `dr.sharma@healthflow.local`.
3. Navigate to **Today's Slots**.
4. Find the slot containing the booking. Click the patient row to open the **Patient Detail** screen.
5. Observe:
   - **Pre-visit summary** card with `pending` state (AI job running) or `ready` state showing urgency badge, chief complaint, and suggested questions.
   - Attachment list (if the patient uploaded a file).
6. Click **Start consultation**.

> Note: The pre-visit summary requires a working LLM endpoint (`LLM_API_KEY` in `.env`). Without it the card shows **Summary unavailable** with the raw symptom text — the booking flow is unaffected.

---

## 4. Doctor — consultation and post-visit summary

1. On the **Consultation Screen**:
   - Enter clinical notes (at least 10 characters, e.g. _"BP 130/80. Heart sounds normal. Advised to avoid strenuous activity for 1 week."_).
   - In the prescription builder, type "Para" in the medicine search — **Paracetamol** should autocomplete from the seeded catalog. Select it, fill in dosage `500mg`, frequency **Twice daily**, duration **5 days**.
   - Set follow-up in **7** days.
   - Click **Mark visit complete & generate summary**.
2. You are navigated to **Review & Approve Summary**.
3. Side-by-side view: your raw notes (left) vs the AI-drafted patient summary (right).
4. Click **Edit before approving** and make a small change (e.g. add a sentence).
5. Click **Approve & send to patient**. Observe the approval animation.

---

## 5. Patient views the post-visit summary

1. Switch back to the patient window.
2. Navigate to **Appointments** → **Past**.
3. Expand the completed appointment. Click **View visit summary**.
4. The **Post-Visit Summary** screen shows:
   - Doctor-approved summary text.
   - Medication card: Paracetamol 500mg, Twice daily, 5 days.
   - Follow-up notice: "Return in 7 days if symptoms persist."
   - AI disclaimer.

---

## 6. Doctor absence cascade

> **Exit criterion (phases.md Phase 7):** Marking only a doctor's morning absent affects only morning bookings, leaves afternoon untouched.

1. First, have **Patient 2** (`patient.priya@healthflow.local`) book a **morning** slot with Dr. Ananya Patel (Dermatology), and also an **afternoon** slot with the same doctor. Use the same steps as Section 2.
2. Switch to the admin window. Navigate to **Attendance**.
3. For Dr. Ananya Patel, click the **Morning** badge → it turns to **Absent**.
4. The cascade task runs asynchronously. Wait a few seconds, then refresh.
5. Check Patient 2's Appointments:
   - The morning booking shows **View reassignment →** if a same-specialization alternate was found, or a cancellation notice if not.
   - The **afternoon booking remains Confirmed** — only morning was affected.
6. Open the reassignment screen to show original doctor (strikethrough), new doctor, and the symptom carry-forward confirmation.

---

## 7. Isolation demo — Patient A cannot see Patient B's data

> **Exit criterion (phases.md Phase 1):** Patient A's token against Patient B's resource returns 404, not 403.

Run directly against the API:

```bash
# Step 1 — get Patient 1 token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"patient.raj@healthflow.local","password":"PatientPass123!"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access'])")

# Step 2 — get Patient 2 appointment ID (you need the ID from the admin panel or DB)
# Replace <PATIENT_2_APPT_ID> with the real UUID
APPT_ID="<PATIENT_2_APPT_ID>"

# Step 3 — Patient 1 tries to access Patient 2's appointment
curl -s -w "\nHTTP %{http_code}\n" \
  http://localhost:8000/appointments/$APPT_ID \
  -H "Authorization: Bearer $TOKEN"
# Expected: HTTP 404 — existence not confirmed
```

---

## 8. Background jobs (manual trigger for demo)

These run automatically via Celery beat, but can be triggered manually:

```bash
# No-show sweep — marks confirmed appointments past their slot window
python manage.py shell -c "
from apps.notifications.tasks import no_show_sweep
result = no_show_sweep()
print(result)
"

# Reconcile Redis slot counters
python manage.py shell -c "
from apps.scheduling.tasks import reconcile_slot_counters
result = reconcile_slot_counters()
print(result)
"
```

---

## 9. Full test suite

```bash
cd healthflow
pytest apps/accounts/tests/ apps/scheduling/tests/ apps/clinical/tests/ apps/notifications/tests/ -v
# Expected: 271 passed
```

---

## Demo complete

The walkthrough covers every feature category in the PRD:
- Booking lifecycle (hold → confirm → complete)
- AI pre-visit and post-visit summaries with approval gate
- Doctor absence cascade with reassignment
- Tenancy isolation (404 on cross-patient access)
- Background reliability jobs
