const SECTION_RULES = [
  { id: 'growth', title: 'Growth', test: (label) => /growth|cagr|year.over.year|\byoy\b/.test(label) },
  { id: 'profitability', title: 'Profitability and Margins', test: (label) => /margin|return on (average )?(equity|assets|capital)|\broe\b|\broa\b|\broic\b|\broce\b/.test(label) },
  { id: 'strength', title: 'Financial Strength', test: (label) => /debt.to.equity|current ratio|quick ratio|interest coverage|debt ratio|total debt|liabilit|cash ratio/.test(label) },
  { id: 'valuation', title: 'Valuation', test: (label) => /price.to.earnings|price earnings|\bp\s*\/?\s*e\b|price.to.book|price.book|\bp\s*\/?\s*b\b|price.to.sales|enterprise value|ev.to|ebitda multiple|dividend yield|market cap|valuation|\bmultiple\b/.test(label) },
  { id: 'income', title: 'Income Statement', test: (label) => /revenue|sales|operating income|operating profit|net income|net profit|gross profit|earnings|\beps\b|\bebitda\b|\bebit\b|cost of goods/.test(label) },
]

const CURRENCY_WORDS = /revenue|sales|income|profit(?!ability|ability)|earnings|market cap|market capitalization|enterprise value|total assets|total debt|liabilities|cash flow|dividend amount|\beps\b|\bprice per share\b|book value per share|\b(?:ebitda|ebit)\b/
const MULTIPLE_WORDS = /price.to.earnings|price earnings|\bp\s*\/?\s*e\b|price.to.book|price.book|\bp\s*\/?\s*b\b|price.to.sales|enterprise value|ev.to|debt.to.equity|current ratio|quick ratio|interest coverage|\bmultiple\b/
const PERCENT_WORDS = /margin|return on (average )?(equity|assets|capital)|\bro[ae]\b|\broic\b|\broce\b|growth|yield|percentage|percent|profitability|payout ratio|change|tax rate/
const SKIP_KEYS = /^(?:date|period|quarter|year|fiscal year|currency|unit|units|display name|key|value|description|source|label|name|id|status|timestamp)$/i

function textKey(value) {
  return String(value ?? '')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
}

function readScalar(value, inheritedUnit = '') {
  if (value == null) return { value: null, unit: inheritedUnit }
  if (typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean') return { value, unit: inheritedUnit }
  if (Array.isArray(value)) return undefined
  if (typeof value === 'object') {
    const unit = value.unit ?? value.units ?? value.currency ?? inheritedUnit
    for (const field of ['displayValue', 'formattedValue', 'value', 'amount', 'rawValue']) {
      if (Object.hasOwn(value, field)) return readScalar(value[field], String(unit || ''))
    }
  }
  return undefined
}

function titleLabel(value) {
  const raw = String(value || '').replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/([a-zA-Z])(\d)/g, '$1 $2').replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim()
  if (!raw) return 'Financial metric'
  const smallWords = new Set(['a', 'an', 'and', 'as', 'at', 'by', 'for', 'in', 'of', 'on', 'or', 'to', 'with'])
  return raw.replace(/\b[a-z][a-z\d']*/gi, (word) => {
    const lower = word.toLowerCase()
    if (['roe', 'roa', 'roic', 'roce', 'eps', 'ebit', 'ebitda', 'pe', 'pb', 'ps', 'ev'].includes(lower)) return lower.toUpperCase()
    if (smallWords.has(lower)) return lower
    if (/^\d+$/.test(word)) return word
    return lower.charAt(0).toUpperCase() + lower.slice(1)
  })
}

function sectionFor(label) {
  const normalized = textKey(label)
  return SECTION_RULES.find((section) => section.test(normalized))?.id || 'other'
}

function metricFrom(label, id, rawValue, unit = '') {
  const scalar = readScalar(rawValue, unit)
  if (!scalar) return null
  const displayName = titleLabel(label || id)
  const normalized = `${textKey(displayName)} ${textKey(id)}`
  return { id: String(id || displayName), label: displayName, value: scalar.value, unit: scalar.unit, section: sectionFor(normalized), normalized }
}

