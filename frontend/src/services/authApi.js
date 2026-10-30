import { getJson } from './http.js'

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`)
  return body
}

export const getCurrentUser = () => getJson('/api/auth/me')
export const signup = (data) => postJson('/api/auth/signup', data)
export const login = (data) => postJson('/api/auth/login', data)
export const logout = () => postJson('/api/auth/logout', {})
