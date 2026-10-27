import type { components } from './types'

export type RadarResponse = components['schemas']['RadarResponse']
export type PricesEvent = components['schemas']['PricesEvent']
export type RadarTick = components['schemas']['RadarTick']
const base = import.meta.env.VITE_API_URL ?? ''

export function openStream(): EventSource {
  return new EventSource(`${base}/stream`)
}

export async function getRadar(): Promise<RadarResponse> {
  const response = await fetch(`${base}/radar`)
  if (!response.ok) throw new Error(`Radar request failed (${response.status})`)
  return response.json() as Promise<RadarResponse>
}
