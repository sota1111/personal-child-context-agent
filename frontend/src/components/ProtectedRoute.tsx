import { Navigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from '../auth/useAuth'

// Gate every protected route behind the resolved auth state. While /auth/me is in
// flight we show a neutral loading line rather than redirecting, so a valid session
// isn't bounced to /login on a hard refresh.
export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, loading } = useAuth()
  if (loading) {
    return (
      <div className="loading" aria-busy="true">
        読み込み中…
      </div>
    )
  }
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}
