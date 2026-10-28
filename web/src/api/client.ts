import type { components } from './types'

export type Schema = components['schemas']
export type RadarResponse = Schema['RadarResponse']
export type PricesEvent = Schema['PricesEvent']
export type RadarTick = Schema['RadarTick']
export type Horizon = '1' | '3' | '5' | '10' | '30' | '60'
export const horizons: Horizon[] = ['1', '3', '5', '10', '30', '60']
const base = (import.meta.env.VITE_API_URL ?? '/api').replace(/\/$/, '')

export function openStream(): EventSource {
  return new EventSource(`${base}/stream`)
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${base}${path}`, { signal })
  if (!response.ok) throw new Error(`Request failed (${response.status}). ${response.status === 503 ? 'Real engine integration is pending.' : 'Please retry.'}`)
  return response.json() as Promise<T>
}

export const getRadar = (signal?: AbortSignal) => get<RadarResponse>('/radar', signal)
export const getMarkets = (signal?: AbortSignal) => get<Schema['MarketsResponse']>('/markets', signal)
export const getCoin = (pair: string, signal?: AbortSignal) => get<Schema['CoinResponse']>(`/coin/${encodeURIComponent(pair)}`, signal)
export const getReplayEvents = (signal?: AbortSignal) => get<Schema['ReplayEventsResponse']>('/replay/events', signal)
export const getReplay = (id: string, signal?: AbortSignal) => get<Schema['ReplayDetailResponse']>(`/replay/${encodeURIComponent(id)}`, signal)
export const getHonesty = (signal?: AbortSignal) => get<Schema['HonestyResponse']>('/honesty', signal)
