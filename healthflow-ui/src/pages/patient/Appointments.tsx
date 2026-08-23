/**
 * Patient — Appointments
 *
 * Upcoming and past appointment cards. Past cards expand to show
 * post-visit summary placeholder (Phase 5 fills the real summary).
 * Doctor-absence notice flows via notifications (Phase 7).
 */
import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getMyAppointments,
  cancelAppointment,
  type AppointmentListItem,
  type HFApiError,
} from '@/lib/api'
import AIDisclaimer from '@/components/AIDisclaimer'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  return new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', {
    weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
  })
}

const STATUS_LABEL: Record<AppointmentListItem['status'], string> = {
  held:       'Hold pending',
  confirmed:  'Confirmed',
  completed:  'Completed',
  cancelled:  'Cancelled',
  no_show:    'Missed',
  reassigned: 'Reassigned',
}

const STATUS_COLOR: Record<AppointmentListItem['status'], string> = {
  held:       'bg-[#FDE8C0] text-[#7A4A00]',
  confirmed:  'bg-[#EEF3EF] text-[#697C70]',
  completed:  'bg-[#D6E8F0] text-[#2A6080]',
  cancelled:  'bg-[#F5D0CC] text-[#8B1A1A]',
  no_show:    'bg-[#F5D0CC] text-[#8B1A1A]',
  reassigned: 'bg-[#FDE8C0] text-[#7A4A00]',
}

// ─── Appointment card ─────────────────────────────────────────────────────────

