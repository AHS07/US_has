/**
 * Admin — Attendance Sheet
 *
 * Shows every active doctor's morning/afternoon status for a selected date.
 * Default = present (no DB row). Toggling absent upserts a record.
 * Toggling back to present deletes it.
 *
 * Cascade note: marking a doctor absent in Phase 7 will cancel their bookings.
 * The warning banner here surfaces that consequence to the admin before they save.
 */
import { useEffect, useState, useCallback } from 'react'
import {
  getAttendanceSheet,
  markAttendance,
  type AttendanceDoctor,
  type HFApiError,
} from '@/lib/api'

type HalfStatus = 'present' | 'absent' | 'on_leave'

interface LocalRow extends AttendanceDoctor {
  pendingMorning?: HalfStatus
  pendingAfternoon?: HalfStatus
}

function statusChip(status: HalfStatus, onClick?: () => void): React.ReactNode {
  const base = 'text-xs font-medium px-3 py-1.5 rounded-lg transition-all'

  if (status === 'on_leave') {
    return (
      <span className={`${base} bg-[#F5D0CC] text-[#8B1A1A] cursor-default`}>
        On leave
      </span>
    )
  }

  if (status === 'absent') {
    return (
      <button
        type="button"
        onClick={onClick}
        className={`${base} bg-[#FDE8C0] text-[#7A4A00] hover:bg-[#FBCF7A]/50`}
      >
        Absent
      </button>
    )
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className={`${base} bg-[#EEF3EF] text-[#697C70] hover:bg-[#D8E8D8]`}
    >
      Present
    </button>
  )
}

