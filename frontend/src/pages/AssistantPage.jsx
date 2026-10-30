import { useState } from 'react'
import { Link } from 'react-router-dom'
import { usePortfolio } from '../app/PortfolioContext.jsx'
import { getPortfolioHoldings } from '../services/portfolioApi.js'

const money = (value) => value == null ? 'unavailable' : `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

export default function AssistantPage() {
  const { activePortfolio } = usePortfolio()
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function ask(event) {
    event.preventDefault(); setBusy(true); setError(''); setAnswer('')
    try {
      if (!activePortfolio) { setAnswer('Create a portfolio and record investments first. I can only answer from your saved portfolio data.'); return }
      const data = await getPortfolioHoldings(activePortfolio.id)
      const items = data.items || []
      const q = question.toLowerCase()
      if (!items.length) { setAnswer('Your active portfolio has no open positions yet. Add a transaction on the Investments page to enable portfolio-specific answers.'); return }
      if (/sector|industry/.test(q)) {
        setAnswer('Sector classifications are available on the Sector Analysis page for direct stock holdings when IndianAPI supplies an industry field. Mutual-fund constituent sectors are not available from the connected NAV data.')
      } else if (/fund|mutual/.test(q)) {
        const funds = items.filter((item) => item.instrument.asset_type === 'mutual_fund')
        setAnswer(funds.length ? `You have ${funds.length} mutual-fund position${funds.length === 1 ? '' : 's'}: ${funds.map((item) => `${item.instrument.display_name} (${money(item.current_value)})`).join('; ')}. Values reflect MFNAV when available.` : 'There are no open mutual-fund positions in this portfolio.')
      } else if (/stock|share|equity/.test(q)) {
        const stocks = items.filter((item) => item.instrument.asset_type === 'stock')
        setAnswer(stocks.length ? `You have ${stocks.length} direct stock position${stocks.length === 1 ? '' : 's'}: ${stocks.map((item) => `${item.instrument.symbol || item.instrument.display_name} (${money(item.current_value)})`).join('; ')}. Values use IndianAPI when available.` : 'There are no open direct stock positions in this portfolio.')
      } else if (/return|gain|loss|profit|performance/.test(q)) {
        if (!data.valuation_complete) setAnswer(`Current cost basis is ${money(data.total_cost_basis)}, but at least one market value is unavailable, so total unrealized gain or loss cannot be calculated reliably.`)
        else { const change = Number(data.current_value) - Number(data.total_cost_basis); setAnswer(`Current snapshot: cost basis ${money(data.total_cost_basis)}, provider-valued holdings ${money(data.current_value)}, unrealized change ${money(change)}. This is not annualized and excludes taxes and dividends.`) }
      } else {
        const types = items.reduce((acc, item) => { acc[item.instrument.asset_type] = (acc[item.instrument.asset_type] || 0) + 1; return acc }, {})
        setAnswer(`${activePortfolio.name} has ${items.length} open positions (${types.stock || 0} stocks and ${types.mutual_fund || 0} mutual funds). Cost basis is ${money(data.total_cost_basis)} and current value is ${data.valuation_complete ? money(data.current_value) : 'incomplete because a provider value is missing'}. Ask about holdings, performance, stocks, funds, or sectors for a focused summary.`)
      }
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return <div className="workspace-page"><div className="page-title"><div><span className="eyebrow">PORTFOLIO Q&A</span><h1>AI Assistant</h1><p>Ask questions about records and provider values in your active portfolio.</p></div></div><section className="assistant-card content-card"><div className="assistant-mark">✳</div><span className="eyebrow">DATA-GROUNDED ANSWERS</span><h2>Ask about your portfolio</h2><p>This assistant currently uses deterministic summaries of your saved portfolio data. A generative AI provider is not configured, so it will not invent recommendations or facts.</p><form onSubmit={ask}><label htmlFor="portfolio-question">Your question</label><textarea id="portfolio-question" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500} minLength={2} required placeholder="How are my holdings performing?" /><button className="button" disabled={busy}>{busy ? 'Checking portfolio…' : 'Ask portfolio question'}</button></form>{error && <p className="form-error" role="alert">{error}</p>}{answer && <div className="assistant-answer" role="status"><b>Portfolio summary</b><p>{answer}</p></div>}<Link to="/app/reports" className="text-link">Review exported portfolio data →</Link></section></div>
}
