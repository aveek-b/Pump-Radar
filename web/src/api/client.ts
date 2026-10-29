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
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Request failed (${response.status}). Please retry.`)
  }
  return response.json() as Promise<T>
}

export const getRadar = (signal?: AbortSignal) => get<RadarResponse>('/radar', signal)
export const getHealth = (signal?: AbortSignal) => get<Schema['HealthResponse']>('/health', signal)
export const getMarkets = (signal?: AbortSignal) => get<Schema['MarketsResponse']>('/markets', signal)
export const getCoin = (pair: string, range: 'week' | 'month' | 'year' = 'week', signal?: AbortSignal) => get<Schema['CoinResponse']>(`/coin/${encodeURIComponent(pair)}?range=${range}`, signal)
export const getReplayEvents = (signal?: AbortSignal) => get<Schema['ReplayEventsResponse']>('/replay/events', signal)
export const getReplay = (id: string, signal?: AbortSignal) => get<Schema['ReplayDetailResponse']>(`/replay/${encodeURIComponent(id)}`, signal)
export const getHonesty = (signal?: AbortSignal) => get<Schema['HonestyResponse']>('/honesty', signal)
export const getExperimentA = (signal?: AbortSignal) => get<Schema['ExperimentAResponse']>('/research/experiment-a', signal)
export const getExperimentB = (signal?: AbortSignal) => get<Schema['ExperimentBResponse']>('/research/experiment-b', signal)
export const getLiveScores = (signal?: AbortSignal) => get<Schema['LiveModelScoresResponse']>('/scores/live', signal)
export const experimentAFigure = (name: 'inflation_by_horizon.png' | 'prevalence_by_horizon.png') => `${base}/research/experiment-a/figures/${name}`
