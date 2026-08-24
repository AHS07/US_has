import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { animate } from 'animejs'
import { useAuth } from '@/context/AuthContext'
import { forgotPassword, resetPassword } from '@/lib/api'
import type { HFApiError } from '@/lib/api'

type Screen = 'login' | 'forgot' | 'reset'

export default function PatientLogin() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [screen, setScreen] = useState<Screen>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [resetToken, setResetToken] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const cardRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (cardRef.current) {
      animate(cardRef.current, { opacity: [0, 1], translateY: [16, 0], duration: 450, easing: 'easeOutCubic' })
    }
  }, [screen])

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await login(email, password)
      if (res.role !== 'patient') {
        setError('This portal is for patients only.')
        return
      }
      if (res.must_reset_password) {
        navigate('/patient/reset-password')
      } else {
        navigate('/patient/search')
      }
    } catch (err) {
      const e = err as HFApiError
      setError(e.message ?? 'Login failed.')
    } finally {
      setLoading(false)
    }
  }

  async function handleForgot(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await forgotPassword(email)
      setInfo('If that email is registered, a reset link has been sent.')
      setScreen('reset')
    } catch {
      setInfo('If that email is registered, a reset link has been sent.')
      setScreen('reset')
    } finally {
      setLoading(false)
    }
  }

  async function handleReset(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await resetPassword(resetToken, newPassword)
      setInfo('Password reset! Please sign in.')
      setScreen('login')
    } catch (err) {
      const e = err as HFApiError
      setError(e.message ?? 'Reset failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#F7F6F3] flex items-center justify-center p-6">
      <div ref={cardRef} className="w-full max-w-sm bg-white border border-[#E8E4DA] rounded-3xl p-8 shadow-sm" style={{ opacity: 0 }}>
        {/* Back to Role Selection */}
        <button
          type="button"
          onClick={() => navigate('/')}
          className="inline-flex items-center gap-1.5 text-xs text-[#697C70] hover:text-[#2D3536] font-medium mb-6 transition-colors"
        >
          <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Change portal
        </button>

        {/* Brand Header */}
        <div className="flex items-center gap-2.5 mb-8">
          <div className="w-9 h-9 rounded-xl bg-[#98AA9D] flex items-center justify-center shadow-sm">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 4v16M4 12h16" stroke="white" strokeWidth="2.5" strokeLinecap="round" />
            </svg>
          </div>
          <div>
            <p className="text-[#2D3536] font-semibold">HealthFlow</p>
            <p className="text-[#697C70] text-xs">Patient Portal</p>
          </div>
        </div>

        {screen === 'login' && (
          <>
            <h1 className="text-2xl font-bold text-[#2D3536] mb-1 font-serif">Patient sign in</h1>
            <p className="text-[#697C70] text-xs mb-6">Book appointments and access your medical summaries.</p>

            {info && <p className="text-xs text-[#2D3536] bg-[#EEF3EF] rounded-xl px-4 py-3 mb-4 font-medium">{info}</p>}
            {error && <p role="alert" className="text-xs text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3 mb-4 font-medium">{error}</p>}

            <form onSubmit={handleLogin} className="space-y-4" noValidate>
              <div>
                <label htmlFor="patient-email" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider font-medium">
                  Email address
                </label>
                <input
                  id="patient-email" type="email" autoComplete="email" required
                  value={email} onChange={e => setEmail(e.target.value)}
                  placeholder="patient.raj@healthflow.local"
                  className="w-full bg-white border border-[#E8E4DA] rounded-xl px-4 py-3 text-[#2D3536] placeholder-[#A0A09A] focus:outline-none focus:border-[#98AA9D] transition-all text-sm shadow-sm"
                />
              </div>
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label htmlFor="patient-password" className="block text-xs text-[#697C70] uppercase tracking-wider font-medium">
                    Password
                  </label>
                  <button type="button" onClick={() => { setError(''); setInfo(''); setScreen('forgot') }}
                    className="text-xs text-[#697C70] hover:text-[#2D3536] transition-colors">
                    Forgot?
                  </button>
                </div>
                <input
                  id="patient-password" type="password" autoComplete="current-password" required
                  value={password} onChange={e => setPassword(e.target.value)}
                  placeholder="Enter your password"
                  className="w-full bg-white border border-[#E8E4DA] rounded-xl px-4 py-3 text-[#2D3536] placeholder-[#A0A09A] focus:outline-none focus:border-[#98AA9D] transition-all text-sm shadow-sm"
                />
              </div>
              <button type="submit" disabled={loading}
                className="w-full bg-[#2D3536] text-white rounded-xl py-3.5 font-semibold text-sm hover:bg-[#3D4546] transition-colors disabled:opacity-60 mt-2 shadow-sm">
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <circle cx="12" cy="12" r="10" stroke="white" strokeWidth="3" strokeDasharray="32" strokeDashoffset="12" />
                    </svg>
                    Signing in…
                  </span>
                ) : 'Sign in'}
              </button>
            </form>
            <p className="mt-6 text-xs text-center text-[#A0A09A]">
              Don't have an account? Contact your clinic to register.
            </p>
          </>
        )}

        {screen === 'forgot' && (
          <>
            <button onClick={() => setScreen('login')} className="flex items-center gap-1.5 text-[#697C70] hover:text-[#2D3536] mb-5 transition-colors text-xs font-semibold">
              <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Back to sign in
            </button>
            <h2 className="text-xl font-bold text-[#2D3536] mb-1 font-serif">Reset password</h2>
            <p className="text-xs text-[#697C70] mb-5">Enter your email and we'll send a reset link.</p>
            {error && <p role="alert" className="text-xs text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3 mb-4 font-medium">{error}</p>}
            <form onSubmit={handleForgot} className="space-y-4" noValidate>
              <div>
                <label htmlFor="forgot-email" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider font-medium">
                  Email address
                </label>
                <input
                  id="forgot-email" type="email" required value={email} onChange={e => setEmail(e.target.value)}
                  placeholder="patient.raj@healthflow.local"
                  className="w-full bg-white border border-[#E8E4DA] rounded-xl px-4 py-3 text-[#2D3536] placeholder-[#A0A09A] focus:outline-none focus:border-[#98AA9D] transition-all text-sm shadow-sm"
                />
              </div>
              <button type="submit" disabled={loading}
                className="w-full bg-[#98AA9D] text-white rounded-xl py-3.5 font-semibold text-sm hover:bg-[#85988A] transition-colors disabled:opacity-60 shadow-sm">
                {loading ? 'Sending…' : 'Send reset link'}
              </button>
            </form>
          </>
        )}

        {screen === 'reset' && (
          <>
            <h2 className="text-xl font-bold text-[#2D3536] mb-1 font-serif">Set new password</h2>
            <p className="text-xs text-[#697C70] mb-5">Enter the token from your email and your new password.</p>
            {info && <p className="text-xs text-[#2D3536] bg-[#EEF3EF] rounded-xl px-4 py-3 mb-4 font-medium">{info}</p>}
            {error && <p role="alert" className="text-xs text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3 mb-4 font-medium">{error}</p>}
            <form onSubmit={handleReset} className="space-y-4" noValidate>
              <div>
                <label htmlFor="reset-token" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider font-medium">
                  Reset token
                </label>
                <input
                  id="reset-token" type="text" required value={resetToken} onChange={e => setResetToken(e.target.value)}
                  placeholder="Paste token from email"
                  className="w-full bg-white border border-[#E8E4DA] rounded-xl px-4 py-3 text-[#2D3536] placeholder-[#A0A09A] focus:outline-none focus:border-[#98AA9D] transition-all text-sm shadow-sm"
                />
              </div>
              <div>
                <label htmlFor="reset-new-pass" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider font-medium">
                  New password
                </label>
                <input
                  id="reset-new-pass" type="password" required value={newPassword} onChange={e => setNewPassword(e.target.value)}
                  placeholder="Min 8 characters"
                  className="w-full bg-white border border-[#E8E4DA] rounded-xl px-4 py-3 text-[#2D3536] placeholder-[#A0A09A] focus:outline-none focus:border-[#98AA9D] transition-all text-sm shadow-sm"
                />
              </div>
              <button type="submit" disabled={loading}
                className="w-full bg-[#98AA9D] text-white rounded-xl py-3.5 font-semibold text-sm hover:bg-[#85988A] transition-colors disabled:opacity-60 shadow-sm">
                {loading ? 'Saving…' : 'Set password & sign in'}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
