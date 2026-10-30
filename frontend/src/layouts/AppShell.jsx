import { useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../app/AuthContext.jsx'
import { usePortfolio } from '../app/PortfolioContext.jsx'

const primaryNav = [
  ['dashboard', 'Dashboard', '⌂'], ['import', 'Import Portfolio', '⇧'],
]
const analysisNav = [
  ['mutual-funds', 'Mutual Funds', '◉'], ['stocks', 'Stocks', '⌁'], ['performance', 'Performance', '↗'],
  ['overlap', 'Overlap Analysis', '◌'], ['sectors', 'Sector Analysis', '◍'], ['research', 'Stock Research', '⌕'],
]
const toolsNav = [['assistant', 'AI Assistant', '✳'], ['reports', 'Reports', '▧'], ['settings', 'Settings', '⚙']]
const navItems = [...primaryNav, ...analysisNav, ...toolsNav]

export default function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false)
  const { user, logout } = useAuth()
  const { portfolios, activePortfolio, setActiveId } = usePortfolio()
  const navigate = useNavigate()
  const location = useLocation()
  const current = navItems.find(([path]) => location.pathname.endsWith(`/${path}`))

  async function handleLogout() {
    await logout()
    navigate('/', { replace: true })
  }

  return <div className="app-layout"><button className={`mobile-backdrop ${menuOpen?'visible':''}`} onClick={()=>setMenuOpen(false)} aria-label="Close navigation" tabIndex={menuOpen?0:-1} />
    <aside className={`sidebar ${menuOpen?'sidebar-open':''}`}><Link to="/app/dashboard" className="sidebar-brand"><span className="brand-icon">P</span><span>Portfolio<strong>AI</strong></span></Link>
      <nav aria-label="Portfolio navigation">
        <p className="sidebar-label">OVERVIEW</p>{primaryNav.map(([path,label,icon])=><NavLink key={path} to={`/app/${path}`} className={({isActive})=>`side-link ${isActive?'active':''}`} onClick={()=>setMenuOpen(false)}><span aria-hidden="true">{icon}</span>{label}</NavLink>)}
        <p className="sidebar-label">ANALYSIS</p>{analysisNav.map(([path,label,icon])=><NavLink key={path} to={`/app/${path}`} className={({isActive})=>`side-link ${isActive?'active':''}`} onClick={()=>setMenuOpen(false)}><span aria-hidden="true">{icon}</span>{label}</NavLink>)}
        <p className="sidebar-label">TOOLS</p>{toolsNav.map(([path,label,icon])=><NavLink key={path} to={`/app/${path}`} className={({isActive})=>`side-link ${isActive?'active':''}`} onClick={()=>setMenuOpen(false)}><span aria-hidden="true">{icon}</span>{label}</NavLink>)}
      </nav><div className="sidebar-bottom"><span className="secure-label"><i /> Private workspace</span><button className="logout-link" onClick={handleLogout}>↪ <span>Log out</span></button></div></aside>
    <div className="app-main"><header className="app-topbar"><button className="menu-toggle" aria-label="Open navigation" aria-expanded={menuOpen} onClick={()=>setMenuOpen(true)}>☰</button><div className="topbar-context"><span className="top-title">{current?.[1] || 'Portfolio'}</span><small>{activePortfolio?.name || 'Your investment workspace'}</small></div>{portfolios.length>1&&<label className="portfolio-top-select"><span className="sr-only">Active portfolio</span><select value={activePortfolio?.id||''} onChange={e=>setActiveId(Number(e.target.value))}>{portfolios.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>}<div className="top-user"><span className="user-avatar">{(user?.display_name || user?.email || 'P').slice(0,1).toUpperCase()}</span><span className="user-name">{user?.display_name || user?.email}</span><button onClick={handleLogout} className="top-logout">Log out</button></div></header><main className="app-content"><Outlet /></main><footer className="app-footer">Market data can be delayed or unavailable. Portfolio insights are informational, not investment advice.</footer></div>
  </div>
}
