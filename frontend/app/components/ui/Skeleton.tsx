import { HTMLAttributes } from 'react'

interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  /** Variant: rectangular block, circular, or text line */
  variant?: 'block' | 'circle' | 'text'
  width?: string
  height?: string
}

export default function Skeleton({
  variant = 'block',
  width,
  height,
  className = '',
  ...props
}: SkeletonProps) {
  const base = 'animate-pulse-soft rounded-lg bg-surface'

  const variantClass = {
    block: '',
    circle: 'rounded-full',
    text: 'h-4 rounded',
  }[variant]

  return (
    <div
      className={`${base} ${variantClass} ${className}`}
      style={{ width, height }}
      aria-hidden="true"
      {...props}
    />
  )
}

/** Full-page loading spinner */
export function PageSpinner() {
  return (
    <div className="flex justify-center py-20" role="status" aria-label="Loading">
      <div className="animate-spin rounded-full h-10 w-10 border-4 border-accent border-t-transparent" />
      <span className="sr-only">Loading…</span>
    </div>
  )
}

/** Dashboard skeleton — stat cards */
export function StatCardsSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      {[1, 2, 3].map((i) => (
        <div key={i} className="glass-card p-5">
          <div className="flex items-center gap-3">
            <Skeleton variant="circle" width="40px" height="40px" />
            <div className="space-y-2">
              <Skeleton variant="text" width="60px" height="28px" />
              <Skeleton variant="text" width="100px" />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

/** History search results — row placeholders (first load only) */
export function HistoryListSkeleton() {
  return (
    <div className="space-y-3" role="status" aria-label="Loading results">
      {[0, 1, 2].map((i) => (
        <div key={i} className="glass-card p-5">
          <div className="flex items-center justify-between gap-3">
            <div className="space-y-2 min-w-0 flex-1">
              <Skeleton variant="text" width="140px" />
              <Skeleton variant="text" width="220px" />
              <Skeleton variant="text" width="160px" />
            </div>
            <Skeleton variant="text" width="56px" height="24px" />
          </div>
        </div>
      ))}
      <span className="sr-only">Loading results…</span>
    </div>
  )
}

/** Inspection detail — layout-matching shell (header → evidence → declarations → actions) */
export function InspectionDetailSkeleton() {
  return (
    <div className="space-y-5" role="status" aria-label="Loading inspection report">
      <div className="rounded-xl border border-surface-border bg-surface p-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-start gap-3">
            <Skeleton variant="circle" width="24px" height="24px" />
            <div className="space-y-2">
              <Skeleton variant="text" width="220px" height="24px" />
              <Skeleton variant="text" width="280px" />
            </div>
          </div>
          <div className="sm:text-right space-y-2">
            <Skeleton variant="text" width="72px" height="36px" className="sm:ml-auto" />
            <Skeleton variant="text" width="120px" className="sm:ml-auto" />
          </div>
        </div>
      </div>

      <div className="glass-card p-5">
        <Skeleton variant="text" width="140px" height="18px" className="mb-4" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
        </div>
      </div>

      <div className="glass-card p-5">
        <Skeleton variant="text" width="180px" height="18px" className="mb-4" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-14" />
          ))}
        </div>
      </div>

      <div className="flex flex-col sm:flex-row gap-3">
        <Skeleton className="h-12 flex-1" />
        <Skeleton className="h-12 flex-1" />
        <Skeleton className="h-12 flex-1" />
      </div>

      <span className="sr-only">Loading inspection report…</span>
    </div>
  )
}
