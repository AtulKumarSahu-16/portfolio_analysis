import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../app/AuthContext.jsx'

export default function AuthPage({ mode }) {
  const isSignup = mode === 'signup'
  const { user, loading, login, signup } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [form, setForm] = useState({ display_name: '', email: '', password: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (!loading && user) return <Navigate to="/app/dashboard" replace />

  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const action = isSignup ? signup : login
      await action(isSignup ? form : { email: form.email, password: form.password })
      navigate(location.state?.from?.pathname || '/app/dashboard', { replace: true })
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return <main className="auth-page"><Link to="/" className="wordmark"><span className="brand-icon">P</span>Portfolio<span>AI</span></Link><section className="auth-card"><span className="eyebrow">{isSignup ? 'YOUR PORTFOLIO, IN CONTEXT' : 'WELCOME BACK'}</span><h1>{isSignup ? 'Create your account' : 'Log in to PortfolioAI'}</h1><p className="auth-subtitle">{isSignup ? 'Set up a private space for your investment records.' : 'Continue to your investment overview.'}</p>
    <form onSubmit={submit} className="auth-form">{isSignup && <label>Your name<input autoComplete="name" value={form.display_name} onChange={e=>setForm({...form,display_name:e.target.value})} required minLength={1} maxLength={120} /></label>}
      <label>Email address<input type="email" autoComplete="email" value={form.email} onChange={e=>setForm({...form,email:e.target.value})} required maxLength={320} /></label>
      <label>Password<input type="password" autoComplete={isSignup?'new-password':'current-password'} value={form.password} onChange={e=>setForm({...form,password:e.target.value})} required minLength={isSignup?12:1} maxLength={128} />{isSignup && <small>Use at least 12 characters.</small>}</label>
      {error && <p className="form-error" role="alert">{error}</p>}<button className="button auth-submit" disabled={busy}>{busy ? 'Please wait…' : isSignup ? 'Create account' : 'Log in'}</button></form>
    <p className="auth-switch">{isSignup ? 'Already have an account?' : 'New to PortfolioAI?'} <Link to={isSignup?'/login':'/signup'}>{isSignup?'Log in':'Create an account'}</Link></p><p className="auth-note">Your investment data is private to your account. Never share provider API keys here.</p>
  </section><Link className="back-home" to="/">← Back to home</Link></main>
}
