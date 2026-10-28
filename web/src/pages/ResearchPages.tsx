import { useQuery } from '@tanstack/react-query'
import { getHonesty } from '../api/client'
import { ErrorState, Loading, Notice, number, percent } from '../components/ui'

export function HonestyPage() {
  const query = useQuery({ queryKey: ['honesty'], queryFn: ({ signal }) => getHonesty(signal) })
  const data = query.data
  return <><div className="eyebrow">EVALUATION & LIMITATIONS</div><h1>Honesty</h1><p className="intro">A useful warning needs an independently measured error rate.</p>
    {query.isPending ? <Loading /> : query.error ? <ErrorState error={query.error} retry={() => void query.refetch()} /> : data && <>
      <Notice mock={data.mock} notice={data.notice} />
      <div className="summary"><div><span>Precision</span><strong>{percent(data.precision)}</strong></div><div><span>Recall</span><strong>{percent(data.recall)}</strong></div><div><span>Median lead (minutes)</span><strong>{number(data.median_lead_minutes)}</strong></div><div><span>Hit@5</span><strong>{percent(data.hit_at_5)}</strong></div></div>
      <section className="panel padded"><h2>False alerts per hour vs budget</h2>{data.false_alerts_per_hour == null || data.alert_budget_per_hour == null ? <p>Not measured yet. Synthetic alerts and session counts are not evidence of a false-alert guarantee.</p> : <><p>Measured: {number(data.false_alerts_per_hour)} / hour · Budget: {number(data.alert_budget_per_hour)} / hour</p><meter aria-label="Measured false alerts per hour" min={0} max={Math.max(1, data.false_alerts_per_hour, data.alert_budget_per_hour)} value={data.false_alerts_per_hour} /></>}</section>
      <section className="panel padded"><h2>Coverage</h2><p>Training-era median and real monitored-universe coverage are awaiting the research and engine handoffs. The 60 mock coins are not live coverage.</p></section>
      <section className="panel padded"><h2>Current limitations</h2><ul>{data.limitations.map(item => <li key={item}>{item}</li>)}</ul></section>
    </>}
  </>
}

export function MethodPage() {
  return <><div className="eyebrow">RESEARCH DESIGN</div><h1>Method</h1><p className="intro">How early can we detect unusual activity, and which coin should we examine?</p>
    <div className="notice"><strong>PLANNED METHOD</strong> This describes the build guide’s research design. The evaluated model, result figures and final paper have not been integrated.</div>
    <section className="panel padded prose"><h2>Start the clock at market onset</h2><p>The planned features compare buying volume, total volume, trade count and returns with each coin’s earlier baseline and with other coins at the same minute. Warning lead is measured before market onset, which can precede a Telegram announcement. Cases without a confirmed onset must retain their uncertainty.</p>
      <h2>Keep whole events together</h2><p>The leakage audit compares a random split with an event-grouped chronological split and a 24-hour gap. The cross-sectional experiment ranks coins together at horizons of 1, 3, 5, 10, 30 and 60 minutes. The same feature function and ordered feature list must be used offline and in the running app.</p>
      <h2>Evaluate at an alert budget</h2><p>The final threshold comes from validation data. Held-out reporting will include precision, recall, warning lead, Hit@5 and false alerts per hour. Replay must use test-era events scored by the frozen model. Current mock scores and the retained volume heuristic have no calibrated probability interpretation.</p>
    </section>
    <section className="panel padded"><h2>Figures and paper</h2><p>The lead-time curve, leakage-inflation figure and final paper link will appear after the research results are frozen. No illustrative result is presented as a measurement.</p></section>
    <section className="panel padded"><h2>Scope</h2><p>The planned historical evaluation covers Binance events from 2018–2021. Event lists can be incomplete; later-era and leave-coin-out tests remain future work. Scores are designed for minute bars, while prices can update every two seconds. No trades are placed.</p></section>
  </>
}