export default function AttendanceSheet() {
  const todayIso = new Date().toISOString().slice(0, 10)
  const [date, setDate]     = useState(todayIso)
  const [rows, setRows]     = useState<LocalRow[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving]   = useState<string | null>(null)  // doctor_id being saved
  const [error, setError]     = useState('')
  const [search, setSearch]   = useState('')

  const loadSheet = useCallback(async (d: string) => {
    setLoading(true)
    setError('')
    try {
      const sheet = await getAttendanceSheet(d)
      setRows(sheet.doctors.map(doc => ({ ...doc })))
    } catch (err) {
      setError((err as HFApiError).message ?? 'Failed to load attendance.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void loadSheet(date) }, [date, loadSheet])

  async function toggle(doctorId: string, shift: 'morning' | 'afternoon') {
    const row = rows.find(r => r.doctor_id === doctorId)
    if (!row || row.on_leave) return

    const currentStatus = shift === 'morning' ? row.morning_status : row.afternoon_status
    if (currentStatus === 'on_leave') return

    const newStatus: HalfStatus = currentStatus === 'absent' ? 'present' : 'absent'

    // Optimistic update
    setRows(prev => prev.map(r =>
      r.doctor_id !== doctorId ? r : {
        ...r,
        morning_status:   shift === 'morning'   ? newStatus : r.morning_status,
        afternoon_status: shift === 'afternoon' ? newStatus : r.afternoon_status,
      }
    ))

    setSaving(doctorId)
    try {
      await markAttendance(doctorId, { date, shift, status: newStatus })
    } catch (err) {
      // Roll back on failure
      setRows(prev => prev.map(r =>
        r.doctor_id !== doctorId ? r : {
          ...r,
          morning_status:   shift === 'morning'   ? currentStatus : r.morning_status,
          afternoon_status: shift === 'afternoon' ? currentStatus : r.afternoon_status,
        }
      ))
      setError((err as HFApiError).message ?? 'Failed to mark attendance.')
    } finally {
      setSaving(null)
    }
  }

  const filtered = rows.filter(r =>
    !search ||
    r.name.toLowerCase().includes(search.toLowerCase()) ||
    r.specialization.toLowerCase().includes(search.toLowerCase())
  )

  const absentCount = rows.filter(
    r => !r.on_leave && (r.morning_status === 'absent' || r.afternoon_status === 'absent')
  ).length

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-[#2D3536]">Attendance sheet</h2>
          <p className="text-xs text-[#697C70] mt-0.5">
            Defaults to present. Toggle a half-day to mark absent. Changes save immediately.
          </p>
        </div>
        <input
          type="date"
          value={date}
          onChange={e => setDate(e.target.value)}
          aria-label="Select attendance date"
          className="bg-white border border-[#D8D2C4] rounded-xl px-3 py-2 text-sm text-[#2D3536] focus:outline-none focus:border-[#98AA9D] shrink-0"
        />
      </div>

      {/* Error */}
      {error && (
        <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3">
          {error}
        </p>
      )}

      {/* Cascade warning — only when someone is marked absent */}
      {absentCount > 0 && (
        <div className="bg-[#FDE8C0]/50 border border-[#FDE8C0] rounded-xl px-4 py-3" role="note">
          <p className="text-xs text-[#7A4A00] leading-relaxed">
            <strong>{absentCount} doctor{absentCount !== 1 ? 's' : ''}</strong> marked absent.
            When Phase 7 is active, this will cancel their bookings for the affected shift and
            notify all affected patients. Confirm absence only when certain.
          </p>
        </div>
      )}

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
          <div className="p-8 text-center text-sm text-[#697C70]">Loading attendance…</div>
        ) : filtered.length === 0 ? (
          <div className="p-8 text-center text-sm text-[#697C70]">
            {search ? 'No doctors match your search.' : 'No doctors found for this hospital.'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="bg-[#F7F6F3] text-[10px] text-[#697C70] uppercase tracking-wider">
                  <th className="px-5 py-3 text-left font-medium">Doctor</th>
                  <th className="px-4 py-3 text-left font-medium">Specialization</th>
                  <th className="px-4 py-3 text-left font-medium">Shift hours</th>
                  <th className="px-4 py-3 text-center font-medium">Morning</th>
                  <th className="px-4 py-3 text-center font-medium">Afternoon</th>
                  <th className="px-4 py-3 text-center font-medium">Overall</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F2EFE2]">
                {filtered.map(row => {
                  const isSaving = saving === row.doctor_id

                  return (
                    <tr
                      key={row.doctor_id}
                      className={`transition-colors ${isSaving ? 'opacity-60' : 'hover:bg-[#F7F6F3]'}`}
                    >
                      {/* Doctor */}
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-2.5">
                          <div
                            className="w-7 h-7 rounded-full bg-[#E8E4DA] flex items-center justify-center text-[#697C70] text-xs font-bold shrink-0"
                            aria-hidden="true"
                          >
                            {row.name.charAt(0)}
                          </div>
                          <span className="font-medium text-[#2D3536]">{row.name}</span>
                        </div>
                      </td>
                      {/* Specialization */}
                      <td className="px-4 py-3.5 text-[#697C70]">{row.specialization}</td>
                      {/* Shifts */}
                      <td className="px-4 py-3.5 text-[#697C70] font-mono text-xs">{row.shifts}</td>
                      {/* Morning */}
                      <td className="px-4 py-3.5 text-center">
                        {statusChip(
                          row.morning_status,
                          row.on_leave ? undefined : () => toggle(row.doctor_id, 'morning'),
                        )}
                      </td>
                      {/* Afternoon */}
                      <td className="px-4 py-3.5 text-center">
                        {statusChip(
                          row.afternoon_status,
                          row.on_leave ? undefined : () => toggle(row.doctor_id, 'afternoon'),
                        )}
                      </td>
                      {/* Overall status badge */}
                      <td className="px-4 py-3.5 text-center">
                        <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${
                          row.on_leave
                            ? 'bg-[#F5D0CC] text-[#8B1A1A]'
                            : row.morning_status === 'absent' || row.afternoon_status === 'absent'
                            ? 'bg-[#FDE8C0] text-[#7A4A00]'
                            : 'bg-[#EEF3EF] text-[#697C70]'
                        }`}>
                          {row.on_leave
                            ? 'On leave'
                            : row.morning_status === 'absent' && row.afternoon_status === 'absent'
                            ? 'Absent (full day)'
                            : row.morning_status === 'absent' || row.afternoon_status === 'absent'
                            ? 'Partial absence'
                            : 'Present'}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 text-xs text-[#697C70]">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm bg-[#EEF3EF] border border-[#C8D8C8]" aria-hidden="true" />
          Present (default)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm bg-[#FDE8C0] border border-[#F5C84A]" aria-hidden="true" />
          Absent (click to toggle)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm bg-[#F5D0CC] border border-[#EBB0AC]" aria-hidden="true" />
          On planned leave
        </span>
      </div>
    </div>
  )
}
