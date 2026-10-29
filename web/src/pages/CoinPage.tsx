import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { getCoin, getMarkets, horizons, type Horizon } from '../api/client'
import { Badge, ErrorState, HorizonPicker, Loading, modelScoreLabel, Notice, number, percent, utc } from '../components/ui'
import { PriceChart } from '../components/LazyPriceChart'
import { defaultSearch } from './RadarPage'

export function CoinPage({ pair }: { pair: string }) {
  const [horizon, setHorizon] = useState<Horizon>('10')
  const [range, setRange] = useState<'week' | 'month' | 'year'>('week')
  const query = useQuery({ queryKey: ['coin', pair, range], queryFn: ({ signal }) => getCoin(pair, range, signal), refetchInterval: 30_000, retry: false })
  const data = query.data
  const markets = useQuery({ queryKey: ['markets'], queryFn: ({ signal }) => getMarkets(signal), staleTime: 30_000 })
  const market = markets.data?.markets.find(m => m.symbol === pair) ?? data?.market
  return <><Link to="/" search={defaultSearch}>← Radar</Link><h1>{pair}</h1>
    {query.isPending ? <Loading /> : query.error ? <ErrorState error={query.error} retry={() => void query.refetch()} /> : data && <>
      <Notice mock={data.mock} notice={data.notice} />
      <div className="summary"><div><span>Last price</span><strong>{number(market?.price)} {market?.quote_asset}</strong></div><div><span>24h quote volume</span><strong>{number(market?.volume_24h_quote)} {market?.quote_asset}</strong></div><div><span>{data.mock ? 'Tier / 10-minute level' : 'Raw 10-minute SVM margin'}</span><strong>{data.mock ? data.current?.tier ?? 'Unavailable' : modelScoreLabel(market ?? {})} {data.current && <Badge level={data.current.level} />}</strong>{!data.mock && market?.btc_pair && <small>Model pair: {market.btc_pair}</small>}</div></div>
      {data.mock && <div className="risk-strip">{horizons.map(h => <div key={h}><span>{h} min</span><strong>{percent(data.current?.risk[h])}</strong></div>)}</div>}
      <section className="panel"><div className="panel-top"><strong>{data.mock ? 'Price & risk · last six hours' : `Public price history · ${range}`}</strong>{data.mock ? <HorizonPicker value={horizon} onChange={setHorizon} /> : <label>Range <select aria-label="Price history range" value={range} onChange={e => setRange(e.target.value as 'week' | 'month' | 'year')}><option value="week">Week</option><option value="month">Month</option><option value="year">Year</option></select></label>}</div><PriceChart bars={data.bars} risks={data.risk_series} alerts={data.alerts} horizon={horizon} /></section>
      {(data.mock || data.drivers.length > 0) && <section className="panel padded"><h2>Score drivers</h2><p className="muted">{data.mock ? 'Illustrative values only. These are not model explanations.' : 'Drivers supplied by the scoring engine.'}</p>{data.drivers.length ? data.drivers.map(d => <div className="driver" key={d.label}><span>{d.label}</span><meter aria-label={d.label} min={0} max={Math.max(1, ...data.drivers.map(x => Math.abs(x.value)))} value={Math.abs(d.value)} /><strong>{d.value.toFixed(3)}</strong></div>) : <p>No driver explanations available.</p>}</section>}
      {(data.mock || data.alerts.length > 0) && <section className="panel padded"><h2>Alerts in this response</h2>{data.alerts.length ? <ul>{data.alerts.map(a => <li key={a.id}>{utc(a.time)} · {a.reasons.join(' ')}</li>)}</ul> : <p>No alerts supplied for this window.</p>}</section>}
    </>}
  </>
}
