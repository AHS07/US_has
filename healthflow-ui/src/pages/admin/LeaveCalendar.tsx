/**
 * Admin — Leave Calendar
 *
 * Per-doctor planned leave management. Admins select a doctor from the
 * sidebar list, then see their existing leave days in a timeline view and
 * can add / remove leave entries.
 *
 * Route: /admin/leave
 */
import { useEffect, useState, useCallback } from 'react'
import {
  listDoctors,
  listLeave,
  createLeave,
  deleteLeave,
  type DoctorProfile,
  type DoctorLeave,
  type HFApiError,
} from '@/lib/api'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
}

function isPast(iso: string): boolean {
  return new Date(iso + 'T00:00:00') < new Date(new Date().toDateString())
}

// ─── Leave timeline ───────────────────────────────────────────────────────────

function LeaveTimeline({
  doctor,
}: {
  doctor: DoctorProfile
}) {
  const [leaves, setLeaves]   = useState<DoctorLeave[]>([])
  const [loading, setLoading] = useState(true)
  const [newDate, setNewDate] = useState('')
  const [reason, setReason]   = useState('')
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listLeave(doctor.user_id)
      setLeaves(data.sort((a, b) => a.date.localeCompare(b.date)))
    } catch { /* best effort */ } finally {
      setLoading(false)
    }
  }, [doctor.user_id])

  useEffect(() => { void load() }, [load])

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    if (!newDate) return
    setError('')
    setSaving(true)
    try {
      const leave = await createLeave(doctor.user_id, { date: newDate, reason })
      setLeaves(prev =>
        [...prev, leave].sort((a, b) => a.date.localeCompare(b.date))
      )
      setNewDate('')
      setReason('')
    } catch (err) {
      setError((err as HFApiError).message ?? 'Failed to add leave.')
    } finally {
      setSaving(false)
    }
  }

  async function handleRemove(leaveId: string) {
    try {
      await deleteLeave(doctor.user_id, leaveId)
      setLeaves(prev => prev.filter(l => l.id !== leaveId))
    } catch { /* best effort */ }
  }

  const upcoming = leaves.filter(l => !isPast(l.date))
  const past     = leaves.filter(l => isPast(l.date))

  return (
    <div className="space-y-6">
      {/* Doctor header */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-[#E8E4DA] flex items-center justify-center text-[#697C70] text-base font-bold shrink-0" aria-hidden="true">
          {doctor.name.charAt(0)}
        </div>
        <div>
          <p className="font-semibold text-[#2D3536]">{doctor.name}</p>
          <p className="text-xs text-[#697C70]">{doctor.specialization}</p>
        </div>
      </div>

      {/* Add leave form */}
      <form onSubmit={handleAdd} className="bg-[#F7F6F3] rounded-2xl p-5 space-y-3" noValidate>
        <p className="text-xs font-semibold text-[#2D3536] uppercase tracking-wider">Add leave day</p>
        {error && (
          <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-3 py-2">
            {error}
          </p>
        )}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="leave-date" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider">
              Date
            </label>
            <input
              id="leave-date"
              type="date"
              required
              value={newDate}
              min={new Date().toISOString().slice(0, 10)}
              onChange={e => setNewDate(e.target.value)}
              className="w-full bg-white border border-[#D8D2C4] rounded-xl px-3 py-2.5 text-[#2D3536] focus:outline-none focus:border-[#98AA9D] text-sm"
            />
          </div>
          <div>
            <label htmlFor="leave-reason" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider">
              Reason (optional)
            </label>
            <input
              id="leave-reason"
              type="text"
              placeholder="Conference, personal…"
              value={reason}
              onChange={e => setReason(e.target.value)}
              className="w-full bg-white border border-[#D8D2C4] rounded-xl px-3 py-2.5 text-[#2D3536] focus:outline-none focus:border-[#98AA9D] text-sm placeholder-[#B8B4AC]"
            />
          </div>
        </div>
        <button
          type="submit"
          disabled={!newDate || saving}
          className="w-full bg-[#98AA9D] text-white rounded-xl py-2.5 font-semibold text-sm hover:bg-[#7A9080] transition-colors disabled:opacity-60"
        >
          {saving ? 'Adding…' : 'Add leave day'}
        </button>
      </form>

      {/* Upcoming leave */}
      <div>
        <p className="text-xs font-semibold text-[#2D3536] uppercase tracking-wider mb-3">
          Upcoming leave ({upcoming.length})
        </p>
        {loading ? (
          <p className="text-sm text-[#697C70]">Loading…</p>
        ) : upcoming.length === 0 ? (
          <p className="text-sm text-[#697C70]">No upcoming leave days.</p>
        ) : (
          <ul className="space-y-2">
            {upcoming.map(l => (
              <li
                key={l.id}
                className="flex items-center justify-between bg-white border border-[#E8E4DA] rounded-xl px-4 py-3"
              >
                <div>
                  <p className="text-sm font-medium text-[#2D3536]">{formatDate(l.date)}</p>
                  {l.reason && (
                    <p className="text-xs text-[#697C70] mt-0.5">{l.reason}</p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => handleRemove(l.id)}
                  className="text-xs text-[#697C70] hover:text-[#8B1A1A] transition-colors font-medium ml-4 shrink-0"
                  aria-label={`Remove leave on ${l.date}`}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Past leave (read-only) */}
      {past.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-[#A0A09A] uppercase tracking-wider mb-3">
            Past leave ({past.length})
          </p>
          <ul className="space-y-1.5">
            {past.map(l => (
              <li
                key={l.id}
                className="flex items-center justify-between bg-[#F7F6F3] rounded-xl px-4 py-2.5 opacity-60"
              >
                <p className="text-sm text-[#697C70] font-mono">{l.date}</p>
                {l.reason && <p className="text-xs text-[#A0A09A]">{l.reason}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function LeaveCalendar() {
  const [doctors, setDoctors]         = useState<DoctorProfile[]>([])
  const [loading, setLoading]         = useState(true)
  const [selected, setSelected]       = useState<DoctorProfile | null>(null)
  const [search, setSearch]           = useState('')

  useEffect(() => {
    setLoading(true)
    listDoctors()
      .then(data => {
        setDoctors(data)
        if (data.length > 0) setSelected(data[0])
      })
      .catch(() => { /* best effort */ })
      .finally(() => setLoading(false))
  }, [])

  const filtered = doctors.filter(d =>
    !search ||
    d.name.toLowerCase().includes(search.toLowerCase()) ||
    d.specialization.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="flex gap-6 h-full">
      {/* Doctor sidebar */}
      <div className="w-56 shrink-0 flex flex-col gap-2">
        <div className="relative mb-1">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 text-[#A0A09A]" width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" strokeLinecap="round" />
          </svg>
          <input
            type="search"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search…"
            aria-label="Search doctors"
            className="w-full bg-white border border-[#D8D2C4] rounded-xl pl-8 pr-3 py-2 text-xs text-[#2D3536] placeholder-[#B8B4AC] focus:outline-none focus:border-[#98AA9D]"
          />
        </div>

        {loading ? (
          <p className="text-xs text-[#697C70] px-1">Loading…</p>
        ) : filtered.length === 0 ? (
          <p className="text-xs text-[#697C70] px-1">No doctors found.</p>
        ) : (
          <nav aria-label="Select doctor">
            {filtered.map(d => (
              <button
                key={d.user_id}
                type="button"
                onClick={() => setSelected(d)}
                className={`w-full text-left flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm font-medium transition-all mb-0.5 ${
                  selected?.user_id === d.user_id
                    ? 'bg-[#EEF3EF] text-[#697C70]'
                    : 'text-[#A0A09A] hover:text-[#2D3536] hover:bg-[#F2EFE2]'
                }`}
                aria-current={selected?.user_id === d.user_id ? 'true' : undefined}
              >
                <div
                  className="w-6 h-6 rounded-full bg-[#E8E4DA] flex items-center justify-center text-[#697C70] text-xs font-bold shrink-0"
                  aria-hidden="true"
                >
                  {d.name.charAt(0)}
                </div>
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium">{d.name}</p>
                  <p className="truncate text-[10px] text-[#A0A09A]">{d.specialization}</p>
                </div>
              </button>
            ))}
          </nav>
        )}
      </div>

      {/* Leave detail */}
      <div className="flex-1 bg-white border border-[#E8E4DA] rounded-2xl p-6 overflow-y-auto">
        {!selected ? (
          <p className="text-sm text-[#697C70]">Select a doctor to manage their leave.</p>
        ) : (
          <LeaveTimeline key={selected.user_id} doctor={selected} />
        )}
      </div>
    </div>
  )
}
