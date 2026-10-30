import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { usePortfolio } from '../app/PortfolioContext.jsx'
import { getPortfolioHoldings } from '../services/portfolioApi.js'
import { getStockPrice } from '../services/stockApi.js'
import FundAllocationOverlap from '../components/FundAllocationOverlap.jsx'

const money = (value) => value == null ? 'Unavailable' : `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

export default function PortfolioInsightsPage({ section }) {
  const { activePortfolio } = usePortfolio()
  const [data, setData] = useState(null)
  const [sectorRows, setSectorRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [sectorUnavailable, setSectorUnavailable] = useState(false)

  useEffect(() => {
    let alive = true
    setData(null); setSectorRows([]); setError(''); setSectorUnavailable(false)
    if (!activePortfolio) return () => { alive = false }
    setLoading(true)
    getPortfolioHoldings(activePortfolio.id).then(async (holdings) => {
      if (!alive) return
      setData(holdings)
      if (section === 'sectors') {
        const stocks = holdings.items.filter((item) => item.instrument.asset_type === 'stock' && item.instrument.symbol)
        const details = await Promise.all(stocks.map(async (item) => {
          try { return { item, result: await getStockPrice(item.instrument.symbol) } }
          catch { return { item, result: null } }
        }))
        if (!alive) return
        setSectorUnavailable(details.some(({ result }) => !result))
        setSectorRows(details.map(({ item, result }) => ({
          name: result?.market_data?.industry || result?.market_data?.sector || 'Industry not supplied',
          value: item.current_value == null ? null : Number(item.current_value),
          symbol: item.instrument.symbol,
        })))
      }
    }).catch((err) => { if (alive) setError(err.message) }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [activePortfolio?.id, section])

  const items = data?.items || []
  const gain = data?.profit_loss == null ? null : data.profit_loss
  const percent = data?.return_pct == null ? null : Number(data.return_pct)
  const sectors = useMemo(() => sectorRows.reduce((map, row) => {
    map.set(row.name, (map.get(row.name) || 0) + (row.value || 0))
    return map
  }, new Map()), [sectorRows])

  const titles = {
    performance: ['Performance', 'A dated snapshot calculated from your transaction ledger, previous stock closes, and latest available mutual fund NAVs.'],
    overlap: ['Overlap Analysis', 'Compare verified underlying fund constituents when that data is available.'],
    sectors: ['Sector Analysis', 'Industry exposure based on provider classifications for your direct stock positions.'],
  }
  const [title, description] = titles[section]
  return <div className="workspace-page"><div className="page-title"><div><span className="eyebrow">PORTFOLIO ANALYTICS</span><h1>{title}</h1><p>{description}</p></div></div>
    {!activePortfolio ? <section className="welcome-card"><div><h2>Create a portfolio first</h2><p>Analytics are calculated from your imported holdings.</p><Link to="/app/import" className="text-link">Go to Import Portfolio →</Link></div></section> : loading ? <p className="muted" role="status">Loading saved holdings and provider values…</p> : error ? <p className="form-error" role="alert">{error}</p> : items.length === 0 ? <section className="welcome-card"><div><h2>No holdings to analyze</h2><p>Import a statement to see portfolio analytics.</p><Link to="/app/import" className="text-link">Import Portfolio →</Link></div></section> : <>
      {section === 'performance' && <><div className="portfolio-metrics"><article><span>Cost basis</span><b>{money(data.total_cost_basis)}</b><small>Computed from recorded purchases and sales</small></article><article><span>Portfolio value</span><b>{data.valuation_complete ? money(data.current_value) : 'Unavailable'}</b><small>{data.data_status || 'unavailable'} · previous close / latest NAV</small></article><article><span>Unrealized change</span><b>{gain == null ? 'Unavailable' : money(gain)}</b><small>{percent == null ? 'Requires complete valuation and nonzero cost basis' : `${percent.toFixed(2)}% of cost basis`}</small></article></div><section className="content-card"><h2>Position performance</h2><p className="note">This snapshot uses previous trading-day stock closes and the latest published mutual fund NAV. Percentage return is unavailable when cost basis is zero or missing.</p><div className="table-scroll"><table className="investment-table"><thead><tr><th>Investment</th><th>Folio</th><th>Cost basis</th><th>Previous close / NAV</th><th>Current value</th><th>Profit / loss</th><th>Price date</th><th>Data status</th></tr></thead><tbody>{items.map((item) => <tr key={item.position_key || item.instrument.id}><td><b>{item.instrument.display_name}</b><small>{item.instrument.symbol || `Scheme ${item.instrument.scheme_code}`}</small></td><td>{item.folio_last4 ? `••${item.folio_last4}` : '—'}</td><td>{money(item.cost_basis)}</td><td>{money(item.current_price)}</td><td>{money(item.current_value)}</td><td>{money(item.profit_loss)}{item.return_pct != null && <small>{Number(item.return_pct).toFixed(2)}%</small>}</td><td>{item.price_date || 'Unavailable'}<small>{item.source || ''}{item.price_timestamp ? ` · ${item.price_timestamp}` : item.queried_at ? ` · queried ${new Date(item.queried_at).toLocaleString()}` : ''}</small></td><td><span className={`market-data-status ${item.data_status || 'unavailable'}`}>{item.data_status || 'unavailable'}</span></td></tr>)}</tbody></table></div><p className="note">Portfolio values are based on the latest available previous trading-day closing prices and mutual fund NAVs. Data may be delayed.</p></section></>}
      {section === 'sectors' && <><section className="content-card"><div className="form-section-heading"><div><span className="eyebrow">CLASSIFIED STOCKS</span><h2>Known industry exposure</h2></div></div>{sectorUnavailable && <p className="note">Some stock classifications could not be loaded. Those positions may be absent from the totals.</p>}{sectors.size ? <div className="sector-list">{[...sectors].sort((a,b) => b[1]-a[1]).map(([name,value]) => <div key={name}><span>{name}</span><b>{money(value)}</b><i style={{ width: `${data.current_value ? Math.max(2, value / Number(data.current_value) * 100) : 2}%` }} /></div>)}</div> : <p className="muted">The provider has not supplied industry classifications for these stock holdings.</p>}{items.some((item) => item.instrument.asset_type === 'mutual_fund') && <p className="note">Mutual-fund underlying sector weights are not available from the configured NAV endpoint and are excluded from this stock-only classification.</p>}</section><section className="content-card"><h2>Direct stock classifications</h2><div className="table-scroll"><table className="investment-table"><thead><tr><th>Symbol</th><th>Provider industry</th><th>Current value</th></tr></thead><tbody>{sectorRows.map((row) => <tr key={row.symbol}><td>{row.symbol}</td><td>{row.name}</td><td>{money(row.value)}</td></tr>)}</tbody></table></div></section></>}
      {section === 'overlap' && <FundAllocationOverlap portfolioId={activePortfolio.id} />}
    </>}
  </div>
}
