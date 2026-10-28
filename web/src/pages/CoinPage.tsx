import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { getCoin, getMarkets, horizons, type Horizon } from '../api/client'
import { Badge, ErrorState, HorizonPicker, Loading, Notice, number, percent, utc } from '../components/ui'
import { PriceChart } from '../components/LazyPriceChart'
import { defaultSearch } from './RadarPage'

export function CoinPage({ pair }: { pair: string }) {
  const [horizon, setHorizon] = useState<Horizon>('10')
  const query = useQuery({ queryKey: ['coin', pair], queryFn: ({ signal }) => getCoin(pair, signal), refetchInterval: 10_000, retry: false })
  const data = query.data
  const markets = useQuery({ queryKey: ['markets'], queryFn: ({ signal }) => getMarkets(signal), staleTime: 30_000 })
  const market = markets.data?.markets.find(m => m.symbol === pair) ?? data?.market
  return <><Link to="/" search={defaultSearch}>← Radar</Link><h1>{pair}</h1>
    {query.isPending ? <Loading /> : query.error ? <ErrorState error={query.error} retry={() => void query.refetch()} /> : data && <>
      <Notice mock={data.mock} notice={data.notice} />
      <div className="summary"><div><span>Last price</span><strong>{number(market?.price)} {market?.quote_asset}</strong></div><div><span>24h quote volume</span><strong>{number(market?.volume_24h_quote)} {market?.quote_asset}</strong></div><div><span>Tier / 10-minute level</span><strong>{data.current?.tier ?? 'Unavailable'} {data.current && <Badge level={data.current.level} />}</strong></div></div>
      <div className="risk-strip">{horizons.map(h => <div key={h}><span>{h} min</span><strong>{percent(data.current?.risk[h])}</strong></div>)}</div>
      <section className="panel"><div className="panel-top"><strong>Price & risk · last six hours</strong><HorizonPicker value={horizon} onChange={setHorizon} /></div><PriceChart bars={data.bars} risks={data.risk_series} alerts={data.alerts} horizon={horizon} /></section>
      <section className="panel padded"><h2>Score drivers</h2><p className="muted">{data.mock ? 'Illustrative values only. These are not model explanations.' : 'Drivers supplied by the scoring engine.'}</p>{data.drivers.length ? data.drivers.map(d => <div className="driver" key={d.label}><span>{d.label}</span><meter aria-label={d.label} min={0} max={Math.max(1, ...data.drivers.map(x => Math.abs(x.value)))} value={Math.abs(d.value)} /><strong>{d.value.toFixed(3)}</strong></div>) : <p>No driver explanations available.</p>}</section>
      <section className="panel padded"><h2>Alerts in this response</h2>{data.alerts.length ? <ul>{data.alerts.map(a => <li key={a.id}>{utc(a.time)} · {a.reasons.join(' ')}</li>)}</ul> : <p>No alerts supplied for this window.</p>}</section>
    </>}
  </>
}
