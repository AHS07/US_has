// Phase 1 — Patient profile (read-only for now, edit in Phase 3)
import { useAuth } from '@/context/AuthContext'
import { useNavigate } from 'react-router-dom'

export default function Profile() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    navigate('/patient/login')
  }

  return (
    <div className="p-6 space-y-4">
      <h2 className="text-xl font-semibold text-[#2D3536] font-serif">Profile</h2>
      <div className="bg-white rounded-2xl border border-[#D8D2C4] p-5 space-y-2">
        <p className="text-xs uppercase tracking-wider text-[#697C70] font-medium">Role</p>
        <p className="text-sm text-[#2D3536] capitalize">{user?.role}</p>
      </div>
      <button
        type="button"
        onClick={handleLogout}
        className="w-full rounded-xl border border-[#D8D2C4] py-3 text-sm font-medium text-[#8B1A1A] hover:bg-[#F5D0CC]/30 transition-colors"
      >
        Sign out
      </button>
    </div>
  )
}
