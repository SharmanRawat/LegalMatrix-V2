'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import {
  CheckCircle, AlertCircle, FileJson, FileDown, ArrowLeft, AlertTriangle,
} from 'lucide-react'
import toast, { Toaster } from 'react-hot-toast'
import Navbar from '@/app/components/Navbar'
import { api, apiError, getUser } from '@/app/lib/api'

interface Violation {
  rule_id: string
  rule_no: string
  severity: string
  status: string
  field: string
  extracted_value: string
  description: string
  remediation: string
}

interface ConsistencyCheck {
  check: string
  severity: string
  detail: string
  extracted_value?: string
}

interface EvidenceImage {
  filename: string
  original_name: string
}

interface InspectionDetail {
  inspection_id: string
  timestamp: string
  status: string
  method: string
  images_processed: number
  images: EvidenceImage[]
  declarations: Record<string, string>
  missing_declarations: string[]
  compliance_score: number
  passed_count: number
  total_rules: number
  violations: Violation[]
  misleading_checks?: ConsistencyCheck[]
  font_measurement?: {
    status: string
    measured_mm: number | null
    uncertainty: number | null
    required_mm: number | null
    calibration?: string | null
    ppm?: number | null
    method?: string | null
    calibration_rejected_reason?: string | null
    box_rejected_reason?: string | null
    implausible?: boolean
    image_index?: number | null
  } | null
  evidence?: { hash: string; images?: EvidenceImage[] }
}

const statusColor: Record<string, string> = {
  COMPLIANT: 'text-green-600 bg-green-50 border-green-200',
  REVIEW_REQUIRED: 'text-yellow-600 bg-yellow-50 border-yellow-200',
  POTENTIAL_VIOLATION: 'text-red-600 bg-red-50 border-red-200',
}

const statusIcon = (s: string) =>
  s === 'COMPLIANT' ? (
    <CheckCircle className="w-6 h-6 text-green-600" />
  ) : s === 'REVIEW_REQUIRED' ? (
    <AlertCircle className="w-6 h-6 text-yellow-600" />
  ) : (
    <AlertCircle className="w-6 h-6 text-red-600" />
  )

const sevStyle: Record<string, string> = {
  CRITICAL: 'bg-red-100 text-red-800 border-red-300',
  HIGH: 'bg-orange-100 text-orange-800 border-orange-300',
  MEDIUM: 'bg-yellow-100 text-yellow-800 border-yellow-300',
}

const FIELD_LABELS: Record<string, string> = {
  usp: 'Unit Sale Price',
  mrp: 'MRP',
  net_quantity: 'Net Quantity',
  product_name: 'Product Name',
  manufacturer: 'Manufacturer',
  manufacturing_date: 'Manufacturing Date',
  expiry_date: 'Expiry Date',
  consumer_care: 'Consumer Care',
  dimensions: 'Dimensions',
  edible: 'Edibility (food?)',
}

