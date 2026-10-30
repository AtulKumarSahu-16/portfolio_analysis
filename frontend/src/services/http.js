export async function getJson(path) {
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`)
  return body
}
