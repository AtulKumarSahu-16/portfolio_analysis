const content = {
  investments: ['Investments', 'Add and manage your stock and mutual-fund transactions.'],
  'mutual-funds': ['Mutual Funds', 'Search schemes and review provider-backed NAV history.'],
  stocks: ['Stocks', 'Review stock prices and historical market data.'],
  performance: ['Performance', 'Portfolio performance will be calculated from your transactions and dated market data.'],
  overlap: ['Overlap Analysis', 'Fund overlap depends on verified portfolio holdings and weights.'],
  sectors: ['Sector Analysis', 'Sector exposure depends on your holdings and verified sector classifications.'],
  research: ['Stock Research', 'Fundamentals and sourced financial news will appear here when provider data is available. Price prediction is not part of this product.'],
  assistant: ['AI Assistant', 'The assistant will answer portfolio questions from your saved records and connected data.'],
  reports: ['Reports', 'Generate portfolio and transaction reports from your own saved records.'],
  settings: ['Settings', 'Manage your account and data preferences.'],
}

export default function WorkspacePage({ section }) {
  const [title, description] = content[section] || content.investments
  return <><div className="page-title"><div><span className="eyebrow">PORTFOLIO WORKSPACE</span><h1>{title}</h1><p>{description}</p></div><span className="availability-badge">Planned for a later stage</span></div><section className="workspace-placeholder"><strong>{title} is not connected yet</strong><p>This workspace will be enabled in a later implementation stage. No sample holdings or financial values are shown.</p></section></>
}