/** Pull named scalar metrics from IndianAPI's object maps and [{displayName,key,value}] arrays. */
export function extractFinancialMetrics(marketData) {
  if (!marketData || typeof marketData !== 'object' || Array.isArray(marketData)) return []
  const output = []
  const seenObjects = new WeakSet()

  function visit(node, path, depth = 0) {
    if (node == null || depth > 8) return
    if (Array.isArray(node)) {
      node.forEach((item, index) => visit(item, path, depth + 1))
      return
    }
    if (typeof node !== 'object') {
      const label = path.at(-1)
      if (label && !SKIP_KEYS.test(String(label))) {
        const metric = metricFrom(label, label, node)
        if (metric) output.push(metric)
      }
      return
    }
    if (seenObjects.has(node)) return
    seenObjects.add(node)

    const label = node.displayName ?? node.label ?? node.name ?? node.metricName
    const id = node.key ?? node.metricKey ?? label
    if (label && Object.hasOwn(node, 'value')) {
      const metric = metricFrom(label, id, node.value, node.unit ?? node.units ?? node.currency ?? '')
      if (metric) output.push(metric)
      return
    }
    for (const [key, value] of Object.entries(node)) {
      if (SKIP_KEYS.test(key)) continue
      visit(value, [...path, key], depth + 1)
    }
  }

  const topLevelMarketCap = marketData.marketCapitalization ?? marketData.marketCap
  const topLevelMarketCapSource = topLevelMarketCap == null ? null : [{ displayName: 'Market Capitalization', key: 'marketCapitalization', value: topLevelMarketCap }]
  for (const source of [marketData.keyMetrics, marketData.financials, marketData.initialStockFinancialData, marketData.stockDetailsReusableData, topLevelMarketCapSource]) {
    visit(source, [])
  }

  const unique = new Map()
  for (const metric of output) {
    const key = textKey(metric.id || metric.label)
    const previous = unique.get(key)
    if (!previous || (previous.value == null && metric.value != null)) unique.set(key, metric)
  }
  return [...unique.values()]
}

function numericValue(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value !== 'string' || !value.trim()) return null
  const cleaned = value.replace(/[₹$€£,\s]/g, '').replace(/\b(?:INR|USD|EUR|GBP|Rs\.?)\b/gi, '').trim()
  if (!/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?%?$/i.test(cleaned)) return null
  const number = Number(cleaned.replace(/%$/, ''))
  return Number.isFinite(number) ? number : null
}

function compactRupees(number, maximumFractionDigits = 2) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR', notation: 'compact', maximumFractionDigits,
  }).format(number)
}

/** Format only units supported by the metric name or explicit API unit metadata. */
export function formatFinancialMetric(metric) {
  const value = metric?.value
  if (value == null || (typeof value === 'string' && !value.trim())) return 'N/A'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  const label = metric?.normalized || textKey(metric?.label || metric?.id)
  const source = String(value).trim()
  const unit = String(metric?.unit || '').trim()
  const number = numericValue(value)
  if (number == null) {
    if (CURRENCY_WORDS.test(label) && /\d/.test(source) && /(?:crore|\bcr\b|lakh|\blac\b|million|\bmn\b|billion|\bbn\b)/i.test(`${source} ${unit}`) && !/₹|\binr\b|\brs\.?/i.test(`${source} ${unit}`)) return `₹${source}`
    return source || 'N/A'
  }

  if (source.endsWith('%') || /%|percent/i.test(unit) || PERCENT_WORDS.test(label)) {
    return `${new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(number)}%`
  }
  if (/\bx\b|times/i.test(unit) || MULTIPLE_WORDS.test(label)) {
    return `${new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(number)}x`
  }
  const hasCurrency = /₹|\binr\b|\brs\.?/i.test(unit)
  const isCurrency = hasCurrency || CURRENCY_WORDS.test(label) || /^(?:inr|₹|rs\.?|rupees?)$/i.test(unit)
  if (isCurrency) {
    const explicitScale = /(?:crore|\bcr\b|lakh|\blac\b|million|\bmn\b|billion|\bbn\b)/i.test(`${source} ${unit}`)
    if (explicitScale) return `${hasCurrency || /₹/i.test(unit) ? '' : '₹'}${source}${unit && !source.toLowerCase().includes(unit.toLowerCase()) ? ` ${unit}` : ''}`
    const isPerShare = /per share|\beps\b|\bprice per share\b|book value per share/i.test(label)
    if (isPerShare) return `₹${new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(number)}`
    return compactRupees(number)
  }
  if (unit) return `${source} ${unit}`
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(number)
}

export function financialMetricSection(metric) {
  return metric.section
}

export const financialMetricSections = SECTION_RULES
