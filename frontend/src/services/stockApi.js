import { getJson } from './http.js'

export const getStockPrice = (symbol) => getJson(`/api/stocks/${encodeURIComponent(symbol)}/price`)
export const getStockPreviousClose = (symbol) => getJson(`/api/stocks/${encodeURIComponent(symbol)}/previous-close`)
export const getStockHistory = (symbol, period) => getJson(`/api/stocks/${encodeURIComponent(symbol)}/history?period=${encodeURIComponent(period)}`)
