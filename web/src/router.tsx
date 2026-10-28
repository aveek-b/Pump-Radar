import { useState } from 'react'
import { Activity, Clock3, FlaskConical, Radar, ShieldCheck } from 'lucide-react'
import { Link, Outlet, createRootRoute, createRoute, createRouter } from '@tanstack/react-router'
import { Toaster } from 'sonner'
import { horizons, type Horizon } from './api/client'
import { LiveProvider, useLiveTicks } from './api/useLiveTicks'
import { utc } from './components/ui'
import { RadarPage, defaultSearch, type RadarSearch } from './pages/RadarPage'
import { CoinPage } from './pages/CoinPage'
import { ReplayPage } from './pages/ReplayPage'
import { HonestyPage, MethodPage } from './pages/ResearchPages'

function Shell() { return <LiveProvider><Layout /></LiveProvider> }
function Layout() {
  const live = useLiveTicks()
  const [light, setLight] = useState(false)
  const connected = live.status === 'Connected'
  return <div className={`shell ${light ? 'light' : ''}`}>
    <a className="skip-link" href="#main">Skip to content</a>
    <aside className="sidebar"><div className="brand"><Radar size={23} /><span>PumpRadar</span></div>
      <nav aria-label="Main navigation">
        <Link to="/" search={defaultSearch} activeOptions={{ exact: true }} activeProps={{ className: 'active' }}><Activity size={18} />Radar</Link>
        <Link to="/replay" activeProps={{ className: 'active' }}><Clock3 size={18} />Replay</Link>
        <Link to="/honesty" activeProps={{ className: 'active' }}><ShieldCheck size={18} />Honesty</Link>
        <Link to="/method" activeProps={{ className: 'active' }}><FlaskConical size={18} />Method</Link>
      </nav><div className="sidebar-note">Research tool. Not financial advice. No trades are placed.</div>
    </aside>
    <div className="body"><header className="topbar"><span><span className={`status-dot ${connected ? 'connected' : ''}`} />{live.status}</span><button aria-pressed={light} onClick={() => setLight(!light)}>Light theme</button></header>
      {!connected && <div className="feed-banner" role="status">{live.status}. Last price event received: {utc(live.lastReceived)}. Connection status does not imply a research model is loaded.</div>}
      <main id="main"><Outlet /><footer className="disclaimer">Research tool. Not financial advice. No trades are placed.</footer></main>
    </div><Toaster theme={light ? 'light' : 'dark'} richColors closeButton />
  </div>
}

const rootRoute = createRootRoute({ component: Shell, notFoundComponent: () => <><h1>Page not found</h1><Link to="/" search={defaultSearch}>Return to Radar</Link></> })
const radarRoute = createRoute({
  getParentRoute: () => rootRoute, path: '/',
  validateSearch: (search: Record<string, unknown>): RadarSearch => ({
    horizon: horizons.includes(String(search.horizon) as Horizon) ? String(search.horizon) as Horizon : '10',
    tab: search.tab === 'markets' ? 'markets' : 'radar', q: typeof search.q === 'string' ? search.q.slice(0, 100) : '',
    tier: ['low', 'medium', 'high'].includes(String(search.tier)) ? String(search.tier) : 'all',
    sort: search.sort === 'pair' ? 'pair' : 'risk',
  }),
  component: function RadarRoute() {
    const filters = radarRoute.useSearch()
    const navigate = radarRoute.useNavigate()
    return <RadarPage filters={filters} change={patch => void navigate({ search: { ...filters, ...patch }, replace: true })} />
  },
})
const coinRoute = createRoute({ getParentRoute: () => rootRoute, path: '/coin/$pair', component: function CoinRoute() { const { pair } = coinRoute.useParams(); return <CoinPage key={pair} pair={pair} /> } })
const replayRoute = createRoute({ getParentRoute: () => rootRoute, path: '/replay', component: ReplayPage })
const honestyRoute = createRoute({ getParentRoute: () => rootRoute, path: '/honesty', component: HonestyPage })
const methodRoute = createRoute({ getParentRoute: () => rootRoute, path: '/method', component: MethodPage })
export const router = createRouter({ routeTree: rootRoute.addChildren([radarRoute, coinRoute, replayRoute, honestyRoute, methodRoute]) })
declare module '@tanstack/react-router' { interface Register { router: typeof router } }
