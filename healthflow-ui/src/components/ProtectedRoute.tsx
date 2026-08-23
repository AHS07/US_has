/**
 * ProtectedRoute — guards a route by role.
 * - Unauthenticated → redirect to the portal's login
 * - Wrong role → redirect to their own portal's login
 * - must_reset_password=true → redirect to /patient/reset-password
 *   (shared reset screen works for all roles)
 */
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth, type UserRole } from '@/context/AuthContext'

interface Props {
  role: UserRole
  children: React.ReactNode
}

const LOGIN_PATHS: Record<UserRole, string> = {
  patient: '/patient/login',
  doctor: '/doctor/login',
  admin: '/admin/login',
}

export default function ProtectedRoute({ role, children }: Props) {
  const { user, loading } = useAuth()
  const location = useLocation()

  // Still hydrating from localStorage — render nothing to avoid flash
  if (loading) return null

  if (!user) {
    return <Navigate to={LOGIN_PATHS[role]} state={{ from: location }} replace />
  }

  if (user.role !== role) {
    return <Navigate to={LOGIN_PATHS[user.role]} replace />
  }

  if (user.must_reset_password && location.pathname !== '/patient/reset-password') {
    return <Navigate to="/patient/reset-password" replace />
  }

  return <>{children}</>
}
