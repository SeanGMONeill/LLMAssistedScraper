// In production: VITE_API_URL is unset → uses relative /api path (routed via CloudFront)
// In development: set VITE_API_URL to your API Gateway URL, e.g.:
//   VITE_API_URL=https://xxx.execute-api.eu-west-2.amazonaws.com npm run dev
const BASE = import.meta.env.VITE_API_URL ?? '/api'

async function request(path) {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${r.statusText}`)
  return r.json()
}

export const getShows = () => request('/shows')
export const getShow = (name) => request(`/shows/${encodeURIComponent(name)}`)
export const getActor = (name) => request(`/actors/${encodeURIComponent(name)}`)
