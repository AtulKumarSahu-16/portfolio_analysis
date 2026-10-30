import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { useAuth } from './AuthContext.jsx'
import { createPortfolio as createPortfolioRequest, getPortfolios } from '../services/portfolioApi.js'

const PortfolioContext = createContext(null)

export function PortfolioProvider({ children }) {
  const { user } = useAuth()
  const [portfolios, setPortfolios] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    setLoading(true); setError('')
    getPortfolios().then((items) => {
      if (!alive) return
      setPortfolios(items)
      setActiveId((current) => items.some((item) => item.id === current) ? current : items[0]?.id ?? null)
    }).catch((err) => { if (alive) setError(err.message) }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [user?.id])

  const activePortfolio = portfolios.find((item) => item.id === activeId) || null
  const value = useMemo(() => ({
    portfolios, activePortfolio, loading, error, setActiveId,
    async createPortfolio(name) {
      const created = await createPortfolioRequest(name)
      setPortfolios((items) => [...items, created])
      setActiveId(created.id)
      setError('')
      return created
    },
    async refresh() {
      const items = await getPortfolios()
      setPortfolios(items)
      setActiveId((current) => items.some((item) => item.id === current) ? current : items[0]?.id ?? null)
      return items
    },
  }), [portfolios, activePortfolio, loading, error])

  return <PortfolioContext.Provider value={value}>{children}</PortfolioContext.Provider>
}

export function usePortfolio() {
  const value = useContext(PortfolioContext)
  if (!value) throw new Error('usePortfolio must be used inside PortfolioProvider')
  return value
}
