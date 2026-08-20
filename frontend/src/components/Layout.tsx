import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'

// App shell for the authenticated area: a top bar with the primary navigation and a
// logout button, plus an <Outlet/> for the active page.
export default function Layout() {
  const { logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">Personal Child Context Agent</span>
        <nav className="app-nav">
          <NavLink to="/context">Child Context</NavLink>
          <NavLink to="/ingest">文書投入</NavLink>
          <NavLink to="/actions">Actions</NavLink>
        </nav>
        <button type="button" className="link-button" onClick={handleLogout}>
          ログアウト
        </button>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
      <footer className="app-footer">
        本アプリは学校からの情報と保護者が登録した文脈を突き合わせて確認事項を提示します。
        医療判断や安全の断定は行いません（必ず保護者が確認してください）。
      </footer>
    </div>
  )
}
