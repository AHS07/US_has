/**
 * context/AuthContext.tsx
 *
 * Single source of truth for authentication state.
 * Provides: user info, login(), logout(), and a loading flag.
 *
 * On mount it reads tokens from localStorage and validates them so
 * a page refresh doesn't log the user out unnecessarily.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  login as apiLogin,
  logout as apiLogout,
  setTokens,
  type LoginResponse,
} from '@/lib/api'

// ─── Types ────────────────────────────────────────────────────────────────────

export type UserRole = 'patient' | 'doctor' | 'admin'

export interface AuthUser {
  role: UserRole
  hospital_id: string | null
  must_reset_password: boolean
}

interface AuthContextValue {
  user: AuthUser | null
  loading: boolean
  login: (email: string, password: string) => Promise<LoginResponse>
  logout: () => Promise<void>
  clearMustReset: () => void  // called after a successful password reset
}

// ─── Context ──────────────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextValue | null>(null)

// ─── Provider ─────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  // On mount: if tokens exist, decode the access token payload to restore state.
  // We don't re-verify the signature client-side — the backend will reject expired
  // tokens on the first real API call and the refresh flow will handle it.
  useEffect(() => {
    const access = getAccessToken()
    if (access) {
      try {
        const payload = JSON.parse(atob(access.split('.')[1]!)) as {
          role: UserRole
          hospital_id: string | null
          must_reset_password?: boolean
          exp: number
        }
        // If expired, clear and let user log in again
        if (payload.exp * 1000 < Date.now()) {
          clearTokens()
        } else {
          setUser({
            role: payload.role,
            hospital_id: payload.hospital_id,
            must_reset_password: payload.must_reset_password ?? false,
          })
        }
      } catch {
        clearTokens()
      }
    }
    setLoading(false)
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const res = await apiLogin(email, password)
    setTokens(res.access, res.refresh)
    setUser({
      role: res.role,
      hospital_id: res.hospital_id,
      must_reset_password: res.must_reset_password,
    })
    return res
  }, [])

  const logout = useCallback(async () => {
    const refresh = getRefreshToken()
    try {
      if (refresh) await apiLogout(refresh)
    } catch { /* best-effort */ }
    clearTokens()
    setUser(null)
  }, [])

  const clearMustReset = useCallback(() => {
    setUser(prev => prev ? { ...prev, must_reset_password: false } : prev)
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, clearMustReset }}>
      {children}
    </AuthContext.Provider>
  )
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
