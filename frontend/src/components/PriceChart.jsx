export default function PriceChart({ points = [], label = 'Price history' }) {
  const valid = points
    .map((point) => ({ date: String(point.date || ''), value: Number(point.price ?? point.nav) }))
    .filter((point) => Number.isFinite(point.value) && point.value > 0)
  if (valid.length < 2) return <div className="chart-empty">Not enough dated provider observations to draw a chart.</div>

  const width = 760
  const height = 220
  const pad = 22
  const min = Math.min(...valid.map((point) => point.value))
  const max = Math.max(...valid.map((point) => point.value))
  const spread = max - min || max * 0.01
  const coords = valid.map((point, index) => ({
    ...point,
    x: pad + index * (width - pad * 2) / (valid.length - 1),
    y: height - pad - (point.value - min) / spread * (height - pad * 2),
  }))
  const polyline = coords.map((point) => `${point.x},${point.y}`).join(' ')
  const latest = coords.at(-1)
  return <figure className="price-chart">
    <figcaption><span>{label}</span><b>₹{latest.value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</b><small>{latest.date}</small></figcaption>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label}, ${valid.length} provider observations`}>
      <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} />
      <line x1={pad} y1={pad} x2={width - pad} y2={pad} />
      <polyline points={polyline} />
      <circle cx={latest.x} cy={latest.y} r="4" />
    </svg>
    <div className="chart-axis"><span>₹{min.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span><span>₹{max.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span></div>
  </figure>
}
