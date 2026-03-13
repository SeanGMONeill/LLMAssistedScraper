import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getProduction } from '../api.js'
import CastTable from '../components/CastTable.jsx'
import CastTimeline from '../components/CastTimeline.jsx'

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export default function ProductionDetail() {
  const { showSlug, productionId } = useParams()
  const [production, setProduction] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    getProduction(showSlug, productionId)
      .then(setProduction)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [showSlug, productionId])

  if (loading) return <div className="status-message">Loading…</div>
  if (error) return <div className="status-message error">Error: {error}</div>
  if (!production) return <div className="status-message error">Production not found.</div>

  const isPress = production.data_source === 'press_release'

  return (
    <div>
      <div className="page-header">
        <Link to="/" className="back-link">← All Shows</Link>
        <h1>{production.show_name}</h1>
        <p className="subtitle">
          {production.production_label && <span>{production.production_label}</span>}
          {production.production_label && production.theatre && <span>·</span>}
          {production.theatre && <span>{production.theatre}</span>}
          {(production.production_label || production.theatre) && <span>·</span>}
          <span>{production.cast_count} cast members</span>
          <span>·</span>
          <span>Updated {formatDate(production.last_updated)}</span>
          <span className={`pill ${isPress ? 'pill-press' : 'pill-live'}`}>
            {isPress ? 'Press Release' : 'Live'}
          </span>
        </p>
      </div>

      <section>
        <h2>Current Cast</h2>
        <CastTable cast={production.cast} />
      </section>

      {production.history.length > 0 && (
        <section className="section">
          <h2>Cast History</h2>
          <CastTimeline history={production.history} />
        </section>
      )}
    </div>
  )
}
