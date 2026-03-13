import { Link } from 'react-router-dom'

export default function NavBar() {
  return (
    <nav className="navbar">
      <Link to="/" className="navbar-brand">West End Cast Tracker</Link>
    </nav>
  )
}
