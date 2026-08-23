import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { animate } from 'animejs'
import { useAuth } from '@/context/AuthContext'
import type { HFApiError } from '@/lib/api'

export default function AdminLogin() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const cardRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!cardRef.current) return
    animate(cardRef.current, { opacity: [0, 1], translateY: [20, 0], duration: 600, easing: 'easeOutCubic' })
  }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await login(email, password)
      if (res.role !== 'admin') { setError('This portal is for admins only.'); return }
      navigate(res.must_reset_password ? '/patient/reset-password' : '/admin/dashboard')
    } catch (err) {
      setError((err as HFApiError).message ?? 'Login failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#F7F6F3] flex items-center justify-center p-6">
      <div ref={cardRef} className="w-full max-w-sm" style={{ opacity: 0 }}>
        <div className="flex items-center gap-2 mb-10">
          <div className="w-8 h-8 rounded-lg bg-[#98AA9D] flex items-center justify-center">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 4v16M4 12h16" stroke="white" strokeWidth="2.5" strokeLinecap="round" />
            </svg>
          </div>
          <div>
            <p className="text-[#2D3536] font-semibold text-sm">HealthFlow</p>
            <p className="text-[#697C70] text-xs">Admin Portal</p>
          </div>
        </div>

        <h1 className="text-2xl text-[#2D3536] mb-1.5 font-serif">Admin sign in</h1>
        <p className="text-sm text-[#697C70] mb-7">Manage clinic operations and schedules.</p>

        {error && <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3 mb-4">{error}</p>}

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div>
            <label htmlFor="admin-email" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider">
              Email
            </label>
            <input
              id="admin-email" type="email" autoComplete="email" required
              value={email} onChange={e => setEmail(e.target.value)}
              placeholder="admin@hospital.in"
              className="w-full bg-white border border-[#D8D2C4] rounded-xl px-4 py-3 text-[#2D3536] focus:outline-none focus:border-[#98AA9D] focus:ring-2 focus:ring-[#98AA9D]/20 text-sm transition-all"
            />
          </div>
          <div>
            <label htmlFor="admin-password" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider">
              Password
            </label>
            <input
              id="admin-password" type="password" autoComplete="current-password" required
              value={password} onChange={e => setPassword(e.target.value)}
              placeholder="Enter your password"
              className="w-full bg-white border border-[#D8D2C4] rounded-xl px-4 py-3 text-[#2D3536] focus:outline-none focus:border-[#98AA9D] focus:ring-2 focus:ring-[#98AA9D]/20 text-sm transition-all"
            />
          </div>
          <button type="submit" disabled={loading}
            className="w-full bg-[#2D3536] text-white rounded-xl py-3.5 font-semibold text-sm hover:bg-[#3D4546] transition-colors mt-2 disabled:opacity-60">
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
