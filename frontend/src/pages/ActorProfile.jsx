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

  const currentShows = actor.shows.filter(s => s.is_current)

  return (
    <div>
      <div className="page-header">
        <Link to="/" className="back-link">← All Shows</Link>
        <h1>{actor.name}</h1>
        <p className="subtitle">
          {currentShows.length > 0
            ? `Currently in ${currentShows.map(s => s.show_name).join(', ')}`
            : 'Former West End performer'}
        </p>
      </div>

      <section>
        <h2>Show History</h2>
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
              {actor.shows.map((s, i) => (
                <tr key={i}>
                  <td>
                    <Link to={`/shows/${encodeURIComponent(s.show_name)}`}>
                      {s.show_name}
                    </Link>
                  </td>
                  <td>{s.roles.join(', ')}</td>
                  <td>{formatDate(s.first_seen)}</td>
                  <td>{formatDate(s.last_seen)}</td>
                  <td>
                    <span className={`badge ${s.is_current ? 'badge-current' : 'badge-past'}`}>
                      {s.is_current ? 'Current' : 'Past'}
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