function AppointmentCard({
  appt,
  onCancel,
}: {
  appt: AppointmentListItem
  onCancel: (id: string) => void
}) {
  const navigate   = useNavigate()
  const [expanded, setExpanded] = useState(false)
  const isPast     = appt.status === 'completed' || appt.status === 'cancelled' || appt.status === 'no_show'
  const isUpcoming = appt.status === 'confirmed' || appt.status === 'held'

  return (
    <article
      className="bg-white border border-[#E8E4DA] rounded-2xl overflow-hidden"
      aria-label={`Appointment with ${appt.doctor_name} on ${formatDate(appt.slot_date)}`}
    >
      {/* Main row */}
      <button
        type="button"
        onClick={() => isPast && setExpanded(e => !e)}
        className={`w-full text-left px-4 py-4 ${isPast ? 'cursor-pointer' : ''}`}
      >
        <div className="flex items-start gap-3">
          {/* Avatar */}
          <div
            className="w-9 h-9 rounded-full bg-[#EEF3EF] flex items-center justify-center text-[#697C70] font-semibold text-sm shrink-0"
            aria-hidden="true"
          >
            {appt.doctor_name.charAt(0)}
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-2">
              <p className="font-semibold text-[#2D3536] text-sm truncate">{appt.doctor_name}</p>
              <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full shrink-0 ${STATUS_COLOR[appt.status]}`}>
                {STATUS_LABEL[appt.status]}
              </span>
            </div>
            <p className="text-xs text-[#697C70] mt-0.5">{appt.specialization}</p>
            <p className="text-xs text-[#A0A09A] font-mono mt-1">
              {formatDate(appt.slot_date)}
            </p>

            {/* Token + urgency */}
            {appt.token && (
              <p className="text-xs text-[#697C70] mt-1">
                Token #{appt.token}
                {appt.urgency_level && ` · ${appt.urgency_level} urgency`}
              </p>
            )}
          </div>

          {isPast && (
            <svg
              width="14" height="14" fill="none" viewBox="0 0 24 24"
              stroke="#A0A09A" strokeWidth="2"
              className={`shrink-0 mt-1 transition-transform ${expanded ? 'rotate-90' : ''}`}
              aria-hidden="true"
            >
              <path d="M9 18l6-6-6-6" strokeLinecap="round" />
            </svg>
          )}
        </div>
      </button>

      {/* Past — expanded post-visit summary */}
      {isPast && expanded && (
        <div className="border-t border-[#F2EFE2] px-4 py-4 space-y-3">
          {appt.status === 'completed' ? (
            appt.pre_summary_status === 'ready' ? (
              <>
                <AIDisclaimer />
                <button
                  type="button"
                  onClick={() => navigate(`/patient/appointments/${appt.id}/summary`)}
                  className="w-full bg-[#2D3536] text-white rounded-xl py-2.5 text-sm font-medium hover:bg-[#3D4546] transition-colors"
                >
                  View visit summary
                </button>
              </>
            ) : (
              <p className="text-xs text-[#697C70]">
                Post-visit summary not yet available.
              </p>
            )
          ) : (
            <p className="text-xs text-[#A0A09A]">
              {appt.status === 'cancelled'
                ? 'This appointment was cancelled.'
                : 'You did not attend this appointment.'}
            </p>
          )}
        </div>
      )}

      {/* Upcoming — action row */}
      {isUpcoming && (
        <div className="border-t border-[#F2EFE2] px-4 py-2.5 flex items-center gap-3">
          {appt.status === 'confirmed' && (
            <>
              <button
                type="button"
                onClick={() => navigate(`/patient/appointments/${appt.id}/reschedule`)}
                className="text-xs text-[#697C70] hover:text-[#2D3536] font-medium transition-colors"
              >
                Reschedule
              </button>
              <span className="text-[#E8E4DA]" aria-hidden="true">·</span>
              <button
                type="button"
                onClick={() => onCancel(appt.id)}
                className="text-xs text-[#697C70] hover:text-[#8B1A1A] font-medium transition-colors"
              >
                Cancel
              </button>
            </>
          )}
          {appt.status === 'held' && (appt as any).original_doctor_name
            ? (
              <button
                type="button"
                onClick={() => navigate(`/patient/appointments/${appt.id}/reassignment`)}
                className="text-xs text-[#E8A838] font-medium hover:text-[#7A4A00] transition-colors"
              >
                View reassignment →
              </button>
            ) : appt.status === 'held' ? (
              <p className="text-xs text-[#A0A09A]">Completing your booking…</p>
            ) : null
          }
        </div>
      )}
    </article>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function Appointments() {
  const navigate = useNavigate()
  const [tab, setTab]             = useState<'upcoming' | 'past'>('upcoming')
  const [appointments, setAppts]  = useState<AppointmentListItem[]>([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState('')
  const [cancelling, setCancelling] = useState<string | null>(null)

  const load = useCallback(async (t: 'upcoming' | 'past') => {
    setLoading(true)
    setError('')
    try {
      const data = await getMyAppointments(t)
      setAppts(data)
    } catch (err) {
      setError((err as HFApiError).message ?? 'Failed to load appointments.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load(tab) }, [tab, load])

  async function handleCancel(id: string) {
    setCancelling(id)
    try {
      const updated = await cancelAppointment(id)
      setAppts(prev => prev.map(a => a.id === id ? { ...a, status: updated.status } : a))
    } catch (err) {
      setError((err as HFApiError).message ?? 'Failed to cancel.')
    } finally {
      setCancelling(null)
    }
  }

  return (
    <div className="p-4 pb-6 space-y-4">
      <h2 className="text-xl font-semibold text-[#2D3536] font-serif">My appointments</h2>

      {/* Tabs */}
      <div className="flex bg-[#E8E4DA] rounded-xl p-1 gap-1" role="tablist">
        {(['upcoming', 'past'] as const).map(t => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all ${
              tab === t
                ? 'bg-white text-[#2D3536] shadow-sm'
                : 'text-[#697C70] hover:text-[#2D3536]'
            }`}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3">
          {error}
        </p>
      )}

      {/* List */}
      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map(i => <div key={i} className="h-24 rounded-2xl bg-[#E8E4DA] animate-pulse" />)}
        </div>
      ) : appointments.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-sm text-[#697C70]">
            {tab === 'upcoming' ? 'No upcoming appointments.' : 'No past appointments yet.'}
          </p>
          {tab === 'upcoming' && (
            <button
              type="button"
              onClick={() => navigate('/patient/search')}
              className="mt-3 text-sm text-[#98AA9D] font-medium hover:underline"
            >
              Book an appointment
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {appointments.map(appt => (
            <div key={appt.id} className={cancelling === appt.id ? 'opacity-60 pointer-events-none' : ''}>
              <AppointmentCard appt={appt} onCancel={handleCancel} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
