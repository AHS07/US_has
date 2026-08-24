/**
 * Doctor — Consultation Screen
 *
 * Free-text notes + prescription builder with medicine autocomplete,
 * fuzzy-match hint, and follow-up field.
 * On submit: POST /doctor/appointments/:id/consultation → navigates to SummaryReview.
 *
 * Route: /doctor/consultation/:appointmentId
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  searchMedicines,
  createMedicine,
  submitConsultation,
  getDoctorAppointment,
  type MedicineCatalogItem,
  type PrescriptionRow,
  type DoctorAppointmentCard,
  type HFApiError,
} from '@/lib/api'

// ─── Constants ────────────────────────────────────────────────────────────────

const FREQUENCY_OPTIONS = [
  { value: 'once_daily',        label: 'Once daily' },
  { value: 'twice_daily',       label: 'Twice daily' },
  { value: 'three_times_daily', label: 'Three times daily' },
  { value: 'four_times_daily',  label: 'Four times daily' },
  { value: 'at_bedtime',        label: 'At bedtime' },
  { value: 'as_needed',         label: 'As needed' },
]

const DURATION_OPTIONS = [
  '1 day', '3 days', '5 days', '7 days',
  '10 days', '14 days', '1 month', 'Ongoing',
]

// ─── Types ────────────────────────────────────────────────────────────────────

interface MedRow {
  medicine_id: string
  medicine_name: string
  dosage: string
  frequency: string
  duration: string
  instructions: string
}

function emptyRow(): MedRow {
  return { medicine_id: '', medicine_name: '', dosage: '', frequency: '', duration: '', instructions: '' }
}

// ─── Prescription row ─────────────────────────────────────────────────────────

function PrescriptionRowEditor({
  index,
  row,
  onChange,
  onRemove,
  showRemove,
}: {
  index: number
  row: MedRow
  onChange: (i: number, field: keyof MedRow, val: string) => void
  onRemove: (i: number) => void
  showRemove: boolean
}) {
  const [query,        setQuery]        = useState(row.medicine_name)
  const [suggestions,  setSuggestions]  = useState<MedicineCatalogItem[]>([])
  const [showDropdown, setShowDropdown] = useState(false)
  const [fuzzyHint,    setFuzzyHint]    = useState('')
  const [creating,     setCreating]     = useState(false)
  const dropRef = useRef<HTMLDivElement>(null)

  // Close dropdown on outside click
  useEffect(() => {
    function handle(e: MouseEvent) {
      if (dropRef.current && !dropRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [])

  async function handleQueryChange(val: string) {
    setQuery(val)
    onChange(index, 'medicine_name', val)
    onChange(index, 'medicine_id', '')    // clear until picked from catalog

    if (val.length < 2) { setSuggestions([]); setFuzzyHint(''); return }

    try {
      const results = await searchMedicines(val, 'active')
      setSuggestions(results)
      setShowDropdown(true)

      // Fuzzy hint: find a match on collapsed string (no spaces/dashes)
      const collapsed = val.toLowerCase().replace(/[\s-]/g, '')
      const hint = results.find(r =>
        r.name.toLowerCase().replace(/[\s-]/g, '').includes(collapsed) &&
        r.name.toLowerCase() !== val.toLowerCase()
      )
      setFuzzyHint(hint?.name ?? '')
    } catch { setSuggestions([]) }
  }

  function pickSuggestion(item: MedicineCatalogItem) {
    setQuery(item.name)
    setShowDropdown(false)
    setSuggestions([])
    setFuzzyHint('')
    onChange(index, 'medicine_id',   item.id)
    onChange(index, 'medicine_name', item.name)
    if (item.default_dosage) onChange(index, 'dosage', item.default_dosage)
  }

  async function handleAddNew() {
    if (!query.trim() || creating) return
    setCreating(true)
    try {
      const med = await createMedicine({ name: query.trim() })
      pickSuggestion(med)
    } catch { /* best effort */ } finally {
      setCreating(false)
    }
    setShowDropdown(false)
  }

  const FieldLabel = ({ children }: { children: React.ReactNode }) => (
    <label className="block text-[10px] text-[#697C70] uppercase tracking-wider font-semibold mb-1">
      {children}
    </label>
  )

  const Input = (props: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input
      {...props}
      className="w-full bg-white border border-[#E8E4DA] rounded-xl px-3 py-2 text-[#2D3536] placeholder-[#A0A09A] focus:outline-none focus:border-[#98AA9D] transition-all text-sm shadow-sm"
    />
  )

  return (
    <div className="bg-[#FAF9F5] border border-[#E8E4DA] rounded-2xl p-4 relative">
      {showRemove && (
        <button
          type="button"
          onClick={() => onRemove(index)}
          className="absolute top-3 right-3 text-[#697C70] hover:text-[#8B1A1A] transition-colors"
          aria-label="Remove medicine"
        >
          <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M18 6 6 18M6 6l12 12" strokeLinecap="round" />
          </svg>
        </button>
      )}

      {/* Medicine search */}
      <div className="mb-3 relative" ref={dropRef}>
        <FieldLabel>Medicine name</FieldLabel>
        <Input
          type="text"
          value={query}
          onChange={e => handleQueryChange(e.target.value)}
          onFocus={() => suggestions.length > 0 && setShowDropdown(true)}
          placeholder="Search medicine catalog…"
          aria-label="Medicine name"
          aria-autocomplete="list"
          aria-expanded={showDropdown}
        />

        {/* Autocomplete dropdown */}
        {showDropdown && (query.length >= 2) && (
          <div
            className="absolute top-full left-0 right-0 mt-1 bg-white border border-[#E8E4DA] rounded-xl overflow-hidden z-20 shadow-xl divide-y divide-[#E8E4DA]/60"
            role="listbox"
          >
            {suggestions.slice(0, 6).map(item => (
              <button
                key={item.id}
                type="button"
                role="option"
                aria-selected={row.medicine_id === item.id}
                onClick={() => pickSuggestion(item)}
                className="w-full text-left flex items-center justify-between px-3.5 py-2.5 hover:bg-[#EEF3EF] transition-colors"
              >
                <span className="text-sm text-[#2D3536] font-medium">{item.name}</span>
                {item.status === 'pending_review' && (
                  <span className="text-[10px] bg-[#FDE8C0] text-[#7A4A00] px-2 py-0.5 rounded-full ml-2 shrink-0 font-medium">
                    Pending review
                  </span>
                )}
              </button>
            ))}
            <button
              type="button"
              onClick={handleAddNew}
              disabled={creating}
              className="w-full text-left flex items-center gap-2 px-3.5 py-2.5 hover:bg-[#EEF3EF] text-[#697C70] hover:text-[#2D3536] text-sm transition-colors font-medium"
            >
              <svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
                <path d="M12 5v14M5 12h14" strokeLinecap="round" />
              </svg>
              {creating ? 'Adding…' : `Add "${query}" as new entry`}
            </button>
          </div>
        )}

        {/* Fuzzy hint */}
        {fuzzyHint && (
          <p className="text-[11px] text-[#7A4A00] mt-1 font-medium">
            Did you mean{' '}
            <button
              type="button"
              onClick={() => handleQueryChange(fuzzyHint)}
              className="underline font-bold"
            >
              {fuzzyHint}
            </button>?
          </p>
        )}
      </div>

      {/* Dosage / Frequency / Duration */}
      <div className="grid grid-cols-3 gap-2 mb-2">
        <div>
          <FieldLabel>Dosage</FieldLabel>
          <Input
            type="text"
            value={row.dosage}
            onChange={e => onChange(index, 'dosage', e.target.value)}
            placeholder="e.g. 500mg"
          />
        </div>
        <div>
          <FieldLabel>Frequency</FieldLabel>
          <select
            value={row.frequency}
            onChange={e => onChange(index, 'frequency', e.target.value)}
            className="w-full bg-white border border-[#E8E4DA] rounded-xl px-3 py-2 text-[#2D3536] focus:outline-none focus:border-[#98AA9D] text-sm shadow-sm"
          >
            <option value="">Select</option>
            {FREQUENCY_OPTIONS.map(f => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </select>
        </div>
        <div>
          <FieldLabel>Duration</FieldLabel>
          <select
            value={row.duration}
            onChange={e => onChange(index, 'duration', e.target.value)}
            className="w-full bg-white border border-[#E8E4DA] rounded-xl px-3 py-2 text-[#2D3536] focus:outline-none focus:border-[#98AA9D] text-sm shadow-sm"
          >
            <option value="">Select</option>
            {DURATION_OPTIONS.map(d => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Instructions */}
      <div>
        <FieldLabel>Instructions to patient</FieldLabel>
        <Input
          type="text"
          value={row.instructions}
          onChange={e => onChange(index, 'instructions', e.target.value)}
          placeholder="e.g. Take after meals. Avoid alcohol."
        />
      </div>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function ConsultationScreen() {
  const { appointmentId } = useParams<{ appointmentId: string }>()
  const navigate = useNavigate()

  const [appt,      setAppt]      = useState<DoctorAppointmentCard | null>(null)
  const [notes,     setNotes]     = useState('')
  const [meds,      setMeds]      = useState<MedRow[]>([emptyRow()])
  const [followUp,  setFollowUp]  = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error,     setError]     = useState('')

  useEffect(() => {
    if (!appointmentId) return
    getDoctorAppointment(appointmentId)
      .then(setAppt)
      .catch(() => { /* best effort */ })
  }, [appointmentId])

  const updateMed = useCallback((i: number, field: keyof MedRow, val: string) => {
    setMeds(prev => prev.map((m, idx) => idx === i ? { ...m, [field]: val } : m))
  }, [])

  const addMed    = () => setMeds(prev => [...prev, emptyRow()])
  const removeMed = (i: number) => setMeds(prev => prev.filter((_, idx) => idx !== i))

  const validNotes = notes.trim().length >= 10
  const validMeds  = meds.every(m =>
    !m.medicine_name || (m.medicine_id && m.dosage && m.frequency && m.duration)
  )
  const canSubmit  = validNotes && validMeds && !submitting

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit || !appointmentId) return
    setError('')
    setSubmitting(true)

    const prescriptions: PrescriptionRow[] = meds
      .filter(m => m.medicine_id)
      .map((m, i) => ({
        medicine_id:  m.medicine_id,
        dosage:       m.dosage,
        frequency:    m.frequency,
        duration:     m.duration,
        instructions: m.instructions,
        sort_order:   i,
      }))

    try {
      await submitConsultation(appointmentId, {
        notes,
        prescriptions,
        follow_up_days: followUp ? parseInt(followUp, 10) : null,
      })
      navigate(`/doctor/summary-review/${appointmentId}`)
    } catch (err) {
      setError((err as HFApiError).message ?? 'Failed to submit consultation.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between bg-white border border-[#E8E4DA] rounded-2xl p-5 shadow-sm">
        <div>
          <h2 className="text-xl text-[#2D3536] font-bold">
            {appt?.patient_name ?? 'Consultation'}
          </h2>
          <p className="text-[#697C70] text-sm mt-0.5">
            {appt ? `Token #${appt.token ?? '—'} · ${appt.urgency_level || ''}` : ''}
          </p>
        </div>
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="text-xs font-semibold text-[#697C70] hover:text-[#2D3536] px-3 py-1.5 rounded-xl hover:bg-[#EEF3EF] transition-colors"
        >
          ← Back
        </button>
      </div>

      {error && (
        <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3 font-medium">
          {error}
        </p>
      )}

      <form onSubmit={handleSubmit} className="space-y-6" noValidate>
        {/* Notes */}
        <div className="bg-white border border-[#E8E4DA] rounded-2xl p-5 shadow-sm">
          <label htmlFor="notes" className="block text-xs text-[#697C70] uppercase tracking-wider font-semibold mb-2">
            Consultation notes
          </label>
          <textarea
            id="notes"
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="Enter your clinical notes — findings, diagnosis, management plan…"
            rows={7}
            minLength={10}
            required
            aria-describedby="notes-hint"
            className="w-full bg-white border border-[#E8E4DA] rounded-xl px-4 py-3 text-[#2D3536] placeholder-[#A0A09A] focus:outline-none focus:border-[#98AA9D] transition-all text-sm resize-none leading-relaxed shadow-sm"
          />
          <p id="notes-hint" className="text-[10px] text-[#697C70] mt-1 text-right">
            {notes.trim().length} chars{notes.trim().length < 10 && notes.length > 0 ? ' — minimum 10' : ''}
          </p>
        </div>

        {/* Prescriptions */}
        <div className="bg-white border border-[#E8E4DA] rounded-2xl p-5 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm font-bold text-[#2D3536]">Prescription</p>
            <button
              type="button"
              onClick={addMed}
              className="text-xs text-[#697C70] hover:text-[#2D3536] font-semibold bg-[#EEF3EF] px-3 py-1.5 rounded-xl transition-colors flex items-center gap-1.5"
            >
              <svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
                <path d="M12 5v14M5 12h14" strokeLinecap="round" />
              </svg>
              Add medicine
            </button>
          </div>
          <div className="space-y-3">
            {meds.map((med, i) => (
              <PrescriptionRowEditor
                key={i}
                index={i}
                row={med}
                onChange={updateMed}
                onRemove={removeMed}
                showRemove={meds.length > 1}
              />
            ))}
          </div>
        </div>

        {/* Follow-up */}
        <div className="bg-white border border-[#E8E4DA] rounded-2xl p-5 shadow-sm">
          <label htmlFor="followup" className="block text-xs text-[#697C70] uppercase tracking-wider font-semibold mb-2">
            Follow up in (days) — optional
          </label>
          <input
            id="followup"
            type="number"
            min="1"
            max="365"
            value={followUp}
            onChange={e => setFollowUp(e.target.value)}
            placeholder="e.g. 7"
            className="w-36 bg-white border border-[#E8E4DA] rounded-xl px-4 py-2.5 text-[#2D3536] placeholder-[#A0A09A] focus:outline-none focus:border-[#98AA9D] text-sm shadow-sm"
          />
        </div>

        <button
          type="submit"
          disabled={!canSubmit}
          className="w-full bg-[#98AA9D] text-white rounded-2xl py-4 font-semibold text-sm hover:bg-[#85988A] transition-colors disabled:opacity-40 shadow-sm"
        >
          {submitting ? 'Completing visit…' : 'Mark visit complete & generate summary'}
        </button>
      </form>
    </div>
  )
}
