/**
 * Doctor — Day View
 *
 * The doctor's primary screen: a slot grid for the selected date showing
 * each hour-window as an expandable row with patient cards inside.
 *
 * Phase 2: slot structure wired to the real API; patient cards are empty
 * (no bookings exist yet). The layout, empty states, unavailable-slot
 * treatment, and stats row are all built and ready for Phase 3 data.
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { animate, stagger } from 'animejs'
import { getDoctorDayView, type AppointmentSlot, type PatientCard, type HFApiError } from '@/lib/api'
import UrgencyBadge from '@/components/UrgencyBadge'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatTime(t: string): string {
  // "HH:MM:SS" → "HH:MM"
  return t.slice(0, 5)
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function dateLabel(iso: string): string {
  const d = new Date(iso + 'T00:00:00')
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diff = Math.round((d.getTime() - today.getTime()) / 86400000)
  if (diff === 0)   return 'Today'
  if (diff === 1)   return 'Tomorrow'
  if (diff === -1)  return 'Yesterday'
  return d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
}

// ─── Patient row ──────────────────────────────────────────────────────────────

function PatientRow({
  patient,
  onClick,
}: {
  patient: PatientCard
  onClick: () => void
}) {
  const statusDot: Record<PatientCard['ai_summary_status'], string> = {
    ready:       'bg-[#98AA9D]',
    unavailable: 'bg-[#A0A09A]',
    pending:     'bg-[#E8A838] animate-pulse',
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left flex items-center gap-3 px-4 py-3 hover:bg-[#EEF3EF] transition-colors"
      aria-label={`Patient ${patient.name}, token ${patient.token}, urgency ${patient.urgency}`}
    >
      {/* Token badge */}
      <div
        className="w-8 h-8 rounded-full bg-[#EEF3EF] flex items-center justify-center text-[#2D3536] text-sm font-bold shrink-0 font-mono border border-[#E8E4DA]"
        aria-hidden="true"
      >
        {patient.token}
      </div>

      {/* Name + complaint */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-[#2D3536] text-sm font-semibold truncate">{patient.name}</span>
          <span className="text-[#697C70] text-xs shrink-0">{patient.age}y</span>
        </div>
        <p className="text-[#697C70] text-xs truncate">{patient.chief_complaint}</p>
      </div>

      {/* Right side: urgency + AI status + chevron */}
      <div className="flex items-center gap-2 shrink-0">
        <UrgencyBadge level={patient.urgency} size="sm" />
        <span
          className={`w-2 h-2 rounded-full ${statusDot[patient.ai_summary_status]}`}
          title={`AI summary: ${patient.ai_summary_status}`}
          aria-label={`AI summary ${patient.ai_summary_status}`}
        />
        <svg
          width="14" height="14" fill="none" viewBox="0 0 24 24"
          stroke="#697C70" strokeWidth="2" aria-hidden="true"
        >
          <path d="M9 18l6-6-6-6" strokeLinecap="round" />
        </svg>
      </div>
    </button>
  )
}

// ─── Slot row ─────────────────────────────────────────────────────────────────

