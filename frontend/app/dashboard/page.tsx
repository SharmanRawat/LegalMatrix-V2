'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { ClipboardList, AlertCircle, TrendingUp, UserRound } from 'lucide-react'
import toast, { Toaster } from 'react-hot-toast'
import Navbar from '@/app/components/Navbar'
import { api, apiError, getUser } from '@/app/lib/api'
import { useI18n } from '@/app/lib/i18n'

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

const statusColor: Record<string, string> = {
  COMPLIANT: 'text-green-600',
  REVIEW_REQUIRED: 'text-yellow-600',
  POTENTIAL_VIOLATION: 'text-red-600',
}

const statusBg: Record<string, string> = {
  COMPLIANT: 'bg-green-50 border-green-200',
  REVIEW_REQUIRED: 'bg-yellow-50 border-yellow-200',
  POTENTIAL_VIOLATION: 'bg-red-50 border-red-200',
}

export default function DashboardPage() {
  const router = useRouter()
  const { t, tStatus } = useI18n()
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [user] = useState(() => {
    try {
      return getUser()
    } catch {
      return null
    }
  })

  useEffect(() => {
    if (!getUser()) {
      router.replace('/login')
      return
    }
    api
      .get('/api/dashboard/stats')
      .then(({ data }) => setStats(data))
      .catch((err: unknown) => {
        if ((err as { response?: { status?: number } })?.response?.status === 401) {
          router.replace('/login')
        } else {
          toast.error(apiError(err, t('Failed to load dashboard')))
        }
      })
      .finally(() => setLoading(false))
  }, [router])

  const total = stats?.total_inspections ?? 0
  const maxTrend = Math.max(1, ...(stats?.daily_trend ?? []).map((t) => t.count))

  return (
    <>
      <Navbar />
      <Toaster position="top-right" />
      <main className="max-w-5xl mx-auto p-4 sm:p-6 space-y-6">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{t('Compliance Dashboard')}</h1>
            <p className="text-sm text-gray-500">{t('Live overview of all inspections')}</p>
          </div>
          {user && (
            <div className="flex items-center gap-3 bg-white rounded-xl shadow-sm border border-gray-200 px-4 py-2.5">
              <div className="p-2 rounded-lg bg-blue-50">
                <UserRound className="w-5 h-5 text-blue-600" />
              </div>
              <div className="text-right">
                <p className="text-sm font-semibold text-gray-900">{user.name || user.username}</p>
                <p className="text-[10px] text-gray-500 uppercase">
                  {t('Instructor')} ({user.role})
                </p>
              </div>
            </div>
          )}
        </header>

        {loading && (
          <div className="flex justify-center py-20">
            <div className="animate-spin rounded-full h-10 w-10 border-4 border-blue-500 border-t-transparent" />
          </div>
        )}

        {!loading && (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-lg bg-blue-50">
                    <ClipboardList className="w-5 h-5 text-blue-600" />
                  </div>
                  <div>
                    <p className="text-2xl font-bold text-gray-900">{total}</p>
                    <p className="text-xs text-gray-500">{t('Total Inspections')}</p>
                  </div>
                </div>
              </div>
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-lg bg-green-50">
                    <TrendingUp className="w-5 h-5 text-green-600" />
                  </div>
                  <div>
                    <p className="text-2xl font-bold text-gray-900">
                      {stats?.avg_compliance_score ?? 0}%
                    </p>
                    <p className="text-xs text-gray-500">{t('Avg Compliance Score')}</p>
                  </div>
                </div>
              </div>
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-lg bg-red-50">
                    <AlertCircle className="w-5 h-5 text-red-600" />
                  </div>
                  <div>
                    <p className="text-2xl font-bold text-gray-900">
                      {Object.values(stats?.by_status ?? {}).reduce((a, b) => a + b, 0) -
                        (stats?.by_status.COMPLIANT ?? 0)}
                    </p>
                    <p className="text-xs text-gray-500">{t('Non-Compliant')}</p>
                  </div>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                <h3 className="font-semibold text-gray-800 mb-4">{t('Status Breakdown')}</h3>
                <div className="space-y-3">
                  {(Object.entries(stats?.by_status ?? {}) as [string, number][]).map(
                    ([status, count]) => (
                      <div key={status}>
                        <div className="flex justify-between text-sm mb-1">
                          <span className={`font-medium ${statusColor[status] || 'text-gray-600'}`}>
                            {tStatus(status)}
                          </span>
                          <span className="text-gray-500">{count}</span>
                        </div>
                        <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${
                              status === 'COMPLIANT'
                                ? 'bg-green-500'
                                : status === 'REVIEW_REQUIRED'
                                  ? 'bg-yellow-500'
                                  : 'bg-red-500'
                            }`}
                            style={{ width: `${total ? (count / total) * 100 : 0}%` }}
                          />
                        </div>
                      </div>
                    ),
                  )}
                  {Object.keys(stats?.by_status ?? {}).length === 0 && (
                    <p className="text-sm text-gray-400">{t('No inspections yet.')}</p>
                  )}
                </div>
              </div>

              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                <h3 className="font-semibold text-gray-800 mb-4">{t('Scans (last 14 days)')}</h3>
                {(stats?.daily_trend ?? []).length > 0 ? (
                  <div className="flex items-end gap-2 h-32">
                    {stats!.daily_trend.map((t) => (
                      <div key={t.date} className="flex-1 flex flex-col items-center gap-1">
                        <span className="text-[10px] text-gray-500">{t.count}</span>
                        <div
                          className="w-full bg-blue-200 rounded-t"
                          style={{ height: `${Math.max(4, (t.count / maxTrend) * 100)}%` }}
                        />
                        <span className="text-[9px] text-gray-400 truncate w-full text-center">
                          {t.date.slice(2)}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-400">{t('No data yet.')}</p>
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                <h3 className="font-semibold text-gray-800 mb-4">{t('Violations by Field')}</h3>
                {(Object.entries(stats?.field_violations ?? {}) as [string, { count: number; severity: string }][]).map(
                  ([field, info]) => (
                    <div key={field} className="flex items-center justify-between py-1.5 border-b border-gray-50 last:border-0">
                      <span className="text-sm text-gray-700 capitalize">{field.replace(/_/g, ' ')}</span>
                      <span className="text-sm">
                        <span className={`font-semibold ${info.severity === 'CRITICAL' ? 'text-red-600' : 'text-orange-500'}`}>
                          {info.count}
                        </span>
                        <span className="text-gray-400 ml-2 text-xs">{info.severity}</span>
                      </span>
                    </div>
                  ),
                )}
                {Object.keys(stats?.field_violations ?? {}).length === 0 && (
                  <p className="text-sm text-gray-400">{t('No violations recorded.')}</p>
                )}
              </div>

              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                <h3 className="font-semibold text-gray-800 mb-3">{t('Recent Inspections')}</h3>
                <div className="space-y-2">
                  {(stats?.recent ?? []).map((r) => (
                    <Link
                      key={r.id}
                      href={`/inspection/${r.id}`}
                      className="flex items-center justify-between p-3 rounded-lg border border-gray-100 hover:bg-gray-50 transition-colors"
                    >
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-gray-800 truncate">
                          {r.product_name || t('Unknown product')}
                        </p>
                        <p className="text-xs text-gray-500 truncate">
                          {r.id} • {new Date(r.created_at).toLocaleString()}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className={`text-xs font-semibold ${statusColor[r.status] || 'text-gray-600'}`}>
                          {r.compliance_score}%
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${statusBg[r.status] || 'bg-gray-50'}`}
                        >
                          {tStatus(r.status)}
                        </span>
                      </div>
                    </Link>
                  ))}
                  {(stats?.recent ?? []).length === 0 && (
                    <p className="text-sm text-gray-400">
                      {t('No inspections yet.')}{' '}
                      <Link href="/" className="text-blue-600 hover:underline">
                        {t('Start one now')}
                      </Link>
                    </p>
                  )}
                </div>
              </div>
            </div>
          </>
        )}
      </main>
    </>
  )
}