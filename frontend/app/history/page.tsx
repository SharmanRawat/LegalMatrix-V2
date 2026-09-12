'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Search, FileDown } from 'lucide-react'
import toast, { Toaster } from 'react-hot-toast'
import Navbar from '@/app/components/Navbar'
import { api, apiError, getUser } from '@/app/lib/api'

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

const statusColor: Record<string, string> = {
  COMPLIANT: 'text-green-600',
  REVIEW_REQUIRED: 'text-yellow-600',
  POTENTIAL_VIOLATION: 'text-red-600',
}

const statusBadge: Record<string, string> = {
  COMPLIANT: 'bg-green-50 text-green-700 border-green-200',
  REVIEW_REQUIRED: 'bg-yellow-50 text-yellow-700 border-yellow-200',
  POTENTIAL_VIOLATION: 'bg-red-50 text-red-700 border-red-200',
}

export default function HistoryPage() {
  const router = useRouter()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [productName, setProductName] = useState('')
  const [manufacturer, setManufacturer] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [results, setResults] = useState<InspectionRow[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!getUser()) {
      router.replace('/login')
    }
  }, [router])

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
    <>
      <Navbar />
      <Toaster position="top-right" />
      <main className="max-w-5xl mx-auto p-4 sm:p-6 space-y-5">
        <header>
          <h1 className="text-2xl font-bold text-gray-900">Inspection History</h1>
          <p className="text-sm text-gray-500">Search previously scanned products and reports</p>
        </header>

        <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 space-y-3">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && runSearch(true)}
                placeholder="Search by ID, product name or manufacturer…"
                className="w-full pl-9 pr-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
              />
            </div>
            <button
              onClick={() => runSearch(true)}
              disabled={loading}
              className="px-5 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm font-semibold"
            >
              {loading ? 'Searching…' : 'Search'}
            </button>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
            >
              <option value="">All statuses</option>
              <option value="COMPLIANT">Compliant</option>
              <option value="REVIEW_REQUIRED">Review required</option>
              <option value="POTENTIAL_VIOLATION">Potential violation</option>
            </select>
            <input
              value={productName}
              onChange={(e) => setProductName(e.target.value)}
              placeholder="Product name"
              className="px-3 py-2 border border-gray-300 rounded-lg text-sm"
            />
            <input
              value={manufacturer}
              onChange={(e) => setManufacturer(e.target.value)}
              placeholder="Manufacturer"
              className="px-3 py-2 border border-gray-300 rounded-lg text-sm"
            />
            <div className="flex gap-2">
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="w-1/2 px-2 py-2 border border-gray-300 rounded-lg text-sm"
                title="From"
              />
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="w-1/2 px-2 py-2 border border-gray-300 rounded-lg text-sm"
                title="To"
              />
            </div>
          </div>
        </section>

        <p className="text-sm text-gray-500">
          {total} result{total !== 1 ? 's' : ''}
        </p>

        {loading ? (
          <div className="flex justify-center py-20">
            <div className="animate-spin rounded-full h-10 w-10 border-4 border-blue-500 border-t-transparent" />
          </div>
        ) : results.length === 0 ? (
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-10 text-center">
            <p className="text-gray-500">No inspections found matching your filters.</p>
          </div>
        ) : (
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-4 py-3">Inspection</th>
                  <th className="px-4 py-3">Product / Maker</th>
                  <th className="px-4 py-3">Score</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr key={r.id} className="border-t border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <p className="font-mono text-xs text-gray-600">{r.id}</p>
                      <p className="text-[11px] text-gray-400">
                        {new Date(r.created_at).toLocaleString()}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <p className="text-gray-800 font-medium">{r.product_name || '—'}</p>
                      <p className="text-xs text-gray-500">{r.manufacturer || ''}</p>
                    </td>
                    <td className={`px-4 py-3 font-semibold ${statusColor[r.status] || 'text-gray-600'}`}>
                      {r.compliance_score}%
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${statusBadge[r.status] || 'bg-gray-50'}`}>
                        {r.status.replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => downloadCsv(r.id)}
                          className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-100"
                        >
                          <FileDown className="w-3.5 h-3.5" /> CSV
                        </button>
                        <Link
                          href={`/inspection/${r.id}`}
                          className="text-xs px-2.5 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700"
                        >
                          View
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </>
  )
}