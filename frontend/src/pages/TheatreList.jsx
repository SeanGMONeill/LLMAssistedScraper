import { useState, useEffect } from 'react'
import { getShows } from '../api.js'
import ShowCard from '../components/ShowCard.jsx'

export default function TheatreList() {
  const [shows, setShows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    getShows()
      .then(data => setShows(data.productions))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="status-message">Loading…</div>
  if (error) return <div className="status-message error">Error: {error}</div>

  // Group by theatre (only productions with a known fixed theatre)
  const byTheatre = {}
  for (const prod of shows) {
    const key = prod.theatre || null
    if (!key) continue
    if (!byTheatre[key]) byTheatre[key] = []
    byTheatre[key].push(prod)
  }
  const theatres = Object.keys(byTheatre).sort()

  return (
    <div>
      <div className="page-header">
        <h1>By Theatre</h1>
        <p className="subtitle">
          <span>{theatres.length} theatres</span>
          <span>·</span>
          <span>{shows.length} productions tracked</span>
        </p>
      </div>
      {theatres.map(theatre => (
        <div key={theatre} className="theatre-section">
          <h2>{theatre}</h2>
          <div className="shows-grid">
            {byTheatre[theatre].map(prod => (
              <ShowCard key={prod.production_id} production={prod} />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
