/**
 * Patient — Doctor Absence / Reassignment screen
 *
 * Shown when a patient's appointment has been reassigned due to their
 * doctor being absent. Displays:
 *   - Original doctor and their specialization
 *   - New doctor and new slot time
 *   - Confirmation that their symptom description was carried forward
 *   - A CTA to confirm the new slot (navigate to SymptomForm pre-filled)
 *     or decline (cancel the new hold)
 *
 * This screen is reached from Appointments.tsx when status = 'held'
 * and original_doctor_name is set (meaning it was system-created by cascade).
 *
 * Route: /patient/appointments/:appointmentId/reassignment
 */
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  getAppointment,
  cancelHold,
  type AppointmentDetail,
  type HFApiError,
} from '@/lib/api'

function formatDate(iso: string): string {
  return new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', {
    weekday: 'long', day: 'numeric', month: 'long',
  })
}

export default function DoctorAbsence() {
  const { appointmentId } = useParams<{ appointmentId: string }>()
  const navigate           = useNavigate()

  const [appt,       setAppt]       = useState<AppointmentDetail | null>(null)
  const [loading,    setLoading]    = useState(true)
  const [declining,  setDeclining]  = useState(false)
  const [error,      setError]      = useState('')

  useEffect(() => {
    if (!appointmentId) return
    getAppointment(appointmentId)
      .then(setAppt)
      .catch(err => setError((err as HFApiError).message ?? 'Failed to load appointment.'))
      .finally(() => setLoading(false))
  }, [appointmentId])

  async function handleDecline() {
    if (!appt) return
    setDeclining(true)
    try {
      await cancelHold(appt.id)
      navigate('/patient/appointments', { replace: true })
    } catch {
      navigate('/patient/appointments', { replace: true })
    }
  }

  function handleConfirm() {
    if (!appt) return
    // Navigate to SymptomForm with the reassigned appointment pre-loaded.
    // Symptom text is already present — patient just confirms.
    navigate('/patient/symptom-form', {
      state: {
        appointment: appt,
        doctor: null,
        slot: undefined,
      },
    })
  }

  if (loading) {
    return (
      <div className="px-4 py-8 space-y-4">
        <div className="h-6 w-48 rounded-lg bg-[#E8E4DA] animate-pulse" />
        <div className="h-32 rounded-2xl bg-[#E8E4DA] animate-pulse" />
      </div>
    )
  }

  if (error || !appt) {
    return (
      <div className="px-4 py-8">
        <p className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3">
          {error || 'Appointment not found.'}
        </p>
      </div>
    )
  }

  // Cast to access Phase 7 fields (reassignment_note, original_doctor_name)
  const extended = appt as AppointmentDetail & {
    reassignment_note: string
    original_doctor_name: string
  }

  const slotLabel = appt.slot_start && appt.slot_end
    ? `${appt.slot_start.slice(0, 5)}–${appt.slot_end.slice(0, 5)}`
    : ''

  return (
    <div className="px-4 py-5 pb-24 space-y-5">
      {/* Header — non-alarming tone per design brief */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <span className="w-2 h-2 rounded-full bg-[#E8A838]" aria-hidden="true" />
          <p className="text-xs text-[#7A4A00] font-medium uppercase tracking-wider">
            Appointment update
          </p>
        </div>
        <h2
          className="text-xl text-[#2D3536] font-semibold leading-snug"
          style={{ fontFamily: 'var(--font-serif, serif)' }}
        >
          We've found you a new doctor
        </h2>
        <p className="text-sm text-[#697C70] mt-1 leading-relaxed">
          Your original doctor is unavailable for this appointment. We've found
          an available doctor with the same specialization for you.
        </p>
      </div>

      {/* What changed */}
      <div className="bg-white border border-[#E8E4DA] rounded-2xl divide-y divide-[#F2EFE2]">
        {extended.original_doctor_name && (
          <div className="px-4 py-3.5">
            <p className="text-[10px] text-[#A0A09A] uppercase tracking-wider mb-0.5">
              Original doctor (unavailable)
            </p>
            <p className="text-sm text-[#697C70] line-through">
              {extended.original_doctor_name}
            </p>
          </div>
        )}
        <div className="px-4 py-3.5">
          <p className="text-[10px] text-[#A0A09A] uppercase tracking-wider mb-0.5">
            New doctor
          </p>
          <p className="text-sm font-medium text-[#2D3536]">{appt.doctor_name}</p>
          <p className="text-xs text-[#697C70]">{appt.specialization}</p>
        </div>
        <div className="px-4 py-3.5">
          <p className="text-[10px] text-[#A0A09A] uppercase tracking-wider mb-0.5">
            New date & time
          </p>
          <p className="text-sm font-medium text-[#2D3536]">
            {appt.slot_date ? formatDate(appt.slot_date) : '—'}
          </p>
          <p className="text-xs text-[#697C70] font-mono">{slotLabel}</p>
        </div>
      </div>

      {/* Symptom carry-forward confirmation */}
      <div className="bg-[#EEF3EF] border border-[#D0E0D4] rounded-2xl px-4 py-4">
        <div className="flex items-start gap-3">
          <svg
            width="18" height="18" fill="none" viewBox="0 0 24 24"
            stroke="#98AA9D" strokeWidth="2" className="shrink-0 mt-0.5"
            aria-hidden="true"
          >
            <path d="M20 6 9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div>
            <p className="text-sm font-medium text-[#2D3536]">
              Your symptom description has been carried forward
            </p>
            <p className="text-xs text-[#697C70] mt-0.5 leading-relaxed">
              The new doctor will see everything you described. You don't need to
              re-enter anything.
            </p>
          </div>
        </div>
        {appt.symptom_text && (
          <div className="mt-3 bg-white rounded-xl px-3 py-2.5">
            <p className="text-[10px] text-[#A0A09A] uppercase tracking-wider mb-1">
              Your symptoms (read-only)
            </p>
            <p className="text-xs text-[#697C70] leading-relaxed line-clamp-4">
              {appt.symptom_text}
            </p>
          </div>
        )}
      </div>

      {/* Reassignment note */}
      {extended.reassignment_note && (
        <p className="text-xs text-[#A0A09A] px-1 leading-relaxed">
          {extended.reassignment_note}
        </p>
      )}

      {/* CTAs */}
      <div className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-md px-4 pb-6 pt-3 bg-[#F2EFE2]/95 backdrop-blur border-t border-[#D8D2C4] space-y-2">
        <button
          type="button"
          onClick={handleConfirm}
          className="w-full bg-[#98AA9D] text-white rounded-2xl py-4 font-semibold text-base hover:bg-[#7A9080] transition-colors"
        >
          Confirm new appointment
        </button>
        <button
          type="button"
          onClick={handleDecline}
          disabled={declining}
          className="w-full text-sm text-[#697C70] hover:text-[#2D3536] transition-colors py-1"
        >
          {declining ? 'Declining…' : "Decline — I'll book manually"}
        </button>
      </div>
    </div>
  )
}
