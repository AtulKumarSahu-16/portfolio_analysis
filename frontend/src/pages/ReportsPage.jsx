import { useState } from 'react'
import { Link } from 'react-router-dom'
import { usePortfolio } from '../app/PortfolioContext.jsx'
import { getPortfolioHoldings, getPortfolioTransactions } from '../services/portfolioApi.js'

function csv(rows) {
  return rows.map((row) => row.map((cell) => `"${String(cell ?? '').replaceAll('"', '""')}"`).join(',')).join('\r\n')
}

function download(filename, content) {
  const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click(); URL.revokeObjectURL(url)
}

export default function ReportsPage() {
  const { activePortfolio } = usePortfolio()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  async function exportTransactions() {
    if (!activePortfolio) return
    setBusy(true); setError(''); setNotice('')
    try {
      const transactions = await getPortfolioTransactions(activePortfolio.id)
      const rows = [['Date','Side','Asset type','Name','Symbol','Scheme code','Quantity','Price per unit','Fees','Notes'], ...transactions.map((tx) => [tx.trade_date, tx.side, tx.instrument.asset_type, tx.instrument.display_name, tx.instrument.symbol, tx.instrument.scheme_code, tx.quantity, tx.price_per_unit, tx.fees, tx.notes])]
      download('portfolio-transactions.csv', csv(rows)); setNotice(`${transactions.length} saved transactions exported.`)
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  async function exportHoldings() {
    if (!activePortfolio) return
    setBusy(true); setError(''); setNotice('')
    try {
      const holdings = await getPortfolioHoldings(activePortfolio.id)
      const rows = [['Name','Asset type','AMC','Category','Sub-category','ISIN','Identity status','Folio last 4','Units','Cost basis INR','Previous close / NAV INR','Current value INR','Profit / loss INR','Return percent','Data status','Price / NAV date','Price timestamp','Queried at','Statement date','Source'], ...holdings.items.map((item) => [item.instrument.display_name, item.instrument.asset_type, item.instrument.amc_name, item.instrument.category, item.instrument.sub_category, item.instrument.isin, item.instrument.identity_status, item.folio_last4, item.quantity, item.cost_basis, item.current_price, item.current_value, item.profit_loss, item.return_pct, item.data_status, item.price_date, item.price_timestamp, item.queried_at, item.statement_as_of_date, item.source])]
      download('portfolio-holdings.csv', csv(rows)); setNotice('Holdings report exported with dated close/NAV values and availability fields.')
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return <div className="workspace-page"><div className="page-title"><div><span className="eyebrow">YOUR PORTFOLIO DATA</span><h1>Reports</h1><p>Export records and holdings valued using previous closes and dated NAVs.</p></div></div>
    {!activePortfolio ? <section className="welcome-card"><div><h2>No active portfolio</h2><p>Create one before exporting portfolio reports.</p><Link to="/app/import" className="text-link">Go to Import Portfolio →</Link></div></section> : <section className="report-grid"><article className="content-card"><span className="eyebrow">LEDGER EXPORT</span><h2>Transactions CSV</h2><p>Download the transaction entries recorded for <b>{activePortfolio.name}</b>, including instrument, quantity, entered unit price, fees, and notes.</p><button className="button" disabled={busy} onClick={exportTransactions}>{busy ? 'Preparing…' : 'Export transactions'}</button></article><article className="content-card"><span className="eyebrow">CURRENT SNAPSHOT</span><h2>Holdings CSV</h2><p>Download current units, transaction-derived cost basis, and provider valuation status. Missing values remain blank in the file.</p><button className="button button-outline" disabled={busy} onClick={exportHoldings}>{busy ? 'Preparing…' : 'Export holdings'}</button></article></section>}
    {error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="form-success" role="status">{notice}</p>}<p className="note">These CSV exports contain the data saved in your account. Keep downloaded files private.</p>
  </div>
}
