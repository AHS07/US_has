/**
 * Admin — Doctor Management
 *
 * Lists all doctors at the hospital with their specialization, shift hours,
 * slot settings, and active status. From here the admin can:
 *   - Add a new doctor (slide-over)
 *   - Edit shift config (nested slide-over)
 *   - View / add / delete leave days (nested slide-over)
 *   - Generate slots for a date range
 *   - Toggle is_active
 */
import { useEffect, useState, useCallback } from 'react'
import {
  listDoctors,
  createDoctor,
  putShiftConfig,
  patchDoctorProfile,
  listLeave,
  createLeave,
  deleteLeave,
  generateSlots,
  type DoctorProfile,
  type DoctorLeave,
  type HFApiError,
} from '@/lib/api'

// ─── Types ────────────────────────────────────────────────────────────────────

type Drawer =
  | { type: 'none' }
  | { type: 'add' }
  | { type: 'shift'; doctor: DoctorProfile }
  | { type: 'leave'; doctor: DoctorProfile }
  | { type: 'generate'; doctor: DoctorProfile }

// ─── Helpers ─────────────────────────────────────────────────────────────────

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function shiftSummary(d: DoctorProfile): string {
  if (!d.shift_config) return 'Not configured'
  const { shift_1_start, shift_1_end, shift_2_start, shift_2_end } = d.shift_config
  return `${shift_1_start.slice(0, 5)}–${shift_1_end.slice(0, 5)} / ${shift_2_start.slice(0, 5)}–${shift_2_end.slice(0, 5)}`
}

function workingDaysLabel(days: number[]): string {
  if (!days?.length) return '—'
  return days.map(d => DAYS[d - 1]).join(', ')
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function SlideOver({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div
      className="fixed inset-0 z-50 flex"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      {/* Backdrop */}
      <div
        className="flex-1 bg-black/30"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* Panel */}
      <div className="w-full max-w-lg bg-white h-full overflow-y-auto shadow-2xl flex flex-col">
        <div className="px-6 py-5 border-b border-[#E8E4DA] flex items-center justify-between shrink-0">
          <h2 className="font-semibold text-[#2D3536]">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-[#697C70] hover:text-[#2D3536] transition-colors p-1 rounded-lg hover:bg-[#F2EFE2]"
            aria-label="Close"
          >
            <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
              <path d="M18 6 6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="flex-1 p-6">{children}</div>
      </div>
    </div>
  )
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider font-medium">
      {children}
    </label>
  )
}

function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className="w-full bg-[#F7F6F3] border border-[#D8D2C4] rounded-xl px-4 py-2.5 text-[#2D3536] placeholder-[#B8B4AC] focus:outline-none focus:border-[#98AA9D] focus:ring-2 focus:ring-[#98AA9D]/20 text-sm transition-all"
    />
  )
}

function PrimaryBtn({ loading, children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={loading || props.disabled}
      className="w-full bg-[#98AA9D] text-white rounded-xl py-3 font-semibold text-sm hover:bg-[#7A9080] transition-colors disabled:opacity-60 mt-2"
    >
      {loading ? 'Saving…' : children}
    </button>
  )
}

function ErrorBanner({ msg }: { msg: string }) {
  return (
    <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3 mb-4">
      {msg}
    </p>
  )
}

// ─── Add Doctor Drawer ────────────────────────────────────────────────────────

function AddDoctorDrawer({ onClose, onCreated }: { onClose: () => void; onCreated: (d: DoctorProfile) => void }) {
  const [form, setForm] = useState({ name: '', email: '', phone: '', specialization: '' })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const doc = await createDoctor(form)
      onCreated(doc)
      onClose()
    } catch (err) {
      setError((err as HFApiError).message ?? 'Failed to create doctor.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <SlideOver title="Add new doctor" onClose={onClose}>
      {error && <ErrorBanner msg={error} />}
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <div>
          <FieldLabel>Full name</FieldLabel>
          <TextInput
            type="text" required placeholder="Dr. Firstname Lastname"
            value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
          />
        </div>
        <div>
          <FieldLabel>Email address</FieldLabel>
          <TextInput
            type="email" required placeholder="doctor@hospital.in"
            value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
          />
        </div>
        <div>
          <FieldLabel>Phone (optional)</FieldLabel>
          <TextInput
            type="tel" placeholder="+91 98765 43210"
            value={form.phone} onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
          />
        </div>
        <div>
          <FieldLabel>Specialization</FieldLabel>
          <TextInput
            type="text" required placeholder="e.g. General Physician"
            value={form.specialization} onChange={e => setForm(f => ({ ...f, specialization: e.target.value }))}
          />
        </div>
        <div className="pt-2 text-xs text-[#697C70] bg-[#F7F6F3] rounded-xl px-4 py-3">
          A temporary password will be emailed to the doctor. They must reset it on first login.
          Shift hours and slot settings can be configured after creation.
        </div>
        <PrimaryBtn type="submit" loading={loading}>
          Add doctor and send credentials
        </PrimaryBtn>
      </form>
    </SlideOver>
  )
}

