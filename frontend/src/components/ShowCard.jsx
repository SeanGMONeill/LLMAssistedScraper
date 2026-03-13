import { Link } from 'react-router-dom'

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export default function ShowCard({ production }) {
  const isPress = production.data_source === 'press_release'
  const subtitle = production.production_label || production.show_type || ''
  return (
    <Link
      to={`/shows/${encodeURIComponent(production.show_slug)}/${encodeURIComponent(production.production_id)}`}
      className="show-card"
    >
      <div className="show-card-name">{production.show_name}</div>
      {subtitle && <div className="show-card-theatre">{subtitle}</div>}
      {production.theatre && <div className="show-card-theatre">{production.theatre}</div>}
      <span className="show-card-count">{production.cast_count}</span>
      <span className="show-card-count-label">cast members</span>
      <div className="show-card-footer">
        <div className="show-card-updated">Updated {formatDate(production.last_updated)}</div>
        <span className={`pill ${isPress ? 'pill-press' : 'pill-live'}`}>
          {isPress ? 'Press' : 'Live'}
        </span>
      </div>
    </Link>
  )
}
