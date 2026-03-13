import { Routes, Route } from 'react-router-dom'
import NavBar from './components/NavBar.jsx'
import Home from './pages/Home.jsx'
import ShowDetail from './pages/ShowDetail.jsx'
import ActorProfile from './pages/ActorProfile.jsx'

export default function App() {
  return (
    <div className="app">
      <NavBar />
      <main className="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/shows/:name" element={<ShowDetail />} />
          <Route path="/actors/:name" element={<ActorProfile />} />
        </Routes>
      </main>
    </div>
  )
}
