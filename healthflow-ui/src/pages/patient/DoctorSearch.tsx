/**
 * Patient — Doctor Search
 *
 * Specialization filter + date range → list of doctor cards each showing
 * the next available slot. Selecting a doctor navigates to DoctorDetail.
 */
import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { searchDoctors, type DoctorSearchResult, type HFApiError } from '@/lib/api'

// ─── Helpers ─────────────────────────────────────────────────────────────────

const SPECIALIZATIONS = [
  'General Physician',
  'Cardiology',
  'Dermatology',
  'ENT',
  'Gynaecology',
  'Neurology',
  'Ophthalmology',
  'Orthopaedics',
  'Paediatrics',
  'Psychiatry',
  'Pulmonology',
  'Urology',
]

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function nextSlotLabel(slot: DoctorSearchResult['next_available_slot']): string {
  if (!slot) return 'No slots available'
  const d = new Date(slot.date + 'T00:00:00')
  const today = new Date(); today.setHours(0, 0, 0, 0)
  const diff = Math.round((d.getTime() - today.getTime()) / 86400000)
  const dayLabel = diff === 0 ? 'Today' : diff === 1 ? 'Tomorrow' : d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
  return `${dayLabel} ${slot.slot_start}`
}

// ─── Doctor card ──────────────────────────────────────────────────────────────

function DoctorCard({
  doctor,
  onClick,
}: {
  doctor: DoctorSearchResult
  onClick: () => void
}) {
  const hasSlot = doctor.next_available_slot !== null
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!hasSlot}
      aria-label={`${doctor.name}, ${doctor.specialization}. ${hasSlot ? `Next slot: ${nextSlotLabel(doctor.next_available_slot)}` : 'No slots available'}`}
      className={`w-full text-left bg-white border rounded-2xl p-4 transition-all active:scale-[0.99] ${
        hasSlot
          ? 'border-[#D8D2C4] hover:border-[#98AA9D] hover:bg-[#F5F8F5] cursor-pointer'
          : 'border-[#E8E4DA] opacity-60 cursor-not-allowed'
      }`}
    >
      <div className="flex items-start gap-3">
        {/* Avatar */}
        <div
          className="w-10 h-10 rounded-full bg-[#EEF3EF] flex items-center justify-center text-[#697C70] font-semibold text-sm shrink-0"
          aria-hidden="true"
        >
          {doctor.name.charAt(0)}
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-[#2D3536] text-sm">{doctor.name}</p>
          <p className="text-xs text-[#697C70] mt-0.5">{doctor.specialization}</p>

          {/* Next slot pill */}
          <div className="mt-2 flex items-center gap-1.5">
            {hasSlot ? (
              <>
                <span
                  className="w-1.5 h-1.5 rounded-full bg-[#98AA9D] shrink-0"
                  aria-hidden="true"
                />
                <span className="text-xs text-[#98AA9D] font-medium">
                  {nextSlotLabel(doctor.next_available_slot)}
                </span>
                <span className="text-xs text-[#A0A09A]">
                  · {doctor.next_available_slot!.remaining} seat{doctor.next_available_slot!.remaining !== 1 ? 's' : ''} open
                </span>
              </>
            ) : (
              <span className="text-xs text-[#A0A09A]">No upcoming slots</span>
            )}
          </div>
        </div>

        {/* Chevron */}
        {hasSlot && (
          <svg
            width="16" height="16" fill="none" viewBox="0 0 24 24"
            stroke="#A0A09A" strokeWidth="2" className="shrink-0 mt-1"
            aria-hidden="true"
          >
            <path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </div>
    </button>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function DoctorSearch() {
  const navigate = useNavigate()
  const [specialization, setSpecialization] = useState('')
  const [dateFrom, setDateFrom]             = useState(todayIso())
  const [dateTo, setDateTo]                 = useState('')
  const [doctors, setDoctors]               = useState<DoctorSearchResult[]>([])
  const [loading, setLoading]               = useState(false)
  const [error, setError]                   = useState('')
  const [searched, setSearched]             = useState(false)

  const search = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const results = await searchDoctors({
        specialization: specialization || undefined,
        date_from:      dateFrom || undefined,
        date_to:        dateTo   || undefined,
      })
      setDoctors(results)
      setSearched(true)
    } catch (err) {
      setError((err as HFApiError).message ?? 'Search failed.')
    } finally {
      setLoading(false)
    }
  }, [specialization, dateFrom, dateTo])

  // Auto-search on mount with defaults
  useEffect(() => { void search() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="p-4 pb-6 space-y-4">
      <h2 className="text-xl font-semibold text-[#2D3536] font-serif">Find a doctor</h2>

      {/* Filters */}
      <div className="bg-white border border-[#E8E4DA] rounded-2xl p-4 space-y-3">
        {/* Specialization */}
        <div>
          <label htmlFor="spec" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider">
            Specialization
          </label>
          <select
            id="spec"
            value={specialization}
            onChange={e => setSpecialization(e.target.value)}
            className="w-full bg-[#F7F6F3] border border-[#D8D2C4] rounded-xl px-3 py-2.5 text-sm text-[#2D3536] focus:outline-none focus:border-[#98AA9D] transition-all"
          >
            <option value="">All specializations</option>
            {SPECIALIZATIONS.map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>

        {/* Date range */}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label htmlFor="from" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider">From</label>
            <input
              id="from" type="date" value={dateFrom}
              min={todayIso()}
              onChange={e => setDateFrom(e.target.value)}
              className="w-full bg-[#F7F6F3] border border-[#D8D2C4] rounded-xl px-3 py-2.5 text-sm text-[#2D3536] focus:outline-none focus:border-[#98AA9D]"
            />
          </div>
          <div>
            <label htmlFor="to" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider">To (optional)</label>
            <input
              id="to" type="date" value={dateTo}
              min={dateFrom || todayIso()}
              onChange={e => setDateTo(e.target.value)}
              className="w-full bg-[#F7F6F3] border border-[#D8D2C4] rounded-xl px-3 py-2.5 text-sm text-[#2D3536] focus:outline-none focus:border-[#98AA9D]"
            />
          </div>
        </div>

        <button
          type="button"
          onClick={search}
          disabled={loading}
          className="w-full bg-[#2D3536] text-white rounded-xl py-3 font-semibold text-sm hover:bg-[#3D4546] transition-colors disabled:opacity-60"
        >
          {loading ? 'Searching…' : 'Search'}
        </button>
      </div>

      {/* Error */}
      {error && (
        <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3">
          {error}
        </p>
      )}

      {/* Results */}
      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map(i => (
            <div key={i} className="h-24 rounded-2xl bg-[#E8E4DA] animate-pulse" />
          ))}
        </div>
      ) : searched && doctors.length === 0 ? (
        <div className="text-center py-10">
          <p className="text-sm text-[#697C70]">No doctors found for your search.</p>
          <p className="text-xs text-[#A0A09A] mt-1">Try a different specialization or date range.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {doctors.map(doc => (
            <DoctorCard
              key={doc.user_id}
              doctor={doc}
              onClick={() => navigate(`/patient/doctors/${doc.user_id}`, { state: { doctor: doc } })}
            />
          ))}
        </div>
      )}
    </div>
  )
}
