import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { experimentAFigure, getExperimentA, getExperimentB, getHonesty, getMarkets } from '../api/client'
import { ErrorState, Loading, Notice, number, percent, utc } from '../components/ui'

function AuditTable() {
  const query = useQuery({ queryKey: ['experiment-a'], queryFn: ({ signal }) => getExperimentA(signal) })
  const [horizon, setHorizon] = useState(10)
  const [features, setFeatures] = useState<'clean' | 'full'>('full')
  if (query.isPending) return <Loading />
  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  const audit = query.data
  const points = audit.points.filter(p => p.horizon_min === horizon && p.feature_set === features)
    .sort((a, b) => (b.honest_ap ?? -1) - (a.honest_ap ?? -1))
  return <section className="panel padded">
    <h2>Historical Experiment A · leakage audit</h2>
    <p>{audit.notice}</p>
    <div className="controls">
      <label>Warning horizon <select aria-label="Audit horizon" value={horizon} onChange={e => setHorizon(Number(e.target.value))}>{[1, 3, 5, 10, 30, 60].map(h => <option key={h} value={h}>{h} min</option>)}</select></label>
      <label>Feature set <select aria-label="Audit feature set" value={features} onChange={e => setFeatures(e.target.value as 'clean' | 'full')}><option value="full">Full</option><option value="clean">Clean</option></select></label>
    </div>
    <p className="muted">Average precision (AP) summarizes ranking quality on historical 25-second chunks. Inflation is random-split AP minus event-grouped chronological AP; it is not a live risk score. Confidence intervals are available at 10 minutes only.</p>
    <div className="table-wrap"><table><thead><tr><th>Model</th><th>Honest AP</th><th>Random AP</th><th>Inflation</th><th>Honest 95% CI</th><th>Honest prevalence</th></tr></thead><tbody>{points.map(p => <tr key={p.model}><td>{p.model.replaceAll('_', ' ')}</td><td>{p.honest_ap?.toFixed(3) ?? 'Unavailable'}</td><td>{p.random_ap?.toFixed(3) ?? 'Unavailable'}</td><td>{p.inflation_ap == null ? 'Unavailable' : `${p.inflation_ap >= 0 ? '+' : ''}${p.inflation_ap.toFixed(3)}`}</td><td>{p.honest_ci_low == null || p.honest_ci_high == null ? 'Not measured at this horizon' : `[${p.honest_ci_low.toFixed(3)}, ${p.honest_ci_high.toFixed(3)}]`}</td><td>{percent(p.honest_prevalence)}</td></tr>)}</tbody></table></div>
    <p className="muted">Source: Kaashvi’s commit <code>{audit.source_commit}</code> · {audit.source_artifacts.join(', ')}</p>
    <ul>{audit.limitations.map(item => <li key={item}>{item}</li>)}</ul>
  </section>
}

function ExperimentBTable() {
  const query = useQuery({ queryKey: ['experiment-b'], queryFn: ({ signal }) => getExperimentB(signal) })
  const [horizon, setHorizon] = useState(10)
  if (query.isPending) return <Loading />
  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  const result = query.data
  const points = result.points.filter(p => p.horizon_min === horizon).sort((a, b) => (b.test_ap ?? -1) - (a.test_ap ?? -1))
  return <section className="panel padded">
    <h2>Historical Experiment B · cross-sectional ranking</h2>
    <p>{result.notice}</p>
    <p>Validation selected <strong>{result.selected_model.replaceAll('_', ' ')}</strong> at {result.selection_horizon_min} minutes. The table shows held-out test results for all evaluated models.</p>
    <label>Warning horizon <select aria-label="Experiment B horizon" value={horizon} onChange={e => setHorizon(Number(e.target.value))}>{[1, 3, 5, 10, 30, 60].map(h => <option key={h} value={h}>{h} min</option>)}</select></label>
    <div className="table-wrap"><table><thead><tr><th>Model</th><th>Test AP</th><th>Prevalence</th><th>Hit@5</th><th>Test events</th></tr></thead><tbody>{points.map(p => <tr key={p.model}><td>{p.model.replaceAll('_', ' ')}{p.model === result.selected_model && horizon === result.selection_horizon_min ? ' · selected' : ''}</td><td>{p.test_ap?.toFixed(5) ?? 'Unavailable'}</td><td>{percent(p.test_prevalence)}</td><td>{percent(p.hit_at_5)}</td><td>{p.n_test_events}</td></tr>)}</tbody></table></div>
    <p className="muted">Source: commit {result.source_commit} · {result.source_artifacts.join(', ')}</p>
    <ul>{result.limitations.map(item => <li key={item}>{item}</li>)}</ul>
  </section>
}

