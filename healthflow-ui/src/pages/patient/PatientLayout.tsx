import { useEffect, useRef } from 'react'
import { useNavigate, useLocation, Outlet } from 'react-router-dom'
import { animate } from 'animejs'

const NAV_ITEMS = [
  {
    path: '/patient/search',
    label: 'Find Doctor',
    icon: (
      <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8">
        <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    path: '/patient/appointments',
    label: 'Appointments',
    icon: (
      <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8">
        <rect x="3" y="4" width="18" height="18" rx="2" />
        <path d="M16 2v4M8 2v4M3 10h18" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    path: '/patient/notifications',
    label: 'Alerts',
    icon: (
      <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    path: '/patient/profile',
    label: 'Profile',
    icon: (
      <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8">
        <circle cx="12" cy="8" r="4" /><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" strokeLinecap="round" />
      </svg>
    ),
  },
] as const

// Paths that get a bottom nav
const NAV_PATHS = ['/patient/search', '/patient/appointments', '/patient/notifications', '/patient/profile']

export default function PatientLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const mainRef = useRef<HTMLDivElement>(null)

  const showNav = NAV_PATHS.some(p => location.pathname.startsWith(p))
  const showBack = !showNav && location.pathname !== '/patient/login'

  useEffect(() => {
    if (!mainRef.current) return
    animate(mainRef.current, { opacity: [0, 1], translateY: [12, 0], duration: 380, easing: 'easeOutCubic' })
  }, [location.pathname])

  return (
    <div className="flex flex-col min-h-screen bg-[#F2EFE2] max-w-md mx-auto relative">
      {/* Header — hidden on login */}
      {location.pathname !== '/patient/login' && (
        <header className="sticky top-0 z-20 bg-[#F2EFE2]/90 backdrop-blur-md border-b border-[#D8D2C4] px-4">
          <div className="flex items-center gap-3 h-14">
            {showBack ? (
              <button
                type="button"
                onClick={() => navigate(-1)}
                className="p-1.5 -ml-1.5 rounded-lg text-[#697C70] hover:text-[#2D3536] hover:bg-[#E8E4DA] transition-colors"
                aria-label="Go back"
              >
                <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            ) : (
              <span className="text-[#98AA9D]" aria-hidden="true">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                  <path d="M12 2C7 2 3 6 3 12s4 10 9 10 9-4.5 9-10S17 2 12 2z" fill="#98AA9D" opacity=".3" />
                  <path d="M12 7v5l3 3" stroke="#98AA9D" strokeWidth="2" strokeLinecap="round" />
                </svg>
              </span>
            )}
            <h1 className="text-base font-semibold text-[#2D3536] flex-1 truncate">
              HealthFlow
            </h1>
          </div>
        </header>
      )}

      {/* Content */}
      <main ref={mainRef} className={`flex-1 overflow-y-auto ${showNav ? 'pb-24' : ''}`} style={{ opacity: 0 }}>
        <Outlet />
      </main>

      {/* Bottom nav */}
      {showNav && (
        <nav
          className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-md z-20 bg-[#F2EFE2]/95 backdrop-blur border-t border-[#D8D2C4]"
          aria-label="Patient navigation"
        >
          <ul className="flex">
            {NAV_ITEMS.map(item => {
              const active = location.pathname.startsWith(item.path)
              return (
                <li key={item.path} className="flex-1">
                  <button
                    type="button"
                    onClick={() => navigate(item.path)}
                    className={`relative w-full flex flex-col items-center gap-1 py-3 text-[10px] font-medium transition-colors ${
                      active ? 'text-[#98AA9D]' : 'text-[#A0A09A] hover:text-[#697C70]'
                    }`}
                    aria-current={active ? 'page' : undefined}
                  >
                    <span className={active ? 'text-[#98AA9D]' : ''} aria-hidden="true">{item.icon}</span>
                    {item.label}
                    {active && (
                      <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-5 h-0.5 bg-[#98AA9D] rounded-full" aria-hidden="true" />
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        </nav>
      )}
    </div>
  )
}
