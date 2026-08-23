/**
 * Patient — Booking Confirmation
 *
 * Shown after successful confirm. Summarises what was booked,
 * explains what happens next (AI summary, calendar, reminders),
 * and links to Appointments.
 */
import { useEffect, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { animate } from 'animejs'
import type { AppointmentDetail, DoctorSearchResult, AppointmentSlot } from '@/lib/api'

interface LocationState {
  appointment: AppointmentDetail
  doctor: DoctorSearchResult | null
  slot: AppointmentSlot | undefined
}

function formatDate(iso: string): string {
  return new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  })
}

export default function BookingConfirmation() {
  const navigate  = useNavigate()
  const location  = useLocation()
  const { appointment, doctor, slot } = (location.state ?? {}) as LocationState

  const cardRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (cardRef.current) {
      animate(cardRef.current, {
        opacity: [0, 1], translateY: [20, 0], duration: 500, easing: 'easeOutCubic',
      })
    }
  }, [])

  if (!appointment) {
    navigate('/patient/search', { replace: true })
    return null
  }

  const slotLabel = slot
    ? `${slot.slot_start.slice(0, 5)}–${slot.slot_end.slice(0, 5)}`
    : `${appointment.slot_start?.slice(0, 5)}–${appointment.slot_end?.slice(0, 5)}`

  return (
    <div className="p-4 pb-10 flex flex-col min-h-[80vh]">
      {/* Check mark */}
      <div className="flex flex-col items-center py-8">
        <div className="w-16 h-16 rounded-full bg-[#EEF3EF] flex items-center justify-center mb-4">
          <svg width="32" height="32" fill="none" viewBox="0 0 24 24" stroke="#98AA9D" strokeWidth="2" aria-hidden="true">
            <path d="M20 6 9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <h2 className="text-2xl font-semibold text-[#2D3536] font-serif">You're booked</h2>
        <p className="text-sm text-[#697C70] mt-1 text-center">
          Your appointment is confirmed. See you soon.
        </p>
      </div>

      {/* Summary card */}
      <div
        ref={cardRef}
        className="bg-white border border-[#E8E4DA] rounded-2xl divide-y divide-[#F2EFE2]"
        style={{ opacity: 0 }}
      >
        <SummaryRow label="Doctor"      value={doctor?.name ?? appointment.doctor_name} />
        <SummaryRow label="Specialization" value={doctor?.specialization ?? appointment.specialization} />
        <SummaryRow label="Date"        value={formatDate(appointment.slot_date)} />
        <SummaryRow label="Time"        value={slotLabel} />
        <SummaryRow label="Token"       value={appointment.token ? `#${appointment.token}` : '—'} />
        <SummaryRow label="Hospital"    value={appointment.hospital_name} />
      </div>

      {/* What happens next */}
      <div className="mt-5 space-y-3">
        <p className="text-xs text-[#697C70] uppercase tracking-wider font-medium">What happens next</p>

        {[
          {
            icon: (
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                <circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" strokeLinecap="round" />
              </svg>
            ),
            text: 'Your doctor will receive an AI-prepared briefing based on the symptoms you described — advisory only.',
          },
          {
            icon: (
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                <rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" strokeLinecap="round" />
              </svg>
            ),
            text: "A calendar invite will arrive shortly by email. You can also download it from your Appointments tab.",
          },
          {
            icon: (
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0" strokeLinecap="round" />
              </svg>
            ),
            text: "We'll send a reminder before your appointment.",
          },
        ].map(({ icon, text }, i) => (
          <div key={i} className="flex items-start gap-3 bg-white border border-[#E8E4DA] rounded-xl px-4 py-3">
            <span className="text-[#98AA9D] shrink-0 mt-0.5">{icon}</span>
            <p className="text-sm text-[#697C70] leading-relaxed">{text}</p>
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className="mt-8 space-y-3">
        <button
          type="button"
          onClick={() => navigate('/patient/appointments')}
          className="w-full bg-[#2D3536] text-white rounded-2xl py-4 font-semibold text-base hover:bg-[#3D4546] transition-colors"
        >
          View my appointments
        </button>
        <button
          type="button"
          onClick={() => navigate('/patient/search')}
          className="w-full text-sm text-[#697C70] hover:text-[#2D3536] transition-colors py-1"
        >
          Book another appointment
        </button>
      </div>
    </div>
  )
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-3 gap-4">
      <span className="text-xs text-[#697C70] uppercase tracking-wider shrink-0">{label}</span>
      <span className="text-sm text-[#2D3536] font-medium text-right">{value}</span>
    </div>
  )
}
