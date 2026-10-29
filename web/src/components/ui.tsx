import { horizons, type Horizon } from '../api/client'

export function utc(value?: string | number | null) {
  return value == null ? 'Unavailable' : new Date(value).toISOString().replace('T', ' ').slice(0, 19) + ' UTC'
}
export const percent = (value?: number | null) => value == null ? 'Unavailable' : `${(value * 100).toFixed(1)}%`
export const number = (value?: number | null) => value == null ? 'Unavailable' : value.toLocaleString('en', { maximumFractionDigits: 8 })
export function modelScoreLabel(market: { model_score?: number | null; model_status?: string | null }) {
  if (market.model_score != null) return market.model_score.toFixed(4)
  switch (market.model_status) {
    case 'no_btc_pair': return 'No BTC model pair'
    case 'warming_up': return 'Waiting for minute bars'
    case 'model_unavailable': return 'Model not loaded'
    default: return 'Not scored'
  }
}

export function HorizonPicker({ value, onChange }: { value: Horizon; onChange: (h: Horizon) => void }) {
  return <label>Horizon <select aria-label="Horizon" value={value} onChange={e => onChange(e.target.value as Horizon)}>{horizons.map(h => <option key={h} value={h}>{h} min</option>)}</select></label>
}
export function Badge({ level }: { level: string }) { return <span className={`badge ${level.toLowerCase()}`}>{level}</span> }
export function Notice({ mock, notice }: { mock: boolean; notice: string }) {
  return <div className="notice" role="note"><strong>{mock ? 'SYNTHETIC PREVIEW' : 'RESEARCH DEMO'}</strong> {notice}</div>
}
export function ErrorState({ error, retry }: { error: Error; retry: () => void }) {
  return <div className="state" role="alert"><p>{error.message}</p><button onClick={retry}>Retry</button></div>
}
export function Loading() { return <div className="state skeleton" role="status">Loading data…</div> }
export function Sparkline({ values }: { values: number[] }) {
  if (!values.length) return <span>Unavailable</span>
  return <svg className="sparkline" viewBox="0 0 100 30" role="img" aria-label="Recent risk trend"><polyline fill="none" stroke="currentColor" strokeWidth="2" points={values.map((v, i) => `${i * 100 / Math.max(1, values.length - 1)},${29 - v * 28}`).join(' ')} /></svg>
}
