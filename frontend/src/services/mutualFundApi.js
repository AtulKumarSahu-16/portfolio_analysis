import { getJson } from './http.js'

export const searchFunds = (query) => getJson(`/api/mutual-funds/search?q=${encodeURIComponent(query)}&page_size=20`)
export const getLatestNav = (schemeCode) => getJson(`/api/mutual-funds/${encodeURIComponent(schemeCode)}/nav`)
export const getNavHistory = (schemeCode, startDate, endDate) => {
  const params = new URLSearchParams()
  if (startDate) params.set('start_date', startDate)
  if (endDate) params.set('end_date', endDate)
  return getJson(`/api/mutual-funds/${encodeURIComponent(schemeCode)}/history?${params}`)
}
