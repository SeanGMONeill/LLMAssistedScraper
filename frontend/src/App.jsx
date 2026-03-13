import { Routes, Route } from 'react-router-dom'
import NavBar from './components/NavBar.jsx'
import Home from './pages/Home.jsx'
import ProductionDetail from './pages/ProductionDetail.jsx'
import ActorProfile from './pages/ActorProfile.jsx'
import TheatreList from './pages/TheatreList.jsx'

export default function App() {
  return (
    <div className="app">
      <NavBar />
      <main className="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/shows/:showSlug/:productionId" element={<ProductionDetail />} />
          <Route path="/actors/:name" element={<ActorProfile />} />
          <Route path="/theatres" element={<TheatreList />} />
        </Routes>
      </main>
    </div>
  )
}
