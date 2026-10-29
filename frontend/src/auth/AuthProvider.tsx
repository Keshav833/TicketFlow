import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api } from '../api'
import { tokenStore } from '../api/client'
import type { User } from '../types'

interface AuthContextValue {
  user: User | null
  loading: boolean
  expired: boolean
  login: (username: string, password: string) => Promise<void>
  register: (data: { username: string; email: string; password: string }) => Promise<void>
  logout: () => void
  clearExpired: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(() => Boolean(tokenStore.getAccess()))
  const [expired, setExpired] = useState(false)

  useEffect(() => {
    const onExpired = () => {
      setUser(null)
      setLoading(false)
      setExpired(true)
    }
    window.addEventListener('ticketflow:session-expired', onExpired)
    if (tokenStore.getAccess()) {
      api.currentUser()
        .then(({ data }) => setUser(data))
        .catch(() => {
          tokenStore.clear()
          setUser(null)
          setExpired(true)
        })
        .finally(() => setLoading(false))
    }
    return () => window.removeEventListener('ticketflow:session-expired', onExpired)
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const { data: tokens } = await api.login(username, password)
    tokenStore.save(tokens.access, tokens.refresh)
    try {
      const { data: currentUser } = await api.currentUser()
      setUser(currentUser)
      setExpired(false)
    } catch (error) {
      tokenStore.clear()
      throw error
    }
  }, [])

  const register = useCallback(
    async (data: { username: string; email: string; password: string }) => {
      await api.register(data)
    },
    [],
  )

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
    setExpired(false)
  }, [])

  const clearExpired = useCallback(() => setExpired(false), [])

  const value = useMemo(
    () => ({ user, loading, expired, login, register, logout, clearExpired }),
    [user, loading, expired, login, register, logout, clearExpired],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}
