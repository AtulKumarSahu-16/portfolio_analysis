import { useState } from 'react'
import PriceChart from '../components/PriceChart.jsx'
import { getStockHistory, getStockPreviousClose, getStockPrice } from '../services/stockApi.js'
import { extractFinancialMetrics, formatFinancialMetric } from '../utils/financialMetrics.js'

const money = (value) => value == null ? 'Unavailable' : `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

export default function StocksPage() {
  const [symbol, setSymbol] = useState('INFY')
  const [stock, setStock] = useState(null)
  const [close, setClose] = useState(null)
  const [points, setPoints] = useState([])
  const [period, setPeriod] = useState('1yr')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function load(event, nextPeriod = period) {
    event?.preventDefault(); setBusy(true); setError('')
    try {
      const [quote, history, previousClose] = await Promise.all([getStockPrice(symbol.trim()).catch(() => null), getStockHistory(symbol.trim(), nextPeriod).catch(() => ({ points: [] })), getStockPreviousClose(symbol.trim()).catch(() => null)])
      if (!quote && !previousClose) throw new Error('Stock details and previous closing data are unavailable for this symbol.')
      setStock(quote || { symbol: symbol.trim().toUpperCase(), market_data: {} }); setPoints(history.points || []); setClose(previousClose)
    } catch (err) { setError(err.message); setStock(null); setClose(null); setPoints([]) } finally { setBusy(false) }
  }

  const market = stock?.market_data || {}
  const keyMetrics = extractFinancialMetrics({ keyMetrics: market.keyMetrics }).slice(0, 12)
  return <div className="workspace-page"><div className="page-title"><div><span className="eyebrow">INDIANAPI · PROVIDER DATA</span><h1>Stocks</h1><p>Look up Indian equities, previous closing prices, and historical price observations.</p></div></div>
    <section className="content-card"><form className="workspace-search" onSubmit={load}><label htmlFor="stock-symbol">Company name or symbol</label><div><input id="stock-symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} maxLength={80} required placeholder="e.g. INFY or Infosys" /><button className="button" disabled={busy}>{busy ? 'Loading…' : 'Look up stock'}</button></div></form>{error && <p className="form-error" role="alert">{error}</p>}</section>
    {stock && <><section className="portfolio-metrics"><article><span>Previous close</span><b>{money(close?.price)}</b><small>{close?.price_date || 'Date unavailable'} · {close?.source || 'IndianAPI'} · {close?.data_status || 'Unavailable'}</small></article><article><span>Company</span><b>{market.companyName || stock.symbol}</b><small>{market.industry || 'Industry not supplied'}</small></article><article><span>Close observation</span><b>{close?.data_status || 'Unavailable'}</b><small>{close?.price_timestamp || close?.queried_at || 'Timestamp unavailable'}</small></article></section>
      <section className="content-card"><div className="history-toolbar"><h2>Historical prices</h2><label>Period<select value={period} onChange={(e) => { setPeriod(e.target.value); load(null, e.target.value) }}><option value="1m">1 month</option><option value="6m">6 months</option><option value="1yr">1 year</option><option value="3yr">3 years</option><option value="5yr">5 years</option><option value="10yr">10 years</option><option value="max">Maximum</option></select></label></div>{busy ? <p className="muted">Loading dated price observations…</p> : <PriceChart points={points} label={`${stock.symbol} price history`} />}<p className="note">IndianAPI may provide delayed or incomplete data depending on your subscription and market hours.</p></section>
      {keyMetrics.length > 0 && <section className="content-card"><div className="form-section-heading"><div><span className="eyebrow">PROVIDER FIELDS</span><h2>Key metrics</h2></div></div><div className="provider-metric-grid">{keyMetrics.map((metric, index) => <div key={`${metric.id}-${index}`}><span>{metric.label}</span><b>{formatFinancialMetric(metric)}</b></div>)}</div></section>}</>}
  </div>
}
