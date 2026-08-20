import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'

// Email/password sign-in. The password is POSTed to /api/auth/session where the
// backend verifies it server-side against Firebase Identity Toolkit and, on success,
// sets the session cookie. The password never persists on the client.
export default function LoginPage() {
  const { login, isAuthenticated, loading: authLoading } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Wait for the initial /auth/me check before deciding what to show, so a redirect
  // login-return doesn't flash the form for a moment.
  if (authLoading) {
    return (
      <div className="loading" aria-busy="true">
        読み込み中…
      </div>
    )
  }
  if (isAuthenticated) {
    return <Navigate to="/context" replace />
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await login(email, password)
      navigate('/context')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'ログインに失敗しました')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={handleSubmit}>
        <h1>ログイン</h1>
        <label>
          メールアドレス
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            required
            placeholder="your-email@example.com"
          />
        </label>
        <label>
          パスワード
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" className="primary" disabled={submitting}>
          {submitting ? '送信中…' : 'ログイン'}
        </button>
      </form>
    </div>
  )
}
