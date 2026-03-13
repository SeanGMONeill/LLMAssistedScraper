import { Link } from 'react-router-dom'

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export default function ShowCard({ show }) {
  return (
    <Link to={`/shows/${encodeURIComponent(show.name)}`} className="show-card">
      <div className="show-card-name">{show.name}</div>
      <span className="show-card-count">{show.cast_count}</span>
      <span className="show-card-count-label">cast members</span>
      <div className="show-card-updated">Updated {formatDate(show.last_updated)}</div>
    </Link>
  )
}
