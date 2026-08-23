/**
 * Patient — Symptom Form (Phase 4)
 *
 * Shown after a slot hold is created. Patient describes their symptoms,
 * optionally attaches lab results/images (PDF, JPEG, PNG ≤ 5 MB, up to 5 files),
 * then confirms. On confirm, navigates to BookingConfirmation.
 * If the patient navigates away without confirming, the hold expires via TTL.
 */
import { useRef, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  confirmAppointment,
  cancelHold,
  uploadAttachment,
  deleteAttachment,
  type AppointmentDetail,
  type DoctorSearchResult,
  type AppointmentSlot,
  type PreVisitAttachment,
  type HFApiError,
} from '@/lib/api'
import AIDisclaimer from '@/components/AIDisclaimer'

interface LocationState {
  appointment: AppointmentDetail
  doctor: DoctorSearchResult | null
  slot: AppointmentSlot | undefined
}

const MAX_FILES     = 5
const MAX_BYTES     = 5 * 1024 * 1024           // 5 MB
const ALLOWED_TYPES = ['application/pdf', 'image/jpeg', 'image/png']
const ALLOWED_EXTS  = ['.pdf', '.jpg', '.jpeg', '.png']

function humanSize(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${(bytes / 1024).toFixed(0)} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function SymptomForm() {
  const navigate    = useNavigate()
  const location    = useLocation()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { appointment, doctor, slot } = (location.state ?? {}) as LocationState

  const [symptoms,    setSymptoms]    = useState('')
  const [attachments, setAttachments] = useState<PreVisitAttachment[]>([])
  const [uploading,   setUploading]   = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [loading,     setLoading]     = useState(false)
  const [cancelling,  setCancelling]  = useState(false)
  const [error,       setError]       = useState('')

  if (!appointment) {
    navigate('/patient/search', { replace: true })
    return null
  }

  const charCount = symptoms.length
  const isValid   = charCount >= 10
  const slotLabel = slot
    ? `${slot.slot_start.slice(0, 5)}–${slot.slot_end.slice(0, 5)}`
    : ''

  // ─── File upload ────────────────────────────────────────────────────────────

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? [])
    if (!files.length) return
    // Reset input so same file can be re-selected after delete
    if (fileInputRef.current) fileInputRef.current.value = ''

    setUploadError('')

    if (attachments.length + files.length > MAX_FILES) {
      setUploadError(`Maximum ${MAX_FILES} files allowed.`)
      return
    }

    for (const file of files) {
      // Client-side validation before touching the server
      const ext = '.' + (file.name.split('.').pop() ?? '').toLowerCase()
      if (!ALLOWED_EXTS.includes(ext) && !ALLOWED_TYPES.includes(file.type)) {
        setUploadError(`${file.name}: unsupported type. Allowed: PDF, JPEG, PNG.`)
        return
      }
      if (file.size > MAX_BYTES) {
        setUploadError(`${file.name}: exceeds 5 MB limit.`)
        return
      }
    }

    setUploading(true)
    try {
      const uploaded: PreVisitAttachment[] = []
      for (const file of files) {
        const att = await uploadAttachment(appointment.id, file)
        uploaded.push(att)
      }
      setAttachments(prev => [...prev, ...uploaded])
    } catch (err) {
      setUploadError((err as HFApiError).message ?? 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }

  async function handleRemoveAttachment(att: PreVisitAttachment) {
    try {
      await deleteAttachment(appointment.id, att.id)
      setAttachments(prev => prev.filter(a => a.id !== att.id))
    } catch {
      // Best effort — file may already be gone server-side
      setAttachments(prev => prev.filter(a => a.id !== att.id))
    }
  }

  // ─── Confirm / cancel ───────────────────────────────────────────────────────

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!isValid) return
    setError('')
    setLoading(true)
    try {
      const confirmed = await confirmAppointment(appointment.id, { symptom_text: symptoms })
      navigate('/patient/booking-confirmation', {
        replace: true,
        state: { appointment: confirmed, doctor, slot },
      })
    } catch (err) {
      const apiErr = err as HFApiError
      if (apiErr.status === 409) {
        setError('This slot is no longer available. Your hold has been released.')
      } else {
        setError(apiErr.message ?? 'Failed to confirm booking.')
      }
    } finally {
      setLoading(false)
    }
  }

  async function handleCancel() {
    setCancelling(true)
    try { await cancelHold(appointment.id) } catch { /* best effort */ }
    navigate(-1)
  }

  // ─── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="p-4 pb-28 space-y-5">
      {/* Header */}
      <div>
        <h2 className="text-xl font-semibold text-[#2D3536] font-serif">Describe your symptoms</h2>
        <p className="text-xs text-[#697C70] mt-1">
          {doctor?.name && `${doctor.name} · `}{slotLabel}
        </p>
      </div>

      {/* Hold notice */}
      <div className="bg-[#FDE8C0]/40 border border-[#FDE8C0] rounded-xl px-4 py-3" role="note">
        <p className="text-xs text-[#7A4A00] leading-relaxed">
          Your seat is temporarily reserved. Complete this form to confirm your booking.
        </p>
      </div>

      {error && (
        <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3">
          {error}
        </p>
      )}

      <form onSubmit={handleSubmit} className="space-y-5" noValidate>
        {/* Symptom text */}
        <div>
          <label htmlFor="symptoms" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider">
            What brings you in?
          </label>
          <textarea
            id="symptoms"
            value={symptoms}
            onChange={e => setSymptoms(e.target.value)}
            rows={6}
            placeholder="Describe your main symptoms, when they started, and anything that makes them better or worse…"
            required
            minLength={10}
            maxLength={2000}
            aria-describedby="symptoms-hint"
            className="w-full bg-white border border-[#D8D2C4] rounded-2xl px-4 py-3 text-[#2D3536] placeholder-[#B8B4AC] focus:outline-none focus:border-[#98AA9D] focus:ring-2 focus:ring-[#98AA9D]/20 text-sm leading-relaxed resize-none transition-all"
          />
          <p id="symptoms-hint" className="text-xs text-[#A0A09A] mt-1.5 text-right">
            {charCount}/2000{charCount < 10 && charCount > 0 ? ' — at least 10 characters' : ''}
          </p>
        </div>

        {/* File attachment — wired to real API */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs text-[#697C70] uppercase tracking-wider">
              Attach lab results (optional)
            </p>
            <p className="text-xs text-[#A0A09A]">{attachments.length}/{MAX_FILES}</p>
          </div>

          {/* Uploaded files list */}
          {attachments.length > 0 && (
            <ul className="space-y-2 mb-3">
              {attachments.map(att => (
                <li
                  key={att.id}
                  className="flex items-center gap-3 bg-white border border-[#E8E4DA] rounded-xl px-3 py-2.5"
                >
                  <div
                    className="w-7 h-7 rounded-lg bg-[#EEF3EF] flex items-center justify-center text-[#697C70] shrink-0 text-[9px] font-bold uppercase"
                    aria-hidden="true"
                  >
                    {att.file_type}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-[#2D3536] truncate">{att.original_filename}</p>
                    <p className="text-[10px] text-[#A0A09A]">{humanSize(att.file_size_bytes)}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleRemoveAttachment(att)}
                    className="text-xs text-[#A0A09A] hover:text-[#8B1A1A] transition-colors shrink-0"
                    aria-label={`Remove ${att.original_filename}`}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}

          {/* Upload button / drop zone */}
          {attachments.length < MAX_FILES && (
            <>
              <input
                ref={fileInputRef}
                type="file"
                id="attachment-input"
                accept=".pdf,.jpg,.jpeg,.png"
                multiple
                onChange={handleFileChange}
                className="sr-only"
                aria-label="Attach files"
              />
              <label
                htmlFor="attachment-input"
                className={`flex flex-col items-center border-2 border-dashed rounded-2xl px-4 py-5 text-center cursor-pointer transition-colors ${
                  uploading
                    ? 'border-[#98AA9D] bg-[#EEF3EF]'
                    : 'border-[#D8D2C4] hover:border-[#98AA9D] hover:bg-[#F5F8F5]'
                }`}
              >
                {uploading ? (
                  <p className="text-xs text-[#697C70]">Uploading…</p>
                ) : (
                  <>
                    <svg
                      width="22" height="22" fill="none" viewBox="0 0 24 24"
                      stroke="#B8B4AC" strokeWidth="1.5" className="mb-1.5"
                      aria-hidden="true"
                    >
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    <p className="text-xs text-[#A0A09A]">PDF, JPEG, or PNG · Max 5 MB each</p>
                    <p className="text-[10px] text-[#B8B4AC] mt-0.5">Click to browse</p>
                  </>
                )}
              </label>
            </>
          )}

          {uploadError && (
            <p role="alert" className="text-xs text-[#8B1A1A] mt-2">{uploadError}</p>
          )}
        </div>

        {/* AI disclaimer */}
        <AIDisclaimer />

        {/* CTA bar */}
        <div className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-md px-4 pb-6 pt-3 bg-[#F2EFE2]/95 backdrop-blur border-t border-[#D8D2C4] space-y-2">
          <button
            type="submit"
            disabled={!isValid || loading || uploading}
            className="w-full bg-[#98AA9D] text-white rounded-2xl py-4 font-semibold text-base hover:bg-[#7A9080] transition-colors disabled:opacity-60"
          >
            {loading ? 'Confirming booking…' : 'Confirm booking'}
          </button>
          <button
            type="button"
            onClick={handleCancel}
            disabled={cancelling || loading}
            className="w-full text-sm text-[#697C70] hover:text-[#2D3536] transition-colors py-1"
          >
            {cancelling ? 'Releasing…' : 'Cancel and go back'}
          </button>
        </div>
      </form>
    </div>
  )
}
