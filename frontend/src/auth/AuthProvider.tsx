import { useState, useEffect, type ReactNode } from 'react'
import { AuthContext } from './authContext'
import * as api from '../api/client'

// Session auth mirrors the おたよりナビ design: email/password is verified server-side
// (Firebase Identity Toolkit REST) and the backend sets a signed HMAC session cookie.
// The client only ever knows "authenticated or not" — it never stores credentials.
export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [loading, setLoading] = useState(true)

  // On mount, ask the backend whether the existing cookie is still valid (/auth/me).
  // Until it resolves we render nothing protected, so a valid session survives reload
  // instead of bouncing to /login.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        await api.fetchMe()
        if (!cancelled) setIsAuthenticated(true)
      } catch {
        if (!cancelled) setIsAuthenticated(false)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const login = async (email: string, password: string) => {
    await api.login(email, password)
    setIsAuthenticated(true)
  }

  const logout = async () => {
    try {
      await api.logout()
    } finally {
      setIsAuthenticated(false)
    }
  }

  return (
    <AuthContext.Provider value={{ isAuthenticated, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
