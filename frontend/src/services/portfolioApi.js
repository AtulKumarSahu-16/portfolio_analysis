import { getJson } from './http.js'

async function send(path, method, data) {
  const response = await fetch(path, {
    method,
    credentials: 'same-origin',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    ...(data ? { body: JSON.stringify(data) } : {}),
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || `Request failed (${response.status})`)
  return body
}

export const getPortfolios = () => getJson('/api/portfolios')
export const createPortfolio = (name) => send('/api/portfolios', 'POST', { name })
export const getPortfolioTransactions = (id) => getJson(`/api/portfolios/${id}/transactions?page_size=500`)
export const getPortfolioHoldings = (id) => getJson(`/api/portfolios/${id}/holdings`)
export const addTransaction = (id, data) => send(`/api/portfolios/${id}/transactions`, 'POST', data)
export const updateTransaction = (portfolioId, transactionId, data) => send(`/api/portfolios/${portfolioId}/transactions/${transactionId}`, 'PUT', data)
export const deleteTransaction = (portfolioId, transactionId) => send(`/api/portfolios/${portfolioId}/transactions/${transactionId}`, 'DELETE')
export const getSIPSchedules = (id) => getJson(`/api/portfolios/${id}/sip-schedules`)
export const getFundAllocations = (id) => getJson(`/api/portfolios/${id}/fund-allocations`)
export const getFundAllocationOverlap = (id) => getJson(`/api/portfolios/${id}/fund-allocations/overlap`)
export const saveFundAllocation = (id, data) => send(`/api/portfolios/${id}/fund-allocations`, 'POST', data)

function xhrRequest(path, method, body, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open(method, path)
    xhr.withCredentials = true
    xhr.timeout = 120000
    xhr.setRequestHeader('Accept', 'application/json')
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress?.(Math.round(event.loaded / event.total * 100)) }
    xhr.onerror = () => reject(new Error('Network error while uploading the statement.'))
    xhr.ontimeout = () => reject(new Error('Statement processing timed out. Try a smaller or text-based file.'))
    xhr.onload = () => {
      let payload = null
      try { payload = JSON.parse(xhr.responseText) } catch { /* use the status fallback below */ }
      if (xhr.status < 200 || xhr.status >= 300) return reject(new Error(payload?.detail || `Request failed (${xhr.status})`))
      resolve(payload)
    }
    xhr.send(body)
  })
}

export function previewPortfolioImport(portfolioId, file, password, onProgress) {
  const form = new FormData()
  form.append('file', file)
  if (password) form.append('password', password)
  return xhrRequest(`/api/portfolios/${portfolioId}/imports/preview`, 'POST', form, onProgress)
}
export const confirmPortfolioImport = (portfolioId, payload) => send(`/api/portfolios/${portfolioId}/imports/confirm`, 'POST', payload)
export const getPortfolioImportHistory = (portfolioId) => getJson(`/api/portfolios/${portfolioId}/imports`)
export const cancelPortfolioImport = (portfolioId, importId) => send(`/api/portfolios/${portfolioId}/imports/${importId}`, 'DELETE')
