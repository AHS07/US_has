/**
 * Doctor — Summary Review & Approval Gate
 *
 * Side-by-side: raw consultation notes (left) vs AI-drafted patient summary (right).
 * Doctor can edit the draft inline before approving.
 * On approve: PUT /doctor/appointments/:id/summary/approve → navigates to DayView.
 *
 * Route: /doctor/summary-review/:appointmentId
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { animate } from 'animejs'
import {
  getSummaryDraft,
  approveSummary,
  type SummaryDraft,
  type HFApiError,
} from '@/lib/api'
import AIDisclaimer from '@/components/AIDisclaimer'

export default function SummaryReview() {
  const { appointmentId } = useParams<{ appointmentId: string }>()
  const navigate           = useNavigate()
  const approveRef         = useRef<HTMLButtonElement>(null)

  const [draft,      setDraft]      = useState<SummaryDraft | null>(null)
  const [loading,    setLoading]    = useState(true)
  const [editMode,   setEditMode]   = useState(false)
  const [editedText, setEditedText] = useState('')
  const [approving,  setApproving]  = useState(false)
  const [approved,   setApproved]   = useState(false)
  const [error,      setError]      = useState('')
  const [pollCount,  setPollCount]  = useState(0)

  // Poll when still pending
  useEffect(() => {
    if (!appointmentId) return
    let timer: ReturnType<typeof setTimeout>

    async function fetch() {
      try {
        const data = await getSummaryDraft(appointmentId!)
        setDraft(data)
        setEditedText(data.summary_text)
        setLoading(false)

        if (data.summary_status === 'pending') {
          // Poll every 3 s while LLM job is running
          timer = setTimeout(() => setPollCount(c => c + 1), 3000)
        }
      } catch (err) {
        setError((err as HFApiError).message ?? 'Failed to load summary.')
        setLoading(false)
      }
    }

    void fetch()
    return () => clearTimeout(timer)
  }, [appointmentId, pollCount])

  async function handleApprove() {
    if (!appointmentId || approving) return
    setError('')
    setApproving(true)
    try {
      await approveSummary(appointmentId, editedText)
      setApproved(true)
      // Bounce the approve button
      if (approveRef.current) {
        animate(approveRef.current, {
          scale: [1, 1.05, 1],
          duration: 400,
          easing: 'easeOutElastic(1, .5)',
        })
      }
      setTimeout(() => navigate('/doctor/day-view'), 900)
    } catch (err) {
      setError((err as HFApiError).message ?? 'Approval failed.')
    } finally {
      setApproving(false)
    }
  }

  if (loading) {
    return (
      <div className="p-6 space-y-4 max-w-5xl mx-auto">
        <div className="h-8 w-64 rounded-xl bg-white border border-[#E8E4DA] animate-pulse" />
        <div className="grid grid-cols-2 gap-4">
          <div className="h-64 rounded-2xl bg-white border border-[#E8E4DA] animate-pulse" />
          <div className="h-64 rounded-2xl bg-white border border-[#E8E4DA] animate-pulse" />
        </div>
      </div>
    )
  }

  if (error && !draft) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <p className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3 font-medium">{error}</p>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="bg-white border border-[#E8E4DA] rounded-2xl p-5 shadow-sm">
        <h2 className="text-xl text-[#2D3536] font-bold">Review & approve summary</h2>
        <p className="text-[#697C70] text-sm mt-0.5">
          {draft?.summary_status === 'pending'
            ? 'AI summary is being generated…'
            : 'Review the AI draft. Edit if needed, then approve to make it visible to the patient.'}
        </p>
      </div>

      {error && (
        <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3 font-medium">
          {error}
        </p>
      )}

      {/* Pending state */}
      {draft?.summary_status === 'pending' && (
        <div className="bg-white border border-[#E8E4DA] rounded-2xl p-8 flex items-center justify-center gap-4 shadow-sm">
          <span className="w-3 h-3 rounded-full bg-[#E8A838] animate-pulse shrink-0" aria-hidden="true" />
          <p className="text-[#697C70] text-sm font-medium">AI is writing the patient summary… checking again in a moment.</p>
        </div>
      )}

      {/* Draft / unavailable state */}
      {draft && draft.summary_status !== 'pending' && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Raw notes */}
            <div className="bg-white border border-[#E8E4DA] rounded-2xl p-5 flex flex-col shadow-sm">
              <p className="text-[10px] text-[#697C70] uppercase tracking-wider font-semibold mb-3">
                Your notes (raw — doctor reference only)
              </p>
              <p className="text-[#2D3536] text-sm leading-relaxed whitespace-pre-line flex-1 bg-[#FAF9F5] p-4 rounded-xl border border-[#E8E4DA]">
                {draft.visit_notes || 'No notes found.'}
              </p>
            </div>

            {/* AI draft */}
            <div className={`border rounded-2xl p-5 flex flex-col transition-all shadow-sm ${
              editMode
                ? 'bg-white border-[#98AA9D] ring-2 ring-[#98AA9D]/20'
                : 'bg-white border-[#E8E4DA]'
            }`}>
              <div className="flex items-center justify-between mb-3">
                <p className="text-[10px] text-[#697C70] uppercase tracking-wider font-semibold">
                  {draft.summary_status === 'unavailable'
                    ? 'AI summary unavailable — edit manually'
                    : 'AI-written patient summary'}
                </p>
                <button
                  type="button"
                  onClick={() => setEditMode(m => !m)}
                  className="text-xs text-[#697C70] hover:text-[#2D3536] font-semibold bg-[#EEF3EF] px-2.5 py-1 rounded-lg transition-colors"
                >
                  {editMode ? 'Preview' : 'Edit'}
                </button>
              </div>

              {editMode ? (
                <textarea
                  value={editedText}
                  onChange={e => setEditedText(e.target.value)}
                  rows={12}
                  aria-label="Edit patient summary"
                  className="w-full bg-[#FAF9F5] border border-[#E8E4DA] rounded-xl p-3 text-[#2D3536] text-sm leading-relaxed resize-none focus:outline-none focus:border-[#98AA9D] transition-all flex-1"
                />
              ) : (
                <p className="text-[#2D3536] text-sm leading-relaxed whitespace-pre-line flex-1 bg-[#FAF9F5] p-4 rounded-xl border border-[#E8E4DA]">
                  {editedText || (
                    <span className="text-[#A0A09A] italic">
                      No draft text yet. Switch to Edit mode to write the summary manually.
                    </span>
                  )}
                </p>
              )}

              <div className="mt-4 pt-4 border-t border-[#E8E4DA]">
                <AIDisclaimer compact />
              </div>
            </div>
          </div>

          {/* Prescription summary */}
          {draft.medications.length > 0 && (
            <div className="bg-white border border-[#E8E4DA] rounded-2xl p-5 shadow-sm">
              <p className="text-xs text-[#697C70] uppercase tracking-wider font-semibold mb-3">
                Prescription ({draft.medications.length} medicine{draft.medications.length !== 1 ? 's' : ''})
              </p>
              <div className="space-y-2">
                {draft.medications.map(rx => (
                  <div
                    key={rx.id}
                    className="flex items-center gap-3 bg-[#FAF9F5] border border-[#E8E4DA] rounded-xl px-4 py-2.5"
                  >
                    <p className="font-semibold text-[#2D3536] text-sm flex-1">{rx.medicine_name}</p>
                    <span className="text-xs font-mono text-[#697C70]">{rx.dosage}</span>
                    <span className="text-xs text-[#697C70]">{rx.frequency_display}</span>
                    <span className="text-xs text-[#697C70]">{rx.duration}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Safety note */}
          <div className="bg-[#FDE8C0]/30 border border-[#FDE8C0] rounded-xl px-4 py-3" role="note">
            <p className="text-xs text-[#7A4A00] leading-relaxed">
              <strong>Important:</strong> The AI summary is based only on the notes and prescription
              you entered. Once you approve, this text will be visible to the patient.
              Every approval is logged with your name and timestamp.
            </p>
          </div>

          {/* Actions */}
          <div className="flex gap-4">
            <button
              type="button"
              onClick={() => setEditMode(true)}
              className="flex-1 bg-white border border-[#E8E4DA] text-[#2D3536] rounded-2xl py-4 text-sm font-semibold hover:bg-[#EEF3EF] transition-colors shadow-sm"
            >
              Edit before approving
            </button>
            <button
              ref={approveRef}
              type="button"
              onClick={handleApprove}
              disabled={approved || approving || editedText.trim().length < 10}
              className={`flex-1 min-w-[200px] rounded-2xl py-4 text-sm font-semibold transition-all shadow-sm ${
                approved
                  ? 'bg-[#98AA9D]/70 text-white cursor-default'
                  : 'bg-[#98AA9D] text-white hover:bg-[#85988A] disabled:opacity-50'
              }`}
            >
              {approved ? (
                <span className="flex items-center justify-center gap-2">
                  <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="white" strokeWidth="2.5" aria-hidden="true">
                    <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Approved — sending to patient
                </span>
              ) : approving ? (
                'Approving…'
              ) : (
                'Approve & send to patient'
              )}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