function SlotRow({
  slot,
  expanded,
  onToggle,
  onSelectPatient,
}: {
  slot: AppointmentSlot
  expanded: boolean
  onToggle: () => void
  onSelectPatient: (p: PatientCard) => void
}) {
  const patientCount    = slot.patients.length
  const hasHighUrgency  = slot.patients.some(p => p.urgency === 'High')
  const isFull          = slot.booked_count >= slot.capacity && !slot.unavailable

  const borderClass = slot.unavailable
    ? 'border-[#E8E4DA] opacity-60'
    : expanded
    ? 'border-[#98AA9D] shadow-sm'
    : 'border-[#E8E4DA] hover:border-[#98AA9D]/50 shadow-sm'

  const bgClass = slot.unavailable
    ? 'bg-[#FAF9F5]'
    : expanded
    ? 'bg-[#FAF9F5]'
    : 'bg-white'

  return (
    <div className={`rounded-2xl border overflow-hidden transition-all ${bgClass} ${borderClass}`}>
      <button
        type="button"
        onClick={onToggle}
        disabled={slot.unavailable}
        className="w-full flex items-center px-4 py-3.5 gap-3 text-left"
        aria-expanded={expanded}
        aria-label={`Slot ${formatTime(slot.slot_start)}–${formatTime(slot.slot_end)}, ${patientCount} patients`}
      >
        {/* Time */}
        <span className="text-sm font-mono font-semibold text-[#2D3536] w-28 shrink-0">
          {formatTime(slot.slot_start)}–{formatTime(slot.slot_end)}
        </span>

        {/* Count / status */}
        <span className="text-xs text-[#697C70] font-medium">
          {slot.unavailable
            ? 'Unavailable'
            : patientCount === 0
            ? 'No bookings'
            : `${patientCount} patient${patientCount !== 1 ? 's' : ''}`}
        </span>

        {/* High urgency flag */}
        {hasHighUrgency && (
          <span className="text-[10px] bg-[#F5D0CC] text-[#8B1A1A] px-2 py-0.5 rounded-full font-semibold">
            High urgency
          </span>
        )}

        {/* Full badge */}
        {isFull && !slot.unavailable && (
          <span className="text-[10px] bg-[#EEF3EF] text-[#697C70] px-2 py-0.5 rounded-full font-medium">
            Full
          </span>
        )}

        <div className="flex-1" />

        {/* Capacity pip row */}
        {!slot.unavailable && slot.capacity > 0 && (
          <div className="hidden sm:flex gap-1 items-center" aria-hidden="true">
            {Array.from({ length: Math.min(slot.capacity, 10) }).map((_, i) => (
              <span
                key={i}
                className={`w-2 h-2 rounded-full ${
                  i < slot.booked_count ? 'bg-[#98AA9D]' : 'bg-[#E8E4DA]'
                }`}
              />
            ))}
          </div>
        )}

        {/* Expand chevron */}
        {patientCount > 0 && !slot.unavailable && (
          <svg
            width="16" height="16" fill="none" viewBox="0 0 24 24"
            stroke="#697C70" strokeWidth="2"
            className={`transition-transform duration-200 ${expanded ? 'rotate-90' : ''}`}
            aria-hidden="true"
          >
            <path d="M9 18l6-6-6-6" strokeLinecap="round" />
          </svg>
        )}
      </button>

      {/* Expanded patient list */}
      {expanded && patientCount > 0 && (
        <div className="border-t border-[#E8E4DA] divide-y divide-[#E8E4DA]/60 bg-white">
          {slot.patients.map(p => (
            <PatientRow key={p.id} patient={p} onClick={() => onSelectPatient(p)} />
          ))}
        </div>
      )}

      {/* Empty expanded state */}
      {expanded && patientCount === 0 && !slot.unavailable && (
        <div className="border-t border-[#E8E4DA] px-4 py-4 bg-white">
          <p className="text-xs text-[#697C70]">No patients booked for this slot yet.</p>
        </div>
      )}
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

interface Props {
  /** Phase 3+: called when doctor taps a patient card */
  onSelectPatient?: (p: PatientCard) => void
}

export default function DayView({ onSelectPatient }: Props) {
  const navigate    = useNavigate()
  const [date, setDate]         = useState(todayIso)
  const [slots, setSlots]       = useState<AppointmentSlot[]>([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const gridRef = useRef<HTMLDivElement>(null)

  const load = useCallback(async (d: string) => {
    setLoading(true)
    setError('')
    try {
      const data = await getDoctorDayView(d)
      setSlots(data.slots)
      // Auto-expand the first slot that has patients
      const firstWithPatients = data.slots.find(s => s.patients.length > 0)
      if (firstWithPatients) setExpanded(firstWithPatients.id)
    } catch (err) {
      setError((err as HFApiError).message ?? 'Failed to load schedule.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load(date) }, [date, load])

  // Animate slot rows in on load
  useEffect(() => {
    if (!gridRef.current || loading || slots.length === 0) return
    const items = gridRef.current.querySelectorAll('.slot-row')
    animate(items, {
      opacity: [0, 1],
      translateX: [-10, 0],
      delay: stagger(60),
      duration: 380,
      easing: 'easeOutCubic',
    })
  }, [loading, slots.length])

  // Stats
  const totalPatients  = slots.reduce((n, s) => n + s.booked_count, 0)
  const completedSlots = slots.filter(s => s.patients.every(p => p.ai_summary_status !== 'pending')).length
  const pendingReview  = slots.reduce(
    (n, s) => n + s.patients.filter(p => p.ai_summary_status === 'pending').length,
    0,
  )

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Date nav */}
      <div className="flex items-center justify-between mb-6 gap-4">
        <div>
          <h2 className="text-xl font-bold text-[#2D3536]">
            {dateLabel(date)}
          </h2>
          <p className="text-xs text-[#697C70] font-mono mt-0.5">{date}</p>
        </div>
        <input
          type="date"
          value={date}
          onChange={e => setDate(e.target.value)}
          aria-label="Select date"
          className="bg-white border border-[#E8E4DA] rounded-xl px-3 py-2 text-sm text-[#2D3536] focus:outline-none focus:border-[#98AA9D] shrink-0 shadow-sm"
        />
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {([
          { label: 'Slots today',    value: String(slots.filter(s => !s.unavailable).length) },
          { label: 'Patients',       value: String(totalPatients) },
          { label: 'Completed',      value: String(completedSlots) },
          { label: 'Pending review', value: String(pendingReview) },
        ] as const).map(({ label, value }) => (
          <div key={label} className="bg-white border border-[#E8E4DA] rounded-2xl p-4 shadow-sm">
            <p className="text-2xl font-bold text-[#2D3536] font-mono">{value}</p>
            <p className="text-[#697C70] text-xs mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Error */}
      {error && (
        <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3 mb-4 font-medium">
          {error}
        </p>
      )}

      {/* Slot grid */}
      {loading ? (
        <div className="space-y-2">
          {[1, 2, 3, 4, 5].map(i => (
            <div key={i} className="h-14 rounded-2xl bg-white border border-[#E8E4DA] animate-pulse" />
          ))}
        </div>
      ) : slots.length === 0 ? (
        <div className="rounded-2xl border border-[#E8E4DA] bg-white px-6 py-10 text-center shadow-sm">
          <p className="text-sm text-[#697C70] font-medium">No slots configured for this date.</p>
          <p className="text-xs text-[#A0A09A] mt-1">
            Contact your admin to set up shift hours and generate slots.
          </p>
        </div>
      ) : (
        <div ref={gridRef} className="space-y-3">
          {slots.map(slot => (
            <div key={slot.id} className="slot-row" style={{ opacity: 0 }}>
              <SlotRow
                slot={slot}
                expanded={expanded === slot.id}
                onToggle={() => setExpanded(prev => prev === slot.id ? null : slot.id)}
                onSelectPatient={p => {
                  if (onSelectPatient) {
                    onSelectPatient(p)
                  } else {
                    // Phase 3: navigate to patient detail
                    navigate(`/doctor/appointments/${p.appointment_id}`)
                  }
                }}
              />
            </div>
          ))}
        </div>
      )}

      {/* AI status legend */}
      {slots.some(s => s.patients.length > 0) && (
        <div className="mt-6 flex items-center gap-4 text-xs text-[#697C70]">
          <span className="font-medium text-[#A0A09A] uppercase tracking-wider">AI summary:</span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-[#98AA9D]" aria-hidden="true" />
            Ready
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-[#E8A838] animate-pulse" aria-hidden="true" />
            Generating
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-[#A0A09A]" aria-hidden="true" />
            Unavailable
          </span>
        </div>
      )}
    </div>
  )
}
