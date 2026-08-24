/**
 * lib/api.ts
 *
 * Typed fetch wrapper for the HealthFlow backend.
 * All requests go through `apiFetch` so:
 *  - Access token is attached automatically from localStorage
 *  - 401 responses trigger a silent token refresh, then retry once
 *  - Error shape is always { error: { code, message } }
 *
 * Never call fetch() directly from a component or context — always use this.
 */

const BASE = ''  // Vite proxy forwards /auth, /admin-api, etc. to :8000

// ─── Token storage ────────────────────────────────────────────────────────────
// Stored in localStorage for simplicity in Phase 1.
// Phase 6 will evaluate moving access token to memory-only.

export function getAccessToken(): string | null {
  return localStorage.getItem('hf_access')
}
export function getRefreshToken(): string | null {
  return localStorage.getItem('hf_refresh')
}
export function setTokens(access: string, refresh: string): void {
  localStorage.setItem('hf_access', access)
  localStorage.setItem('hf_refresh', refresh)
}
export function clearTokens(): void {
  localStorage.removeItem('hf_access')
  localStorage.removeItem('hf_refresh')
}

// ─── Error shape ─────────────────────────────────────────────────────────────

export interface ApiError {
  code: string
  message: string
  detail?: Record<string, string[]>
}

export class HFApiError extends Error {
  status: number
  code: string
  detail?: Record<string, string[]>

  constructor(status: number, err: ApiError) {
    super(err.message)
    this.status = status
    this.code = err.code
    this.detail = err.detail
  }
}

// ─── Core fetch ──────────────────────────────────────────────────────────────

let _refreshing: Promise<boolean> | null = null

