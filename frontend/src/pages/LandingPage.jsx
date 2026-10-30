import { Link } from 'react-router-dom'

const features = [
  ['01', 'Portfolio tracking', 'Keep your stock and mutual-fund transactions together and see values from connected market data.'],
  ['02', 'Mutual fund analysis', 'Explore NAV history and, when holdings data is available, compare fund exposure.'],
  ['03', 'Stock research', 'Review provider-backed fundamentals and sourced financial news. No future price forecasts.'],
  ['04', 'Portfolio assistant', 'Ask questions grounded in the holdings and market data available in your account.'],
]

export default function LandingPage() {
  return <div className="public-page">
    <header className="public-nav"><Link to="/" className="wordmark"><span className="brand-icon">P</span>Portfolio<span>AI</span></Link>
      <nav aria-label="Main navigation"><a href="#features">Features</a><a href="#pricing">Pricing</a><a href="#about">About</a></nav>
      <div className="nav-actions"><Link className="nav-login" to="/login">Log in</Link><Link className="button button-small" to="/signup">Create account</Link></div>
    </header>
    <main>
      <section className="hero" id="about"><div className="hero-copy"><span className="hero-kicker">A clearer view of your investments</span><h1>Track. Understand.<br /><em>Invest with context.</em></h1><p>Bring your Indian stocks and mutual funds into one calm, useful view. Your portfolio data stays yours; market data comes from connected sources.</p><div className="hero-actions"><Link className="button" to="/signup">Get started <span aria-hidden="true">→</span></Link><a className="button button-outline" href="#features">Explore features</a></div><p className="hero-footnote">No sample portfolio values. Start with your own records.</p></div>
        <div className="hero-art" aria-label="Illustration of a portfolio dashboard waiting for your holdings"><div className="art-window"><div className="art-top"><span>PORTFOLIO OVERVIEW</span><span className="art-avatar">P</span></div><div className="art-status"><i /><span>Ready for your portfolio</span></div><div className="art-empty"><div className="art-orbit">↗</div><strong>Your data, organized</strong><small>Holdings and market updates in one place</small></div><div className="art-bottom"><span>STOCKS</span><span>MUTUAL FUNDS</span><span>REPORTS</span></div></div><div className="art-glow" /></div>
      </section>
      <section className="feature-section" id="features"><div className="section-head"><span className="eyebrow">BUILT AROUND YOUR PORTFOLIO</span><h2>Useful context, without the noise.</h2><p>Financial views are calculated from your saved records and provider data. Missing data stays clearly marked.</p></div><div className="feature-grid">{features.map(([number,title,description])=><article className="feature-card" key={number}><span>{number}</span><h3>{title}</h3><p>{description}</p></article>)}</div></section>
      <section className="pricing-section" id="pricing"><div><span className="eyebrow">PROVIDER ACCESS</span><h2>Check provider terms before connecting.</h2><p>Stock-data access and request limits depend on your IndianAPI plan. MFNAV documents public NAV access with an anonymous rate limit. Provider charges and terms are separate from this application.</p></div><div className="pricing-links"><a href="https://indianapi.in/indian-stock-market" target="_blank" rel="noreferrer">IndianAPI plans and pricing <span aria-hidden="true">↗</span></a><a href="https://mfnav.in/api-docs" target="_blank" rel="noreferrer">MFNAV API terms <span aria-hidden="true">↗</span></a></div></section>
      <section className="how-section" id="how-it-works"><div><span className="eyebrow">HOW IT WORKS</span><h2>Your portfolio starts with your statement.</h2></div><ol><li><b>Create your private account</b><span>Keep your investment records associated with your account.</span></li><li><b>Import a portfolio statement</b><span>Upload a PDF, Excel, or CSV statement and review the extracted holdings.</span></li><li><b>Review sourced market context</b><span>See what providers return, with dates and availability shown.</span></li></ol></section>
      <section className="closing-cta"><div><span className="eyebrow">PORTFOLIO INTELLIGENCE AI</span><h2>Start with a better view.</h2></div><Link className="button" to="/signup">Create your account <span aria-hidden="true">→</span></Link></section>
    </main>
    <footer className="public-footer"><Link to="/" className="wordmark"><span className="brand-icon">P</span>Portfolio<span>AI</span></Link><span>Market information is for research and organization, not investment advice.</span><span>© {new Date().getFullYear()} PortfolioAI</span></footer>
  </div>
}
