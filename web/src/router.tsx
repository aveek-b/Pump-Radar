import { useQuery } from '@tanstack/react-query'
import { Activity, BarChart3, Clock3, FlaskConical, Radar, ShieldCheck } from 'lucide-react'
import { Link, Outlet, createRootRoute, createRoute, createRouter } from '@tanstack/react-router'
import { getRadar } from './api/client'
import { useLiveTicks } from './api/useLiveTicks'

function Shell() {
  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><Radar size={23} /> <span>PumpRadar</span></div>
      <nav aria-label="Main navigation">
        <Link to="/" activeProps={{ className: 'active' }}><Activity size={18} /> Radar</Link>
        <Link to="/replay" activeProps={{ className: 'active' }}><Clock3 size={18} /> Replay</Link>
        <Link to="/honesty" activeProps={{ className: 'active' }}><ShieldCheck size={18} /> Honesty</Link>
        <Link to="/method" activeProps={{ className: 'active' }}><FlaskConical size={18} /> Method</Link>
      </nav>
      <div className="sidebar-note">Research tool. Not financial advice. No trades are placed.</div>
    </aside>
    <div className="body">
      <header className="topbar"><span>BTC pair surveillance</span><span className="pill">Contract preview</span></header>
      <main><Outlet /></main>
    </div>
  </div>
}

function RadarPage() {
  const { data, error, isPending } = useQuery({ queryKey: ['radar'], queryFn: getRadar, refetchInterval: 5000 })
  const { prices, status, alertCount } = useLiveTicks()
  const priceByPair = new Map(prices?.markets.map(market => [market.symbol, market.price]))
  return <>
    <div className="eyebrow">MARKET WATCH / {data?.mock ? 'MOCK DATA' : 'DEMO MODE'}</div>
    <h1>Radar</h1>
    <p className="intro">{data?.mock ? '60 synthetic coins. Prices update about every 2 seconds; mock scores every 10 seconds. These are not trained predictions.' : "Current closed minute. A score of zero means volume did not exceed the coin's earlier median."}</p>
    <p role="status">Stream: {status}{data?.mock && ` · scoring tick ${data.sequence ?? 0} · ${alertCount} synthetic alert(s) in last tick`}</p>
    {data?.mock && <p>Fixture clock: {prices?.as_of ?? 'Waiting for first price event'}. Timestamps and prices are synthetic.</p>}
    <div className="panel">
      <div className="panel-top"><strong>Coin ranking</strong><span>{data?.minute ? `Updated ${new Date(data.minute).toLocaleString()}` : 'Waiting for bars'}</span></div>
      {isPending ? <p className="state">Loading the latest minute…</p> : error ? <p className="state">API unavailable. Start FastAPI on port 8000.</p> :
        data.mock ? <div className="table-wrap"><table><thead><tr><th>Rank</th><th>Mock pair</th><th>Mock price (BTC)</th><th>Tier</th><th>Mock risk (10 min)</th><th>Mock level</th></tr></thead><tbody>
          {data.rows?.map((coin, index) => <tr key={coin.pair}><td>{index + 1}</td><td>{coin.pair}</td><td className="number">{priceByPair.get(coin.pair)?.toFixed(8) ?? 'Waiting for stream'}</td><td>{coin.tier}</td><td className="number">{((coin.risk['10'] ?? 0) * 100).toFixed(1)}%</td><td>{coin.level}</td></tr>)}
        </tbody></table></div> :
        data.coins.length === 0 ? <p className="state">No closed bars yet. Start the feeder or send bars through the API.</p> :
        <div className="table-wrap"><table><thead><tr><th>Rank</th><th>Pair</th><th>Volume vs median</th><th>Buy share</th><th>Demo score</th></tr></thead><tbody>
          {data.coins.map((coin, index) => <tr key={coin.symbol}><td>{index + 1}</td><td><Link to="/coin/$pair" params={{ pair: coin.symbol }}>{coin.symbol}</Link></td><td>{coin.relative_volume == null ? 'Warming up' : `${coin.relative_volume.toFixed(2)}×`}</td><td>{(coin.buy_share * 100).toFixed(0)}%</td><td className="number">{coin.score == null ? '—' : coin.score.toFixed(3)}</td></tr>)}
        </tbody></table></div>}
    </div>
    <p className="disclaimer">These values are a wiring test, not calibrated pump probabilities. The research model and multi-horizon risks are pending the team handoff.</p>
  </>
}

function PendingPage({ title, owner, detail }: { title: string; owner: string; detail: string }) {
  return <><div className="eyebrow">PLATFORM / INITIAL STRUCTURE</div><h1>{title}</h1><div className="panel placeholder"><BarChart3 size={30} /><h2>Waiting for {owner}'s handoff</h2><p>{detail}</p></div></>
}

const rootRoute = createRootRoute({ component: Shell })
const radarRoute = createRoute({ getParentRoute: () => rootRoute, path: '/', component: RadarPage })
const coinRoute = createRoute({ getParentRoute: () => rootRoute, path: '/coin/$pair', component: () => <PendingPage title="Coin view" owner="model and bar data" detail="Candles, risk series and driver explanations will use the final API contract." /> })
const replayRoute = createRoute({ getParentRoute: () => rootRoute, path: '/replay', component: () => <PendingPage title="Replay" owner="held-out replay JSON" detail="This page will show test-era events only after the frozen model scores them." /> })
const honestyRoute = createRoute({ getParentRoute: () => rootRoute, path: '/honesty', component: () => <PendingPage title="Honesty" owner="evaluation results" detail="Alert rate, lead-time metrics and limitations will come from measured results." /> })
const methodRoute = createRoute({ getParentRoute: () => rootRoute, path: '/method', component: () => <PendingPage title="Method" owner="the paper's final method" detail="This page will explain onset anchoring, splits, features and the alert budget." /> })

const routeTree = rootRoute.addChildren([radarRoute, coinRoute, replayRoute, honestyRoute, methodRoute])
export const router = createRouter({ routeTree })
declare module '@tanstack/react-router' { interface Register { router: typeof router } }
