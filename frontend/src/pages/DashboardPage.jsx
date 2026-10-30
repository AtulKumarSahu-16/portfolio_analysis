import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { usePortfolio } from '../app/PortfolioContext.jsx'
import { getPortfolioHoldings } from '../services/portfolioApi.js'

const money = (value) => value == null || !Number.isFinite(Number(value)) ? 'Unavailable' : `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
const istTime = (value) => value ? new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) : 'Not recorded yet'

function Kpi({ label, value, meta, tone = '' }) {
  return <article className={`overview-kpi ${tone}`}><span>{label}</span><b>{value}</b><small>{meta}</small></article>
}

export default function DashboardPage() {
  const { activePortfolio, loading: portfoliosLoading } = usePortfolio()
  const [holdings, setHoldings] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    setHoldings(null); setError('')
    if (!activePortfolio) return () => { alive = false }
    setLoading(true)
    getPortfolioHoldings(activePortfolio.id).then((data) => { if (alive) setHoldings(data) }).catch((err) => { if (alive) setError(err.message) }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [activePortfolio?.id])

  const items = holdings?.items || []
  const valuedItems = items.filter((item) => item.current_value != null && Number.isFinite(Number(item.current_value)))
  const allocation = useMemo(() => {
    const groups = [
      { key: 'mutual_fund', label: 'Mutual funds', color: '#3975ef' },
      { key: 'stock', label: 'Stocks', color: '#20b98a' },
    ].map((group) => ({ ...group, value: valuedItems.filter((item) => item.instrument.asset_type === group.key).reduce((sum, item) => sum + Number(item.current_value), 0) }))
    const total = groups.reduce((sum, group) => sum + group.value, 0)
    let offset = 0
    const stops = groups.map((group) => {
      const start = offset
      offset += total > 0 ? group.value / total * 100 : 0
      return `${group.color} ${start}% ${offset}%`
    })
    return { groups: groups.map((group) => ({ ...group, pct: total ? group.value / total * 100 : 0 })), total, background: total ? `conic-gradient(${stops.join(', ')})` : 'conic-gradient(#e8edf4 0 100%)' }
  }, [valuedItems])
  const topHoldings = [...items].sort((a, b) => Number(b.current_value || 0) - Number(a.current_value || 0)).slice(0, 5)
  const maxPosition = Math.max(1, ...topHoldings.map((item) => Number(item.current_value || 0)))
  const positive = holdings?.profit_loss != null && Number(holdings.profit_loss) >= 0

  if (portfoliosLoading || loading) return <div className="workspace-page"><p className="muted" role="status">Loading portfolio data…</p></div>
  if (error) return <div className="workspace-page"><p className="form-error" role="alert">{error}</p></div>
  if (!activePortfolio || !items.length) return <div className="workspace-page dashboard-page"><div className="page-title"><div><span className="eyebrow">PORTFOLIO OVERVIEW</span><h1>Dashboard</h1><p>{activePortfolio?.name || 'Your investment portfolio'}</p></div>{activePortfolio && <Link to="/app/import" className="button">Import portfolio <span aria-hidden="true">⇧</span></Link>}</div><section className="welcome-card dashboard-welcome"><div className="welcome-icon">↗</div><div><span className="eyebrow">YOUR PORTFOLIO STARTS HERE</span><h2>{activePortfolio ? 'No holdings imported yet' : 'Create your portfolio'}</h2><p>Import a statement to review your stock and mutual fund holdings, then see available values and analysis here.</p><Link to="/app/import" className="button">Import Portfolio <span aria-hidden="true">→</span></Link></div></section></div>

  return <div className="workspace-page dashboard-page">
    <div className="page-title dashboard-heading"><div><span className="eyebrow">PORTFOLIO OVERVIEW</span><h1>Dashboard</h1><p>{activePortfolio.name} · Your investment portfolio at a glance.</p></div><Link to="/app/import" className="button">Import portfolio <span aria-hidden="true">⇧</span></Link></div>
    <div className="dashboard-kpis">
      <Kpi label="Total invested" value={money(holdings.total_cost_basis)} meta="Based on saved purchase records" />
      <Kpi label="Current value" value={holdings.valuation_complete ? money(holdings.current_value) : 'Unavailable'} meta={`${valuedItems.length} of ${items.length} holdings valued`} />
      <Kpi label="Total gain / loss" value={holdings.profit_loss == null ? 'Unavailable' : money(holdings.profit_loss)} meta={holdings.return_pct == null ? 'Return needs complete values and cost basis' : `${Number(holdings.return_pct).toFixed(2)}% return`} tone={holdings.profit_loss == null ? '' : positive ? 'kpi-positive' : 'kpi-negative'} />
      <Kpi label="Positions" value={items.length.toLocaleString('en-IN')} meta={`${items.filter((item) => item.instrument.asset_type === 'stock').length} stocks · ${items.filter((item) => item.instrument.asset_type === 'mutual_fund').length} mutual funds`} />
    </div>
    <div className="dashboard-meta"><span><i className={holdings.data_status || 'unavailable'} /> Market data: <b>{holdings.data_status || 'unavailable'}</b></span><span>Latest market-data date: <b>{holdings.latest_market_data_date || 'Unavailable'}</b></span><span>Last refresh: <b>{istTime(holdings.last_successful_refresh_at)} IST</b></span></div>

    <div className="dashboard-visual-grid">
      <section className="content-card dashboard-performance-card"><div className="section-card-heading"><div><span className="eyebrow">PORTFOLIO SNAPSHOT</span><h2>Invested vs. current value</h2></div><Link to="/app/performance" className="text-link">Performance details →</Link></div>
        {valuedItems.length ? <div className="comparison-chart" role="img" aria-label="Invested and current value comparison by asset type">
          {allocation.groups.map((group) => {
            const positions = valuedItems.filter((item) => item.instrument.asset_type === group.key)
            if (!positions.length) return null
            const current = positions.reduce((sum, item) => sum + Number(item.current_value), 0)
            const invested = positions.reduce((sum, item) => sum + Number(item.cost_basis || 0), 0)
            const scale = Math.max(current, invested, 1)
            return <div className="comparison-row" key={group.key}><div className="comparison-label"><i style={{ background: group.color }} /><b>{group.label}</b></div><div className="comparison-bars"><div className="comparison-bar invested" style={{ width: `${invested / scale * 100}%` }} title={`Invested ${money(invested)}`} /><div className="comparison-bar current" style={{ width: `${current / scale * 100}%`, background: group.color }} title={`Current ${money(current)}`} /></div><div className="comparison-values"><span>{money(invested)}</span><b>{money(current)}</b></div></div>
          })}
          <div className="chart-legend"><span><i className="legend-invested" />Invested</span><span><i className="legend-current" />Current</span><small>Values are based on available holding data; no historical series is inferred.</small></div>
        </div> : <div className="dashboard-chart-empty"><span>◌</span><b>Market values are not available yet</b><small>Holdings stay visible while provider data is delayed or unavailable.</small></div>}
      </section>
      <section className="content-card allocation-card"><div className="section-card-heading"><div><span className="eyebrow">ASSET MIX</span><h2>Allocation</h2></div></div><div className="allocation-content"><div className="allocation-donut" style={{ background: allocation.background }}><div><b>{allocation.total ? money(allocation.total) : '—'}</b><small>valued assets</small></div></div><div className="allocation-legend">{allocation.groups.map((group) => <div key={group.key}><span><i style={{ background: group.color }} />{group.label}</span><b>{allocation.total ? `${group.pct.toFixed(1)}%` : '—'}</b><small>{money(group.value)}</small></div>)}</div></div>{valuedItems.length < items.length && <p className="allocation-footnote">{items.length - valuedItems.length} position(s) excluded until market data is available.</p>}</section>
    </div>

    <div className="dashboard-lower-grid">
      <section className="content-card top-holdings-card"><div className="section-card-heading"><div><span className="eyebrow">YOUR LARGEST POSITIONS</span><h2>Top holdings</h2></div><Link to="/app/performance" className="text-link">View analysis →</Link></div>{topHoldings.length ? <div className="top-holding-list">{topHoldings.map((item) => <div className="top-holding-row" key={item.position_key || item.instrument.id}><div className="holding-avatar">{item.instrument.asset_type === 'stock' ? (item.instrument.symbol || item.instrument.display_name).slice(0, 1) : '◉'}</div><div className="holding-main"><b>{item.instrument.display_name}</b><small>{item.instrument.asset_type === 'stock' ? item.instrument.symbol || 'Stock' : 'Mutual fund'} · {Number(item.quantity).toLocaleString('en-IN', { maximumFractionDigits: 4 })} units</small><div className="holding-progress"><i style={{ width: `${Math.max(2, Number(item.current_value || 0) / maxPosition * 100)}%` }} /></div></div><div className="holding-value"><b>{money(item.current_value)}</b><small>{item.data_status || 'unavailable'}</small></div></div>)}</div> : <p className="muted">No valued positions yet.</p>}</section>
      <section className="content-card dashboard-actions-card"><div className="section-card-heading"><div><span className="eyebrow">NEXT STEPS</span><h2>Explore your portfolio</h2></div></div><div className="dashboard-action-list"><Link to="/app/import"><span className="action-icon">⇧</span><span><b>Import a statement</b><small>Add stocks and mutual funds from a statement</small></span><i>→</i></Link><Link to="/app/overlap"><span className="action-icon">◌</span><span><b>Compare fund overlap</b><small>Review available fund exposure data</small></span><i>→</i></Link><Link to="/app/sectors"><span className="action-icon">◍</span><span><b>View sector analysis</b><small>Explore stock industry allocation</small></span><i>→</i></Link><Link to="/app/assistant"><span className="action-icon">✳</span><span><b>Ask your assistant</b><small>Get a summary of saved portfolio data</small></span><i>→</i></Link></div></section>
    </div>
    <p className="dashboard-disclaimer">Portfolio values use the latest available previous trading-day closing prices and mutual fund NAVs. Data may be delayed. This dashboard is informational and does not provide investment advice.</p>
  </div>
}
