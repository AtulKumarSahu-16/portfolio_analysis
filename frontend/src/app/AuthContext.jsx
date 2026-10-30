import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { getCurrentUser, login as loginRequest, logout as logoutRequest, signup as signupRequest } from '../services/authApi.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getCurrentUser().then(setUser).catch(() => setUser(null)).finally(() => setLoading(false))
  }, [])

  const value = useMemo(() => ({
    user,
    loading,
    async signup(data) { const next = await signupRequest(data); setUser(next); return next },
    async login(data) { const next = await loginRequest(data); setUser(next); return next },
    async logout() { try { await logoutRequest() } finally { setUser(null) } },
  }), [user, loading])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
