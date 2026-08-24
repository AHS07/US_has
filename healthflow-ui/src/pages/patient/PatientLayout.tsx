import { useEffect, useRef } from 'react'
import { useNavigate, useLocation, Outlet } from 'react-router-dom'
import { animate } from 'animejs'
import { useAuth } from '@/context/AuthContext'

const NAV_ITEMS = [
  {
    path: '/patient/search',
    label: 'Find Doctor',
    icon: (
      <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    path: '/patient/appointments',
    label: 'Appointments',
    icon: (
      <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <rect x="3" y="4" width="18" height="18" rx="2" />
        <path d="M16 2v4M8 2v4M3 10h18" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    path: '/patient/notifications',
    label: 'Alerts',
    icon: (
      <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    path: '/patient/profile',
    label: 'Profile',
    icon: (
      <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <circle cx="12" cy="8" r="4" /><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" strokeLinecap="round" />
      </svg>
    ),
  },
] as const

const ROOT_PATHS = ['/patient/search', '/patient/appointments', '/patient/notifications', '/patient/profile']

export default function PatientLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { logout } = useAuth()
  const mainRef = useRef<HTMLDivElement>(null)
  const isLogin = location.pathname === '/patient/login'

  const isRoot = ROOT_PATHS.includes(location.pathname)

  useEffect(() => {
    if (!mainRef.current || isLogin) return
    animate(mainRef.current, { opacity: [0, 1], translateY: [8, 0], duration: 320, easing: 'easeOutCubic' })
  }, [location.pathname, isLogin])

  async function handleLogout() {
    await logout()
    navigate('/patient/login')
  }

  if (isLogin) return <div className="min-h-screen bg-[#F7F6F3]"><Outlet /></div>

  const currentLabel = NAV_ITEMS.find(n => location.pathname.startsWith(n.path))?.label ?? 'Patient Portal'

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
              P
            </div>
            <div>
              <p className="text-[#2D3536] text-xs font-semibold">Patient</p>
              <p className="text-[#697C70] text-[11px]">Portal</p>
            </div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4" aria-label="Patient navigation">
          <p className="text-[10px] text-[#A0A09A] uppercase tracking-wider px-3 mb-2 font-medium">Menu</p>
          {NAV_ITEMS.map(item => {
            const active = location.pathname.startsWith(item.path)
            return (
              <button
                key={item.path}
                type="button"
                onClick={() => navigate(item.path)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all mb-1 ${
                  active
                    ? 'bg-[#EEF3EF] text-[#2D3536] font-semibold border-l-2 border-[#98AA9D]'
                    : 'text-[#697C70] hover:text-[#2D3536] hover:bg-[#EEF3EF]'
                }`}
                aria-current={active ? 'page' : undefined}
              >
                <span className={active ? 'text-[#98AA9D]' : 'text-[#697C70]'}>{item.icon}</span>
                {item.label}
              </button>
            )
          })}
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

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="bg-white border-b border-[#E8E4DA] px-6 h-14 flex items-center gap-3">
          {!isRoot && (
            <button
              type="button"
              onClick={() => navigate(-1)}
              className="p-1.5 -ml-1.5 rounded-lg text-[#697C70] hover:text-[#2D3536] hover:bg-[#EEF3EF] transition-colors"
              aria-label="Go back"
            >
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          )}
          <h1 className="text-[#2D3536] font-semibold text-sm flex-1">
            {currentLabel}
          </h1>
          <div className="flex items-center gap-2 text-[#697C70] text-xs">
            <span className="w-2 h-2 rounded-full bg-[#98AA9D]" aria-hidden="true" />
            HealthFlow Patient
          </div>
        </header>
        <main ref={mainRef} className="flex-1 overflow-y-auto p-6 max-w-5xl w-full mx-auto" style={{ opacity: 0 }}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
