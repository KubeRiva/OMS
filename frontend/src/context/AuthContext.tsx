import { createContext, useContext, useState, useCallback, ReactNode } from 'react'

export interface AuthUser {
  id: string
  email: string
  full_name: string | null
  is_superadmin: boolean
  platform_role: string  // 'PLATFORM_OWNER' | 'SUPERADMIN' | 'USER'
  permissions: string[]
}

export function isPlatformOwner(user: AuthUser | null): boolean {
  return user?.platform_role === 'PLATFORM_OWNER'
}

interface AuthContextValue {
  user: AuthUser | null
  token: string | null   // always null — JWT lives in httpOnly cookie only
  isAuthenticated: boolean
  login: (token: string, user: AuthUser) => void
  logout: () => void
  hasPermission: (permission: string) => boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

const USER_KEY = 'oms_auth_user'

function parseStoredUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // User profile stored for UI purposes only (name, role, permissions).
  // The JWT itself is never stored in localStorage — it lives in the httpOnly
  // cookie that the backend sets on login.
  const [user, setUser] = useState<AuthUser | null>(() => parseStoredUser())

  const login = useCallback((_token: string, newUser: AuthUser) => {
    // _token is ignored — the httpOnly cookie was already set by the backend.
    localStorage.setItem(USER_KEY, JSON.stringify(newUser))
    setUser(newUser)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(USER_KEY)
    setUser(null)
    window.location.href = '/login'
  }, [])

  const hasPermission = useCallback(
    (permission: string): boolean => {
      if (!user) return false
      if (user.is_superadmin) return true
      if (user.permissions.includes('*')) return true
      return user.permissions.includes(permission)
    },
    [user],
  )

  return (
    <AuthContext.Provider
      value={{ user, token: null, isAuthenticated: !!user, login, logout, hasPermission }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
