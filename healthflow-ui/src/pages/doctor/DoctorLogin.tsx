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
    <div className="min-h-screen bg-[#2D3536] flex items-center justify-center p-6">
      <div ref={formRef} className="w-full max-w-sm" style={{ opacity: 0 }}>
        <div className="flex items-center gap-2.5 mb-10">
          <div className="w-9 h-9 rounded-xl bg-[#98AA9D] flex items-center justify-center">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 4v16M4 12h16" stroke="white" strokeWidth="2.5" strokeLinecap="round" />
            </svg>
          </div>
          <div>
            <p className="text-white font-semibold">HealthFlow</p>
            <p className="text-[#697C70] text-xs">Doctor Portal</p>
          </div>
        </div>

        <h1 className="text-3xl text-white mb-2 font-serif">Good morning,<br />Doctor.</h1>
        <p className="text-[#697C70] text-sm mb-8">Sign in to see today's schedule.</p>

        {error && <p role="alert" className="text-sm text-[#F5D0CC] bg-[#8B1A1A]/20 rounded-xl px-4 py-3 mb-4">{error}</p>}

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div>
            <label htmlFor="doc-email" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider">
              Hospital email
            </label>
            <input
              id="doc-email" type="email" autoComplete="email" required
              value={email} onChange={e => setEmail(e.target.value)}
              placeholder="doctor@hospital.in"
              className="w-full bg-[#3A4546] border border-[#4A5556] rounded-xl px-4 py-3 text-white placeholder-[#697C70] focus:outline-none focus:border-[#98AA9D] transition-all text-sm"
            />
          </div>
          <div>
            <label htmlFor="doc-password" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider">
              Password
            </label>
            <input
              id="doc-password" type="password" autoComplete="current-password" required
              value={password} onChange={e => setPassword(e.target.value)}
              placeholder="Enter your password"
              className="w-full bg-[#3A4546] border border-[#4A5556] rounded-xl px-4 py-3 text-white placeholder-[#697C70] focus:outline-none focus:border-[#98AA9D] transition-all text-sm"
            />
          </div>
          <button type="submit" disabled={loading}
            className="w-full bg-[#98AA9D] text-white rounded-xl py-3.5 font-semibold text-sm hover:bg-[#7A9080] transition-colors disabled:opacity-60 mt-2">
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
