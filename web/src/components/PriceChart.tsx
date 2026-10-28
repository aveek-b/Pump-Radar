import { useEffect, useRef } from 'react'
import { CandlestickSeries, ColorType, LineSeries, createChart, createSeriesMarkers, type UTCTimestamp } from 'lightweight-charts'
import type { Horizon, Schema } from '../api/client'
import { utc } from './ui'

export function PriceChart({ bars, risks, alerts, horizon, onset }: {
  bars: Schema['Candle'][]; risks: Schema['RiskPoint'][]; alerts: Schema['RiskAlert'][]; horizon: Horizon; onset?: string
}) {
  const host = useRef<HTMLDivElement>(null)
  const marker = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!host.current) return
    const time = (value: string) => Math.floor(Date.parse(value) / 1000) as UTCTimestamp
    const chart = createChart(host.current, {
      autoSize: true, height: 380,
      layout: { background: { type: ColorType.Solid, color: '#12151a' }, textColor: '#a1adbb', attributionLogo: true },
      grid: { vertLines: { color: '#1f242c' }, horzLines: { color: '#1f242c' } },
      timeScale: { timeVisible: true, secondsVisible: false },
    })
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: '#5b9bff', downColor: '#e9c479', wickUpColor: '#5b9bff', wickDownColor: '#e9c479', borderVisible: false,
      priceFormat: { type: 'price', precision: 8, minMove: 0.00000001 },
    })
    // Never invent OHLC values when an artifact only supplies a close.
    candles.setData(bars.filter(b => b.open != null && b.high != null && b.low != null).map(b => ({ time: time(b.time), open: b.open!, high: b.high!, low: b.low!, close: b.close })))
    const line = chart.addSeries(LineSeries, { color: '#ed9f60', priceScaleId: 'left', title: `Risk ${horizon}m`, priceFormat: { type: 'percent' } })
    line.setData(risks.filter(p => p.risk[horizon] != null).map(p => ({ time: time(p.time), value: p.risk[horizon]! * 100 })))
    const candleTimes = new Set(bars.map(b => time(b.time)))
    createSeriesMarkers(candles, alerts.map(a => ({ time: Math.floor(time(a.time) / 60) * 60 as UTCTimestamp, position: 'aboveBar' as const, color: '#f17878', shape: 'arrowDown' as const, text: 'Alert' })).filter(m => candleTimes.has(m.time)).sort((a, b) => a.time - b.time))
    chart.timeScale().fitContent()
    const positionOnset = () => {
      if (!marker.current || !onset) return
      const x = chart.timeScale().timeToCoordinate(time(onset))
      marker.current.style.display = x == null ? 'none' : 'block'
      marker.current.style.left = `${x ?? 0}px`
    }
    chart.timeScale().subscribeVisibleLogicalRangeChange(positionOnset)
    const observer = new ResizeObserver(positionOnset)
    observer.observe(host.current)
    positionOnset()
    return () => { observer.disconnect(); chart.remove() }
  }, [bars, risks, alerts, horizon, onset])
  return <figure className="chart-figure"><div className="chart-container"><div ref={host} className="chart" role="img" aria-label={`Candlestick price chart and ${horizon}-minute risk series`} />{onset && <div ref={marker} className="onset-marker"><span>Onset</span></div>}</div><figcaption>Price: right scale · risk: left scale · times in UTC. {bars.length} bars, {utc(bars[0]?.time)} to {utc(bars.at(-1)?.time)}. <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">Charts by TradingView</a></figcaption></figure>
}
