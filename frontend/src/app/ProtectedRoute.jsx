import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext.jsx'

export default function ProtectedRoute({ children }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="page-loading" role="status">Checking your session…</div>
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />
  return children
}
