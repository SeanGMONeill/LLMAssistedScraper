import { Link } from 'react-router-dom'

function roleSortKey(role) {
  const r = role.toLowerCase()
  if (r === 'swing' || r.startsWith('swing /') || r.endsWith('/ swing')) return 2
  if (r === 'ensemble' || r.includes('ensemble')) return 1
  return 0
}

export default function CastTable({ cast }) {
  if (!cast || cast.length === 0) {
    return <p style={{ color: 'var(--text-muted)', marginTop: '0.5rem' }}>No cast data available.</p>
  }

  const sorted = [...cast].sort((a, b) => roleSortKey(a.role) - roleSortKey(b.role))

  return (
    <div className="table-container">
      <table>
        <thead>
          <tr>
            <th>Role</th>
            <th>Actor</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((member, i) => (
            <tr key={i}>
              <td>{member.role}</td>
              <td>
                <Link to={`/actors/${encodeURIComponent(member.actor)}`}>
                  {member.actor}
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
