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
  const heroRef = useRef<HTMLDivElement>(null)
  const formRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (heroRef.current) {
      animate(heroRef.current, { opacity: [0, 1], translateY: [-20, 0], duration: 700, easing: 'easeOutCubic' })
    }
    if (formRef.current) {
      animate(formRef.current, { opacity: [0, 1], translateY: [30, 0], duration: 600, delay: 200, easing: 'easeOutCubic' })
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
    <div className="min-h-screen bg-[#F2EFE2] flex flex-col">
      {/* Hero */}
      <div ref={heroRef} className="relative bg-[#2D3536] px-8 pt-16 pb-12 overflow-hidden" style={{ opacity: 0 }}>
        <div className="absolute inset-0 opacity-10" aria-hidden="true">
          <div className="absolute top-6 right-6 w-40 h-40 rounded-full border border-[#98AA9D]" />
          <div className="absolute top-16 right-16 w-24 h-24 rounded-full border border-[#B3C9D6]" />
        </div>
        <div className="relative">
          <div className="flex items-center gap-2 mb-8">
            <div className="w-8 h-8 rounded-lg bg-[#98AA9D] flex items-center justify-center">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M12 4v16M4 12h16" stroke="white" strokeWidth="2.5" strokeLinecap="round" />
              </svg>
            </div>
            <span className="text-white font-semibold tracking-wide text-lg">HealthFlow</span>
          </div>
          <h1 className="text-white text-3xl leading-tight font-serif">
            Your clinic,<br />at your fingertips.
          </h1>
          <p className="text-[#98AA9D] text-sm mt-3 leading-relaxed max-w-xs">
            Book appointments, track visits, and receive care summaries — all in one place.
          </p>
        </div>
      </div>

      {/* Form area */}
      <div ref={formRef} className="flex-1 px-6 pt-8 pb-10" style={{ opacity: 0 }}>
        {screen === 'login' && (
          <>
            <h2 className="text-xl font-semibold text-[#2D3536] mb-6">Sign in to your account</h2>
            {info && <p className="text-sm text-[#697C70] bg-[#EEF3EF] rounded-xl px-4 py-3 mb-4">{info}</p>}
            {error && <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3 mb-4">{error}</p>}
            <form onSubmit={handleLogin} className="space-y-4" noValidate>
              <div>
                <label htmlFor="email" className="block text-xs font-medium text-[#697C70] mb-1.5 uppercase tracking-wider">
                  Email address
                </label>
                <input
                  id="email" type="email" autoComplete="email" required
                  value={email} onChange={e => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="w-full bg-white border border-[#D8D2C4] rounded-xl px-4 py-3 text-[#2D3536] placeholder-[#B8B4AC] focus:outline-none focus:border-[#98AA9D] focus:ring-2 focus:ring-[#98AA9D]/20 transition-all text-base"
                />
              </div>
              <div>
                <label htmlFor="password" className="block text-xs font-medium text-[#697C70] mb-1.5 uppercase tracking-wider">
                  Password
                </label>
                <input
                  id="password" type="password" autoComplete="current-password" required
                  value={password} onChange={e => setPassword(e.target.value)}
                  placeholder="Enter your password"
                  className="w-full bg-white border border-[#D8D2C4] rounded-xl px-4 py-3 text-[#2D3536] placeholder-[#B8B4AC] focus:outline-none focus:border-[#98AA9D] focus:ring-2 focus:ring-[#98AA9D]/20 transition-all text-base"
                />
              </div>
              <button type="button" onClick={() => { setError(''); setInfo(''); setScreen('forgot') }}
                className="text-sm text-[#697C70] hover:text-[#98AA9D] transition-colors">
                Forgot password?
              </button>
              <button type="submit" disabled={loading}
                className="w-full bg-[#2D3536] text-white rounded-xl py-3.5 font-semibold text-base hover:bg-[#3D4546] active:scale-[0.98] transition-all disabled:opacity-60 mt-2">
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
            <button onClick={() => setScreen('login')} className="flex items-center gap-2 text-[#697C70] hover:text-[#2D3536] mb-6 transition-colors text-sm">
              <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Back to sign in
            </button>
            <h2 className="text-xl font-semibold text-[#2D3536] mb-2">Reset your password</h2>
            <p className="text-sm text-[#697C70] mb-6">Enter your email and we'll send a reset link.</p>
            {error && <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3 mb-4">{error}</p>}
            <form onSubmit={handleForgot} className="space-y-4" noValidate>
              <input type="email" required value={email} onChange={e => setEmail(e.target.value)}
                placeholder="your@email.com"
                className="w-full bg-white border border-[#D8D2C4] rounded-xl px-4 py-3 text-[#2D3536] placeholder-[#B8B4AC] focus:outline-none focus:border-[#98AA9D] focus:ring-2 focus:ring-[#98AA9D]/20 transition-all text-base" />
              <button type="submit" disabled={loading}
                className="w-full bg-[#98AA9D] text-white rounded-xl py-3.5 font-semibold text-base hover:bg-[#7A9080] transition-colors disabled:opacity-60">
                {loading ? 'Sending…' : 'Send reset link'}
              </button>
            </form>
          </>
        )}

        {screen === 'reset' && (
          <>
            <h2 className="text-xl font-semibold text-[#2D3536] mb-2">Set a new password</h2>
            <p className="text-sm text-[#697C70] mb-6">Paste the token from your reset email and choose a new password.</p>
            {info && <p className="text-sm text-[#697C70] bg-[#EEF3EF] rounded-xl px-4 py-3 mb-4">{info}</p>}
            {error && <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3 mb-4">{error}</p>}
            <form onSubmit={handleReset} className="space-y-4" noValidate>
              <input type="text" required value={resetToken} onChange={e => setResetToken(e.target.value)}
                placeholder="Reset token from email"
                className="w-full bg-white border border-[#D8D2C4] rounded-xl px-4 py-3 text-[#2D3536] placeholder-[#B8B4AC] focus:outline-none focus:border-[#98AA9D] focus:ring-2 focus:ring-[#98AA9D]/20 transition-all text-base" />
              <input type="password" required value={newPassword} onChange={e => setNewPassword(e.target.value)}
                placeholder="New password (min 8 chars)"
                className="w-full bg-white border border-[#D8D2C4] rounded-xl px-4 py-3 text-[#2D3536] placeholder-[#B8B4AC] focus:outline-none focus:border-[#98AA9D] focus:ring-2 focus:ring-[#98AA9D]/20 transition-all text-base" />
              <button type="submit" disabled={loading}
                className="w-full bg-[#98AA9D] text-white rounded-xl py-3.5 font-semibold text-base hover:bg-[#7A9080] transition-colors disabled:opacity-60">
                {loading ? 'Saving…' : 'Set password & sign in'}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
