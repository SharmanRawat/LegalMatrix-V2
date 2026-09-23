'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import {
  ClipboardList, TrendingUp, AlertCircle, Plus, ArrowRight,
  type LucideIcon,
} from 'lucide-react'
import toast, { Toaster } from 'react-hot-toast'
import AppShell from '@/app/components/AppShell'
import Card from '@/app/components/ui/Card'
import Badge, { statusToVariant, formatStatus } from '@/app/components/ui/Badge'
import { StatCardsSkeleton } from '@/app/components/ui/Skeleton'
import { api, apiError, getUser, formatDate, titleCaseField } from '@/app/lib/api'

interface Recent {
  id: string
  product_name: string | null
  manufacturer: string | null
  status: string
  compliance_score: number
  images_count: number
  created_at: string
}

interface Stats {
  total_inspections: number
  by_status: Record<string, number>
  avg_compliance_score: number
  recent: Recent[]
  field_violations: Record<string, { count: number; severity: string }>
  daily_trend: { date: string; count: number }[]
}

const severityVariant: Record<string, 'danger' | 'warning' | 'info'> = {
  CRITICAL: 'danger',
  HIGH: 'danger',
  MEDIUM: 'warning',
  LOW: 'info',
}

function StatCard({
  icon: Icon,
  label,
  value,
  accent,
  index = 0,
}: {
  icon: LucideIcon
  label: string
  value: string | number
  accent: string
  index?: number
}) {
  return (
    <Card
      className="flex items-center gap-3 animate-reveal"
      style={{ animationDelay: `${index * 60}ms` }}
    >
      <div
        className="flex items-center justify-center w-10 h-10 rounded-lg shrink-0"
        style={{
          backgroundColor: `color-mix(in srgb, var(--color-${accent}) 14%, transparent)`,
        }}
      >
        <Icon className="w-5 h-5" style={{ color: `var(--color-${accent})` }} />
      </div>
      <div className="min-w-0">
        <p className="text-2xl font-bold text-text-primary leading-tight">{value}</p>
        <p className="text-xs text-text-secondary">{label}</p>
      </div>
    </Card>
  )
}

