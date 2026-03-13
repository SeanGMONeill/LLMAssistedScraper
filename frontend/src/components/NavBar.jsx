import { Link, NavLink } from 'react-router-dom'

export default function NavBar() {
  return (
    <nav className="navbar">
      <Link to="/" className="navbar-brand">West End Cast Tracker</Link>
      <div className="navbar-links">
        <NavLink to="/" end className={({ isActive }) => 'navbar-link' + (isActive ? ' active' : '')}>Shows</NavLink>
        <NavLink to="/theatres" className={({ isActive }) => 'navbar-link' + (isActive ? ' active' : '')}>Theatres</NavLink>
      </div>
    </nav>
  )
}
