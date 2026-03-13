import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getShow } from '../api.js'
import CastTable from '../components/CastTable.jsx'
import CastTimeline from '../components/CastTimeline.jsx'

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export default function ShowDetail() {
  const { name } = useParams()
  const showName = decodeURIComponent(name)
  const [show, setShow] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    getShow(showName)
      .then(setShow)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [showName])

  if (loading) return <div className="status-message">Loading…</div>
  if (error) return <div className="status-message error">Error: {error}</div>
  if (!show) return <div className="status-message error">Show not found.</div>

  return (
    <div>
      <div className="page-header">
        <Link to="/" className="back-link">← All Shows</Link>
        <h1>{show.name}</h1>
        <p className="subtitle">
          {show.cast_count} cast members · Updated {formatDate(show.last_updated)}
        </p>
      </div>

      <section>
        <h2>Current Cast</h2>
        <CastTable cast={show.cast} />
      </section>

      {show.history.length > 0 && (
        <section className="section">
          <h2>Cast History</h2>
          <CastTimeline history={show.history} />
        </section>
      )}
    </div>
  )
}
