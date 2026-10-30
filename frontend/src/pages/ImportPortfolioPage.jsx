import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { usePortfolio } from '../app/PortfolioContext.jsx'
import { cancelPortfolioImport, confirmPortfolioImport, getPortfolioImportHistory, previewPortfolioImport } from '../services/portfolioApi.js'
import { getLatestNav } from '../services/mutualFundApi.js'
import '../importPreview.css'

const MAX_BYTES = 15 * 1024 * 1024
const ALLOWED = ['.pdf', '.csv', '.xlsx', '.xls']
const sizeLabel = (bytes) => `${(bytes / (1024 * 1024)).toFixed(2)} MB`

function decimalParts(value) {
  const match = String(value ?? '').trim().match(/^([+-]?)(\d+)(?:\.(\d*))?$/)
  if (!match) return null
  const fraction = match[3] || ''
  return { integer: BigInt(`${match[1] === '-' ? '-' : ''}${match[2]}${fraction}`), scale: fraction.length }
}

function decimalString(integer, scale) {
  const negative = integer < 0n
  let digits = String(negative ? -integer : integer).padStart(scale + 1, '0')
  if (scale) {
    const whole = digits.slice(0, -scale)
    const fraction = digits.slice(-scale).replace(/0+$/, '')
    digits = fraction ? `${whole}.${fraction}` : whole
  }
  return `${negative ? '-' : ''}${digits}`
}

function decimalProduct(left, right) {
  const a = decimalParts(left); const b = decimalParts(right)
  return a && b ? decimalString(a.integer * b.integer, a.scale + b.scale) : ''
}

function decimalQuotient(left, right) {
  const a = decimalParts(left); const b = decimalParts(right)
  if (!a || !b || b.integer === 0n) return ''
  const scaled = (a.integer * 10n ** BigInt(b.scale + 8)) / (b.integer * 10n ** BigInt(a.scale))
  return decimalString(scaled, 8)
}

function decimalDifference(left, right) {
  const a = decimalParts(left); const b = decimalParts(right)
  if (!a || !b) return ''
  const scale = Math.max(a.scale, b.scale)
  const leftScaled = a.integer * 10n ** BigInt(scale - a.scale)
  const rightScaled = b.integer * 10n ** BigInt(scale - b.scale)
  return decimalString(leftScaled - rightScaled, scale)
}

function rowProblem(row) {
  if (!row.scheme_name?.trim()) return 'Scheme name is required.'
  if (!['stock', 'mutual_fund'].includes(row.asset_type)) return 'Choose whether this holding is a stock or mutual fund.'
  if (row.asset_type === 'mutual_fund' && row.record_type !== 'holding' && !row.scheme_code && !/^[A-Z0-9]{12}$/i.test(row.isin || '')) return 'Add a valid scheme code or 12-character ISIN.'
  if (row.record_type === 'holding') {
    if (!row.snapshot_date) return 'Add the statement holdings as-of date.'
    if (!Number(row.units) || Number(row.units) <= 0) return 'Enter positive units.'
  } else if (['BUY', 'SELL'].includes(row.transaction_type)) {
    if (!row.transaction_date) return 'Add the transaction date.'
    if (!Number(row.units) || Number(row.units) <= 0) return 'Enter positive transaction units.'
    if ((!Number(row.nav) || Number(row.nav) <= 0) && (!Number(row.amount) || Number(row.amount) < 0)) return 'Enter NAV or transaction amount.'
  } else if (['DIVIDEND', 'FEE'].includes(row.transaction_type)) {
    if (!row.transaction_date) return 'Add the transaction date.'
    if (row.amount == null || row.amount === '' || Number(row.amount) < 0) return 'Enter the cash amount.'
  } else return 'Choose a recognized transaction type.'
  if (row.duplicate) return 'This row appears to be duplicated in the file; remove one copy.'
  return ''
}

function editableRecord(record) {
  return {
    ...record,
    scheme_code: record.scheme_code == null ? '' : String(record.scheme_code),
    units: record.units ?? '', nav: record.nav ?? '', average_cost: record.average_cost ?? '', current_price: record.current_price ?? '', amount: record.amount ?? '', current_value: record.current_value ?? '',
    isin: record.isin || '', folio_number: record.folio_number || '', transaction_date: record.transaction_date || '',
    snapshot_date: record.snapshot_date || '', transaction_type: record.transaction_type || '',
    category: record.category || '', sub_category: record.sub_category || '', returns_value: record.returns_value ?? '', xirr_pct: record.xirr_pct ?? '',
  }
}