export function HonestyPage() {
  const query = useQuery({ queryKey: ['honesty'], queryFn: ({ signal }) => getHonesty(signal) })
  const markets = useQuery({ queryKey: ['markets'], queryFn: ({ signal }) => getMarkets(signal), refetchInterval: 30_000 })
  const data = query.data
  return <><div className="eyebrow">EVALUATION & LIMITATIONS</div><h1>Honesty</h1><p className="intro">The live alert budget and historical leakage audit answer different questions.</p>
    {query.isPending ? <Loading /> : query.error ? <ErrorState error={query.error} retry={() => void query.refetch()} /> : data && <>
      <Notice mock={data.mock} notice={data.notice} />
      <div className="summary"><div><span>Live-model precision</span><strong>{percent(data.precision)}</strong></div><div><span>Live-model recall</span><strong>{percent(data.recall)}</strong></div><div><span>Median warning lead (minutes)</span><strong>{number(data.median_lead_minutes)}</strong></div><div><span>Cross-sectional Hit@5</span><strong>{percent(data.hit_at_5)}</strong></div></div>
      <section className="panel padded"><h2>False alerts per hour vs budget</h2>{data.false_alerts_per_hour == null || data.alert_budget_per_hour == null ? <p>Not measured yet. Synthetic alerts and session counts are not evidence of a false-alert guarantee.</p> : <><p>Measured: {number(data.false_alerts_per_hour)} / hour · Budget: {number(data.alert_budget_per_hour)} / hour</p><meter aria-label="Measured false alerts per hour" min={0} max={Math.max(1, data.false_alerts_per_hour, data.alert_budget_per_hour)} value={data.false_alerts_per_hour} /></>}</section>
      <AuditTable />
      <ExperimentBTable />
      <section className="panel padded"><h2>Market coverage and model status</h2>{markets.isPending ? <Loading /> : markets.error ? <ErrorState error={markets.error} retry={() => void markets.refetch()} /> : <><div className="summary"><div><span>{markets.data.mock ? 'Synthetic fixture markets' : 'Public markets with prices'}</span><strong>{markets.data.markets.length}</strong></div><div><span>Markets scored by research model</span><strong>{markets.data.mock ? 'Unavailable in mock mode' : markets.data.markets.filter(m => m.scored).length}</strong></div><div><span>{markets.data.mock ? 'Synthetic price time' : 'Price snapshot time'}</span><strong className="timestamp">{utc(markets.data.as_of)}</strong></div></div><p>{markets.data.mock ? 'The 60 scored mock pairs are fixtures, not live model coverage.' : 'Real prices and raw SVM ranking margins are separate from calibrated probabilities and live alert performance. A score appears only after the BTC pair has enough closed minute bars; the provisional threshold has no validated live false-alert rate.'}</p></>}</section>
      <section className="panel padded"><h2>Current limitations</h2><ul>{data.limitations.map(item => <li key={item}>{item}</li>)}</ul></section>
    </>}
  </>
}

export function MethodPage() {
  const audit = useQuery({ queryKey: ['experiment-a'], queryFn: ({ signal }) => getExperimentA(signal) })
  return <><div className="eyebrow">RESEARCH DESIGN</div><h1>Method</h1><p className="intro">How early can we detect unusual activity, and which coin should we examine?</p>
    <div className="notice"><strong>RESEARCH STATUS</strong> Experiments A and B have historical results. A frozen Experiment B model can rank live BTC pairs using raw SVM margins after minute-bar history is loaded. The threshold is provisional, and live alert performance has not been measured.</div>
    <ExperimentBTable />
    <section className="panel padded prose"><h2>Start the clock at market onset</h2><p>The planned live features compare buying volume, total volume, trade count and returns with each coin’s earlier baseline and with other coins at the same minute. Warning lead is measured before market onset, which can precede a Telegram announcement. Cases without a confirmed onset retain their uncertainty.</p>
      <h2>Keep whole events together</h2><p>Experiment A compares random splits with an event-grouped chronological split and a 24-hour gap. Its Sapienza chunk features are separate from the planned live minute-bar features. The future cross-sectional experiment ranks coins together at horizons of 1, 3, 5, 10, 30 and 60 minutes.</p>
      <h2>Evaluate at an alert budget</h2><p>The final threshold must come from validation data. Held-out reporting will include precision, recall, warning lead, Hit@5 and false alerts per hour. Current mock scores and the retained volume heuristic have no calibrated probability interpretation.</p>
    </section>
    <section className="panel padded"><h2>Measured Experiment A figures</h2><p>These figures are present in Kaashvi’s commit a434e86 and describe historical average precision and prevalence. They do not evaluate the live dashboard.</p><img className="research-figure" src={experimentAFigure('inflation_by_horizon.png')} alt="Historical Experiment A: random minus honest average precision across warning horizons" /><img className="research-figure" src={experimentAFigure('prevalence_by_horizon.png')} alt="Historical Experiment A: positive prevalence by warning horizon" /><p className="muted">Source: results/figures/inflation_by_horizon.png and results/figures/prevalence_by_horizon.png. The cross-sectional lead-time curve and final paper link still await the research handoff.</p></section>
    <section className="panel padded"><h2>Historical feature importance</h2><p>Permutation importance for the honest-split LightGBM model at 10 minutes, measured as change in average precision. These are not explanations of current dashboard scores.</p>{audit.isPending ? <Loading /> : audit.error ? <ErrorState error={audit.error} retry={() => void audit.refetch()} /> : <div className="table-wrap"><table><thead><tr><th>Full feature set</th><th>Mean AP change</th><th>Std. dev.</th></tr></thead><tbody>{audit.data.importance_by_feature_set.full.slice(0, 5).map(item => <tr key={item.feature}><td>{item.feature.replaceAll('_', ' ')}</td><td>{item.importance_mean.toFixed(3)}</td><td>{item.importance_std.toFixed(3)}</td></tr>)}</tbody></table></div>}</section>
    <section className="panel padded"><h2>Scope</h2><p>The planned historical evaluation covers Binance events from 2018–2021. Event lists can be incomplete; later-era and leave-coin-out tests remain future work. Scores are designed for minute bars, while prices may update separately. No trades are placed.</p></section>
  </>
}
