import { useEffect, useRef } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { animate } from 'animejs'
import { useAuth } from '@/context/AuthContext'

type AdminRoute = '/admin/dashboard' | '/admin/doctors' | '/admin/attendance' | '/admin/leave' | '/admin/patients' | '/admin/medicine-catalog'

const NAV_ITEMS: { path: AdminRoute; label: string; badge?: string; icon: React.ReactNode }[] = [
  {
    path: '/admin/dashboard', label: 'Dashboard',
    icon: <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg>,
  },
  {
    path: '/admin/doctors', label: 'Doctors',
    icon: <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" strokeLinecap="round" /></svg>,
  },
  {
    path: '/admin/attendance', label: 'Attendance',
    icon: <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18M9 16l2 2 4-4" strokeLinecap="round" /></svg>,
  },
  {
    path: '/admin/leave', label: 'Leave',
    icon: <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18M8 14h8M8 18h5" strokeLinecap="round" /></svg>,
  },
  {
    path: '/admin/patients', label: 'Patients',
    icon: <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><circle cx="12" cy="8" r="4" /><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" strokeLinecap="round" /></svg>,
  },
  {
    path: '/admin/medicine-catalog', label: 'Medicines',
    icon: <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2v-4M9 21H5a2 2 0 0 1-2-2v-4m0 0h18" strokeLinecap="round" /></svg>,
  },
]

export default function AdminLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const { logout } = useAuth()
  const mainRef = useRef<HTMLDivElement>(null)
  const isLogin = location.pathname === '/admin/login'

  useEffect(() => {
    if (!mainRef.current || isLogin) return
    animate(mainRef.current, { opacity: [0, 1], duration: 300, easing: 'easeOutCubic' })
  }, [location.pathname, isLogin])

  async function handleLogout() {
    await logout()
    navigate('/admin/login')
  }

  if (isLogin) return <div className="min-h-screen bg-white"><Outlet /></div>

  return (
    <div className="min-h-screen bg-[#F7F6F3] flex">
      {/* Sidebar */}
      <aside className="w-52 bg-white border-r border-[#E8E4DA] flex flex-col shrink-0">
        <div className="px-5 py-5 border-b border-[#E8E4DA]">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-[#98AA9D] flex items-center justify-center">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M12 4v16M4 12h16" stroke="white" strokeWidth="2.5" strokeLinecap="round" />
              </svg>
            </div>
            <span className="text-[#2D3536] font-semibold text-sm">HealthFlow</span>
          </div>
          <p className="text-xs text-[#697C70] mt-1.5">Admin Portal</p>
        </div>

        <nav className="flex-1 px-3 py-4" aria-label="Admin navigation">
          {NAV_ITEMS.map(item => {
            const active = location.pathname.startsWith(item.path)
            return (
              <button
                key={item.path}
                type="button"
                onClick={() => navigate(item.path)}
                className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm font-medium transition-all mb-0.5 ${
                  active ? 'bg-[#EEF3EF] text-[#697C70]' : 'text-[#A0A09A] hover:text-[#2D3536] hover:bg-[#F2EFE2]'
                }`}
                aria-current={active ? 'page' : undefined}
              >
                <span className={active ? 'text-[#98AA9D]' : ''}>{item.icon}</span>
                {item.label}
                {item.badge && (
                  <span className="ml-auto text-[10px] bg-[#FDE8C0] text-[#7A4A00] px-1.5 py-0.5 rounded-full font-medium">
                    {item.badge}
                  </span>
                )}
              </button>
            )
          })}
        </nav>

        <div className="px-3 py-4 border-t border-[#E8E4DA]">
          <button type="button" onClick={handleLogout}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm font-medium text-[#A0A09A] hover:text-[#8B1A1A] transition-colors">
            <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" strokeLinecap="round" />
            </svg>
            Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="bg-white border-b border-[#E8E4DA] px-6 h-[52px] flex items-center">
          <h1 className="text-sm font-semibold text-[#2D3536] flex-1 capitalize">
            {location.pathname.split('/').pop()?.replace('-', ' ') ?? 'Admin'}
          </h1>
          <div className="text-xs text-[#697C70]">HealthFlow Admin</div>
        </header>
        <main ref={mainRef} className="flex-1 overflow-y-auto p-6" style={{ opacity: 0 }}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
