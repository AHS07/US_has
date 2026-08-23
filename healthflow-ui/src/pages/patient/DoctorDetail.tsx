/**
 * Patient — Doctor Detail + Slot Picker
 *
 * Shows the doctor's profile and a day-by-day slot grid using BatchSlotCard.
 * Selecting an available slot calls holdSlot() then navigates to SymptomForm.
 */
import { useEffect, useState, useCallback } from 'react'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
import {
  getDoctorSlots,
  holdSlot,
  type DoctorSearchResult,
  type AppointmentSlot,
  type HFApiError,
} from '@/lib/api'
import BatchSlotCard, { type BatchSlot } from '@/components/BatchSlotCard'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function isoToLabel(iso: string): string {
  const d = new Date(iso + 'T00:00:00')
  const today = new Date(); today.setHours(0, 0, 0, 0)
  const diff = Math.round((d.getTime() - today.getTime()) / 86400000)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Tomorrow'
  return d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
}

function slotToCard(s: AppointmentSlot): BatchSlot {
  return {
    id:        s.id,
    time:      s.slot_start.slice(0, 5),
    endTime:   s.slot_end.slice(0, 5),
    capacity:  s.capacity,
    booked:    s.booked_count,
    date:      s.date,
    status:    s.unavailable ? 'unavailable' : s.true_remaining === 0 ? 'full' : 'open',
  }
}

function dateRange(from: Date, days: number): string[] {
  return Array.from({ length: days }, (_, i) => {
    const d = new Date(from)
    d.setDate(d.getDate() + i)
    return d.toISOString().slice(0, 10)
  })
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function DoctorDetail() {
  const navigate           = useNavigate()
  const { doctorId }       = useParams<{ doctorId: string }>()
  const location           = useLocation()
  const doctor             = (location.state as { doctor?: DoctorSearchResult })?.doctor ?? null

  const [selectedDate, setSelectedDate]     = useState(new Date().toISOString().slice(0, 10))
  const [slots, setSlots]                   = useState<AppointmentSlot[]>([])
  const [loadingSlots, setLoadingSlots]     = useState(false)
  const [selectedSlotId, setSelectedSlotId] = useState<string | null>(null)
  const [holding, setHolding]               = useState(false)
  const [error, setError]                   = useState('')

  const dates = dateRange(new Date(), 7)

  const loadSlots = useCallback(async (date: string) => {
    if (!doctorId) return
    setLoadingSlots(true)
    setError('')
    try {
      const data = await getDoctorSlots(doctorId, date)
      setSlots(data.slots)
    } catch (err) {
      setError((err as HFApiError).message ?? 'Failed to load slots.')
    } finally {
      setLoadingSlots(false)
    }
  }, [doctorId])

  useEffect(() => { void loadSlots(selectedDate) }, [selectedDate, loadSlots])

  async function handleBookSlot() {
    if (!selectedSlotId || !doctorId) return
    setHolding(true)
    setError('')
    try {
      const appointment = await holdSlot({ slot_id: selectedSlotId, doctor_id: doctorId })
      navigate('/patient/symptom-form', {
        state: { appointment, doctor, slot: slots.find(s => s.id === selectedSlotId) },
      })
    } catch (err) {
      const apiErr = err as HFApiError
      if (apiErr.status === 409) {
        setError('This slot just became fully booked. Please pick another time.')
        setSelectedSlotId(null)
        void loadSlots(selectedDate)
      } else {
        setError(apiErr.message ?? 'Failed to hold slot.')
      }
    } finally {
      setHolding(false)
    }
  }

  if (!doctorId) return null

  return (
    <div className="pb-8">
      {/* Doctor header */}
      <div className="px-4 pt-4 pb-3 border-b border-[#E8E4DA] bg-white">
        <div className="flex items-center gap-3">
          <div
            className="w-12 h-12 rounded-full bg-[#EEF3EF] flex items-center justify-center text-[#697C70] font-bold text-base shrink-0"
            aria-hidden="true"
          >
            {doctor?.name.charAt(0) ?? '?'}
          </div>
          <div>
            <p className="font-semibold text-[#2D3536]">{doctor?.name ?? 'Doctor'}</p>
            <p className="text-xs text-[#697C70]">{doctor?.specialization ?? ''}</p>
            <p className="text-xs text-[#A0A09A] mt-0.5">
              {doctor?.slot_duration_minutes} min slots · up to {doctor?.slot_capacity} patients
            </p>
          </div>
        </div>
      </div>

      <div className="px-4 pt-4 space-y-4">
        {/* Date strip */}
        <div>
          <p className="text-xs text-[#697C70] uppercase tracking-wider font-medium mb-2">Select a date</p>
          <div className="flex gap-2 overflow-x-auto pb-1 -mx-4 px-4">
            {dates.map(d => {
              const active = d === selectedDate
              const label  = isoToLabel(d)
              return (
                <button
                  key={d}
                  type="button"
                  onClick={() => { setSelectedDate(d); setSelectedSlotId(null) }}
                  aria-pressed={active}
                  className={`shrink-0 flex flex-col items-center px-3 py-2 rounded-xl text-xs font-medium border transition-all ${
                    active
                      ? 'bg-[#2D3536] text-white border-[#2D3536]'
                      : 'bg-white text-[#697C70] border-[#D8D2C4] hover:border-[#98AA9D]'
                  }`}
                >
                  <span>{label.slice(0, 3)}</span>
                  <span className="text-[10px] mt-0.5 font-mono">
                    {new Date(d + 'T00:00:00').getDate()}
                  </span>
                </button>
              )
            })}
          </div>
        </div>

        {/* Error */}
        {error && (
          <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3">
            {error}
          </p>
        )}

        {/* Slot grid */}
        {loadingSlots ? (
          <div className="space-y-2">
            {[1, 2, 3].map(i => <div key={i} className="h-16 rounded-xl bg-[#E8E4DA] animate-pulse" />)}
          </div>
        ) : slots.length === 0 ? (
          <div className="text-center py-8">
            <p className="text-sm text-[#697C70]">No slots on this day.</p>
          </div>
        ) : (
          <div className="space-y-2" role="list" aria-label="Available time slots">
            {slots.map(slot => (
              <div key={slot.id} role="listitem">
                <BatchSlotCard
                  slot={slotToCard(slot)}
                  selected={selectedSlotId === slot.id}
                  onClick={slot.unavailable || slot.true_remaining === 0
                    ? undefined
                    : () => setSelectedSlotId(slot.id)}
                />
              </div>
            ))}
          </div>
        )}

        {/* CTA */}
        {selectedSlotId && (
          <div className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-md px-4 pb-6 pt-3 bg-[#F2EFE2]/95 backdrop-blur border-t border-[#D8D2C4]">
            <button
              type="button"
              onClick={handleBookSlot}
              disabled={holding}
              className="w-full bg-[#98AA9D] text-white rounded-2xl py-4 font-semibold text-base hover:bg-[#7A9080] transition-colors disabled:opacity-60"
            >
              {holding ? 'Holding your seat…' : 'Book this slot'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
