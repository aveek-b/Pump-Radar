import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { openStream, type PricesEvent, type RadarResponse, type RadarTick } from './client'

export function useLiveTicks() {
  const cache = useQueryClient()
  const [prices, setPrices] = useState<PricesEvent | null>(null)
  const [status, setStatus] = useState('Connecting')
  const [alertCount, setAlertCount] = useState(0)

  useEffect(() => {
    const stream = openStream()
    stream.onopen = () => setStatus('Connected')
    stream.onerror = () => setStatus('Reconnecting — showing last received data')
    stream.addEventListener('prices', event => {
      try {
        setPrices(JSON.parse((event as MessageEvent).data) as PricesEvent)
      } catch {
        setStatus('Invalid price event')
      }
    })
    stream.addEventListener('tick', event => {
      try {
        const tick = JSON.parse((event as MessageEvent).data) as RadarTick
        cache.setQueryData<RadarResponse>(['radar'], {
          scorer: tick.scorer, mock: tick.mock, notice: tick.notice,
          model_version: tick.model_version, sequence: tick.sequence,
          minute: tick.as_of, rows: tick.rows, coins: [],
        })
        setAlertCount(tick.newAlerts.length)
      } catch {
        setStatus('Invalid scoring event')
      }
    })
    return () => stream.close()
  }, [cache])

  return { prices, status, alertCount }
}
