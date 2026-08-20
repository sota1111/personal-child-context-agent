import { Routes, Route, Navigate } from 'react-router-dom'
import LoginPage from './pages/LoginPage'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import ContextPage from './pages/ContextPage'
import IngestPage from './pages/IngestPage'
import ActionsPage from './pages/ActionsPage'

// Route map: /login is public; everything else is wrapped in the authenticated Layout
// behind ProtectedRoute. The index route redirects to /context.
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/context" replace />} />
        <Route path="/context" element={<ContextPage />} />
        <Route path="/ingest" element={<IngestPage />} />
        <Route path="/actions" element={<ActionsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/context" replace />} />
    </Routes>
  )
}
