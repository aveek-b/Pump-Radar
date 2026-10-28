import { lazy, Suspense, type ComponentProps } from 'react'
import { Loading } from './ui'

const Chart = lazy(() => import('./PriceChart').then(module => ({ default: module.PriceChart })))
export function PriceChart(props: ComponentProps<typeof Chart>) {
  return <Suspense fallback={<Loading />}><Chart {...props} /></Suspense>
}
