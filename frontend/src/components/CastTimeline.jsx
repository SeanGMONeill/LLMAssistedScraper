import { Link } from 'react-router-dom'

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export default function CastTimeline({ history }) {
  if (!history || history.length === 0) {
    return <p style={{ color: 'var(--text-muted)', marginTop: '0.5rem' }}>No history available.</p>
  }

  return (
    <div className="timeline">
      {history.map((entry, i) => (
        <div key={i} className="timeline-item">
          <div className="timeline-actor">
            <div className="timeline-actor-name">
              <Link to={`/actors/${encodeURIComponent(entry.actor_name)}`}>
                {entry.actor_name}
              </Link>
              {' '}
              <span className={`badge ${entry.is_current ? 'badge-current' : 'badge-past'}`}>
                {entry.is_current ? 'Current' : 'Past'}
              </span>
            </div>
            <div className="timeline-actor-role">{entry.roles.join(', ')}</div>
          </div>
          <div className="timeline-dates">
            <div>From {formatDate(entry.first_seen)}</div>
            {!entry.is_current && <div>To {formatDate(entry.last_seen)}</div>}
          </div>
        </div>
      ))}
    </div>
  )
}
