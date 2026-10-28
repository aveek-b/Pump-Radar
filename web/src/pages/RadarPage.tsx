import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { getMarkets, getRadar, type Horizon } from '../api/client'
import { useLiveTicks } from '../api/useLiveTicks'
import { Badge, ErrorState, HorizonPicker, Loading, Notice, number, percent, Sparkline, utc } from '../components/ui'

export type RadarSearch = { horizon: Horizon; tab: 'radar' | 'markets'; q: string; tier: string; sort: 'risk' | 'pair' }
export const defaultSearch: RadarSearch = { horizon: '10', tab: 'radar', q: '', tier: 'all', sort: 'risk' }

export function RadarPage({ filters, change }: { filters: RadarSearch; change: (patch: Partial<RadarSearch>) => void }) {
  const radar = useQuery({ queryKey: ['radar'], queryFn: ({ signal }) => getRadar(signal), refetchInterval: query => query.state.data?.mock ? false : 5000 })
  const markets = useQuery({ queryKey: ['markets'], queryFn: ({ signal }) => getMarkets(signal), refetchInterval: 30_000 })
  const live = useLiveTicks()
  const data = radar.data
  const rows = [...(data?.rows ?? [])].sort((a, b) => filters.sort === 'pair' ? a.pair.localeCompare(b.pair) : (b.risk[filters.horizon] ?? -1) - (a.risk[filters.horizon] ?? -1) || a.pair.localeCompare(b.pair))
  const riskByPair = new Map(rows.map(row => [row.pair, row]))
  const marketByPair = new Map(markets.data?.markets.map(m => [m.symbol, m]))
  const matches = (pair: string) => pair.toLowerCase().includes(filters.q.toLowerCase()) && (filters.tier === 'all' || riskByPair.get(pair)?.tier === filters.tier)
  const visible = rows.filter(row => matches(row.pair))
  const marketRows = [...(markets.data?.markets ?? [])].filter(m => matches(m.symbol)).sort((a, b) => filters.sort === 'pair' ? a.symbol.localeCompare(b.symbol) : (riskByPair.get(b.symbol)?.risk[filters.horizon] ?? -1) - (riskByPair.get(a.symbol)?.risk[filters.horizon] ?? -1) || a.symbol.localeCompare(b.symbol))
  const now = data?.minute ? Date.parse(data.minute) : 0
  const recentAlerts = live.alerts.filter(a => Date.parse(a.time) <= now && Date.parse(a.time) >= now - 3600_000)
  const sinceAlert = (pair: string) => {
    const alert = recentAlerts.find(a => a.pair === pair)
    return alert ? `${Math.max(0, Math.floor((now - Date.parse(alert.time)) / 60_000))} min` : 'Not observed'
  }

  return <>
    <div className="eyebrow">MARKET WATCH</div><h1>Radar</h1>
    <p className="intro">Follow unusual activity across coins. Choose a horizon to compare their scores.</p>
    {data && <Notice mock={data.mock ?? false} notice={data.notice ?? ''} />}
    <div className="summary">
      <div><span>Coins monitored</span><strong>{data?.mock ? rows.length : data?.coins.length ?? '—'}</strong></div>
      <div><span>Alerts observed this session, last hour</span><strong>{recentAlerts.length}</strong><small>Budget unavailable · not an evaluated alert rate</small></div>
      <div><span>{data?.mock ? 'Synthetic scoring time' : 'Last closed minute'}</span><strong className="timestamp">{utc(data?.minute)}</strong></div>
    </div>
    <div className="controls">
      <div className="tabs" aria-label="Market views"><button aria-pressed={filters.tab === 'radar'} onClick={() => change({ tab: 'radar' })}>Pump radar</button><button aria-pressed={filters.tab === 'markets'} onClick={() => change({ tab: 'markets' })}>All markets</button></div>
      <HorizonPicker value={filters.horizon} onChange={horizon => change({ horizon })} />
      <label>Search <input type="search" placeholder="Find a pair" value={filters.q} onChange={e => change({ q: e.target.value })} /></label>
      <label>Tier <select aria-label="Tier" value={filters.tier} onChange={e => change({ tier: e.target.value })}><option value="all">All tiers</option>{['low', 'medium', 'high'].map(t => <option key={t}>{t}</option>)}</select></label>
      <label>Sort <select aria-label="Sort" value={filters.sort} onChange={e => change({ sort: e.target.value as RadarSearch['sort'] })}><option value="risk">Risk, highest first</option><option value="pair">Pair A–Z</option></select></label>
      <button onClick={() => void live.enableAlerts()} disabled={live.notification === 'Alerts enabled'}>{live.notification}</button>
    </div>
    <p className="muted">Level badges use the 10-minute threshold. The selected horizon controls risk sorting. Mock values are not probabilities.</p>
    <div className="panel">
      {radar.isPending ? <Loading /> : radar.error ? <ErrorState error={radar.error} retry={() => void radar.refetch()} /> : filters.tab === 'markets' ? <>
        <div className="panel-top"><strong>All markets</strong><span>{marketRows.length} pairs · {markets.data?.mock ? 'synthetic prices' : 'market prices'}</span></div>
        {markets.isPending ? <Loading /> : markets.error ? <ErrorState error={markets.error} retry={() => void markets.refetch()} /> : !marketRows.length ? <p className="state">No markets match. Clear filters, or wait for the market-feed integration.</p> : <div className="table-wrap"><table><thead><tr><th>Pair</th><th>Price</th><th>24h change</th><th>24h quote volume</th><th>Risk · {filters.horizon} min</th></tr></thead><tbody>{marketRows.map(m => <tr key={m.symbol}><td>{m.scored ? <Link to="/coin/$pair" params={{ pair: m.symbol }}>{m.symbol}</Link> : m.symbol}</td><td>{number(m.price)} {m.quote_asset}</td><td>{m.change_24h_pct == null ? 'Unavailable' : `${m.change_24h_pct.toFixed(2)}%`}</td><td>{number(m.volume_24h_quote)} {m.quote_asset}</td><td>{m.scored ? percent(riskByPair.get(m.symbol)?.risk[filters.horizon]) : 'Not scored'}</td></tr>)}</tbody></table></div>}
      </> : data?.mock ? <>
        <div className="panel-top"><strong>Coin ranking</strong><span>{visible.length} matching coins</span></div>
        {!visible.length ? <p className="state">No coins match. Try another search or tier.</p> : <div className="table-wrap"><table><thead><tr><th>Rank</th><th>Pair</th><th>Price (BTC)</th><th>Risk · {filters.horizon} min</th><th>Level · 10 min</th><th>Tier</th><th>Recent trend</th><th>Last observed alert</th></tr></thead><tbody>{visible.map(row => <tr key={row.pair}><td>{rows.findIndex(r => r.pair === row.pair) + 1}</td><td><Link to="/coin/$pair" params={{ pair: row.pair }}>{row.pair}</Link></td><td>{number(marketByPair.get(row.pair)?.price)}</td><td className="number">{percent(row.risk[filters.horizon])}</td><td><Badge level={row.level} /></td><td>{row.tier}</td><td><Sparkline values={row.sparkline ?? []} /></td><td>{sinceAlert(row.pair)}</td></tr>)}</tbody></table></div>}
      </> : <>
        <div className="panel-top"><strong>Manual / feeder demo</strong><span>Five-earlier-bar volume heuristic</span></div>
        {!data?.coins.length ? <p className="state">No closed bars yet. Start the feeder or send bars through the API.</p> : <div className="table-wrap"><table><thead><tr><th>Pair</th><th>Volume vs median</th><th>Buy share</th><th>Demo score</th></tr></thead><tbody>{data.coins.filter(c => c.symbol.toLowerCase().includes(filters.q.toLowerCase())).map(c => <tr key={c.symbol}><td>{c.symbol}</td><td>{c.relative_volume == null ? 'Warming up' : `${c.relative_volume.toFixed(2)}×`}</td><td>{percent(c.buy_share)}</td><td>{c.score?.toFixed(3) ?? 'Warming up'}</td></tr>)}</tbody></table></div>}
        <p className="state">Horizon, tier and risk sort apply to model-shaped rows only. Demo scores are not probabilities.</p>
      </>}
    </div>
    {!!recentAlerts.length && <section className="panel"><div className="panel-top"><strong>Recent observed alerts</strong><span>Session history only</span></div><ul className="alert-list">{recentAlerts.slice(0, 5).map(a => <li key={a.id}><Link to="/coin/$pair" params={{ pair: a.pair }}>{a.pair}</Link> · {utc(a.time)}<p>{a.reasons.join(' ')}</p></li>)}</ul></section>}
  </>
}
