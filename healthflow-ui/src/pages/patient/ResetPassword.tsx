/**
 * Forced-reset screen — shown when must_reset_password=true after login.
 * Uses the reset-password API endpoint (token-based, same flow as forgot-password).
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { forgotPassword, resetPassword } from '@/lib/api'
import type { HFApiError } from '@/lib/api'

export default function ResetPassword() {
  const navigate = useNavigate()
  const { user, clearMustReset } = useAuth()
  const [step, setStep] = useState<'request' | 'reset'>('request')
  const [email, setEmail] = useState('')
  const [token, setToken] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')

  async function handleRequest(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await forgotPassword(email)
      setInfo('Check your email for the reset link / token.')
      setStep('reset')
    } catch {
      setInfo('Check your email for the reset link / token.')
      setStep('reset')
    } finally {
      setLoading(false)
    }
  }

  async function handleReset(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await resetPassword(token, newPassword)
      clearMustReset()
      navigate(user?.role === 'doctor' ? '/doctor/day-view' : user?.role === 'admin' ? '/admin/dashboard' : '/patient/search')
    } catch (err) {
      const e = err as HFApiError
      setError(e.message ?? 'Reset failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#F2EFE2] flex items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2 mb-8">
          <div className="w-8 h-8 rounded-lg bg-[#98AA9D] flex items-center justify-center">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 4v16M4 12h16" stroke="white" strokeWidth="2.5" strokeLinecap="round" />
            </svg>
          </div>
          <span className="text-[#2D3536] font-semibold">HealthFlow</span>
        </div>

        <h1 className="text-2xl font-semibold text-[#2D3536] mb-1 font-serif">Set your password</h1>
        <p className="text-sm text-[#697C70] mb-7">
          Your account requires a password reset before you can continue.
        </p>

        {error && <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3 mb-4">{error}</p>}
        {info && <p className="text-sm text-[#697C70] bg-[#EEF3EF] rounded-xl px-4 py-3 mb-4">{info}</p>}

        {step === 'request' ? (
          <form onSubmit={handleRequest} className="space-y-4" noValidate>
            <div>
              <label htmlFor="reset-email" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider">
                Your email
              </label>
              <input
                id="reset-email" type="email" required
                value={email} onChange={e => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full bg-white border border-[#D8D2C4] rounded-xl px-4 py-3 text-[#2D3536] focus:outline-none focus:border-[#98AA9D] focus:ring-2 focus:ring-[#98AA9D]/20 transition-all text-sm"
              />
            </div>
            <button type="submit" disabled={loading}
              className="w-full bg-[#98AA9D] text-white rounded-xl py-3.5 font-semibold text-sm hover:bg-[#7A9080] transition-colors disabled:opacity-60">
              {loading ? 'Sending…' : 'Send reset token to email'}
            </button>
          </form>
        ) : (
          <form onSubmit={handleReset} className="space-y-4" noValidate>
            <div>
              <label htmlFor="reset-token" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider">
                Reset token (from email)
              </label>
              <input
                id="reset-token" type="text" required
                value={token} onChange={e => setToken(e.target.value)}
                placeholder="Paste token here"
                className="w-full bg-white border border-[#D8D2C4] rounded-xl px-4 py-3 text-[#2D3536] font-mono text-sm focus:outline-none focus:border-[#98AA9D] focus:ring-2 focus:ring-[#98AA9D]/20 transition-all"
              />
            </div>
            <div>
              <label htmlFor="new-password" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider">
                New password
              </label>
              <input
                id="new-password" type="password" required minLength={8}
                value={newPassword} onChange={e => setNewPassword(e.target.value)}
                placeholder="At least 8 characters"
                className="w-full bg-white border border-[#D8D2C4] rounded-xl px-4 py-3 text-[#2D3536] focus:outline-none focus:border-[#98AA9D] focus:ring-2 focus:ring-[#98AA9D]/20 transition-all text-sm"
              />
            </div>
            <button type="submit" disabled={loading}
              className="w-full bg-[#2D3536] text-white rounded-xl py-3.5 font-semibold text-sm hover:bg-[#3D4546] transition-colors disabled:opacity-60">
              {loading ? 'Saving…' : 'Set password & continue'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
