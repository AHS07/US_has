import { useEffect, useRef, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { animate } from 'animejs'
import { useAuth } from '@/context/AuthContext'
import {
  getCalendarStatus,
  getCalendarConnectUrl,
  disconnectCalendar,
  type CalendarStatus,
} from '@/lib/api'

export default function DoctorLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const mainRef = useRef<HTMLDivElement>(null)
  const isLogin = location.pathname === '/doctor/login'

  const [calStatus,    setCalStatus]    = useState<CalendarStatus | null>(null)
  const [calLoading,   setCalLoading]   = useState(false)

  useEffect(() => {
    if (isLogin) return
    getCalendarStatus()
      .then(setCalStatus)
      .catch(() => { /* best effort */ })
  }, [isLogin])

  useEffect(() => {
    if (!mainRef.current || isLogin) return
    animate(mainRef.current, { opacity: [0, 1], translateX: [10, 0], duration: 320, easing: 'easeOutCubic' })
  }, [location.pathname, isLogin])

  async function handleLogout() {
    await logout()
    navigate('/doctor/login')
  }

  async function handleCalendarToggle() {
    if (calLoading) return
    setCalLoading(true)
    try {
      if (calStatus?.connected) {
        const updated = await disconnectCalendar()
        setCalStatus(updated)
      } else {
        const { auth_url } = await getCalendarConnectUrl()
        window.location.href = auth_url
      }
    } catch { /* best effort */ } finally {
      setCalLoading(false)
    }
  }

  if (isLogin) return <div className="min-h-screen bg-[#F7F6F3]"><Outlet /></div>

  const isDayView = location.pathname === '/doctor/day-view'

  return (
    <div className="min-h-screen bg-[#F7F6F3] flex">
      {/* Sidebar */}
      <aside className="w-56 bg-white border-r border-[#E8E4DA] flex flex-col shrink-0">
        <div className="px-5 py-6 border-b border-[#E8E4DA]">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-[#98AA9D] flex items-center justify-center">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M12 4v16M4 12h16" stroke="white" strokeWidth="2.5" strokeLinecap="round" />
              </svg>
            </div>
            <span className="text-[#2D3536] font-semibold text-sm">HealthFlow</span>
          </div>
          <div className="mt-4 flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-[#EEF3EF] flex items-center justify-center text-[#697C70] text-sm font-semibold shrink-0" aria-hidden="true">
              {user?.role === 'doctor' ? 'D' : '?'}
            </div>
            <div>
              <p className="text-[#2D3536] text-xs font-semibold">{user?.name ?? 'Doctor'}</p>
              <p className="text-[#697C70] text-[11px]">Doctor Portal</p>
            </div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4" aria-label="Doctor navigation">
          <p className="text-[10px] text-[#A0A09A] uppercase tracking-wider px-3 mb-2 font-medium">Today</p>
          <button
            type="button"
            onClick={() => navigate('/doctor/day-view')}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all ${
              isDayView
                ? 'bg-[#EEF3EF] text-[#2D3536] font-semibold border-l-2 border-[#98AA9D]'
                : 'text-[#697C70] hover:text-[#2D3536] hover:bg-[#EEF3EF]'
            }`}
            aria-current={isDayView ? 'page' : undefined}
          >
            <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <rect x="3" y="4" width="18" height="18" rx="2" />
              <path d="M16 2v4M8 2v4M3 10h18" strokeLinecap="round" />
            </svg>
            Today's Slots
          </button>

          {/* Google Calendar integration */}
          <div className="mt-4 pt-4 border-t border-[#E8E4DA]">
            <p className="text-[10px] text-[#A0A09A] uppercase tracking-wider px-3 mb-2 font-medium">Integrations</p>
            <button
              type="button"
              onClick={handleCalendarToggle}
              disabled={calLoading}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all ${
                calStatus?.connected
                  ? 'text-[#697C70] bg-[#EEF3EF] hover:text-[#8B1A1A] hover:bg-[#F5D0CC]/40'
                  : 'text-[#697C70] hover:text-[#2D3536] hover:bg-[#EEF3EF]'
              }`}
              aria-label={calStatus?.connected ? 'Disconnect Google Calendar' : 'Connect Google Calendar'}
            >
              {/* Google Calendar icon */}
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                <rect x="3" y="4" width="18" height="18" rx="2" />
                <path d="M16 2v4M8 2v4M3 10h18M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01" strokeLinecap="round" />
              </svg>
              <span className="flex-1 text-left text-xs">
                {calLoading
                  ? 'Connecting…'
                  : calStatus?.connected
                  ? 'Calendar connected'
                  : 'Connect Calendar'}
              </span>
              {calStatus?.connected && (
                <span className="w-1.5 h-1.5 rounded-full bg-[#98AA9D] shrink-0" aria-hidden="true" />
              )}
            </button>
          </div>
        </nav>

        <div className="px-3 py-4 border-t border-[#E8E4DA]">
          <button
            type="button"
            onClick={handleLogout}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-[#697C70] hover:text-[#8B1A1A] hover:bg-[#F5D0CC]/30 transition-colors"
          >
            <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" strokeLinecap="round" />
            </svg>
            Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="bg-white border-b border-[#E8E4DA] px-6 h-14 flex items-center gap-3">
          {!isDayView && (
            <button type="button" onClick={() => navigate(-1)}
              className="p-1.5 -ml-1.5 rounded-lg text-[#697C70] hover:text-[#2D3536] hover:bg-[#EEF3EF] transition-colors"
              aria-label="Go back">
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          )}
          <h1 className="text-[#2D3536] font-semibold text-sm flex-1">HealthFlow Doctor Portal</h1>
          <div className="flex items-center gap-2 text-[#697C70] text-xs">
            <span className="w-2 h-2 rounded-full bg-[#98AA9D]" aria-hidden="true" />
            Today
          </div>
        </header>
        <main ref={mainRef} className="flex-1 overflow-y-auto" style={{ opacity: 0 }}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
