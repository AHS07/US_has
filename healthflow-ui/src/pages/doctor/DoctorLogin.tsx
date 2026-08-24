import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { animate } from 'animejs'
import { useAuth } from '@/context/AuthContext'
import type { HFApiError } from '@/lib/api'

export default function DoctorLogin() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const formRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!formRef.current) return
    animate(formRef.current, { opacity: [0, 1], translateY: [24, 0], duration: 600, easing: 'easeOutCubic' })
  }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await login(email, password)
      if (res.role !== 'doctor') { setError('This portal is for doctors only.'); return }
      navigate(res.must_reset_password ? '/patient/reset-password' : '/doctor/day-view')
    } catch (err) {
      setError((err as HFApiError).message ?? 'Login failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#F7F6F3] flex items-center justify-center p-6">
      <div ref={formRef} className="w-full max-w-sm bg-white border border-[#E8E4DA] rounded-3xl p-8 shadow-sm" style={{ opacity: 0 }}>
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

        <div className="flex items-center gap-2.5 mb-8">
          <div className="w-9 h-9 rounded-xl bg-[#98AA9D] flex items-center justify-center shadow-sm">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 4v16M4 12h16" stroke="white" strokeWidth="2.5" strokeLinecap="round" />
            </svg>
          </div>
          <div>
            <p className="text-[#2D3536] font-semibold">HealthFlow</p>
            <p className="text-[#697C70] text-xs">Doctor Portal</p>
          </div>
        </div>

        <h1 className="text-2xl font-bold text-[#2D3536] mb-1 font-serif">Good morning,<br />Doctor.</h1>
        <p className="text-[#697C70] text-xs mb-6">Sign in to see today's schedule.</p>

        {error && <p role="alert" className="text-xs text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3 mb-4 font-medium">{error}</p>}

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div>
            <label htmlFor="doc-email" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider font-medium">
              Hospital email
            </label>
            <input
              id="doc-email" type="email" autoComplete="email" required
              value={email} onChange={e => setEmail(e.target.value)}
              placeholder="dr.sharma@healthflow.local"
              className="w-full bg-white border border-[#E8E4DA] rounded-xl px-4 py-3 text-[#2D3536] placeholder-[#A0A09A] focus:outline-none focus:border-[#98AA9D] transition-all text-sm shadow-sm"
            />
          </div>
          <div>
            <label htmlFor="doc-password" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider font-medium">
              Password
            </label>
            <input
              id="doc-password" type="password" autoComplete="current-password" required
              value={password} onChange={e => setPassword(e.target.value)}
              placeholder="Enter your password"
              className="w-full bg-white border border-[#E8E4DA] rounded-xl px-4 py-3 text-[#2D3536] placeholder-[#A0A09A] focus:outline-none focus:border-[#98AA9D] transition-all text-sm shadow-sm"
            />
          </div>
          <button type="submit" disabled={loading}
            className="w-full bg-[#98AA9D] text-white rounded-xl py-3.5 font-semibold text-sm hover:bg-[#85988A] transition-colors disabled:opacity-60 mt-2 shadow-sm">
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