export default function ImportPortfolioPage() {
  const { activePortfolio, createPortfolio, refresh } = usePortfolio()
  const fileInput = useRef(null)
  const [file, setFile] = useState(null)
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [requiresPassword, setRequiresPassword] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [processing, setProcessing] = useState(false)
  const [importId, setImportId] = useState(null)
  const [records, setRecords] = useState([])
  const [history, setHistory] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [portfolioName, setPortfolioName] = useState('My Portfolio')

  async function loadHistory(portfolioId = activePortfolio?.id) {
    if (!portfolioId) { setHistory([]); return }
    try { setHistory(await getPortfolioImportHistory(portfolioId)) } catch { /* history is secondary to the current review flow */ }
  }
  useEffect(() => { setHistory([]); loadHistory() }, [activePortfolio?.id])

  const invalidCount = useMemo(() => records.filter((row) => rowProblem(row)).length, [records])

  function chooseFile(nextFile) {
    setError(''); setNotice('')
    if (!nextFile) return
    const extension = `.${nextFile.name.split('.').pop()?.toLowerCase()}`
    if (!ALLOWED.includes(extension)) { setError('Choose a PDF, CSV, XLSX, or XLS statement.'); return }
    if (nextFile.size > MAX_BYTES) { setError('The maximum file size is 15 MB.'); return }
    if (importId) { setError('Cancel the current review before selecting another statement.'); return }
    setFile(nextFile); setRequiresPassword(false); setPassword(''); setRecords([]); setUploadProgress(0)
  }

  async function processFile(event) {
    event.preventDefault()
    if (!activePortfolio || !file) return
    setBusy(true); setProcessing(true); setError(''); setNotice(''); setUploadProgress(0)
    try {
      const result = await previewPortfolioImport(activePortfolio.id, file, password, setUploadProgress)
      if (result.requires_password) { setRequiresPassword(true); setProcessing(false); setError(result.message); return }
      setRequiresPassword(false); setPassword(''); setImportId(result.import_id); setRecords((result.records || []).map(editableRecord)); setNotice(result.message)
      setProcessing(false)
    } catch (err) {
      setError(err.message)
      setProcessing(false)
    } finally { setBusy(false) }
  }

  function updateRow(index, key, value) {
    const sourceField = ({ units: 'units', average_cost: 'average_cost', nav: 'current_price', current_price: 'current_price', amount: 'invested_value', current_value: 'current_value', returns_value: 'profit_loss' })[key]
    setRecords((rows) => rows.map((row, rowIndex) => rowIndex === index ? {
      ...(() => {
        const next = {
          ...row, [key]: value,
          ...(sourceField ? { field_sources: { ...(row.field_sources || {}), [sourceField]: 'edited' } } : {}),
          ...(key === 'asset_type' && value === 'stock' ? { record_type: 'holding', snapshot_date: row.snapshot_date || row.transaction_date || '', transaction_date: '', transaction_type: '' } : {}),
          ...(['scheme_name', 'symbol', 'exchange'].includes(key) && row.asset_type === 'stock' ? { identity_status: 'unverified', stock_match_status: 'unverified', stock_match_message: 'Edited stock identity. Review carefully; it will be imported as unverified.' } : {}),
        }
        const sources = next.field_sources || {}
        if (sources.average_cost === 'calculated' && next.amount && next.units) next.average_cost = decimalQuotient(next.amount, next.units)
        if (sources.invested_value === 'calculated' && next.average_cost && next.units) next.amount = decimalProduct(next.average_cost, next.units)
        if (sources.current_price === 'calculated' && next.current_value && next.units) next.current_price = decimalQuotient(next.current_value, next.units)
        if (sources.current_value === 'calculated' && (next.current_price || next.nav) && next.units) next.current_value = decimalProduct(next.current_price || next.nav, next.units)
        if (sources.profit_loss === 'calculated' && next.current_value && next.amount) next.returns_value = decimalDifference(next.current_value, next.amount)
        return next
      })(),
    } : row))
  }

  async function chooseScheme(index, candidate) {
    setRecords((rows) => rows.map((row, rowIndex) => rowIndex === index ? {
      ...row,
      scheme_code: String(candidate.scheme_code),
      isin: candidate.isin || '',
      matched_name: candidate.scheme_name,
      amc_name: candidate.fund_house || row.amc_name,
      category: row.category || candidate.category || '',
      sub_category: row.sub_category || candidate.sub_category || '',
      scheme_match_status: 'selected',
      scheme_match_message: 'Scheme selected from MFNAV. Loading its latest NAV…',
    } : row))
    if (records[index]?.record_type !== 'holding') return
    try {
      const latest = await getLatestNav(candidate.scheme_code)
      if (Number(latest?.nav) > 0) {
        setRecords((rows) => rows.map((row, rowIndex) => rowIndex === index && row.scheme_code === String(candidate.scheme_code) ? {
          ...row,
          nav: row.nav || String(latest.nav),
          current_price: row.current_price || String(latest.nav),
          field_sources: { ...(row.field_sources || {}), ...(!row.current_price ? { current_price: 'MFNAV' } : {}) },
          nav_date: row.nav ? row.nav_date : latest.nav_date || row.nav_date,
          scheme_match_message: row.nav ? 'Scheme selected from MFNAV; the statement NAV was retained.' : `Scheme selected from MFNAV; latest NAV loaded${latest.nav_date ? ` for ${latest.nav_date}` : ''}.`,
        } : row))
      } else {
        setRecords((rows) => rows.map((row, rowIndex) => rowIndex === index && row.scheme_code === String(candidate.scheme_code) ? { ...row, scheme_match_message: 'Scheme selected from MFNAV, but no valid latest NAV was returned.' } : row))
      }
    } catch {
      setRecords((rows) => rows.map((row, rowIndex) => rowIndex === index && row.scheme_code === String(candidate.scheme_code) ? { ...row, scheme_match_message: 'Scheme selected from MFNAV, but its latest NAV is currently unavailable.' } : row))
    }
  }

  async function confirm() {
    if (!activePortfolio || !importId || invalidCount) return
    setBusy(true); setError(''); setNotice('')
    const confirmedRecords = records.map((row) => ({
      record_type: row.record_type,
      asset_type: row.asset_type,
      scheme_name: row.scheme_name.trim(),
      symbol: row.symbol?.trim().toUpperCase() || null,
      exchange: row.exchange?.trim().toUpperCase() || null,
      identity_status: row.identity_status || 'unverified',
      amc_name: row.amc_name || null,
      category: row.category || null,
      sub_category: row.sub_category || null,
      folio_number: row.folio_number || null,
      isin: row.isin.trim().toUpperCase() || null,
      scheme_code: row.scheme_code ? Number(row.scheme_code) : null,
      scheme_match_status: ['exact', 'selected'].includes(row.scheme_match_status) ? row.scheme_match_status : row.scheme_code ? 'manual' : 'unverified',
      transaction_date: row.transaction_date || null,
      transaction_type: row.transaction_type || null,
      units: row.units === '' ? null : row.units,
      nav: row.nav === '' ? null : row.nav,
      average_cost: row.average_cost === '' ? null : row.average_cost,
      field_sources: row.field_sources || {},
      current_price: row.current_price === '' ? null : row.current_price,
      amount: row.amount === '' ? null : row.amount,
      current_value: row.current_value === '' ? null : row.current_value,
      returns_value: row.returns_value === '' ? null : row.returns_value,
      xirr_pct: row.xirr_pct === '' ? null : row.xirr_pct,
      snapshot_date: row.snapshot_date || null,
    }))
    try {
      const result = await confirmPortfolioImport(activePortfolio.id, { import_id: importId, records: confirmedRecords })
      await refresh(); await loadHistory(activePortfolio.id)
      setNotice(`Import complete: ${result.transaction_rows_imported} transactions and ${result.holding_snapshots_imported} holding snapshots added; ${result.skipped_duplicates} duplicates skipped.`)
      setImportId(null); setRecords([]); setFile(null); setPassword(''); setRequiresPassword(false)
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function cancelReview() {
    setBusy(true); setError(''); setNotice('')
    try {
      if (importId && activePortfolio) await cancelPortfolioImport(activePortfolio.id, importId)
      setImportId(null); setRecords([]); setFile(null); setPassword(''); setRequiresPassword(false); setNotice('Review cancelled. No investment records were imported.')
      await loadHistory()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function cancelHistoryPreview(id) {
    if (!activePortfolio) return
    setBusy(true); setError(''); setNotice('')
    try {
      await cancelPortfolioImport(activePortfolio.id, id)
      if (importId === id) { setImportId(null); setRecords([]); setFile(null); setPassword('') }
      await loadHistory(activePortfolio.id)
      setNotice('Pending preview cancelled. You can upload that statement again.')
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  function removeRow(index) { setRecords((rows) => rows.filter((_, rowIndex) => rowIndex !== index)) }

  async function handleCreatePortfolio(event) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('')
    try { await createPortfolio(portfolioName.trim()); setNotice('Portfolio created. Upload a statement to review your holdings.') }
    catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return <div className="workspace-page import-page"><div className="page-title"><div><span className="eyebrow">STATEMENT IMPORT</span><h1>Import Portfolio</h1><p>Upload a stock or mutual-fund statement, review extracted values, then confirm what should be added to your portfolio.</p></div></div>
    {!activePortfolio ? <section className="content-card create-portfolio-card"><span className="eyebrow">START HERE</span><h2>Create a portfolio</h2><p>Imported statement data will be saved into this private portfolio.</p><form className="inline-form" onSubmit={handleCreatePortfolio}><label>Portfolio name<input value={portfolioName} onChange={(event) => setPortfolioName(event.target.value)} maxLength={120} required /></label><button className="button" disabled={busy}>{busy ? 'Creating…' : 'Create portfolio'}</button></form>{error && <p className="form-error" role="alert">{error}</p>}</section> : <>
      <section className="content-card import-upload-card"><div className="form-section-heading"><div><span className="eyebrow">SECURE LOCAL PROCESSING</span><h2>Choose a statement</h2></div><span className="field-badge">Up to 15 MB</span></div>
        <input ref={fileInput} className="sr-only" type="file" accept=".pdf,.csv,.xlsx,.xls,application/pdf,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel" onChange={(e) => chooseFile(e.target.files?.[0])} />
        <button type="button" className={`import-dropzone ${dragging ? 'dragging' : ''}`} onDragOver={(e) => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={(e) => { e.preventDefault(); setDragging(false); chooseFile(e.dataTransfer.files?.[0]) }} onClick={() => fileInput.current?.click()} disabled={busy || Boolean(importId)}>
          <span className="import-drop-icon">⇧</span><b>{file ? file.name : 'Drag and drop a statement here'}</b><small>{file ? `${sizeLabel(file.size)} · ${file.name.split('.').pop()?.toUpperCase()}` : 'or click to choose a file'}</small><span className="button button-outline">Browse files</span>
        </button>
        <p className="note">Supported: stock, mutual-fund, or mixed text-based/password-protected PDF, CSV, XLSX, and XLS statements. Names and holdings are detected from statement columns; stock identifiers are checked through the configured IndianAPI service. The upload is not stored permanently. Scanned PDFs use OCR if Tesseract is installed.</p>
        {file && !importId && <form className="import-process-form" onSubmit={processFile}>
          {requiresPassword && <label className="import-password">PDF password<div><input type={showPassword ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" /><button type="button" className="subtle-button" onClick={() => setShowPassword(!showPassword)}>{showPassword ? 'Hide' : 'Show'}</button></div><small>Used only for this processing request; it is not saved.</small></label>}
          {processing && <div className="upload-progress" role="status"><span>{uploadProgress < 100 ? `Uploading ${uploadProgress}%` : 'Processing statement…'}</span><i><b style={{ width: `${uploadProgress}%` }} /></i></div>}
          <button className="button" disabled={busy}>{busy ? (uploadProgress < 100 ? 'Uploading…' : 'Processing…') : requiresPassword ? 'Unlock and preview' : 'Upload and preview'}</button>
        </form>}
      </section>
      {error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="form-success" role="status">{notice}</p>}
      {importId && <section className="content-card import-review-card"><div className="form-section-heading"><div><span className="eyebrow">REVIEW BEFORE SAVING</span><h2>Extracted records</h2></div><span className="field-badge">{records.length} rows · {invalidCount} need attention</span></div>
        <p className="note">Nothing is saved until you confirm. The importer detects asset types from the statement and lets you correct ambiguous rows. Review stock identity matches, MFNAV scheme matches, and keep folios separate.</p>
        <div className="table-scroll"><table className="investment-table import-review-table"><thead><tr><th>Asset type</th><th>Name</th><th>Symbol / scheme code</th><th>Exchange / AMC</th><th>ISIN</th><th>Folio</th><th>Record type</th><th>Date</th><th>Quantity / units</th><th>Average price / NAV</th><th>Current price</th><th>Invested value</th><th>Current value</th><th>Profit / loss</th><th>Match status / warnings</th></tr></thead><tbody>{records.map((row, index) => { const issue = rowProblem(row); return <tr key={`${row.row_id}-${index}`} className={`${issue || row.warnings?.length ? 'review-warning' : ''}`}>
          <td><select aria-label="Asset type" value={row.asset_type} onChange={(e) => updateRow(index, 'asset_type', e.target.value)}><option value="ambiguous">Choose type…</option><option value="stock">Stock</option><option value="mutual_fund">Mutual fund</option></select></td>
          <td><label><span className="sr-only">Name</span><input aria-label="Name" value={row.scheme_name} onChange={(e) => updateRow(index, 'scheme_name', e.target.value)} /></label></td>
          <td>{row.asset_type === 'stock' ? <input aria-label="Stock symbol" value={row.symbol || ''} onChange={(e) => updateRow(index, 'symbol', e.target.value.toUpperCase())} placeholder="Symbol" /> : <><input aria-label="Scheme code" inputMode="numeric" value={row.scheme_code} onChange={(e) => updateRow(index, 'scheme_code', e.target.value.replace(/\D/g, ''))} placeholder="Scheme code" />{row.scheme_candidates?.length > 0 && <select aria-label="Match mutual fund scheme" value={row.scheme_code || ''} onChange={(e) => { const candidate = row.scheme_candidates.find((item) => String(item.scheme_code) === e.target.value); if (candidate) chooseScheme(index, candidate); else setRecords((rows) => rows.map((item, rowIndex) => rowIndex === index ? { ...item, scheme_code: '', isin: '', scheme_match_status: 'unverified', nav_date: null } : item)) }}><option value="">Select scheme match…</option>{row.scheme_candidates.map((candidate) => <option key={candidate.scheme_code} value={candidate.scheme_code}>{candidate.scheme_name} · {candidate.fund_house || 'AMC unavailable'}{candidate.plan_type ? ` · ${candidate.plan_type}` : ''}{candidate.option_type ? ` · ${candidate.option_type}` : ''}{candidate.isin ? ` · ${candidate.isin}` : ''}</option>)}</select>}</>}</td>
          <td>{row.asset_type === 'stock' ? <input aria-label="Exchange" value={row.exchange || ''} onChange={(e) => updateRow(index, 'exchange', e.target.value.toUpperCase())} placeholder="NSE / BSE" /> : <input aria-label="AMC or fund house" value={row.amc_name || ''} onChange={(e) => updateRow(index, 'amc_name', e.target.value)} placeholder="AMC / fund house" />}</td>
          <td><input aria-label="ISIN" value={row.isin} maxLength={12} onChange={(e) => updateRow(index, 'isin', e.target.value.toUpperCase())} placeholder="Optional" /></td>
          <td>{row.asset_type === 'mutual_fund' && <input aria-label="Folio number" value={row.folio_number} onChange={(e) => updateRow(index, 'folio_number', e.target.value)} />}</td>
          <td>{row.asset_type === 'mutual_fund' && row.record_type !== 'holding' ? <select aria-label="Transaction type" value={row.transaction_type} onChange={(e) => updateRow(index, 'transaction_type', e.target.value)}><option value="">Select</option><option>BUY</option><option>SELL</option><option>DIVIDEND</option><option>FEE</option></select> : 'Holding'}</td>
          <td><input aria-label={row.record_type === 'holding' ? 'Statement date' : 'Transaction date'} type="date" value={row.record_type === 'holding' ? row.snapshot_date : row.transaction_date} onChange={(e) => updateRow(index, row.record_type === 'holding' ? 'snapshot_date' : 'transaction_date', e.target.value)} /></td>
          <td><input aria-label="Units" type="number" step="any" value={row.units} onChange={(e) => updateRow(index, 'units', e.target.value)} /></td>
          <td><input aria-label="Average cost" type="number" step="any" value={row.average_cost || (row.asset_type === 'stock' ? row.nav : '')} onChange={(e) => updateRow(index, 'average_cost', e.target.value)} />{row.asset_type === 'mutual_fund' && row.record_type !== 'holding' && <input aria-label="Transaction NAV" type="number" step="any" value={row.nav} onChange={(e) => updateRow(index, 'nav', e.target.value)} placeholder="Transaction NAV" />}</td>
          <td><input aria-label="Current price" type="number" step="any" value={row.current_price} onChange={(e) => updateRow(index, 'current_price', e.target.value)} /></td>
          <td><input aria-label="Amount or invested amount" type="number" step="0.01" value={row.amount} onChange={(e) => updateRow(index, 'amount', e.target.value)} /></td>
          <td><input aria-label="Current value" type="number" step="0.01" value={row.current_value} onChange={(e) => updateRow(index, 'current_value', e.target.value)} /></td>
          <td><input aria-label="Returns value" type="number" step="0.01" value={row.returns_value} onChange={(e) => updateRow(index, 'returns_value', e.target.value)} /><input aria-label="XIRR percent" type="number" step="any" value={row.xirr_pct} onChange={(e) => updateRow(index, 'xirr_pct', e.target.value)} placeholder="XIRR %" /></td>
          <td><div className="import-row-warning">{issue && <b>{issue}</b>}{row.source_sheet && <small>Worksheet: {row.source_sheet}</small>}{row.matched_name && <small>Matched name: {row.matched_name}</small>}{Object.keys(row.field_sources || {}).length > 0 && <small>Value sources: {Object.entries(row.field_sources).map(([field, source]) => `${field.replaceAll('_', ' ')}: ${{ statement: 'statement', IndianAPI: 'IndianAPI', MFNAV: 'MFNAV', calculated: 'calculated', edited: 'edited by you' }[source] || source}`).join(' · ')}</small>}{row.stock_match_message && <small>{row.stock_match_message}</small>}{row.scheme_match_message && <small>{row.scheme_match_message}</small>}{row.asset_type === 'stock' && <small>Stock identity: {row.identity_status || 'unverified'}</small>}{row.asset_type === 'mutual_fund' && row.scheme_match_status === 'unverified' && !row.scheme_code && <small>Unverified fund holding is allowed; live NAV lookup will be unavailable until the scheme is resolved.</small>}{row.warnings?.map((warning, warningIndex) => <small key={warningIndex}>{warning}</small>)}{row.duplicate && <small>Possible duplicate; remove this copy.</small>}<button className="subtle-button" type="button" onClick={() => removeRow(index)}>Remove row</button></div></td>
        </tr> })}</tbody></table></div>
        <div className="import-review-actions"><button className="button" disabled={busy || !records.length || invalidCount > 0} onClick={confirm}>{busy ? 'Importing…' : `Confirm import (${records.length})`}</button><button className="button button-outline" disabled={busy} onClick={cancelReview}>Cancel review</button><span>{invalidCount ? 'Fix required fields or remove those rows before confirming.' : 'Review every value and source statement before importing.'}</span></div>
      </section>}
      {notice.startsWith('Import complete') && <div className="import-success-links"><Link className="button" to="/app/dashboard">View updated dashboard</Link></div>}
      <section className="content-card import-history-card"><div className="form-section-heading"><div><span className="eyebrow">ACCOUNT HISTORY</span><h2>Statement imports</h2></div><button className="subtle-button" onClick={() => loadHistory()} disabled={busy}>Refresh</button></div>{history.length ? <div className="table-scroll"><table className="investment-table"><thead><tr><th>Date</th><th>File type</th><th>Status</th><th>Rows imported</th><th>Duplicates skipped</th><th>Action</th></tr></thead><tbody>{history.map((item) => <tr key={item.id}><td>{new Date(item.created_at).toLocaleString()}</td><td>{item.file_type.toUpperCase()}</td><td>{item.status}</td><td>{item.imported_rows} / {item.total_rows}</td><td>{item.skipped_duplicates}</td><td>{item.status === 'previewed' ? <button className="subtle-button" disabled={busy} onClick={() => cancelHistoryPreview(item.id)}>Cancel pending preview</button> : '—'}</td></tr>)}</tbody></table></div> : <p className="muted">No statement imports yet.</p>}</section>
    </>}
  </div>
}
