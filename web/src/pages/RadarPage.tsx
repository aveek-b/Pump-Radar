import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { getLiveScores, getMarkets, getRadar, type Horizon } from '../api/client'
import { useLiveTicks } from '../api/useLiveTicks'
import { Badge, ErrorState, HorizonPicker, Loading, modelScoreLabel, Notice, number, percent, Sparkline, utc } from '../components/ui'

export type RadarSearch = { horizon: Horizon; tab: 'radar' | 'markets'; q: string; tier: string; sort: 'risk' | 'pair' }
export const defaultSearch: RadarSearch = { horizon: '10', tab: 'radar', q: '', tier: 'all', sort: 'risk' }

export function RadarPage({ filters, change }: { filters: RadarSearch; change: (patch: Partial<RadarSearch>) => void }) {
  const radar = useQuery({ queryKey: ['radar'], queryFn: ({ signal }) => getRadar(signal), refetchInterval: query => query.state.data?.mock ? false : 5000 })
  const markets = useQuery({ queryKey: ['markets'], queryFn: ({ signal }) => getMarkets(signal), refetchInterval: 30_000 })
  const modelScores = useQuery({ queryKey: ['live-model-scores'], queryFn: ({ signal }) => getLiveScores(signal), enabled: radar.data?.mock === false, refetchInterval: 30_000 })
  const live = useLiveTicks()
  const data = radar.data
  const rows = [...(data?.rows ?? [])].sort((a, b) => filters.sort === 'pair' ? a.pair.localeCompare(b.pair) : (b.risk[filters.horizon] ?? -1) - (a.risk[filters.horizon] ?? -1) || a.pair.localeCompare(b.pair))
  const riskByPair = new Map(rows.map(row => [row.pair, row]))
  const marketByPair = new Map(markets.data?.markets.map(m => [m.symbol, m]))
  const matches = (pair: string) => pair.toLowerCase().includes(filters.q.toLowerCase()) && (filters.tier === 'all' || riskByPair.get(pair)?.tier === filters.tier)
  const visible = rows.filter(row => matches(row.pair))
  const marketRows = [...(markets.data?.markets ?? [])].filter(m => matches(m.symbol)).sort((a, b) => filters.sort === 'pair' ? a.symbol.localeCompare(b.symbol) : markets.data?.mock ? (riskByPair.get(b.symbol)?.risk[filters.horizon] ?? -1) - (riskByPair.get(a.symbol)?.risk[filters.horizon] ?? -1) || a.symbol.localeCompare(b.symbol) : (b.model_score ?? -Infinity) - (a.model_score ?? -Infinity) || a.symbol.localeCompare(b.symbol))
  const priceWatch = [...(markets.data?.markets ?? [])].filter(m => m.quote_asset === 'USDT' && m.symbol.toLowerCase().includes(filters.q.toLowerCase())).sort((a, b) => (b.volume_24h_quote ?? 0) - (a.volume_24h_quote ?? 0)).slice(0, 10)
  const now = data?.minute ? Date.parse(data.minute) : 0
  const recentAlerts = live.alerts.filter(a => Date.parse(a.time) <= now && Date.parse(a.time) >= now - 3600_000)
  const scoredModels = [...(modelScores.data?.coins ?? [])].filter(coin => coin.score != null).sort((a, b) => b.score! - a.score!)
  const sinceAlert = (pair: string) => {
    const alert = recentAlerts.find(a => a.pair === pair)
    return alert ? `${Math.max(0, Math.floor((now - Date.parse(alert.time)) / 60_000))} min` : 'Not observed'
  }

  return <>
    <div className="eyebrow">MARKET WATCH</div><h1>Radar</h1>
    <p className="intro">Follow unusual activity across coins. {data?.mock ? 'Choose a horizon to compare synthetic scores.' : 'Live research rankings use a fixed 10-minute horizon.'}</p>
    {data?.mock && <Notice mock notice={data.notice ?? ''} />}
    <div className="summary">
      <div><span>Coins with radar scores</span><strong>{data?.mock ? rows.length : scoredModels.length}</strong></div>
      <div><span>Markets with prices</span><strong>{markets.data?.markets.length ?? '—'}</strong><small>{markets.data?.mock ? 'Synthetic fixtures' : 'Public Binance snapshot, refreshed about every 30 seconds'}</small></div>
      <div><span>{data?.mock ? 'Alerts observed this session, last hour' : 'BTC pairs tracked by model'}</span><strong>{data?.mock ? recentAlerts.length : modelScores.data?.n_tracked_pairs ?? '—'}</strong><small>{data?.mock ? 'Not an evaluated alert rate' : 'Live false-alert rate not measured'}</small></div>
      <div><span>{data?.mock ? 'Synthetic scoring time' : 'Last model-scored minute'}</span><strong className="timestamp">{utc(data?.mock ? data.minute : scoredModels[0]?.as_of)}</strong></div>
    </div>
    <div className="controls">
      <div className="tabs" aria-label="Market views"><button aria-pressed={filters.tab === 'radar'} onClick={() => change({ tab: 'radar' })}>Pump radar</button><button aria-pressed={filters.tab === 'markets'} onClick={() => change({ tab: 'markets' })}>All markets</button></div>
      {data?.mock && <HorizonPicker value={filters.horizon} onChange={horizon => change({ horizon })} />}
      <label>Search <input type="search" placeholder="Find a pair" value={filters.q} onChange={e => change({ q: e.target.value })} /></label>
      {data?.mock && <label>Tier <select aria-label="Tier" value={filters.tier} onChange={e => change({ tier: e.target.value })}><option value="all">All tiers</option>{['low', 'medium', 'high'].map(t => <option key={t}>{t}</option>)}</select></label>}
      <label>Sort <select aria-label="Sort" value={filters.sort} onChange={e => change({ sort: e.target.value as RadarSearch['sort'] })}><option value="risk">{data?.mock ? 'Risk, highest first' : 'Raw margin, highest first'}</option><option value="pair">Pair A–Z</option></select></label>
      {data?.mock && <button onClick={() => void live.enableAlerts()} disabled={live.notification === 'Alerts enabled'}>{live.notification}</button>}
    </div>
    <p className="muted">{data?.mock ? 'Level badges use the 10-minute threshold. The selected horizon controls risk sorting. Mock values are not probabilities.' : 'Live model values below are raw 10-minute SVM ranking margins, not probabilities. Only BTC pairs with enough real bars receive a value.'}</p>
    <div className="panel">
      {filters.tab === 'markets' ? <>
        <div className="panel-top"><strong>All markets</strong><span>{marketRows.length} pairs · {markets.data?.mock ? 'synthetic prices' : 'market prices'}</span></div>
        {markets.isPending ? <Loading /> : markets.error ? <ErrorState error={markets.error} retry={() => void markets.refetch()} /> : !marketRows.length ? <p className="state">No markets match. Clear filters, or check the market-price feed.</p> : <div className="table-wrap"><table><thead><tr><th>Pair</th><th>Price</th><th>24h change</th><th>24h quote volume</th><th>{markets.data.mock ? `Risk · ${filters.horizon} min` : 'Raw SVM margin · 10 min'}</th></tr></thead><tbody>{marketRows.map(m => <tr key={m.symbol}><td>{m.scored || !markets.data.mock ? <Link to="/coin/$pair" params={{ pair: m.symbol }}>{m.symbol}</Link> : m.symbol}</td><td>{number(m.price)} {m.quote_asset}</td><td>{m.change_24h_pct == null ? 'Unavailable' : `${m.change_24h_pct.toFixed(2)}%`}</td><td>{number(m.volume_24h_quote)} {m.quote_asset}</td><td>{markets.data.mock ? m.scored ? percent(riskByPair.get(m.symbol)?.risk[filters.horizon]) : 'Not scored' : modelScoreLabel(m)}</td></tr>)}</tbody></table></div>}
      </> : radar.isPending ? <Loading /> : radar.error ? <ErrorState error={radar.error} retry={() => void radar.refetch()} /> : data?.mock ? <>
        <div className="panel-top"><strong>Coin ranking</strong><span>{visible.length} matching coins</span></div>
        {!visible.length ? <p className="state">No coins match. Try another search or tier.</p> : <div className="table-wrap"><table><thead><tr><th>Rank</th><th>Pair</th><th>Price (BTC)</th><th>Risk · {filters.horizon} min</th><th>Level · 10 min</th><th>Tier</th><th>Recent trend</th><th>Last observed alert</th></tr></thead><tbody>{visible.map(row => <tr key={row.pair}><td>{rows.findIndex(r => r.pair === row.pair) + 1}</td><td><Link to="/coin/$pair" params={{ pair: row.pair }}>{row.pair}</Link></td><td>{number(marketByPair.get(row.pair)?.price)}</td><td className="number">{percent(row.risk[filters.horizon])}</td><td><Badge level={row.level} /></td><td>{row.tier}</td><td><Sparkline values={row.sparkline ?? []} /></td><td>{sinceAlert(row.pair)}</td></tr>)}</tbody></table></div>}
      </> : <>
        <div className="panel-top"><strong>Experiment B · live 10-minute ranking</strong><span>{scoredModels.length} scored BTC pairs</span></div>
        {modelScores.isPending ? <Loading /> : modelScores.error ? <ErrorState error={modelScores.error} retry={() => void modelScores.refetch()} /> : <>
          <p className="state">{modelScores.data.notice} {modelScores.data.threshold_status}</p>
          {scoredModels.length ? <div className="table-wrap"><table><thead><tr><th>Rank</th><th>BTC pair</th><th>Raw SVM margin</th><th>As of (UTC)</th><th>Provisional alert</th></tr></thead><tbody>{scoredModels.filter(coin => coin.pair.toLowerCase().includes(filters.q.toLowerCase())).map((coin, index) => <tr key={coin.pair}><td>{index + 1}</td><td>{coin.pair}</td><td>{coin.score?.toFixed(4)}</td><td>{utc(coin.as_of)}</td><td>{coin.is_alert ? 'Threshold crossed' : 'No'}</td></tr>)}</tbody></table></div> : <p className="state">{modelScores.data.status === 'unavailable' ? 'Research model unavailable.' : `Waiting for closed minute bars and baseline history across ${modelScores.data.n_tracked_pairs} BTC pairs.`}</p>}
        </>}
        <div className="panel-top"><strong>Public price watch · largest USDT markets by quote volume</strong><span>Ordered by volume, not model rank</span></div>
        {markets.isPending ? <Loading /> : markets.error ? <ErrorState error={markets.error} retry={() => void markets.refetch()} /> : !priceWatch.length ? <p className="state">No USDT markets match this search. Try All Markets.</p> : <div className="table-wrap"><table><thead><tr><th>Pair</th><th>Price (USDT)</th><th>24h change</th><th>24h volume (USDT)</th><th>Raw SVM margin · 10 min</th></tr></thead><tbody>{priceWatch.map(m => <tr key={m.symbol}><td><Link to="/coin/$pair" params={{ pair: m.symbol }}>{m.symbol}</Link></td><td>{number(m.price)}</td><td>{m.change_24h_pct == null ? 'Unavailable' : `${m.change_24h_pct.toFixed(2)}%`}</td><td>{number(m.volume_24h_quote)}</td><td>{modelScoreLabel(m)}</td></tr>)}</tbody></table></div>}
      </>}
    </div>
    {!!recentAlerts.length && <section className="panel"><div className="panel-top"><strong>Recent observed alerts</strong><span>Session history only</span></div><ul className="alert-list">{recentAlerts.slice(0, 5).map(a => <li key={a.id}><Link to="/coin/$pair" params={{ pair: a.pair }}>{a.pair}</Link> · {utc(a.time)}<p>{a.reasons.join(' ')}</p></li>)}</ul></section>}
  </>
}
