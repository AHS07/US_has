/**
 * Patient — Post-Visit Summary
 *
 * Doctor-approved visit summary with medication cards and follow-up notice.
 * Only visible when summary_status = 'approved'.
 * Loaded from /appointments/:id/post-visit-summary.
 *
 * Accessed from the Appointments screen by tapping a completed appointment.
 * Route: /patient/appointments/:appointmentId/summary
 */
import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { animate, stagger } from 'animejs'
import {
  getPostVisitSummary,
  type PostVisitSummaryData,
  type HFApiError,
} from '@/lib/api'
import AIDisclaimer from '@/components/AIDisclaimer'

// ─── Medication card ──────────────────────────────────────────────────────────

function MedCard({ med }: { med: PostVisitSummaryData['medications'][number] }) {
  return (
    <div
      className="bg-white border border-[#E8E4DA] rounded-2xl p-4"
      style={{ opacity: 0 }}
      data-med-card
    >
      <div className="flex items-start justify-between gap-2 mb-3">
        <p className="text-sm font-semibold text-[#2D3536]">{med.name}</p>
        <span className="text-xs font-mono text-[#697C70] bg-[#F2EFE2] px-2 py-0.5 rounded-md shrink-0">
          {med.dosage}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 mb-2.5">
        <div>
          <p className="text-[10px] text-[#A0A09A] uppercase tracking-wider">Frequency</p>
          <p className="text-xs text-[#2D3536] mt-0.5 font-medium">{med.frequency}</p>
        </div>
        <div>
          <p className="text-[10px] text-[#A0A09A] uppercase tracking-wider">Duration</p>
          <p className="text-xs text-[#2D3536] mt-0.5 font-medium">{med.duration}</p>
        </div>
      </div>
      {med.instructions && (
        <div className="bg-[#F2EFE2] rounded-lg px-3 py-2">
          <p className="text-[11px] text-[#697C70] leading-relaxed">{med.instructions}</p>
        </div>
      )}
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function PostVisitSummary() {
  const { appointmentId } = useParams<{ appointmentId: string }>()
  const navigate = useNavigate()
  const containerRef = useRef<HTMLDivElement>(null)

  const [data,    setData]    = useState<PostVisitSummaryData | null>(null)
  const [loading, setLoading] = useState(true)
  const [status,  setStatus]  = useState<string | null>(null) // 202 state
  const [error,   setError]   = useState('')

  useEffect(() => {
    if (!appointmentId) return
    getPostVisitSummary(appointmentId)
      .then(d => { setData(d) })
      .catch(async err => {
        const apiErr = err as HFApiError
        if (apiErr.status === 202) {
          // Summary not yet ready
          setStatus('pending')
        } else {
          setError(apiErr.message ?? 'Failed to load summary.')
        }
      })
      .finally(() => setLoading(false))
  }, [appointmentId])

  // Animate medication cards in
  useEffect(() => {
    if (!containerRef.current || !data) return
    const cards = containerRef.current.querySelectorAll('[data-med-card]')
    if (cards.length) {
      animate(cards, {
        opacity: [0, 1],
        translateY: [12, 0],
        delay: stagger(70),
        duration: 380,
        easing: 'easeOutCubic',
      })
    }
  }, [data])

  if (loading) {
    return (
      <div className="px-4 py-5 space-y-4">
        <div className="h-6 w-40 rounded-lg bg-[#E8E4DA] animate-pulse" />
        <div className="h-32 rounded-2xl bg-[#E8E4DA] animate-pulse" />
        <div className="h-24 rounded-2xl bg-[#E8E4DA] animate-pulse" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="px-4 py-5">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="mb-4 flex items-center gap-1.5 text-xs text-[#697C70]"
        >
          ← Back
        </button>
        <p className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3">{error}</p>
      </div>
    )
  }

  if (status === 'pending') {
    return (
      <div className="px-4 py-5 space-y-4">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="flex items-center gap-1.5 text-xs text-[#697C70]"
        >
          ← Back
        </button>
        <div className="bg-white border border-[#E8E4DA] rounded-2xl p-8 text-center">
          <p className="text-sm text-[#697C70]">
            Your visit summary is being prepared and will appear here once your doctor approves it.
          </p>
        </div>
      </div>
    )
  }

  if (!data) return null

  const visitDate = data.approved_at
    ? new Date(data.approved_at).toLocaleDateString('en-IN', {
        day: 'numeric', month: 'long', year: 'numeric',
      })
    : ''

  const approvedTime = data.approved_at
    ? new Date(data.approved_at).toLocaleTimeString('en-IN', {
        hour: '2-digit', minute: '2-digit',
      })
    : ''

  return (
    <div className="px-4 py-5 space-y-5 pb-10" ref={containerRef}>
      {/* Back */}
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="flex items-center gap-1.5 text-xs text-[#697C70] hover:text-[#2D3536] transition-colors"
      >
        ← Back to appointments
      </button>

      {/* Header */}
      <div>
        <p className="text-xs text-[#697C70] mb-1">{visitDate}</p>
        <h2
          className="text-xl text-[#2D3536] leading-tight font-semibold"
          style={{ fontFamily: 'var(--font-serif, serif)' }}
        >
          Your visit summary
        </h2>
        {data.approved_by && (
          <p className="text-xs text-[#697C70] mt-1">
            Approved by {data.approved_by} · {approvedTime}
          </p>
        )}
      </div>

      <AIDisclaimer />

      {/* Summary text */}
      <div className="bg-white border border-[#E8E4DA] rounded-2xl p-5">
        <h3 className="text-sm font-semibold text-[#2D3536] mb-3">What happened at your visit</h3>
        <p className="text-sm text-[#2D3536] leading-relaxed whitespace-pre-line">
          {data.summary_text}
        </p>

        {/* Follow-up */}
        {data.follow_up_days && (
          <div className="mt-4 flex items-center gap-3 bg-[#EEF4F7] rounded-xl px-4 py-3">
            <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="#4A7A94" strokeWidth="1.8" aria-hidden="true">
              <rect x="3" y="4" width="18" height="18" rx="2" />
              <path d="M16 2v4M8 2v4M3 10h18" strokeLinecap="round" />
            </svg>
            <p className="text-sm text-[#2A5570]">
              <strong>Follow up</strong> in {data.follow_up_days} day{data.follow_up_days !== 1 ? 's' : ''}{' '}
              if symptoms persist
            </p>
          </div>
        )}
        {data.follow_up_note && (
          <p className="text-xs text-[#697C70] mt-3 leading-relaxed">{data.follow_up_note}</p>
        )}
      </div>

      {/* Medications */}
      {data.medications.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-[#2D3536] mb-3">
            Medications prescribed ({data.medications.length})
          </h3>
          <div className="space-y-3">
            {data.medications.map((med, i) => (
              <MedCard key={i} med={med} />
            ))}
          </div>
        </div>
      )}

      {/* Disclaimer footer */}
      <div className="text-center pb-2">
        <AIDisclaimer compact />
      </div>
    </div>
  )
}
