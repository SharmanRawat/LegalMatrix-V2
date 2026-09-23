'use client'

import { Suspense, useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { Search, FileDown, Inbox, SearchX, Plus, X } from 'lucide-react'
import toast, { Toaster } from 'react-hot-toast'
import AppShell from '@/app/components/AppShell'
import Card from '@/app/components/ui/Card'
import Badge, { statusToVariant, formatStatus } from '@/app/components/ui/Badge'
import { HistoryListSkeleton, PageSpinner } from '@/app/components/ui/Skeleton'
import { api, apiError, getUser, formatDateTime } from '@/app/lib/api'

interface InspectionRow {
  id: string
  inspection_id?: string
  product_name: string | null
  manufacturer: string | null
  status: string
  compliance_score: number
  images_count: number
  created_at: string
}

function scoreTextClass(score: number): string {
  if (score >= 90) return 'text-success'
  if (score >= 70) return 'text-warning'
  return 'text-danger'
}

function HistoryContent() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const [q, setQ] = useState(() => searchParams.get('q') ?? '')
  const [status, setStatus] = useState(() => searchParams.get('status') ?? '')
  const [productName, setProductName] = useState(() => searchParams.get('product_name') ?? '')
  const [manufacturer, setManufacturer] = useState(() => searchParams.get('manufacturer') ?? '')
  const [dateFrom, setDateFrom] = useState(() => searchParams.get('date_from') ?? '')
  const [dateTo, setDateTo] = useState(() => searchParams.get('date_to') ?? '')
  const [results, setResults] = useState<InspectionRow[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const hasActiveFilters = !!(q || status || productName || manufacturer || dateFrom || dateTo)

  useEffect(() => {
    if (!getUser()) {
      router.replace('/login')
    }
  }, [router])

  const syncUrl = (next: Record<string, string>) => {
    const params = new URLSearchParams()
    Object.entries(next).forEach(([k, v]) => {
      if (v) params.set(k, v)
    })
    const qs = params.toString()
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
  }

  const runSearch = async (resetPage = true) => {
    if (resetPage) setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (q) params.q = q
      if (status) params.status = status
      if (productName) params.product_name = productName
      if (manufacturer) params.manufacturer = manufacturer
      if (dateFrom) params.date_from = new Date(dateFrom).toISOString()
      if (dateTo) params.date_to = new Date(dateTo + 'T23:59:59').toISOString()
      const { data } = await api.get('/api/search', { params })
      setResults(data.results ?? [])
      setTotal(data.total ?? 0)
      syncUrl({
        q,
        status,
        product_name: productName,
        manufacturer,
        date_from: dateFrom,
        date_to: dateTo,
      })
    } catch (err: unknown) {
      if ((err as { response?: { status?: number } })?.response?.status === 401) {
        router.replace('/login')
      } else {
        toast.error(apiError(err, 'Search failed'))
      }
    } finally {
      if (resetPage) setLoading(false)
    }
  }

  useEffect(() => {
    const t = setTimeout(() => runSearch(true), 0)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router])

  const clearFilters = () => {
    setQ('')
    setStatus('')
    setProductName('')
    setManufacturer('')
    setDateFrom('')
    setDateTo('')
    syncUrl({})
    runSearch(true)
  }

  const removeFilter = (key: 'q' | 'status' | 'product_name' | 'manufacturer' | 'date_from' | 'date_to') => {
    if (key === 'q') setQ('')
    if (key === 'status') setStatus('')
    if (key === 'product_name') setProductName('')
    if (key === 'manufacturer') setManufacturer('')
    if (key === 'date_from') setDateFrom('')
    if (key === 'date_to') setDateTo('')
    setTimeout(() => runSearch(true), 0)
  }

  const chips: { key: Parameters<typeof removeFilter>[0]; label: string }[] = []
  if (q) chips.push({ key: 'q', label: `Search: ${q}` })
  if (status) chips.push({ key: 'status', label: formatStatus(status) })
  if (productName) chips.push({ key: 'product_name', label: productName })
  if (manufacturer) chips.push({ key: 'manufacturer', label: manufacturer })
  if (dateFrom) chips.push({ key: 'date_from', label: `From ${dateFrom}` })
  if (dateTo) chips.push({ key: 'date_to', label: `To ${dateTo}` })

  const downloadCsv = async (id: string) => {
    try {
      const resp = await api.get(`/api/inspect/${id}/export?format=csv`, { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([resp.data]))
      const a = document.createElement('a')
      a.href = url
      a.download = `${id}.csv`
      a.click()
      window.URL.revokeObjectURL(url)
      toast.success('CSV downloaded')
    } catch {
      toast.error('Export failed')
    }
  }

  return (
    <AppShell>
      <Toaster position="top-right" />
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-5">
        <header>
          <h1 className="text-xl sm:text-2xl font-bold text-text-primary">Inspection History</h1>
          <p className="text-sm text-text-secondary">Search previously scanned products and reports</p>
        </header>

        <Card>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <label htmlFor="hist-q" className="sr-only">
                Search by ID, product name or manufacturer
              </label>
              <Search
                className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
                aria-hidden="true"
              />
              <input
                id="hist-q"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && runSearch(true)}
                placeholder="Search by ID, product name or manufacturer…"
                className="w-full pr-3 py-2.5 glass-input glass-input-icon"
              />
            </div>
            <button
              onClick={() => runSearch(true)}
              disabled={loading}
              className="btn-primary"
            >
              {loading ? 'Searching…' : 'Search'}
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-3">
            <div>
              <label htmlFor="hist-status" className="block text-[11px] font-medium text-text-secondary mb-1">
                Status
              </label>
              <select
                id="hist-status"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="px-3 py-2 glass-input"
              >
                <option value="">All statuses</option>
                <option value="COMPLIANT">Compliant</option>
                <option value="REVIEW_REQUIRED">Review required</option>
                <option value="POTENTIAL_VIOLATION">Potential violation</option>
              </select>
            </div>
            <div>
              <label htmlFor="hist-product" className="block text-[11px] font-medium text-text-secondary mb-1">
                Product name
              </label>
              <input
                id="hist-product"
                value={productName}
                onChange={(e) => setProductName(e.target.value)}
                placeholder="e.g. Amul Milk"
                className="px-3 py-2 glass-input"
              />
            </div>
            <div>
              <label htmlFor="hist-manufacturer" className="block text-[11px] font-medium text-text-secondary mb-1">
                Manufacturer
              </label>
              <input
                id="hist-manufacturer"
                value={manufacturer}
                onChange={(e) => setManufacturer(e.target.value)}
                placeholder="e.g. Hindustan Unilever"
                className="px-3 py-2 glass-input"
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label htmlFor="hist-from" className="block text-[11px] font-medium text-text-secondary mb-1">
                  From
                </label>
                <input
                  id="hist-from"
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="px-2 py-2 glass-input"
                />
              </div>
              <div>
                <label htmlFor="hist-to" className="block text-[11px] font-medium text-text-secondary mb-1">
                  To
                </label>
                <input
                  id="hist-to"
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className="px-2 py-2 glass-input"
                />
              </div>
            </div>
          </div>

          {hasActiveFilters && (
            <div className="flex flex-wrap items-center gap-2 mt-3 pt-3 border-t border-surface-border">
              {chips.map((chip) => (
                <span
                  key={chip.key}
                  className="inline-flex items-center gap-1 pl-2.5 pr-1.5 py-1 rounded-full bg-bg-secondary border border-surface-border text-xs text-text-secondary"
                >
                  {chip.label}
                  <button
                    type="button"
                    onClick={() => removeFilter(chip.key)}
                    className="p-0.5 rounded-full hover:bg-surface-active text-text-muted hover:text-text-primary"
                    aria-label={`Remove filter ${chip.label}`}
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
              <button
                type="button"
                onClick={clearFilters}
                className="text-xs font-semibold text-accent hover:text-accent-hover underline underline-offset-2"
              >
                Clear all
              </button>
            </div>
          )}
        </Card>

        <p className="text-sm text-text-secondary">
          {total} result{total !== 1 ? 's' : ''}
        </p>

        {/* First load / empty re-search → skeletons; re-search with rows → dim in place */}
        {loading && results.length === 0 ? (
          <HistoryListSkeleton />
        ) : results.length === 0 && !loading ? (
          <Card>
            <div className="text-center py-10 px-4">
              <div className="mx-auto w-14 h-14 rounded-2xl bg-bg-secondary border border-surface-border flex items-center justify-center mb-4">
                {hasActiveFilters ? (
                  <SearchX className="w-7 h-7 text-text-muted" />
                ) : (
                  <Inbox className="w-7 h-7 text-text-muted" />
                )}
              </div>
              <h2 className="text-base font-semibold text-text-primary">
                {hasActiveFilters ? 'No matching inspections' : 'No inspections yet'}
              </h2>
              <p className="text-sm text-text-secondary mt-1 mb-5 max-w-sm mx-auto">
                {hasActiveFilters
                  ? 'Try removing or relaxing some filters to broaden the search.'
                  : 'Scan your first product label to start building compliance history.'}
              </p>
              {!hasActiveFilters && (
                <Link href="/" className="btn-primary inline-flex items-center gap-2 text-sm">
                  <Plus className="w-4 h-4" />
                  Start your first inspection
                </Link>
              )}
              {hasActiveFilters && (
                <button onClick={clearFilters} className="btn-secondary inline-flex items-center gap-2 text-sm">
                  Clear filters
                </button>
              )}
            </div>
          </Card>
        ) : (
          <div
            className={`space-y-3 transition-opacity duration-200 ${
              loading ? 'opacity-50 pointer-events-none' : 'opacity-100'
            }`}
            aria-busy={loading}
          >
            {results.map((r, i) => (
              <Card
                key={r.id}
                className="lift-hover animate-reveal"
                style={{ animationDelay: `${Math.min(i, 8) * 45}ms` }}
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="font-mono text-xs text-text-muted">{r.id}</span>
                      <Badge variant={statusToVariant(r.status)}>{formatStatus(r.status)}</Badge>
                    </div>
                    <p className="text-sm font-medium text-text-primary truncate">{r.product_name || '—'}</p>
                    <p className="text-xs text-text-muted">{r.manufacturer || ''}</p>
                    <p className="text-[11px] text-text-muted mt-0.5">{formatDateTime(r.created_at)}</p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <span className={`text-lg font-bold tabular-nums ${scoreTextClass(r.compliance_score)}`}>
                      {r.compliance_score}%
                    </span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => downloadCsv(r.id)}
                        className="btn-ghost btn-sm"
                      >
                        <FileDown className="w-3.5 h-3.5" /> CSV
                      </button>
                      <Link href={`/inspection/${r.id}`} className="btn-primary btn-sm">
                        View
                      </Link>
                    </div>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  )
}

export default function HistoryPage() {
  return (
    <Suspense fallback={<PageSpinner />}>
      <HistoryContent />
    </Suspense>
  )
}
