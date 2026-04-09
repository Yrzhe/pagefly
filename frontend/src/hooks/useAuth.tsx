import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'
import api from '@/api/client'

interface AuthContextType {
  isAuthenticated: boolean
  login: (account: string, password: string, totp: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(
    () => !!localStorage.getItem('pagefly_token')
  )

  const login = useCallback(async (account: string, password: string, totp: string) => {
    const { data } = await api.post('/auth/login', { account, password, totp })
    localStorage.setItem('pagefly_token', data.token)
    setIsAuthenticated(true)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('pagefly_token')
    setIsAuthenticated(false)
  }, [])

  return (
    <AuthContext.Provider value={{ isAuthenticated, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}
