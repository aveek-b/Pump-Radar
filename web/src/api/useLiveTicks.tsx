import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { openStream, type Schema, type PricesEvent, type RadarResponse, type RadarTick } from './client'

type LiveState = { status: string; lastReceived: number | null; alerts: Schema['RiskAlert'][]; notification: string; enableAlerts: () => Promise<void> }
const LiveContext = createContext<LiveState | null>(null)

export function LiveProvider({ children }: { children: ReactNode }) {
  const cache = useQueryClient()
  const [status, setStatus] = useState('Connecting')
  const [lastReceived, setLastReceived] = useState<number | null>(null)
  const [alerts, setAlerts] = useState<Schema['RiskAlert'][]>([])
  const [notification, setNotification] = useState('Enable alerts')
  const notifyEnabled = useRef(false)
  const seen = useRef(new Set<string>())

  async function enableAlerts() {
    if (!('Notification' in window)) { setNotification('Notifications unsupported'); return }
    try {
      const permission = await Notification.requestPermission()
      notifyEnabled.current = permission === 'granted'
      setNotification(permission === 'granted' ? 'Alerts enabled' : 'Notifications not enabled')
    } catch { setNotification('Notifications unavailable') }
  }

  useEffect(() => {
    const stream = openStream()
    let received = 0
    let receivedTick = 0
    let started = Date.now()
    let firstTick = true
    let lastPriceSequence = -1
    let lastTickSequence = -1
    let scoreTimeout = 25_000
    let transportOpen = false
    const updateStatus = () => {
      if (!transportOpen) setStatus('Reconnecting — showing last received data')
      else if (Date.now() - (received || started) > 15_000) setStatus('Feed unavailable — showing last received data')
      else if (Date.now() - (receivedTick || started) > scoreTimeout) setStatus('Scores delayed — prices still updating')
      else setStatus(received ? 'Connected' : 'Connected — waiting for data')
    }
    stream.onopen = () => {
      transportOpen = true
      setStatus('Connected — waiting for data')
      firstTick = true
      lastPriceSequence = lastTickSequence = -1
      received = receivedTick = 0
      started = Date.now()
    }
    stream.onerror = () => { transportOpen = false; updateStatus() }
    stream.addEventListener('prices', event => {
      try {
        const data = JSON.parse((event as MessageEvent).data) as PricesEvent
        if (!Array.isArray(data.markets) || !Number.isFinite(data.sequence)) throw new Error()
        if (data.sequence <= lastPriceSequence) return
        lastPriceSequence = data.sequence
        received = Date.now()
        setLastReceived(received)
        updateStatus()
        cache.setQueryData<Schema['MarketsResponse']>(['markets'], data)
      } catch { setStatus('Invalid price event — showing last received data') }
    })
    stream.addEventListener('tick', event => {
      try {
        const tick = JSON.parse((event as MessageEvent).data) as RadarTick
        if (!Array.isArray(tick.rows) || !Array.isArray(tick.newAlerts) || !Number.isFinite(tick.sequence)) throw new Error()
        if (tick.sequence <= lastTickSequence) return
        lastTickSequence = tick.sequence
        receivedTick = Date.now()
        scoreTimeout = tick.mock ? 25_000 : 90_000
        updateStatus()
        cache.setQueryData<RadarResponse>(['radar'], {
          scorer: tick.scorer, mock: tick.mock, notice: tick.notice,
          model_version: tick.model_version, sequence: tick.sequence,
          minute: tick.as_of, rows: tick.rows, coins: [],
        })
        const fresh = tick.newAlerts.filter(alert => !seen.current.has(alert.id))
        for (const alert of fresh) {
          seen.current.add(alert.id)
          if (seen.current.size > 5000) seen.current.delete(seen.current.values().next().value!)
          // Reconnect delivers a current snapshot, not a backlog of new alerts.
          if (firstTick) continue
          const title = `${alert.mock ? 'Synthetic alert' : 'Alert'}: ${alert.pair}`
          toast.warning(title, { id: alert.id, description: alert.reasons.join(' ') })
          if (notifyEnabled.current && 'Notification' in window && Notification.permission === 'granted') {
            try { new Notification(title, { body: alert.reasons.join(' '), tag: alert.id }) } catch { /* Toast remains available. */ }
          }
        }
        setAlerts(previous => {
          const cutoff = Date.parse(tick.as_of) - 3600_000
          return [...fresh, ...previous].filter(a => Date.parse(a.time) >= cutoff && Date.parse(a.time) <= Date.parse(tick.as_of)).slice(0, 5000)
        })
        firstTick = false
      } catch { setStatus('Invalid scoring event — showing last received data') }
    })
    const watchdog = window.setInterval(updateStatus, 5000)
    return () => { stream.close(); window.clearInterval(watchdog) }
  }, [cache])
  return <LiveContext.Provider value={{ status, lastReceived, alerts, notification, enableAlerts }}>{children}</LiveContext.Provider>
}

export function useLiveTicks() {
  const live = useContext(LiveContext)
  if (!live) throw new Error('LiveProvider is required')
  return live
}