export default function DashboardPage() {
  const router = useRouter()
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  const loadStats = useCallback(() => {
  if (!getUser()) {
    router.replace('/login')
    return
  }
  api
    .get('/api/dashboard/stats')
    .then(({ data }) => {
      setStats(data)
      setFailed(false)
    })
    .catch((err: unknown) => {
      if ((err as { response?: { status?: number } })?.response?.status === 401) {
        router.replace('/login')
      } else {
        setFailed(true)
        toast.error(apiError(err, 'Failed to load dashboard'))
      }
    })
    .finally(() => setLoading(false))
}, [router])

useEffect(() => {
  loadStats()
}, [loadStats, reloadKey])

const retry = () => {
  setLoading(true)
  setReloadKey((k) => k + 1)
}

  const total = stats?.total_inspections ?? 0
  const maxTrend = Math.max(1, ...(stats?.daily_trend ?? []).map((t) => t.count))
  const nonCompliant =
    Object.values(stats?.by_status ?? {}).reduce((a, b) => a + b, 0) -
    (stats?.by_status.COMPLIANT ?? 0)

  return (
    <AppShell>
      <Toaster position="top-right" />
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-6">
        {/* Header */}
        <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-text-primary">
              Compliance Dashboard
            </h1>
            <p className="text-sm text-text-secondary">
              Live overview of all inspections
            </p>
          </div>
          <Link
            href="/"
            className="btn-primary inline-flex items-center gap-2 self-start"
          >
            <Plus className="w-4 h-4" />
            New Inspection
          </Link>
        </header>

        {/* Loading state */}
        {loading && <StatCardsSkeleton />}

        {/* Error state */}
        {!loading && failed && (
          <Card>
            <div className="text-center py-10 px-4">
              <div className="mx-auto w-14 h-14 rounded-2xl bg-danger-subtle border border-danger/20 flex items-center justify-center mb-4">
                <AlertCircle className="w-7 h-7 text-danger" />
              </div>
              <h2 className="text-base font-semibold text-text-primary">
                Couldn&apos;t load the dashboard
              </h2>
              <p className="text-sm text-text-secondary mt-1 mb-5 max-w-sm mx-auto">
                Something went wrong while fetching the latest compliance stats. Check that the
                backend service is running, then try again.
              </p>
              <button
                onClick={retry}
                className="btn-primary inline-flex items-center gap-2 text-sm"
              >
                <AlertCircle className="w-4 h-4" />
                Retry
              </button>
            </div>
          </Card>
        )}

        {/* Content */}
        {!loading && stats && (
          <>
            {/* Stat cards */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <StatCard
                icon={ClipboardList}
                label="Total Inspections"
                value={total}
                accent="accent"
                index={0}
              />
              <StatCard
                icon={TrendingUp}
                label="Avg Compliance Score"
                value={`${stats.avg_compliance_score}%`}
                accent="success"
                index={1}
              />
              <StatCard
                icon={AlertCircle}
                label="Non-Compliant"
                value={nonCompliant}
                accent="danger"
                index={2}
              />
            </div>

            {/* Charts row */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6 animate-reveal" style={{ animationDelay: '180ms' }}>
              {/* Status breakdown */}
              <Card>
                <h2 className="text-sm font-semibold text-text-primary mb-4">
                  Status Breakdown
                </h2>
                <div className="space-y-3">
                  {Object.entries(stats.by_status).map(([status, count]) => {
                    const pct = total ? (count / total) * 100 : 0
                    return (
                      <div key={status}>
                        <div className="flex items-center justify-between text-sm mb-1.5">
                          <Badge variant={statusToVariant(status)}>
                            {formatStatus(status)}
                          </Badge>
                          <span className="text-text-secondary tabular-nums">
                            {count} <span className="text-text-muted">({Math.round(pct)}%)</span>
                          </span>
                        </div>
                        <div
                          className="h-2 bg-surface rounded-full overflow-hidden"
                          role="progressbar"
                          aria-valuenow={count}
                          aria-valuemax={total}
                          aria-label={`${formatStatus(status)}: ${count} inspections`}
                        >
                          <div
                            className={`h-full rounded-full transition-all duration-500 ${
                              status === 'COMPLIANT'
                                ? 'bg-success'
                                : status === 'REVIEW_REQUIRED'
                                  ? 'bg-warning'
                                  : 'bg-danger'
                            }`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    )
                  })}
                  {Object.keys(stats.by_status).length === 0 && (
                    <p className="text-sm text-text-muted py-4 text-center">
                      No inspections yet.
                    </p>
                  )}
                </div>
              </Card>

              {/* Daily trend */}
              <Card>
                <h2 className="text-sm font-semibold text-text-primary mb-4">
                  Scans (last 14 days)
                </h2>
                {stats.daily_trend.length > 0 ? (
                  <div
                    className="flex items-end gap-1.5 h-36"
                    role="img"
                    aria-label={`Bar chart showing ${stats.daily_trend.length} days of scan activity`}
                  >
                    {stats.daily_trend.map((t) => {
                      // Pixel height — % of an auto-height flex column collapses to 0
                      const barPx = Math.max(8, Math.round((t.count / maxTrend) * 96))
                      return (
                        <div
                          key={t.date}
                          className="flex-1 min-w-0 h-full flex flex-col items-center gap-1 justify-end"
                        >
                          <span className="text-[10px] text-text-muted tabular-nums">
                            {t.count}
                          </span>
                          <div
                            className="w-full bg-accent/60 rounded-t transition-all duration-500"
                            style={{ height: `${barPx}px` }}
                            aria-hidden="true"
                          />
                          <span className="text-[9px] text-text-muted truncate w-full text-center">
                            {t.date.slice(5)}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <p className="text-sm text-text-muted py-4 text-center">No data yet.</p>
                )}
              </Card>
            </div>

            {/* Bottom row */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6 animate-reveal" style={{ animationDelay: '300ms' }}>
              {/* Field violations */}
              <Card>
                <h2 className="text-sm font-semibold text-text-primary mb-4">
                  Violations by Field
                </h2>
                {Object.keys(stats.field_violations).length > 0 ? (
                  <div className="space-y-1">
                    {Object.entries(stats.field_violations)
                      .sort((a, b) => b[1].count - a[1].count)
                      .map(([field, info]) => (
                        <div
                          key={field}
                          className="flex items-center justify-between py-2 border-b border-surface-border last:border-0"
                        >
                          <span className="text-sm text-text-primary">
                            {titleCaseField(field)}
                          </span>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold text-text-primary tabular-nums">
                              {info.count}
                            </span>
                            <Badge variant={severityVariant[info.severity] ?? 'info'}>
                              {info.severity}
                            </Badge>
                          </div>
                        </div>
                      ))}
                  </div>
                ) : (
                  <p className="text-sm text-text-muted py-4 text-center">
                    No violations recorded.
                  </p>
                )}
              </Card>

              {/* Recent inspections */}
              <Card>
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-sm font-semibold text-text-primary">
                    Recent Inspections
                  </h2>
                  {stats.recent.length > 0 && (
                    <Link
                      href="/history"
                      className="text-xs text-accent hover:text-accent-hover transition-colors inline-flex items-center gap-1"
                    >
                      View all <ArrowRight className="w-3 h-3" />
                    </Link>
                  )}
                </div>
                {stats.recent.length > 0 ? (
                  <div className="space-y-2">
                    {stats.recent.map((r) => {
                      // Score tint matches the status badge — no orange score under a green "Compliant"
                      const scoreClass =
                        r.status === 'COMPLIANT'
                          ? 'text-success'
                          : r.status === 'REVIEW_REQUIRED'
                            ? 'text-warning'
                            : r.status === 'POTENTIAL_VIOLATION'
                              ? 'text-danger'
                              : r.compliance_score >= 90
                                ? 'text-success'
                                : r.compliance_score >= 70
                                  ? 'text-warning'
                                  : 'text-danger'
                      return (
                        <Link
                          key={r.id}
                          href={`/inspection/${r.id}`}
                          className="flex items-center justify-between gap-3 p-3 rounded-lg bg-surface hover:bg-surface-hover hover:shadow-glass-lg hover:-translate-y-0.5 transition-all group"
                        >
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-medium text-text-primary truncate group-hover:text-accent transition-colors">
                              {r.product_name || 'Unknown product'}
                            </p>
                            <span className="text-xs text-text-muted truncate block">
                              {formatDate(r.created_at)}
                            </span>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <span className={`text-sm font-semibold tabular-nums ${scoreClass}`}>
                              {r.compliance_score}%
                            </span>
                            <Badge variant={statusToVariant(r.status)}>
                              {formatStatus(r.status)}
                            </Badge>
                          </div>
                        </Link>
                      )
                    })}
                  </div>
                ) : (
                  <div className="text-center py-6">
                    <p className="text-sm text-text-muted mb-3">
                      No inspections yet.
                    </p>
                    <Link href="/" className="btn-primary inline-flex items-center gap-2 text-sm">
                      <Plus className="w-4 h-4" />
                      Start your first inspection
                    </Link>
                  </div>
                )}
              </Card>
            </div>
          </>
        )}
      </div>
    </AppShell>
  )
}
