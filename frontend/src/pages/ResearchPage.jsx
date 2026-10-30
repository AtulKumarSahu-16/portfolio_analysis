import { useMemo, useState } from 'react'
import { getStockPrice } from '../services/stockApi.js'
import { extractFinancialMetrics, financialMetricSection, financialMetricSections, formatFinancialMetric } from '../utils/financialMetrics.js'

const positive = /beat|growth|gain|surge|profit|upgrade|strong|buy|record|rise|positive|expan|outperform|dividend/gi
const negative = /miss|fall|loss|cut|downgrade|weak|risk|decline|drop|investigation|debt|negative|sell|fraud|layoff/gi

function sentiment(text) {
  const up = (text.match(positive) || []).length
  const down = (text.match(negative) || []).length
  if (up === down) return { label: 'Mixed / neutral', className: 'neutral' }
  return up > down ? { label: 'Positive language', className: 'positive' } : { label: 'Negative language', className: 'negative' }
}

function asRecord(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function safeText(value) {
  if (typeof value === 'string' || typeof value === 'number') return String(value).trim()
  return ''
}

function findText(record, keys) {
  const entries = Object.entries(record)
  for (const candidate of keys) {
    const match = entries.find(([key, value]) => key.toLowerCase() === candidate.toLowerCase() && safeText(value))
    if (match) return safeText(match[1])
  }
  for (const value of Object.values(record)) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) continue
    const result = findText(value, keys)
    if (result) return result
  }
  return ''
}

function collectArticles(value, output = [], depth = 0) {
  if (!value || depth > 4 || output.length >= 10) return output
  if (Array.isArray(value)) { value.forEach((item) => collectArticles(item, output, depth + 1)); return output }
  if (typeof value !== 'object') return output
  const title = safeText(value.headline || value.title || value.articleTitle)
  const summary = safeText(value.summary || value.description || value.contentSnippet)
  const url = safeText(value.url || value.link)
  if (title && (summary || url)) output.push({ title, summary, url, date: safeText(value.lastPublishedDate || value.date || value.publishedAt), source: safeText(value.source || value.publisher) })
  else Object.values(value).forEach((item) => collectArticles(item, output, depth + 1))
  return output
}

function MetricCards({ metrics }) {
  if (!metrics.length) return <p className="metric-empty">No metrics in this section were supplied for this company.</p>
  return <div className="financial-metric-grid">{metrics.map((metric, index) => <article className="financial-metric-card" key={`${metric.id}-${index}`}>
    <span>{metric.label}</span><b>{formatFinancialMetric(metric)}</b>
  </article>)}</div>
}

export default function ResearchPage() {
  const [symbol, setSymbol] = useState('INFY')
  const [research, setResearch] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function load(event) {
    event.preventDefault(); setBusy(true); setError('')
    try { setResearch(await getStockPrice(symbol.trim())) } catch (err) { setResearch(null); setError(err.message) } finally { setBusy(false) }
  }

  const data = asRecord(research?.market_data)
  const profile = asRecord(data.companyProfile)
  const metrics = useMemo(() => extractFinancialMetrics(data), [data])
  const metricSections = useMemo(() => {
    const sections = [...financialMetricSections, { id: 'other', title: 'Other Available Metrics' }]
    return sections.map((section) => ({ ...section, metrics: metrics.filter((metric) => financialMetricSection(metric) === section.id) }))
  }, [metrics])
  const marketCap = metrics.find((metric) => /market cap|market capitalization/i.test(`${metric.label} ${metric.id}`))
  const currentPrices = asRecord(data.currentPrice)
  const exchanges = Object.keys(currentPrices).filter((exchange) => safeText(currentPrices[exchange]))
  const ticker = safeText(data.tickerId || data.symbol || research?.symbol)
  const companyName = safeText(data.companyName) || findText(profile, ['companyName', 'name']) || ticker || 'Company profile'
  const description = safeText(profile.companyDescription || profile.description || profile.businessDescription) || findText(profile, ['companyDescription', 'businessDescription', 'description'])
  const articles = [...new Map(collectArticles(data.recentNews).map((item) => [item.title, item])).values()]
  const hasMetrics = metrics.length > 0

  return <div className="workspace-page research-page"><div className="page-title"><div><span className="eyebrow">FUNDAMENTALS & NEWS</span><h1>Stock Research</h1><p>Company profile and financial metrics from the IndianAPI response, alongside sourced financial news.</p></div></div>
    <section className="content-card"><form className="workspace-search" onSubmit={load}><label htmlFor="research-symbol">Company name or symbol</label><div><input id="research-symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} maxLength={80} required placeholder="e.g. INFY or Reliance" /><button className="button" disabled={busy}>{busy ? 'Researching…' : 'Research stock'}</button></div></form>{error && <p className="form-error" role="alert">{error}</p>}</section>
    {research && <>
      <section className="content-card research-profile-card"><div className="form-section-heading"><div><span className="eyebrow">COMPANY PROFILE</span><h2>{companyName}</h2></div><span className="field-badge">{research.source || 'Provider data'}</span></div>
        <p className="research-industry">{safeText(data.industry) || safeText(profile.industry) || 'Industry not supplied'}</p>
        {description && <p className="research-profile">{description}</p>}
        <div className="research-profile-facts">
          <div><span>Ticker</span><b>{ticker || 'N/A'}</b></div>
          <div><span>Exchange</span><b>{exchanges.length ? exchanges.join(' · ') : safeText(profile.exchange || profile.exchangeName) || 'N/A'}</b></div>
          <div><span>Market capitalization</span><b>{marketCap ? formatFinancialMetric(marketCap) : 'N/A'}</b></div>
        </div>
        {!description && <p className="metric-empty">Business description was not present in the provider response.</p>}
      </section>

      <div className="research-financial-sections">{metricSections.map((section) => <section className="content-card research-metric-section" key={section.id}>
        <div className="form-section-heading"><div><span className="eyebrow">FINANCIALS</span><h2>{section.title}</h2></div><span className="field-badge">{section.metrics.length} available</span></div>
        {section.metrics.length ? <MetricCards metrics={section.metrics} /> : <p className="metric-empty">No {section.title.toLowerCase()} data was supplied for this company.</p>}
      </section>)}</div>
      {!hasMetrics && <p className="form-error" role="status">The stock response contained a company profile but no readable financial metrics.</p>}

      <section className="content-card"><div className="form-section-heading"><div><span className="eyebrow">PROVIDER NEWS</span><h2>Article language signals</h2></div></div>{articles.length ? <div className="research-news">{articles.map((article, index) => { const signal = sentiment(`${article.title} ${article.summary}`); return <article key={`${article.title}-${index}`}><div><span className={`sentiment-chip ${signal.className}`}>{signal.label}</span>{article.source && <small>{article.source}</small>}{article.date && <small>{article.date}</small>}</div><h3>{article.url ? <a href={article.url.startsWith('http') ? article.url : `https://www.google.com/search?q=${encodeURIComponent(article.title)}`} target="_blank" rel="noreferrer">{article.title}</a> : article.title}</h3>{article.summary && <p>{article.summary}</p>}</article> })}</div> : <p className="muted">No article records were supplied in this stock response.</p>}<p className="note">Language labels use a simple word-match heuristic, not a trained financial sentiment model. Headlines can be ambiguous; this is not a trading signal or investment advice.</p></section>
    </>}
  </div>
}
