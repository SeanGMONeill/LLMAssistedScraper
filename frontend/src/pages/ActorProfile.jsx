import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getActor } from '../api.js'

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export default function ActorProfile() {
  const { name } = useParams()
  const actorName = decodeURIComponent(name)
  const [actor, setActor] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    getActor(actorName)
      .then(setActor)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [actorName])

  if (loading) return <div className="status-message">Loading…</div>
  if (error) return <div className="status-message error">Error: {error}</div>
  if (!actor) return <div className="status-message error">Actor not found.</div>

  const productions = actor.productions || []
  const currentProductions = productions.filter(p => p.is_current)

  return (
    <div>
      <div className="page-header">
        <Link to="/" className="back-link">← All Shows</Link>
        <h1>{actor.name}</h1>
        <p className="subtitle">
          {currentProductions.length > 0
            ? `Currently in ${currentProductions.map(p => p.show_name).join(', ')}`
            : 'Former theatre performer'}
        </p>
      </div>

      <section>
        <h2>Production History</h2>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Show</th>
                <th>Role(s)</th>
                <th>First seen</th>
                <th>Last seen</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {productions.map((p, i) => (
                <tr key={i}>
                  <td>
                    <Link to={`/shows/${encodeURIComponent(p.show_slug)}/${encodeURIComponent(p.production_id)}`}>
                      {p.show_name}{p.production_label ? ` — ${p.production_label}` : ''}
                    </Link>
                  </td>
                  <td>{p.roles.join(', ')}</td>
                  <td>{formatDate(p.first_seen)}</td>
                  <td>{formatDate(p.last_seen)}</td>
                  <td>
                    <span className={`badge ${p.is_current ? 'badge-current' : 'badge-past'}`}>
                      {p.is_current ? 'Current' : 'Past'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
