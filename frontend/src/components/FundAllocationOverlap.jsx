import { useEffect, useState } from 'react'
import { getFundAllocationOverlap, getFundAllocations, saveFundAllocation } from '../services/portfolioApi.js'

const categories = [
  ['large_cap_pct', 'Large cap'],
  ['mid_cap_pct', 'Mid cap'],
  ['small_cap_pct', 'Small cap'],
  ['commodities_pct', 'Commodities'],
]

export default function FundAllocationOverlap({ portfolioId }) {
  const [funds, setFunds] = useState([])
  const [pairs, setPairs] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [form, setForm] = useState({ snapshot_date: '', source_label: '', source_url: '', large_cap_pct: '', mid_cap_pct: '', small_cap_pct: '', commodities_pct: '' })
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  async function reload() {
    setLoading(true); setError('')
    try {
      const [allocationResult, overlapResult] = await Promise.all([getFundAllocations(portfolioId), getFundAllocationOverlap(portfolioId)])
      setFunds(allocationResult.funds || []); setPairs(overlapResult.pairs || [])
      setSelectedId((current) => (allocationResult.funds || []).some((fund) => String(fund.instrument.id) === String(current)) ? current : String(allocationResult.funds?.[0]?.instrument.id || ''))
    } catch (err) { setError(err.message) } finally { setLoading(false) }
  }
  useEffect(() => { reload() }, [portfolioId])

  async function save(event) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('')
    const payload = {
      instrument_id: Number(selectedId),
      snapshot_date: form.snapshot_date,
      source_label: form.source_label,
      ...(form.source_url.trim() ? { source_url: form.source_url.trim() } : {}),
      ...Object.fromEntries(categories.map(([key]) => [key, form[key] === '' ? null : form[key]])),
    }
    try {
      await saveFundAllocation(portfolioId, payload)
      setForm({ snapshot_date: '', source_label: '', source_url: '', large_cap_pct: '', mid_cap_pct: '', small_cap_pct: '', commodities_pct: '' })
      await reload(); setNotice('Dated allocation disclosure saved. Comparisons use matching snapshot dates only.')
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  const selectedFund = funds.find((fund) => String(fund.instrument.id) === String(selectedId))
  if (loading && !funds.length) return <p className="muted">Loading mutual-fund allocations…</p>
  if (!funds.length) return <section className="content-card"><h2>No mutual funds in this portfolio</h2><p>Record a mutual-fund purchase first, then add its disclosed category allocations.</p></section>

  return <div className="allocation-overlap-workspace">
    <section className="content-card"><div className="form-section-heading"><div><span className="eyebrow">ENTER DISCLOSED ALLOCATION</span><h2>Save a fund allocation snapshot</h2></div><span className="field-badge">Source and date required</span></div>
      <p className="note">Copy percentages from the fund’s AMC factsheet or portfolio disclosure. Enter every value as a percentage of total scheme NAV/assets. If market-cap figures are shown as a percentage of equity, multiply them by the scheme’s equity-allocation percentage first. MFNAV provides NAVs, not these allocation values.</p>
      <form className="allocation-form" onSubmit={save}>
        <label>Mutual fund<select required value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>{funds.map((item) => <option key={item.instrument.id} value={item.instrument.id}>{item.instrument.display_name}</option>)}</select></label>
        <label>Portfolio as-of date<input type="date" required max={new Date().toISOString().slice(0, 10)} value={form.snapshot_date} onChange={(e) => setForm({ ...form, snapshot_date: e.target.value })} /></label>
        <label>Source name<input required minLength={3} maxLength={180} placeholder="AMC monthly factsheet" value={form.source_label} onChange={(e) => setForm({ ...form, source_label: e.target.value })} /></label>
        <label className="allocation-source-url">Source URL (optional)<input type="url" placeholder="https://fund-house.example/factsheet" value={form.source_url} onChange={(e) => setForm({ ...form, source_url: e.target.value })} /></label>
        <div className="allocation-input-grid">{categories.map(([key, label]) => <label key={key}>{label} allocation (%)<input type="number" min="0" max="100" step="0.01" placeholder="Not disclosed" value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} /></label>)}</div>
        <p className="note allocation-hint">Leave a category blank if the disclosure doesn’t report it. Entered categories may total less than 100% because other assets can be present; totals over 100% are rejected.</p>
        <button className="button" disabled={busy || !selectedId}>{busy ? 'Saving…' : 'Save disclosed allocation'}</button>
      </form>
      {error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="form-success" role="status">{notice}</p>}
    </section>

    <section className="content-card"><div className="form-section-heading"><div><span className="eyebrow">PAIRWISE COMPARISON</span><h2>Shared category allocation</h2></div><button className="subtle-button" onClick={reload} disabled={loading}>Refresh</button></div>
      {pairs.length ? <div className="table-scroll"><table className="investment-table allocation-overlap-table"><thead><tr><th>Fund pair</th><th>Large cap</th><th>Mid cap</th><th>Small cap</th><th>Commodities</th><th>Snapshots</th></tr></thead><tbody>{pairs.map((pair) => <tr key={`${pair.fund_a.instrument_id}-${pair.fund_b.instrument_id}`}><td><b>{pair.fund_a.scheme_name}</b><small>and {pair.fund_b.scheme_name}</small></td>{categories.map(([key]) => <td key={key}>{pair.comparable && pair.overlap_pct[key] != null ? `${Number(pair.overlap_pct[key]).toFixed(2)}%` : 'Unavailable'}</td>)}<td>{pair.fund_a.snapshot_date || 'Missing'}<small>{pair.fund_b.snapshot_date || 'Missing'}</small></td></tr>)}</tbody></table></div> : <p className="muted">Add allocation disclosures for at least two schemes to see a pairwise comparison.</p>}
      {funds.map((item) => <div className="allocation-saved-row" key={item.instrument.id}><b>{item.instrument.display_name}</b>{item.allocation ? <span>{item.allocation.snapshot_date} · {item.allocation.source_label}{item.allocation.source_url ? <> · <a href={item.allocation.source_url} target="_blank" rel="noreferrer">source</a></> : ''}</span> : <span>No disclosure saved yet</span>}{selectedFund?.instrument.id === item.instrument.id && item.allocation && <small>{categories.map(([key,label]) => `${label}: ${item.allocation[key] == null ? 'not reported' : `${Number(item.allocation[key]).toFixed(2)}%`}`).join(' · ')}</small>}</div>)}
      <p className="note">For each category, shared allocation is the lower of the two reported percentages. Use the same NAV denominator and compatible category definitions for both funds. This compares allocation only; funds can hold completely different securities. A pair is calculated only when both snapshots have the same as-of date.</p>
    </section>
  </div>
}
