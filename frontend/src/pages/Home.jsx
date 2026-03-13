import { useState, useEffect } from 'react'
import { getShows } from '../api.js'
import ShowCard from '../components/ShowCard.jsx'

export default function Home() {
  const [shows, setShows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    getShows()
      .then(data => setShows(data.productions))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="status-message">Loading shows…</div>
  if (error) return <div className="status-message error">Error: {error}</div>

  return (
    <div>
      <div className="page-header">
        <h1>UK Theatre</h1>
        <p className="subtitle">{shows.length} productions tracked</p>
      </div>
      <div className="shows-grid">
        {shows.map(prod => (
          <ShowCard key={prod.production_id} production={prod} />
        ))}
      </div>
    </div>
  )
}
