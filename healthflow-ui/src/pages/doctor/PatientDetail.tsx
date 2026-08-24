/**
 * Doctor — Patient Detail (pre-visit briefing card)  [Phase 4]
 *
 * Fetches the full DoctorAppointmentCard from /doctor/appointments/:id.
 * Shows real AI pre-visit summary content when pre_summary_status = 'ready',
 * the generating spinner when 'pending', and a symptom fallback when 'unavailable'.
 * Attachment list with view links.
 *
 * Route: /doctor/appointments/:appointmentId
 */
import { useParams, useNavigate } from 'react-router-dom'
import { useEffect, useRef, useState } from 'react'
import { animate } from 'animejs'
import AIDisclaimer from '@/components/AIDisclaimer'
import UrgencyBadge from '@/components/UrgencyBadge'
import {
  getDoctorAppointment,
  type DoctorAppointmentCard,
  type PreSummaryContent,
  type HFApiError,
} from '@/lib/api'

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function Skeleton({ className }: { className: string }) {
  return <div className={`bg-[#E8E4DA] rounded-lg animate-pulse ${className}`} />
}

// ─── AI summary card ──────────────────────────────────────────────────────────

function AISummaryCard({
  status,
  content,
  symptomText,
}: {
  status: DoctorAppointmentCard['pre_summary_status']
  content: PreSummaryContent | null
  symptomText: string
}) {
  if (status === 'pending') {
    return (
      <div className="bg-white border border-[#E8E4DA] rounded-2xl p-5 space-y-3 shadow-sm">
        <p className="text-xs text-[#697C70] uppercase tracking-wider font-semibold">Pre-visit summary</p>
        <div className="flex items-center gap-3">
          <span className="w-2 h-2 rounded-full bg-[#E8A838] animate-pulse shrink-0" aria-hidden="true" />
          <p className="text-sm text-[#697C70]">AI summary is being generated…</p>
        </div>
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    )
  }

  if (status === 'unavailable' || !content) {
    return (
      <div className="bg-white border border-[#E8E4DA] rounded-2xl p-5 space-y-4 shadow-sm">
        <div className="flex items-center justify-between">
          <p className="text-xs text-[#697C70] uppercase tracking-wider font-semibold">Pre-visit summary</p>
          <span className="text-xs text-[#697C70] bg-[#EEF3EF] px-2.5 py-0.5 rounded-full font-medium">
            Summary unavailable
          </span>
        </div>
        <p className="text-xs text-[#697C70] leading-relaxed">
          The AI summary could not be generated. Patient's symptom text is shown below.
        </p>
        {symptomText && (
          <div className="bg-[#FAF9F5] border border-[#E8E4DA] rounded-xl px-4 py-3">
            <p className="text-xs text-[#697C70] uppercase tracking-wider font-semibold mb-2">
              Patient's symptoms
            </p>
            <p className="text-sm text-[#2D3536] leading-relaxed">{symptomText}</p>
          </div>
        )}
      </div>
    )
  }

  // ready — show structured content
  return (
    <div className="bg-white border border-[#E8E4DA] rounded-2xl p-5 space-y-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-[#697C70] uppercase tracking-wider font-semibold">Pre-visit summary</p>
        <span className="text-[10px] text-[#697C70] bg-[#EEF3EF] px-2.5 py-0.5 rounded-full font-semibold">
          AI-suggested — advisory only
        </span>
      </div>

      {/* Urgency + chief complaint */}
      <div className="flex items-start gap-3">
        <UrgencyBadge level={content.urgency} />
        <p className="text-sm text-[#2D3536] leading-relaxed flex-1 font-medium">{content.chief_complaint}</p>
      </div>

      {/* Duration */}
      {content.duration_mentioned && (
        <p className="text-xs text-[#697C70]">
          Duration mentioned: <span className="text-[#2D3536] font-semibold">{content.duration_mentioned}</span>
        </p>
      )}

      {/* Red flags */}
      {content.red_flags.length > 0 && (
        <div className="bg-[#F5D0CC]/30 border border-[#F5D0CC] rounded-xl px-4 py-3">
          <p className="text-[10px] text-[#8B1A1A] uppercase tracking-wider font-bold mb-1.5">
            Red flags noted
          </p>
          <div className="flex flex-wrap gap-1.5">
            {content.red_flags.map((flag, i) => (
              <span
                key={i}
                className="text-[11px] bg-[#F5D0CC] text-[#8B1A1A] px-2.5 py-0.5 rounded-full font-medium"
              >
                {flag}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Suggested questions */}
      {content.suggested_questions.length > 0 && (
        <div className="bg-[#FAF9F5] border border-[#E8E4DA] rounded-xl p-4">
          <p className="text-xs text-[#697C70] uppercase tracking-wider font-semibold mb-2">
            Suggested questions
          </p>
          <ol className="space-y-2">
            {content.suggested_questions.map((q, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-[#2D3536]">
                <span className="text-[#98AA9D] shrink-0 font-mono text-xs mt-0.5 font-bold">{i + 1}.</span>
                {q}
              </li>
            ))}
          </ol>
        </div>
      )}

      <div className="pt-1">
        <AIDisclaimer compact />
      </div>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function PatientDetail() {
  const { appointmentId } = useParams<{ appointmentId: string }>()
  const navigate    = useNavigate()
  const cardRef     = useRef<HTMLDivElement>(null)

  const [data,    setData]    = useState<DoctorAppointmentCard | null>(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')

  useEffect(() => {
    if (!appointmentId) return
    setLoading(true)
    getDoctorAppointment(appointmentId)
      .then(d => { setData(d) })
      .catch(err => setError((err as HFApiError).message ?? 'Failed to load patient.'))
      .finally(() => setLoading(false))
  }, [appointmentId])

  // Slide card in on load
  useEffect(() => {
    if (!cardRef.current || loading || !data) return
    animate(cardRef.current.querySelectorAll('.anim-in'), {
      opacity: [0, 1],
      translateY: [12, 0],
      delay: (_, i) => (i ?? 0) * 60,
      duration: 350,
      easing: 'easeOutCubic',
    })
  }, [loading, data])

  if (loading) {
    return (
      <div className="p-6 space-y-4 max-w-2xl mx-auto">
        <div className="h-10 rounded-xl bg-white border border-[#E8E4DA] animate-pulse w-1/2" />
        <div className="h-48 rounded-2xl bg-white border border-[#E8E4DA] animate-pulse" />
        <div className="h-32 rounded-2xl bg-white border border-[#E8E4DA] animate-pulse" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6 max-w-2xl mx-auto">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="mb-4 flex items-center gap-1.5 text-xs text-[#697C70] hover:text-[#2D3536] transition-colors"
        >
          <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" />
          </svg>
          Back
        </button>
        <p className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3 font-medium">{error}</p>
      </div>
    )
  }

  if (!data) return null

  return (
    <div className="p-6 space-y-5 max-w-2xl mx-auto" ref={cardRef}>
      {/* Back + title */}
      <div className="flex items-center gap-3 anim-in bg-white border border-[#E8E4DA] rounded-2xl p-4 shadow-sm" style={{ opacity: 0 }}>
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="p-1.5 rounded-lg text-[#697C70] hover:text-[#2D3536] hover:bg-[#EEF3EF] transition-colors"
          aria-label="Go back"
        >
          <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <div className="flex-1">
          <h2 className="text-base font-bold text-[#2D3536]">{data.patient_name}</h2>
          <p className="text-xs text-[#697C70]">
            Token #{data.token ?? '—'}
            {data.urgency_level && ` · ${data.urgency_level} urgency`}
          </p>
        </div>
        {data.urgency_level && (
          <UrgencyBadge level={data.urgency_level as 'Low' | 'Medium' | 'High'} />
        )}
      </div>

      {/* AI summary card */}
      <div className="anim-in" style={{ opacity: 0 }}>
        <AISummaryCard
          status={data.pre_summary_status}
          content={data.pre_summary_content}
          symptomText={data.symptom_text}
        />
      </div>

      {/* Attachments */}
      {data.attachments.length > 0 && (
        <div className="bg-white border border-[#E8E4DA] rounded-2xl p-5 shadow-sm anim-in" style={{ opacity: 0 }}>
          <p className="text-xs text-[#697C70] uppercase tracking-wider font-semibold mb-3">
            Attached files ({data.attachments.length})
          </p>
          <ul className="space-y-2">
            {data.attachments.map(att => (
              <li key={att.id} className="flex items-center gap-3 p-2.5 rounded-xl hover:bg-[#FAF9F5] border border-transparent hover:border-[#E8E4DA] transition-all">
                <div
                  className="w-8 h-8 rounded-lg bg-[#EEF3EF] flex items-center justify-center text-[#697C70] text-[9px] font-bold uppercase shrink-0"
                  aria-hidden="true"
                >
                  {att.file_type}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-[#2D3536] font-medium truncate">{att.original_filename}</p>
                  <p className="text-[10px] text-[#A0A09A]">
                    {new Date(att.uploaded_at).toLocaleDateString('en-IN')}
                  </p>
                </div>
                <a
                  href={att.file_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs font-semibold text-[#697C70] hover:text-[#2D3536] shrink-0"
                  aria-label={`View ${att.original_filename}`}
                >
                  View
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Start consultation CTA */}
      <div className="anim-in" style={{ opacity: 0 }}>
        <button
          type="button"
          onClick={() => navigate(`/doctor/consultation/${data.id}`)}
          className="w-full bg-[#98AA9D] text-white rounded-2xl py-4 font-semibold text-sm hover:bg-[#85988A] transition-colors shadow-sm"
        >
          Start consultation
        </button>
      </div>
    </div>
  )
}
