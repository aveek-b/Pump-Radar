import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getReplay, getReplayEvents, type Horizon, type Schema } from '../api/client'
import { Badge, ErrorState, HorizonPicker, Loading, Notice, percent, utc } from '../components/ui'
import { PriceChart } from '../components/LazyPriceChart'

function lead(event: Schema['ReplayEvent']) {
  if (event.era === 'mock') return 'Not evaluated'
  return event.first_alert_lead_minutes == null ? 'Unavailable / not reported' : `${event.first_alert_lead_minutes.toFixed(1)} min`
}

export function ReplayPage() {
  const events = useQuery({ queryKey: ['replay-events'], queryFn: ({ signal }) => getReplayEvents(signal) })
  const [selected, setSelected] = useState('')
  const id = selected || events.data?.events[0]?.event_id || ''
  return <><div className="eyebrow">HISTORICAL PLAYBACK</div><h1>Replay</h1><p className="intro">Watch the ranking unfold through time. Synthetic examples are separate from held-out evaluation.</p>
    {events.isPending ? <Loading /> : events.error ? <ErrorState error={events.error} retry={() => void events.refetch()} /> : events.data && <>
      <Notice mock={events.data.mock} notice={events.data.notice} />
      <section className="panel"><div className="panel-top"><strong>{events.data.mock ? 'Synthetic examples' : 'Held-out event scoreboard'}</strong><span>{events.data.events.length} events</span></div>
        <p className="state">{events.data.mock ? 'Catch rate and median lead are not evaluated for fixtures.' : 'Aggregate catch rate requires an explicit evaluated/missed status from the research handoff. Missing metrics are not counted as misses.'}</p>
        {events.data.events.length ? <div className="table-wrap"><table><thead><tr><th>Onset (UTC)</th><th>Pair</th><th>Era</th><th>Warning lead</th><th>Rank at onset</th><th>Playback</th></tr></thead><tbody>{events.data.events.map(event => <tr key={event.event_id}><td>{utc(event.t_onset)}</td><td>{event.pair}</td><td>{event.era}</td><td>{lead(event)}</td><td>{event.rank_at_onset ?? 'Unavailable'}</td><td><button onClick={() => setSelected(event.event_id)}>Open {event.event_id}</button></td></tr>)}</tbody></table></div> : <p className="state">No held-out replay files are available yet.</p>}
      </section>
      {!!events.data.events.length && <><label className="event-picker">Event <select value={id} onChange={e => setSelected(e.target.value)}>{events.data.events.map(event => <option key={event.event_id} value={event.event_id}>{event.pair} · {utc(event.t_onset)} · {event.era}</option>)}</select></label><ReplayLoader key={id} id={id} /></>}
    </>}
  </>
}

function ReplayLoader({ id }: { id: string }) {
  const query = useQuery({ queryKey: ['replay', id], queryFn: ({ signal }) => getReplay(id, signal), staleTime: Infinity })
  if (query.isPending) return <Loading />
  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  return <ReplayPlayer data={query.data} />
}

function ReplayPlayer({ data }: { data: Schema['ReplayDetailResponse'] }) {
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [horizon, setHorizon] = useState<Horizon>('10')
  const frames = data.frames
  useEffect(() => {
    if (!playing || index >= frames.length - 1) return
    const delay = Math.max(16, (Date.parse(frames[index + 1].as_of) - Date.parse(frames[index].as_of)) / speed)
    const timer = window.setTimeout(() => {
      setIndex(i => i + 1)
      if (index + 1 >= frames.length - 1) setPlaying(false)
    }, delay)
    return () => window.clearTimeout(timer)
  }, [playing, index, speed, frames])
  const frame = frames[index]
  const history = useMemo(() => {
    const revealed = frames.slice(0, index + 1)
    return {
      bars: data.bars.filter(b => Date.parse(b.time) <= Date.parse(frame?.as_of ?? '')),
      risks: revealed.flatMap(f => { const row = f.rows.find(r => r.pair === data.event.pair); return row ? [{ time: f.as_of, risk: row.risk }] : [] }),
      alerts: [...new Map(revealed.flatMap(f => f.newAlerts).filter(a => a.pair === data.event.pair).map(a => [a.id, a])).values()],
    }
  }, [data, frames, index, frame])
  if (!frame) return <p className="state">This event contains no playback frames.</p>
  const ranking = [...frame.rows].sort((a, b) => (b.risk[horizon] ?? -1) - (a.risk[horizon] ?? -1) || a.pair.localeCompare(b.pair))
  const rank = ranking.findIndex(r => r.pair === data.event.pair) + 1
  const start = Date.parse(frames[0].as_of)
  const end = Date.parse(frames.at(-1)!.as_of)
  const onset = (Date.parse(data.event.t_onset) - start) / Math.max(1, end - start) * 100
  return <section className="panel padded">
    <h2>{data.event.pair} · {data.mock ? 'synthetic playback' : 'held-out playback'}</h2>
    <div className="controls"><button disabled={frames.length < 2} onClick={() => { if (index === frames.length - 1) setIndex(0); setPlaying(!playing) }}>{playing ? 'Pause' : index === frames.length - 1 ? 'Restart' : 'Play'}</button><label>Speed <select aria-label="Speed" value={speed} onChange={e => setSpeed(Number(e.target.value))}>{[1, 4, 16].map(s => <option key={s} value={s}>{s}×</option>)}</select></label><HorizonPicker value={horizon} onChange={setHorizon} /><output aria-live="polite">Frame {index + 1} / {frames.length}{index === frames.length - 1 ? ' · Playback complete' : ''}</output></div>
    <div className="scrubber"><input aria-label="Replay time" type="range" min={0} max={frames.length - 1} value={index} onChange={e => { setPlaying(false); setIndex(Number(e.target.value)) }} />{onset >= 0 && onset <= 100 && <span className="scrubber-onset" style={{ left: `${onset}%` }}>Onset</span>}</div>
    <p>{utc(frame.as_of)} · Onset: {utc(data.event.t_onset)}</p>
    <div className="summary"><div><span>Current rank · {horizon} min</span><strong>{rank ? `${rank} of ${ranking.length}` : 'Not scored'}</strong></div><div><span>Reported first-alert lead</span><strong>{lead(data.event)}</strong></div><div><span>Reported rank at onset</span><strong>{data.event.rank_at_onset ?? 'Unavailable'}</strong></div></div>
    <PriceChart bars={history.bars} risks={history.risks} alerts={history.alerts} horizon={horizon} onset={data.event.t_onset} />
    <div className="table-wrap"><table><thead><tr><th>Rank</th><th>Pair</th><th>Risk · {horizon} min</th><th>Level · 10 min</th></tr></thead><tbody>{ranking.map((row, i) => <tr key={row.pair} className={row.pair === data.event.pair ? 'highlight' : ''}><td>{i + 1}</td><td>{row.pair}{row.pair === data.event.pair ? ' · event coin' : ''}</td><td>{percent(row.risk[horizon])}</td><td><Badge level={row.level} /></td></tr>)}</tbody></table></div>
  </section>
}