// ─── Shift Config Drawer ──────────────────────────────────────────────────────

function ShiftConfigDrawer({ doctor, onClose, onSaved }: { doctor: DoctorProfile; onClose: () => void; onSaved: (d: DoctorProfile) => void }) {
  const existing = doctor.shift_config
  const [form, setForm] = useState({
    shift_1_start:         existing?.shift_1_start?.slice(0, 5) ?? '09:00',
    shift_1_end:           existing?.shift_1_end?.slice(0, 5)   ?? '13:00',
    shift_2_start:         existing?.shift_2_start?.slice(0, 5) ?? '14:00',
    shift_2_end:           existing?.shift_2_end?.slice(0, 5)   ?? '17:00',
    working_days:          existing?.working_days ?? [1, 2, 3, 4, 5],
    slot_duration_minutes: existing?.slot_duration_minutes ?? doctor.slot_duration_minutes,
    slot_capacity:         existing?.slot_capacity ?? doctor.slot_capacity,
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [generateRange, setGenerateRange] = useState({ from: '', to: '' })
  const [genResult, setGenResult] = useState<{ created: number; guarded: number } | null>(null)
  const [genLoading, setGenLoading] = useState(false)

  function toggleDay(day: number) {
    setForm(f => ({
      ...f,
      working_days: f.working_days.includes(day)
        ? f.working_days.filter(d => d !== day)
        : [...f.working_days, day].sort(),
    }))
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const updated = await putShiftConfig(doctor.user_id, form)
      onSaved(updated)
      onClose()
    } catch (err) {
      setError((err as HFApiError).message ?? 'Failed to save shift config.')
    } finally {
      setLoading(false)
    }
  }

  async function handleGenerate() {
    if (!generateRange.from || !generateRange.to) return
    setGenLoading(true)
    setGenResult(null)
    try {
      const r = await generateSlots(doctor.user_id, { date_from: generateRange.from, date_to: generateRange.to })
      setGenResult(r)
    } catch (err) {
      setError((err as HFApiError).message ?? 'Slot generation failed.')
    } finally {
      setGenLoading(false)
    }
  }

  return (
    <SlideOver title={`Shift config — ${doctor.name}`} onClose={onClose}>
      {error && <ErrorBanner msg={error} />}
      <form onSubmit={handleSave} className="space-y-5" noValidate>
        {/* Shift 1 */}
        <div>
          <p className="text-xs font-semibold text-[#2D3536] uppercase tracking-wider mb-3">Morning shift</p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <FieldLabel>Start</FieldLabel>
              <TextInput type="time" required value={form.shift_1_start}
                onChange={e => setForm(f => ({ ...f, shift_1_start: e.target.value }))} />
            </div>
            <div>
              <FieldLabel>End</FieldLabel>
              <TextInput type="time" required value={form.shift_1_end}
                onChange={e => setForm(f => ({ ...f, shift_1_end: e.target.value }))} />
            </div>
          </div>
        </div>

        {/* Shift 2 */}
        <div>
          <p className="text-xs font-semibold text-[#2D3536] uppercase tracking-wider mb-3">Afternoon shift</p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <FieldLabel>Start</FieldLabel>
              <TextInput type="time" required value={form.shift_2_start}
                onChange={e => setForm(f => ({ ...f, shift_2_start: e.target.value }))} />
            </div>
            <div>
              <FieldLabel>End</FieldLabel>
              <TextInput type="time" required value={form.shift_2_end}
                onChange={e => setForm(f => ({ ...f, shift_2_end: e.target.value }))} />
            </div>
          </div>
        </div>

        {/* Working days */}
        <div>
          <FieldLabel>Working days</FieldLabel>
          <div className="flex gap-2 flex-wrap mt-1">
            {DAYS.map((label, i) => {
              const day = i + 1
              const active = form.working_days.includes(day)
              return (
                <button
                  key={day}
                  type="button"
                  onClick={() => toggleDay(day)}
                  aria-pressed={active}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                    active
                      ? 'bg-[#98AA9D] text-white border-[#98AA9D]'
                      : 'bg-white text-[#697C70] border-[#D8D2C4] hover:border-[#98AA9D]'
                  }`}
                >
                  {label}
                </button>
              )
            })}
          </div>
        </div>

        {/* Slot settings */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <FieldLabel>Slot duration (min)</FieldLabel>
            <select
              value={form.slot_duration_minutes}
              onChange={e => setForm(f => ({ ...f, slot_duration_minutes: Number(e.target.value) }))}
              className="w-full bg-[#F7F6F3] border border-[#D8D2C4] rounded-xl px-4 py-2.5 text-[#2D3536] focus:outline-none focus:border-[#98AA9D] text-sm"
            >
              {[15, 20, 30, 45, 60, 90, 120].map(v => (
                <option key={v} value={v}>{v} min</option>
              ))}
            </select>
          </div>
          <div>
            <FieldLabel>Patients per slot</FieldLabel>
            <TextInput
              type="number" min={1} max={50} required
              value={form.slot_capacity}
              onChange={e => setForm(f => ({ ...f, slot_capacity: Number(e.target.value) }))}
            />
          </div>
        </div>

        <PrimaryBtn type="submit" loading={loading}>Save shift config</PrimaryBtn>

        {/* Slot generation */}
        <div className="border-t border-[#E8E4DA] pt-5 mt-1">
          <p className="text-xs font-semibold text-[#2D3536] uppercase tracking-wider mb-3">Generate slots</p>
          <p className="text-xs text-[#697C70] mb-3">
            Pre-generates appointment slots from the saved config. Existing booked slots are never touched.
          </p>
          <div className="grid grid-cols-2 gap-3 mb-3">
            <div>
              <FieldLabel>From</FieldLabel>
              <TextInput type="date" value={generateRange.from}
                onChange={e => setGenerateRange(r => ({ ...r, from: e.target.value }))} />
            </div>
            <div>
              <FieldLabel>To</FieldLabel>
              <TextInput type="date" value={generateRange.to}
                onChange={e => setGenerateRange(r => ({ ...r, to: e.target.value }))} />
            </div>
          </div>
          {genResult && (
            <div className="bg-[#EEF3EF] rounded-xl px-4 py-3 mb-3 text-xs text-[#2D3536]">
              Generated {genResult.created} slot{genResult.created !== 1 ? 's' : ''}.
              {genResult.guarded > 0 && ` ${genResult.guarded} booked slot${genResult.guarded !== 1 ? 's' : ''} left untouched.`}
            </div>
          )}
          <button
            type="button"
            disabled={!generateRange.from || !generateRange.to || genLoading}
            onClick={handleGenerate}
            className="w-full bg-[#2D3536] text-white rounded-xl py-2.5 font-semibold text-sm hover:bg-[#3D4546] transition-colors disabled:opacity-50"
          >
            {genLoading ? 'Generating…' : 'Generate slots for range'}
          </button>
        </div>
      </form>
    </SlideOver>
  )
}

// ─── Leave Drawer ─────────────────────────────────────────────────────────────

function LeaveDrawer({ doctor, onClose }: { doctor: DoctorProfile; onClose: () => void }) {
  const [leaves, setLeaves] = useState<DoctorLeave[]>([])
  const [loading, setLoading] = useState(true)
  const [newDate, setNewDate] = useState('')
  const [newReason, setNewReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const loadLeaves = useCallback(async () => {
    try {
      const data = await listLeave(doctor.user_id)
      setLeaves(data)
    } catch { /* best effort */ } finally {
      setLoading(false)
    }
  }, [doctor.user_id])

  useEffect(() => { void loadLeaves() }, [loadLeaves])

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    if (!newDate) return
    setError('')
    setSaving(true)
    try {
      const leave = await createLeave(doctor.user_id, { date: newDate, reason: newReason })
      setLeaves(l => [...l, leave].sort((a, b) => a.date.localeCompare(b.date)))
      setNewDate('')
      setNewReason('')
    } catch (err) {
      setError((err as HFApiError).message ?? 'Failed to add leave.')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(leaveId: string) {
    try {
      await deleteLeave(doctor.user_id, leaveId)
      setLeaves(l => l.filter(x => x.id !== leaveId))
    } catch { /* best effort */ }
  }

  return (
    <SlideOver title={`Leave — ${doctor.name}`} onClose={onClose}>
      {error && <ErrorBanner msg={error} />}

      {/* Add new leave */}
      <form onSubmit={handleAdd} className="space-y-3 mb-6" noValidate>
        <p className="text-xs font-semibold text-[#2D3536] uppercase tracking-wider">Add leave day</p>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <FieldLabel>Date</FieldLabel>
            <TextInput
              type="date" required value={newDate}
              min={new Date().toISOString().slice(0, 10)}
              onChange={e => setNewDate(e.target.value)}
            />
          </div>
          <div>
            <FieldLabel>Reason (optional)</FieldLabel>
            <TextInput
              type="text" placeholder="Conference, personal…"
              value={newReason} onChange={e => setNewReason(e.target.value)}
            />
          </div>
        </div>
        <PrimaryBtn type="submit" loading={saving} disabled={!newDate}>
          Add leave day
        </PrimaryBtn>
      </form>

      {/* Existing leave list */}
      <div>
        <p className="text-xs font-semibold text-[#2D3536] uppercase tracking-wider mb-3">
          Scheduled leave ({leaves.length})
        </p>
        {loading ? (
          <p className="text-sm text-[#697C70]">Loading…</p>
        ) : leaves.length === 0 ? (
          <p className="text-sm text-[#697C70]">No leave days scheduled.</p>
        ) : (
          <ul className="space-y-2">
            {leaves.map(l => (
              <li
                key={l.id}
                className="flex items-center justify-between bg-[#F7F6F3] rounded-xl px-4 py-3"
              >
                <div>
                  <p className="text-sm font-medium text-[#2D3536] font-mono">{l.date}</p>
                  {l.reason && <p className="text-xs text-[#697C70] mt-0.5">{l.reason}</p>}
                </div>
                <button
                  type="button"
                  onClick={() => handleDelete(l.id)}
                  className="text-[#697C70] hover:text-[#8B1A1A] transition-colors text-xs font-medium"
                  aria-label={`Remove leave on ${l.date}`}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </SlideOver>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function DoctorManagement() {
  const [doctors, setDoctors] = useState<DoctorProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [drawer, setDrawer] = useState<Drawer>({ type: 'none' })

  const loadDoctors = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listDoctors()
      setDoctors(data)
    } catch { /* best effort */ } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void loadDoctors() }, [loadDoctors])

  const filtered = doctors.filter(d =>
    !search ||
    d.name.toLowerCase().includes(search.toLowerCase()) ||
    d.specialization.toLowerCase().includes(search.toLowerCase())
  )

  function handleCreated(doc: DoctorProfile) {
    setDoctors(prev => [...prev, doc])
  }

  function handleSaved(updated: DoctorProfile) {
    setDoctors(prev => prev.map(d => d.user_id === updated.user_id ? updated : d))
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-[#2D3536]">Doctor management</h2>
          <p className="text-xs text-[#697C70] mt-0.5">
            {loading ? 'Loading…' : `${doctors.length} doctor${doctors.length !== 1 ? 's' : ''}`}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setDrawer({ type: 'add' })}
          className="flex items-center gap-2 bg-[#98AA9D] text-white text-sm px-4 py-2 rounded-xl font-medium hover:bg-[#7A9080] transition-colors"
        >
          <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
            <path d="M12 5v14M5 12h14" strokeLinecap="round" />
          </svg>
          Add doctor
        </button>
      </div>

      {/* Search */}
      <div className="relative">
        <svg className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#A0A09A]" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" strokeLinecap="round" />
        </svg>
        <input
          type="search"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search by name or specialization…"
          aria-label="Search doctors"
          className="w-full bg-white border border-[#D8D2C4] rounded-xl pl-9 pr-4 py-2.5 text-[#2D3536] placeholder-[#B8B4AC] focus:outline-none focus:border-[#98AA9D] text-sm transition-all"
        />
      </div>

      {/* Table */}
      <div className="bg-white border border-[#E8E4DA] rounded-2xl overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-sm text-[#697C70]">Loading doctors…</div>
        ) : filtered.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-sm text-[#697C70]">
              {search ? 'No doctors match your search.' : 'No doctors yet. Add one to get started.'}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[700px]">
              <thead>
                <tr className="bg-[#F7F6F3] text-[10px] text-[#697C70] uppercase tracking-wider">
                  <th className="px-5 py-3 text-left font-medium">Doctor</th>
                  <th className="px-4 py-3 text-left font-medium">Specialization</th>
                  <th className="px-4 py-3 text-left font-medium">Shift hours</th>
                  <th className="px-4 py-3 text-left font-medium">Working days</th>
                  <th className="px-4 py-3 text-center font-medium">Cap/slot</th>
                  <th className="px-4 py-3 text-center font-medium">Duration</th>
                  <th className="px-4 py-3 text-center font-medium">Status</th>
                  <th className="px-4 py-3 text-left font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F2EFE2]">
                {filtered.map(doc => (
                  <tr key={doc.user_id} className="hover:bg-[#F7F6F3] transition-colors">
                    {/* Doctor */}
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-2.5">
                        <div
                          className="w-8 h-8 rounded-full bg-[#E8E4DA] flex items-center justify-center text-[#697C70] text-sm font-bold shrink-0"
                          aria-hidden="true"
                        >
                          {doc.name.charAt(0)}
                        </div>
                        <div>
                          <p className="font-medium text-[#2D3536]">{doc.name}</p>
                          <p className="text-xs text-[#A0A09A]">{doc.email}</p>
                        </div>
                      </div>
                    </td>
                    {/* Specialization */}
                    <td className="px-4 py-3.5 text-[#697C70]">{doc.specialization}</td>
                    {/* Shift hours */}
                    <td className="px-4 py-3.5 text-[#697C70] font-mono text-xs">
                      {shiftSummary(doc)}
                    </td>
                    {/* Working days */}
                    <td className="px-4 py-3.5 text-[#697C70] text-xs">
                      {doc.shift_config ? workingDaysLabel(doc.shift_config.working_days) : '—'}
                    </td>
                    {/* Capacity */}
                    <td className="px-4 py-3.5 text-center font-mono text-[#2D3536]">
                      {doc.slot_capacity}
                    </td>
                    {/* Duration */}
                    <td className="px-4 py-3.5 text-center text-[#697C70] text-xs">
                      {doc.slot_duration_minutes} min
                    </td>
                    {/* Status */}
                    <td className="px-4 py-3.5 text-center">
                      <span className={`text-[11px] font-medium px-2.5 py-0.5 rounded-full ${
                        doc.is_active
                          ? 'bg-[#EEF3EF] text-[#697C70]'
                          : 'bg-[#F5D0CC] text-[#8B1A1A]'
                      }`}>
                        {doc.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    {/* Actions */}
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-3 text-xs">
                        <button
                          type="button"
                          onClick={() => setDrawer({ type: 'shift', doctor: doc })}
                          className="text-[#697C70] hover:text-[#2D3536] transition-colors font-medium"
                        >
                          Shifts
                        </button>
                        <span className="text-[#E8E4DA]" aria-hidden="true">·</span>
                        <button
                          type="button"
                          onClick={() => setDrawer({ type: 'leave', doctor: doc })}
                          className="text-[#697C70] hover:text-[#2D3536] transition-colors font-medium"
                        >
                          Leave
                        </button>
                        <span className="text-[#E8E4DA]" aria-hidden="true">·</span>
                        <button
                          type="button"
                          onClick={async () => {
                            await patchDoctorProfile(doc.user_id, { is_active: !doc.is_active })
                            setDoctors(prev => prev.map(d =>
                              d.user_id === doc.user_id ? { ...d, is_active: !d.is_active } : d
                            ))
                          }}
                          className="text-[#697C70] hover:text-[#2D3536] transition-colors font-medium"
                        >
                          {doc.is_active ? 'Deactivate' : 'Activate'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Drawers */}
      {drawer.type === 'add' && (
        <AddDoctorDrawer
          onClose={() => setDrawer({ type: 'none' })}
          onCreated={handleCreated}
        />
      )}
      {drawer.type === 'shift' && (
        <ShiftConfigDrawer
          doctor={drawer.doctor}
          onClose={() => setDrawer({ type: 'none' })}
          onSaved={handleSaved}
        />
      )}
      {drawer.type === 'leave' && (
        <LeaveDrawer
          doctor={drawer.doctor}
          onClose={() => setDrawer({ type: 'none' })}
        />
      )}
    </div>
  )
}