export default function InspectionDetailPage() {
  const params = useParams<{ id: string }>()
  const id = params.id
  const router = useRouter()
  const [data, setData] = useState<InspectionDetail | null>(null)
  const [images, setImages] = useState<{ url: string; name: string }[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!getUser()) {
      router.replace('/login')
      return
    }
    api
      .get(`/api/inspect/${id}`)
      .then(async ({ data }: { data: InspectionDetail }) => {
        setData(data)
        const cols = data.images ?? data.evidence?.images ?? []
        const urls = await Promise.all(
          cols.map(async (img, i) => {
            try {
              const resp = await api.get(`/api/inspect/${id}/evidence/${i}`, { responseType: 'blob' })
              return { url: window.URL.createObjectURL(resp.data), name: img.original_name }
            } catch {
              return { url: '', name: img.original_name }
            }
          }),
        )
        setImages(urls)
      })
      .catch((err: unknown) => {
        if ((err as { response?: { status?: number } })?.response?.status === 401) router.replace('/login')
        else toast.error(apiError(err, 'Failed to load inspection'))
      })
      .finally(() => setLoading(false))
  }, [id, router])

  const downloadExport = async (format: 'json' | 'csv') => {
    try {
      const resp = await api.get(`/api/inspect/${id}/export?format=${format}`, { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([resp.data]))
      const a = document.createElement('a')
      a.href = url
      a.download = `${id}.${format}`
      a.click()
      window.URL.revokeObjectURL(url)
      toast.success(`${format.toUpperCase()} exported`)
    } catch {
      toast.error('Export failed')
    }
  }

  const score = data?.compliance_score ?? 0

  return (
    <>
      <Navbar />
      <Toaster position="top-right" />
      <main className="max-w-5xl mx-auto p-4 sm:p-6 space-y-5">
        <Link href="/history" className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-800">
          <ArrowLeft className="w-4 h-4" /> Back to history
        </Link>

        {loading && (
          <div className="flex justify-center py-20">
            <div className="animate-spin rounded-full h-10 w-10 border-4 border-blue-500 border-t-transparent" />
          </div>
        )}

        {!loading && data && (
          <>
            <header className={`rounded-xl border p-5 ${statusColor[data.status] || 'bg-gray-50 border-gray-200'}`}>
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  {statusIcon(data.status)}
                  <div>
                    <h1 className="text-xl font-bold">Status: {data.status.replace(/_/g, ' ')}</h1>
                    <p className="text-sm opacity-80">
                      {data.inspection_id} • {new Date(data.timestamp).toLocaleString()}
                      {data.method && <span> • Model: {data.method}</span>}
                    </p>
                  </div>
                </div>
                <div className="text-center sm:text-right">
                  <p className="text-3xl font-bold">{score}%</p>
                  <p className="text-xs opacity-80">
                    {data.passed_count}/{data.total_rules} rules passed
                  </p>
                </div>
              </div>
            </header>

            <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
              <h3 className="font-semibold text-gray-800 mb-3">Evidence Photos</h3>
              {images.length > 0 ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {images.map((img, i) => (
                    <figure key={i} className="border border-gray-200 rounded-lg overflow-hidden bg-gray-50">
                      {img.url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={img.url} alt={img.name} className="w-full h-48 object-contain bg-white" />
                      ) : (
                        <div className="w-full h-48 flex items-center justify-center text-gray-400 text-sm">
                          Image unavailable
                        </div>
                      )}
                      <figcaption className="px-3 py-2 text-xs text-gray-500 bg-white border-t border-gray-100 truncate">
                        {img.name}
                      </figcaption>
                    </figure>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-400">No evidence images stored.</p>
              )}
              {data.evidence?.hash && (
                <p className="mt-3 text-[11px] text-gray-400 break-all">
                  Evidence SHA-256: {data.evidence.hash}
                </p>
              )}
            </section>

            <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
              <h3 className="font-semibold text-gray-800 mb-3">Extracted Declarations</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {Object.entries(data.declarations ?? {}).map(([key, value]) => (
                  <div key={key} className="flex items-start gap-2 p-2 bg-gray-50 rounded-lg">
                    <span className="text-sm font-medium text-gray-600 capitalize min-w-[120px]">
                      {FIELD_LABELS[key] ?? key.replace(/_/g, ' ')}:
                    </span>
                    <span className={`text-sm ${value ? 'text-gray-900' : 'text-red-400 italic'}`}>
                      {value || 'Not detected'}
                    </span>
                  </div>
                ))}
              </div>
            </section>

            {data.font_measurement && (
              <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                <h3 className="font-semibold text-gray-800 mb-3">Font Size &amp; Readability</h3>
                {data.font_measurement.status === 'CANNOT_MEASURE' ? (
                  <div className="rounded-lg bg-gray-50 border border-gray-200 p-3">
                    <p className="text-sm font-medium text-gray-800">
                      Cannot measure — manual review required.
                    </p>
                    {data.font_measurement.calibration_rejected_reason && (
                      <p className="mt-1 text-xs text-gray-500">
                        Reason: {data.font_measurement.calibration_rejected_reason}
                      </p>
                    )}
                  </div>
                ) : (
                  <>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                      <div>
                        <p className="text-xs text-gray-500">Measured</p>
                        <p className="text-lg font-semibold">
                          {data.font_measurement.measured_mm ?? '—'} mm
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Required</p>
                        <p className="text-lg font-semibold">
                          {data.font_measurement.required_mm ?? '—'} mm
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Uncertainty</p>
                        <p className="text-lg font-semibold">
                          ±{data.font_measurement.uncertainty ?? '—'} mm
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Status</p>
                        <p className={`text-lg font-semibold ${
                          data.font_measurement.status === 'COMPLIANT' ? 'text-green-600' :
                          data.font_measurement.status === 'REVIEW_REQUIRED' ? 'text-yellow-600' : 'text-red-600'
                        }`}>
                          {data.font_measurement.status.replace(/_/g, ' ')}
                        </p>
                      </div>
                    </div>
                    {data.font_measurement.implausible && (
                      <p className="mt-2 text-xs text-yellow-700 bg-yellow-50 border border-yellow-200 rounded px-2 py-1">
                        Reading flagged implausible relative to the legal minimum — box may have
                        hit the wrong text. Manual review.
                      </p>
                    )}
                    {data.font_measurement.box_rejected_reason && (
                      <p className="mt-2 text-xs text-gray-500">
                        VLM text box rejected ({data.font_measurement.box_rejected_reason}) —
                        value is informational only.
                      </p>
                    )}
                    <p className="mt-2 text-[11px] text-gray-400">
                      Calibration: {data.font_measurement.calibration ?? '—'}
                      {data.font_measurement.ppm != null && ` at ${data.font_measurement.ppm} px/mm`}
                      {' · '}Method: {data.font_measurement.method ?? '—'}
                      {data.font_measurement.image_index != null &&
                        ` · Measured from photo #${data.font_measurement.image_index + 1}`}
                    </p>
                  </>
                )}
              </section>
            )}

            <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
              <h3 className="font-semibold text-gray-800 mb-3 flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-orange-500" />
                Rule Violations ({data.violations?.length ?? 0})
              </h3>
              {data.violations && data.violations.length > 0 ? (
                <div className="space-y-3">
                  {data.violations.map((v, idx) => (
                    <div key={idx} className={`border rounded-lg p-4 ${sevStyle[v.severity] || 'bg-gray-50'}`}>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs font-bold px-2 py-0.5 rounded bg-white/60 border">{v.severity}</span>
                        <span className="text-xs font-mono font-semibold">{v.rule_no}</span>
                        <span className="text-xs opacity-70">({v.status.replace(/_/g, ' ')})</span>
                      </div>
                      <p className="text-sm font-medium">{v.description}</p>
                      {v.extracted_value && (
                        <p className="text-xs mt-1 opacity-70">Extracted: &quot;{v.extracted_value}&quot;</p>
                      )}
                      {v.remediation && (
                        <p className="text-xs mt-1 italic">
                          <span className="font-semibold">Fix:</span> {v.remediation}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-6 bg-green-50 rounded-lg border border-green-200">
                  <CheckCircle className="w-8 h-8 text-green-600 mx-auto mb-1" />
                  <p className="font-semibold text-green-800">All rules passed</p>
                </div>
              )}
            </section>

            {data.misleading_checks && data.misleading_checks.length > 0 && (
              <section className="bg-white rounded-xl shadow-sm border border-orange-200 p-5">
                <h3 className="font-semibold text-gray-800 mb-3 flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-amber-600" />
                  Consistency Checks ({data.misleading_checks.length})
                </h3>
                <div className="space-y-3">
                  {data.misleading_checks.map((c, idx) => (
                    <div key={idx} className="border rounded-lg p-4 bg-amber-50 border-amber-200">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs font-bold px-2 py-0.5 rounded bg-white/60 border">{c.severity}</span>
                        <span className="text-xs font-mono font-semibold">{c.check}</span>
                      </div>
                      <p className="text-sm font-medium">{c.detail}</p>
                      {c.extracted_value && (
                        <p className="text-xs mt-1 opacity-70">Extracted: &quot;{c.extracted_value}&quot;</p>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            )}

            <div className="flex gap-3">
              <button
                onClick={() => downloadExport('json')}
                className="flex-1 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center justify-center gap-2 font-semibold"
              >
                <FileJson className="w-4 h-4" /> Export JSON
              </button>
              <button
                onClick={() => downloadExport('csv')}
                className="flex-1 py-3 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 flex items-center justify-center gap-2 font-semibold"
              >
                <FileDown className="w-4 h-4" /> Export CSV
              </button>
            </div>
          </>
        )}
      </main>
    </>
  )
}