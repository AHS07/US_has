/**
 * Admin — Dashboard
 *
 * Hospital-scoped overview: stat cards + today's appointment activity.
 * All data is scoped to the admin's hospital on the backend.
 *
 * Route: /admin/dashboard
 */
import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { getDashboardStats, type DashboardStats, type HFApiError } from '@/lib/api'

// ─── Stat card ────────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  icon,
  accent,
  onClick,
}: {
  label: string
  value: number | string
  icon: React.ReactNode
  accent: string
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      className={`w-full text-left bg-white border border-[#E8E4DA] rounded-2xl p-5 transition-all ${
        onClick ? 'hover:border-[#98AA9D] hover:bg-[#F5F8F5] cursor-pointer' : 'cursor-default'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[10px] text-[#A0A09A] uppercase tracking-wider font-medium mb-1.5">
            {label}
          </p>
          <p className={`text-3xl font-bold font-mono ${accent}`}>{value}</p>
        </div>
        <div
          className="w-10 h-10 rounded-xl bg-[#F7F6F3] flex items-center justify-center shrink-0"
          aria-hidden="true"
        >
          {icon}
        </div>
      </div>
    </button>
  )
}

// ─── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ s }: { s: string }) {
  const map: Record<string, string> = {
    confirmed:  'bg-[#EEF3EF] text-[#697C70]',
    completed:  'bg-[#D6E8F0] text-[#2A6080]',
    held:       'bg-[#FDE8C0] text-[#7A4A00]',
    cancelled:  'bg-[#F5D0CC] text-[#8B1A1A]',
    no_show:    'bg-[#F5D0CC] text-[#8B1A1A]',
    reassigned: 'bg-[#FDE8C0] text-[#7A4A00]',
  }
  const label: Record<string, string> = {
    confirmed: 'Confirmed', completed: 'Completed', held: 'Hold',
    cancelled: 'Cancelled', no_show: 'No show', reassigned: 'Reassigned',
  }
  return (
    <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${map[s] ?? 'bg-[#F2EFE2] text-[#697C70]'}`}>
      {label[s] ?? s}
    </span>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function Dashboard() {
  const navigate = useNavigate()
  const [stats,   setStats]   = useState<DashboardStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getDashboardStats()
      setStats(data)
    } catch (err) {
      setError((err as HFApiError).message ?? 'Failed to load dashboard.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const today = new Date().toLocaleDateString('en-IN', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-[#2D3536]">Dashboard</h2>
        <p className="text-xs text-[#697C70] mt-0.5">{today}</p>
      </div>

      {/* Error */}
      {error && (
        <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3">
          {error}
        </p>
      )}

      {/* Stat cards */}
      {loading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="h-28 rounded-2xl bg-[#E8E4DA] animate-pulse" />
          ))}
        </div>
      ) : stats ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            label="Today's bookings"
            value={stats.todays_bookings}
            accent="text-[#2D3536]"
            onClick={() => navigate('/admin/attendance')}
            icon={
              <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="#98AA9D" strokeWidth="1.8" aria-hidden="true">
                <rect x="3" y="4" width="18" height="18" rx="2" />
                <path d="M16 2v4M8 2v4M3 10h18M9 16l2 2 4-4" strokeLinecap="round" />
              </svg>
            }
          />
          <StatCard
            label="Active doctors"
            value={stats.doctor_count}
            accent="text-[#2D3536]"
            onClick={() => navigate('/admin/doctors')}
            icon={
              <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="#98AA9D" strokeWidth="1.8" aria-hidden="true">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                <circle cx="9" cy="7" r="4" />
                <path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" strokeLinecap="round" />
              </svg>
            }
          />
          <StatCard
            label="Pending medicines"
            value={stats.pending_medicines}
            accent={stats.pending_medicines > 0 ? 'text-[#7A4A00]' : 'text-[#2D3536]'}
            onClick={stats.pending_medicines > 0 ? () => navigate('/admin/medicine-catalog') : undefined}
            icon={
              <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke={stats.pending_medicines > 0 ? '#E8A838' : '#98AA9D'} strokeWidth="1.8" aria-hidden="true">
                <path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2v-4M9 21H5a2 2 0 0 1-2-2v-4m0 0h18" strokeLinecap="round" />
              </svg>
            }
          />
          <StatCard
            label="Unread alerts"
            value={stats.unread_notifications}
            accent={stats.unread_notifications > 0 ? 'text-[#8B1A1A]' : 'text-[#2D3536]'}
            icon={
              <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke={stats.unread_notifications > 0 ? '#C84B4B' : '#98AA9D'} strokeWidth="1.8" aria-hidden="true">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0" strokeLinecap="round" />
              </svg>
            }
          />
        </div>
      ) : null}

      {/* Today's activity */}
      <div>
        <h3 className="text-sm font-semibold text-[#2D3536] mb-3">
          Today's appointments
          {stats && (
            <span className="ml-2 text-xs font-normal text-[#697C70]">
              (showing up to 10)
            </span>
          )}
        </h3>

        <div className="bg-white border border-[#E8E4DA] rounded-2xl overflow-hidden">
          {loading ? (
            <div className="p-8 text-center text-sm text-[#697C70]">Loading…</div>
          ) : !stats || stats.recent_appointments.length === 0 ? (
            <div className="p-8 text-center">
              <p className="text-sm text-[#697C70]">No appointments today yet.</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-[#F7F6F3] text-[10px] text-[#697C70] uppercase tracking-wider">
                  <th className="px-5 py-3 text-left font-medium">Patient</th>
                  <th className="px-4 py-3 text-left font-medium">Doctor</th>
                  <th className="px-4 py-3 text-center font-medium">Time</th>
                  <th className="px-4 py-3 text-center font-medium">Token</th>
                  <th className="px-4 py-3 text-center font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F2EFE2]">
                {stats.recent_appointments.map(appt => (
                  <tr key={appt.appointment_id} className="hover:bg-[#F7F6F3] transition-colors">
                    <td className="px-5 py-3 font-medium text-[#2D3536]">{appt.patient_name}</td>
                    <td className="px-4 py-3 text-[#697C70]">{appt.doctor_name}</td>
                    <td className="px-4 py-3 text-center font-mono text-xs text-[#697C70]">
                      {appt.slot_start}
                    </td>
                    <td className="px-4 py-3 text-center font-mono text-[#2D3536]">
                      {appt.token ?? '—'}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <StatusBadge s={appt.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Quick actions */}
      <div>
        <h3 className="text-sm font-semibold text-[#2D3536] mb-3">Quick actions</h3>
        <div className="grid grid-cols-2 gap-3">
          {[
            { label: 'Manage doctors',    path: '/admin/doctors',          desc: 'Shifts, leave, slots' },
            { label: 'Attendance sheet',  path: '/admin/attendance',        desc: "Today's status" },
            { label: 'Patient accounts',  path: '/admin/patients',          desc: 'All hospital patients' },
            { label: 'Medicine catalog',  path: '/admin/medicine-catalog',  desc: 'Review pending entries' },
          ].map(item => (
            <button
              key={item.path}
              type="button"
              onClick={() => navigate(item.path)}
              className="text-left bg-white border border-[#E8E4DA] rounded-xl px-4 py-3.5 hover:border-[#98AA9D] hover:bg-[#F5F8F5] transition-all"
            >
              <p className="text-sm font-medium text-[#2D3536]">{item.label}</p>
              <p className="text-xs text-[#A0A09A] mt-0.5">{item.desc}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
