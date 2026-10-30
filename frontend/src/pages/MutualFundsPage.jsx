import { useState } from 'react'
import PriceChart from '../components/PriceChart.jsx'
import { getLatestNav, getNavHistory, searchFunds } from '../services/mutualFundApi.js'

const money = (value) => value == null ? 'Unavailable' : `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 4 })}`

export default function MutualFundsPage() {
  const [query, setQuery] = useState('')
  const [funds, setFunds] = useState([])
  const [fund, setFund] = useState(null)
  const [nav, setNav] = useState(null)
  const [points, setPoints] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [range, setRange] = useState('1y')

  async function search(event) {
    event.preventDefault(); setBusy(true); setError(''); setFunds([]); setFund(null); setNav(null); setPoints([])
    try { const data = await searchFunds(query.trim()); setFunds(data.results || []) }
    catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function selectFund(item, selectedRange = range) {
    setFund(item); setBusy(true); setError(''); setNav(null); setPoints([])
    try {
      const end = new Date()
      const start = new Date(end)
      start.setFullYear(start.getFullYear() - (selectedRange === '5y' ? 5 : selectedRange === '3y' ? 3 : 1))
      const [latest, history] = await Promise.all([
        getLatestNav(item.scheme_code),
        getNavHistory(item.scheme_code, start.toISOString().slice(0, 10), end.toISOString().slice(0, 10)),
      ])
      setNav(latest)
      setPoints((history.data || []).map((row) => ({ date: row.nav_date || row.date, nav: row.nav, price: row.nav })).filter((row) => row.date && row.price))
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return <div className="workspace-page"><div className="page-title"><div><span className="eyebrow">MFNAV · PROVIDER DATA</span><h1>Mutual Funds</h1><p>Search real schemes and inspect the latest published NAV and dated NAV history.</p></div></div>
    <section className="content-card"><form className="workspace-search" onSubmit={search}><label htmlFor="fund-query">Scheme name</label><div><input id="fund-query" value={query} onChange={(e) => setQuery(e.target.value)} minLength={2} maxLength={120} required placeholder="e.g. HDFC Flexi Cap Fund" /><button className="button" disabled={busy}>{busy ? 'Loading…' : 'Search schemes'}</button></div></form>
      {error && <p className="form-error" role="alert">{error}</p>}
      {funds.length > 0 && <div className="fund-results"><h2>Matching schemes</h2>{funds.map((item) => <button key={item.scheme_code} className={`fund-result ${fund?.scheme_code === item.scheme_code ? 'selected' : ''}`} onClick={() => selectFund(item)}><span><b>{item.scheme_name}</b><small>{item.plan_type || 'Plan not specified'} · {item.option_type || 'Option not specified'} · Scheme {item.scheme_code}</small></span><span>View NAV →</span></button>)}</div>}
    </section>
    {fund && <section className="content-card fund-detail"><div className="form-section-heading"><div><span className="eyebrow">SCHEME DETAILS</span><h2>{fund.scheme_name}</h2></div><span className="field-badge">Scheme {fund.scheme_code}</span></div>
      {nav && <div className="portfolio-metrics"><article><span>Latest available NAV</span><b>{money(nav.nav)}</b><small>NAV date: {nav.nav_date || 'not provided'} · {nav.source || 'MFNAV'}</small></article><article><span>Data status</span><b><span className={`market-data-status ${nav.data_status || 'unavailable'}`}>{nav.data_status || 'unavailable'}</span></b><small>Queried: {nav.queried_at ? new Date(nav.queried_at).toLocaleString() : 'time unavailable'}</small></article><article><span>Plan / option</span><b>{fund.plan_type || 'Not provided'} · {fund.option_type || 'Not provided'}</b><small>Provider scheme metadata</small></article></div>}
      <div className="history-toolbar"><h3>Historical NAV</h3><label>Period<select value={range} onChange={(e) => { setRange(e.target.value); selectFund(fund, e.target.value) }}><option value="1y">1 year</option><option value="3y">3 years</option><option value="5y">5 years</option></select></label></div>
      {busy ? <p className="muted">Loading provider NAV history…</p> : <PriceChart points={points} label="NAV history" />}
      <p className="note">NAV is provider-reported for its actual publication date; weekends, holidays, and publication delays can make it older than today. Portfolio values are based on the latest available previous trading-day closing prices and mutual fund NAVs. Data may be delayed.</p>
    </section>}
  </div>
}