async function _doRefresh(): Promise<boolean> {
  const refresh = getRefreshToken()
  if (!refresh) return false
  try {
    const res = await fetch(`${BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    })
    if (!res.ok) { clearTokens(); return false }
    const data = await res.json() as { access: string; refresh: string }
    setTokens(data.access, data.refresh)
    return true
  } catch {
    clearTokens()
    return false
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  _retry = true,
): Promise<T> {
  const token = getAccessToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> ?? {}),
  }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${BASE}${path}`, { ...options, headers })

  if (res.status === 401 && _retry) {
    // Deduplicate concurrent refresh attempts
    if (!_refreshing) _refreshing = _doRefresh().finally(() => { _refreshing = null })
    const ok = await _refreshing
    if (ok) return apiFetch<T>(path, options, false)
    // Refresh failed — caller handles redirect
    throw new HFApiError(401, { code: 'token_expired', message: 'Session expired. Please log in again.' })
  }

  if (!res.ok) {
    let errBody: { error: ApiError } | null = null
    try { errBody = await res.json() as { error: ApiError } } catch { /* empty */ }
    const err = errBody?.error ?? { code: `http_${res.status}`, message: 'An error occurred.' }
    throw new HFApiError(res.status, err)
  }

  // 204 No Content
  if (res.status === 204) return undefined as T

  return res.json() as Promise<T>
}

// ─── Auth endpoints ───────────────────────────────────────────────────────────

export interface LoginResponse {
  access: string
  refresh: string
  role: 'patient' | 'doctor' | 'admin'
  hospital_id: string | null
  must_reset_password: boolean
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export async function logout(refresh: string): Promise<void> {
  await apiFetch<void>('/auth/logout', {
    method: 'POST',
    body: JSON.stringify({ refresh }),
  })
}

export async function forgotPassword(email: string): Promise<void> {
  await apiFetch<void>('/auth/forgot-password', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export async function resetPassword(token: string, new_password: string): Promise<void> {
  await apiFetch<void>('/auth/reset-password', {
    method: 'POST',
    body: JSON.stringify({ token, new_password }),
  })
}

// ─── Hospital bootstrap ───────────────────────────────────────────────────────

export async function bootstrapHospital(payload: {
  hospital_name: string
  contact_email: string
  admin_name: string
  admin_email: string
  admin_password: string
  hospital_address?: string
}): Promise<LoginResponse & { hospital_id: string }> {
  return apiFetch('/admin-api/hospitals', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

// ─── Phase 2: Scheduling types & endpoints ────────────────────────────────────

export interface ShiftConfig {
  shift_1_start: string          // "HH:MM"
  shift_1_end: string
  shift_2_start: string
  shift_2_end: string
  working_days: number[]         // ISO weekday 1=Mon…7=Sun
  slot_duration_minutes: number
  slot_capacity: number
  updated_at?: string
}

export interface DoctorProfile {
  user_id: string
  name: string
  email: string
  phone: string
  hospital_id: string
  specialization: string
  is_active: boolean
  slot_duration_minutes: number
  slot_capacity: number
  google_oauth_connected: boolean
  shift_config: ShiftConfig | null
}

export interface DoctorLeave {
  id: string
  doctor_id: string
  date: string                   // "YYYY-MM-DD"
  reason: string
  created_by: string | null
  created_at: string
}

export interface AttendanceDoctor {
  doctor_id: string
  name: string
  specialization: string
  shifts: string                 // "09:00–13:00 / 14:00–17:00"
  morning_status: 'present' | 'absent' | 'on_leave'
  afternoon_status: 'present' | 'absent' | 'on_leave'
  on_leave: boolean
}

export interface AttendanceSheet {
  date: string
  doctors: AttendanceDoctor[]
}

export interface AppointmentSlot {
  id: string
  doctor_id: string
  hospital_id: string
  date: string
  slot_start: string
  slot_end: string
  capacity: number
  booked_count: number
  true_remaining: number
  shift: 'morning' | 'afternoon'
  unavailable: boolean
  patients: PatientCard[]
}

export interface PatientCard {
  id: string
  name: string
  age: number
  token: number
  chief_complaint: string
  urgency: 'Low' | 'Medium' | 'High'
  ai_summary_status: 'pending' | 'ready' | 'unavailable'
  appointment_id: string
}

export interface DoctorDayView {
  date: string
  slots: AppointmentSlot[]
}

export interface SlotGenerateResult {
  created: number
  skipped: number
  guarded: number
}

// ── Doctor profiles ──────────────────────────────────────────────────────────

export async function listDoctors(): Promise<DoctorProfile[]> {
  return apiFetch<DoctorProfile[]>('/admin-api/doctors')
}

export async function getDoctorProfile(doctorId: string): Promise<DoctorProfile> {
  return apiFetch<DoctorProfile>(`/admin-api/doctors/${doctorId}/profile`)
}

export async function patchDoctorProfile(
  doctorId: string,
  payload: { specialization?: string; is_active?: boolean },
): Promise<DoctorProfile> {
  return apiFetch<DoctorProfile>(`/admin-api/doctors/${doctorId}/profile`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function createDoctor(payload: {
  name: string
  email: string
  phone?: string
  specialization: string
}): Promise<DoctorProfile> {
  return apiFetch<DoctorProfile>('/admin-api/doctors', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function patchDoctorUser(
  doctorId: string,
  payload: { name?: string; phone?: string },
): Promise<unknown> {
  return apiFetch(`/admin-api/doctors/${doctorId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

// ── Shift config ─────────────────────────────────────────────────────────────

export async function getShiftConfig(doctorId: string): Promise<ShiftConfig> {
  return apiFetch<ShiftConfig>(`/admin-api/doctors/${doctorId}/shift-config`)
}

export async function putShiftConfig(
  doctorId: string,
  payload: ShiftConfig,
): Promise<DoctorProfile> {
  return apiFetch<DoctorProfile>(`/admin-api/doctors/${doctorId}/shift-config`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

// ── Leave CRUD ───────────────────────────────────────────────────────────────

export async function listLeave(doctorId: string): Promise<DoctorLeave[]> {
  return apiFetch<DoctorLeave[]>(`/admin-api/doctors/${doctorId}/leave`)
}

export async function createLeave(
  doctorId: string,
  payload: { date: string; reason?: string },
): Promise<DoctorLeave> {
  return apiFetch<DoctorLeave>(`/admin-api/doctors/${doctorId}/leave`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function deleteLeave(doctorId: string, leaveId: string): Promise<void> {
  await apiFetch<void>(`/admin-api/doctors/${doctorId}/leave/${leaveId}`, {
    method: 'DELETE',
  })
}

// ── Slot generation ───────────────────────────────────────────────────────────

export async function generateSlots(
  doctorId: string,
  payload: { date_from: string; date_to: string },
): Promise<SlotGenerateResult> {
  return apiFetch<SlotGenerateResult>(
    `/admin-api/doctors/${doctorId}/slots/generate`,
    { method: 'POST', body: JSON.stringify(payload) },
  )
}

// ── Attendance ────────────────────────────────────────────────────────────────

export async function getAttendanceSheet(date?: string): Promise<AttendanceSheet> {
  const qs = date ? `?date=${date}` : ''
  return apiFetch<AttendanceSheet>(`/admin-api/attendance${qs}`)
}

export async function markAttendance(
  doctorId: string,
  payload: { date: string; shift: 'morning' | 'afternoon'; status: 'present' | 'absent' },
): Promise<unknown> {
  return apiFetch(`/admin-api/attendance/${doctorId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

// ── Doctor day-view ───────────────────────────────────────────────────────────

export async function getDoctorDayView(date?: string): Promise<DoctorDayView> {
  const qs = date ? `?date=${date}` : ''
  return apiFetch<DoctorDayView>(`/doctor/slots${qs}`)
}

// ─── Phase 3: Booking types & endpoints ──────────────────────────────────────

export interface AppointmentListItem {
  id: string
  status: 'held' | 'confirmed' | 'completed' | 'cancelled' | 'no_show' | 'reassigned'
  cancel_reason: string
  doctor_name: string
  specialization: string
  hospital_name: string
  slot_date: string        // "YYYY-MM-DD"
  slot_start: string       // "HH:MM:SS"
  slot_end: string
  token: number | null
  urgency_level: string
  pre_summary_status: 'pending' | 'ready' | 'unavailable'
  created_at: string
}

export interface AppointmentDetail extends AppointmentListItem {
  doctor_id: string
  slot_id: string
  symptom_text: string
  ai_pre_summary_id: string
  held_until: string | null
  updated_at: string
}

export interface DoctorSearchResult extends DoctorProfile {
  next_available_slot: {
    slot_id: string
    date: string
    slot_start: string
    slot_end: string
    remaining: number
  } | null
}

// ── Booking ───────────────────────────────────────────────────────────────────

export async function holdSlot(payload: {
  slot_id: string
  doctor_id: string
}): Promise<AppointmentDetail> {
  return apiFetch<AppointmentDetail>('/appointments/hold', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function confirmAppointment(
  appointmentId: string,
  payload: { symptom_text: string },
): Promise<AppointmentDetail> {
  return apiFetch<AppointmentDetail>(`/appointments/${appointmentId}/confirm`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function cancelHold(appointmentId: string): Promise<void> {
  await apiFetch<void>(`/appointments/${appointmentId}/hold`, { method: 'DELETE' })
}

export async function cancelAppointment(appointmentId: string): Promise<AppointmentDetail> {
  return apiFetch<AppointmentDetail>(`/appointments/${appointmentId}/cancel`, {
    method: 'POST',
  })
}

export async function rescheduleAppointment(
  appointmentId: string,
  payload: { new_slot_id: string; new_doctor_id: string },
): Promise<AppointmentDetail> {
  return apiFetch<AppointmentDetail>(`/appointments/${appointmentId}/reschedule`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function getMyAppointments(
  status?: 'upcoming' | 'past' | 'all',
): Promise<AppointmentListItem[]> {
  const qs = status ? `?status=${status}` : ''
  return apiFetch<AppointmentListItem[]>(`/appointments/me${qs}`)
}

export async function getAppointment(appointmentId: string): Promise<AppointmentDetail> {
  return apiFetch<AppointmentDetail>(`/appointments/${appointmentId}`)
}

// ── Discovery ─────────────────────────────────────────────────────────────────

export async function searchDoctors(params?: {
  specialization?: string
  date_from?: string
  date_to?: string
  hospital_id?: string
}): Promise<DoctorSearchResult[]> {
  const qs = new URLSearchParams()
  if (params?.specialization) qs.set('specialization', params.specialization)
  if (params?.date_from)      qs.set('date_from', params.date_from)
  if (params?.date_to)        qs.set('date_to', params.date_to)
  if (params?.hospital_id)    qs.set('hospital_id', params.hospital_id)
  const query = qs.toString() ? `?${qs.toString()}` : ''
  return apiFetch<DoctorSearchResult[]>(`/doctors${query}`)
}

export async function getDoctorSlots(
  doctorId: string,
  date?: string,
): Promise<{ doctor_id: string; date: string; slots: AppointmentSlot[] }> {
  const qs = date ? `?date=${date}` : ''
  return apiFetch(`/doctors/${doctorId}/slots${qs}`)
}

// ─── Phase 4: Attachment & AI summary types & endpoints ──────────────────────

export interface PreVisitAttachment {
  id: string
  appointment_id: string
  file_type: 'pdf' | 'jpeg' | 'png'
  original_filename: string
  file_size_bytes: number
  file_url: string
  uploaded_at: string
}

/** Parsed content from the MongoDB audit log, populated when pre_summary_status = 'ready' */
export interface PreSummaryContent {
  urgency: 'Low' | 'Medium' | 'High'
  chief_complaint: string
  suggested_questions: string[]
  red_flags: string[]
  duration_mentioned: string | null
}

/** Doctor-facing appointment card with Phase 4 AI content */
export interface DoctorAppointmentCard {
  id: string
  status: string
  patient_id: string
  patient_name: string
  slot_date: string
  slot_start: string
  token: number | null
  symptom_text: string
  urgency_level: string
  pre_summary_status: 'pending' | 'ready' | 'unavailable'
  /** null when status is not 'ready' */
  pre_summary_content: PreSummaryContent | null
  attachments: PreVisitAttachment[]
}

// ── Attachment endpoints ───────────────────────────────────────────────────────

/**
 * Upload a file attachment for an appointment.
 * Uses raw fetch (not apiFetch) because multipart/form-data must NOT set
 * Content-Type — the browser sets it with the correct boundary automatically.
 */
export async function uploadAttachment(
  appointmentId: string,
  file: File,
): Promise<PreVisitAttachment> {
  const token = getAccessToken()
  const form  = new FormData()
  form.append('file', file)

  const res = await fetch(`/appointments/${appointmentId}/attachments`, {
    method:  'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body:    form,
  })

  if (!res.ok) {
    let errBody: { error: { code: string; message: string } } | null = null
    try { errBody = await res.json() } catch { /* empty */ }
    const err = errBody?.error ?? { code: `http_${res.status}`, message: 'Upload failed.' }
    throw new HFApiError(res.status, err)
  }
  return res.json() as Promise<PreVisitAttachment>
}

export async function listAttachments(
  appointmentId: string,
): Promise<PreVisitAttachment[]> {
  return apiFetch<PreVisitAttachment[]>(`/appointments/${appointmentId}/attachments`)
}

export async function deleteAttachment(
  appointmentId: string,
  attachmentId: string,
): Promise<void> {
  await apiFetch<void>(
    `/appointments/${appointmentId}/attachments/${attachmentId}`,
    { method: 'DELETE' },
  )
}

/** Doctor endpoint — returns DoctorAppointmentCard with Phase 4 fields */
export async function getDoctorAppointment(
  appointmentId: string,
): Promise<DoctorAppointmentCard> {
  return apiFetch<DoctorAppointmentCard>(`/doctor/appointments/${appointmentId}`)
}

// ─── Phase 5: Consultation types & endpoints ─────────────────────────────────

export interface MedicineCatalogItem {
  id: string
  name: string
  generic_name: string
  default_dosage: string
  status: 'active' | 'pending_review' | 'rejected'
}

export interface PrescriptionRow {
  medicine_id: string
  dosage: string
  frequency: string           // "once_daily" | "twice_daily" | ...
  duration: string
  instructions?: string
  sort_order?: number
}

export interface PrescriptionReadRow {
  id: string
  medicine_id: string
  medicine_name: string
  dosage: string
  frequency: string
  frequency_display: string
  duration: string
  instructions: string
  sort_order: number
}

export interface ConsultationPayload {
  notes: string
  prescriptions: PrescriptionRow[]
  follow_up_days?: number | null
}

export interface SummaryDraft {
  appointment_id: string
  summary_status: 'pending' | 'draft' | 'approved' | 'unavailable'
  summary_text: string
  medications: PrescriptionReadRow[]
  follow_up_note: string | null
  visit_notes: string
}

export interface PostVisitSummaryData {
  appointment_id: string
  summary_text: string
  medications: {
    name: string
    dosage: string
    frequency: string
    duration: string
    instructions: string
  }[]
  follow_up_note: string | null
  follow_up_days: number | null
  approved_by: string
  approved_at: string
}

// ── Medicine catalog ───────────────────────────────────────────────────────────

export async function searchMedicines(
  q: string,
  statusFilter: 'active' | 'pending' | 'all' = 'active',
): Promise<MedicineCatalogItem[]> {
  const qs = new URLSearchParams({ q, status: statusFilter })
  return apiFetch<MedicineCatalogItem[]>(`/medicine-catalog?${qs}`)
}

export async function createMedicine(payload: {
  name: string
  generic_name?: string
  default_dosage?: string
}): Promise<MedicineCatalogItem> {
  return apiFetch<MedicineCatalogItem>('/medicine-catalog/new', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateMedicineStatus(
  medicineId: string,
  payload: { status: 'active' | 'rejected'; name?: string },
): Promise<MedicineCatalogItem> {
  return apiFetch<MedicineCatalogItem>(`/medicine-catalog/${medicineId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

// ── Consultation ───────────────────────────────────────────────────────────────

export async function submitConsultation(
  appointmentId: string,
  payload: ConsultationPayload,
): Promise<{ id: string; status: string; summary_status: string }> {
  return apiFetch(`/doctor/appointments/${appointmentId}/consultation`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

// ── Summary review (doctor) ───────────────────────────────────────────────────

export async function getSummaryDraft(appointmentId: string): Promise<SummaryDraft> {
  return apiFetch<SummaryDraft>(`/doctor/appointments/${appointmentId}/summary`)
}

export async function approveSummary(
  appointmentId: string,
  editedText: string,
): Promise<{ id: string; summary_status: string; approved_at: string }> {
  return apiFetch(`/doctor/appointments/${appointmentId}/summary/approve`, {
    method: 'PUT',
    body: JSON.stringify({ edited_text: editedText }),
  })
}

// ── Post-visit summary (patient) ───────────────────────────────────────────────

export async function getPostVisitSummary(
  appointmentId: string,
): Promise<PostVisitSummaryData> {
  return apiFetch<PostVisitSummaryData>(
    `/appointments/${appointmentId}/post-visit-summary`,
  )
}

// ─── Phase 6: Notifications & calendar types & endpoints ─────────────────────

export type NotificationEventType =
  | 'booking_confirmed'
  | 'booking_cancelled'
  | 'booking_rescheduled'
  | 'doctor_absent'
  | 'reschedule_offer'
  | 'running_late'
  | 'follow_up_available'
  | 'visit_summary_ready'

export interface AppNotification {
  id: string
  event_type: NotificationEventType
  title: string
  body: string
  is_read: boolean
  appointment_id: string | null
  created_at: string
}

export interface NotificationListResponse {
  unread_count: number
  notifications: AppNotification[]
}

export interface CalendarStatus {
  connected: boolean
  calendar_id: string | null
  connected_at?: string
}

// ── Notifications ─────────────────────────────────────────────────────────────

export async function getNotifications(
  unreadOnly = false,
): Promise<NotificationListResponse> {
  const qs = unreadOnly ? '?unread_only=true' : ''
  return apiFetch<NotificationListResponse>(`/notifications${qs}`)
}

export async function markNotificationRead(notificationId: string): Promise<void> {
  await apiFetch<void>(`/notifications/${notificationId}/read`, { method: 'PATCH' })
}

export async function markAllNotificationsRead(): Promise<{ marked_read: number }> {
  return apiFetch('/notifications/read-all', { method: 'POST' })
}

// ── Google Calendar ───────────────────────────────────────────────────────────

export async function getCalendarStatus(): Promise<CalendarStatus> {
  return apiFetch<CalendarStatus>('/doctor/calendar/status')
}

export async function getCalendarConnectUrl(): Promise<{ auth_url: string }> {
  return apiFetch<{ auth_url: string }>('/doctor/calendar/connect')
}

export async function disconnectCalendar(): Promise<CalendarStatus> {
  return apiFetch<CalendarStatus>('/doctor/calendar/disconnect', { method: 'DELETE' })
}

// ─── Phase 7: Reassignment types ─────────────────────────────────────────────

export interface ReassignedAppointmentDetail extends AppointmentDetail {
  reassignment_note: string
  original_doctor_name: string   // pulled from the original_request chain
}

/** Fetch a reassigned appointment — same endpoint, extra fields populated */
export async function getReassignedAppointment(
  appointmentId: string,
): Promise<ReassignedAppointmentDetail> {
  return apiFetch<ReassignedAppointmentDetail>(`/appointments/${appointmentId}`)
}

// ─── Phase 9: Admin dashboard & patient accounts ──────────────────────────────

export interface DashboardStats {
  date: string
  doctor_count: number
  todays_bookings: number
  pending_medicines: number
  unread_notifications: number
  recent_appointments: {
    appointment_id: string
    patient_name: string
    doctor_name: string
    slot_start: string
    status: string
    token: number | null
  }[]
}

export interface AdminPatient {
  id: string
  name: string
  email: string
  phone: string
  created_at: string
  appointment_count: number
  last_appointment_date: string | null
  last_appointment_status: string | null
}

export async function getDashboardStats(): Promise<DashboardStats> {
  return apiFetch<DashboardStats>('/admin-api/dashboard')
}

export async function listAdminPatients(search?: string): Promise<AdminPatient[]> {
  const qs = search ? `?search=${encodeURIComponent(search)}` : ''
  return apiFetch<AdminPatient[]>(`/admin-api/patients${qs}`)
}
