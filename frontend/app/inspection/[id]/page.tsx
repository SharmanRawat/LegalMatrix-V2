'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import {
  CheckCircle, AlertCircle, FileJson, FileDown, ArrowLeft, AlertTriangle,
  Pencil, Save,
} from 'lucide-react'
import toast, { Toaster } from 'react-hot-toast'
import Navbar from '@/app/components/Navbar'
import RadarChart from '@/app/components/RadarChart'
import { api, apiError, getUser, downloadBlob } from '@/app/lib/api'
import type { HeatmapInfo, RadarResult, SessionUser } from '@/app/lib/api'

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

interface ExtractionConfidence {
  overall: number
  coverage_ratio: number
  fields_present: number
  fields_required: number
  by_field: Record<string, number>
}

interface FieldEvidence {
  source: string
  text: string
  image_index: number | null
}

interface ManualOverride {
  [field: string]: {
    original: string
    corrected: string
    by_user_id?: number | null
    at?: string
  }
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
  manual_overrides?: ManualOverride
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
  compliance_radar?: RadarResult | null
  grade?: string
  heatmaps?: HeatmapInfo[]
  evidence?: { hash: string; images?: EvidenceImage[] }
  field_evidence?: Record<string, FieldEvidence>
  extraction_confidence?: ExtractionConfidence
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
  const [heatmapUrls, setHeatmapUrls] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [editing, setEditing] = useState<Record<string, boolean>>({})
  const [savingFields, setSavingFields] = useState<Record<string, boolean>>({})
  const user: SessionUser | null = getUser()
  const canEdit = !!user && (user.role === 'ADMIN' || user.role === 'INSPECTOR')

  const startEdit = (key: string) => {
    setEditing((prev) => ({ ...prev, [key]: true }))
    setDrafts((prev) => ({ ...prev, [key]: data?.declarations?.[key] ?? '' }))
  }

  const cancelEdit = (key: string) => {
    setEditing((prev) => ({ ...prev, [key]: false }))
    setDrafts((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })
  }

  const saveField = async (key: string) => {
    if (!data) return
    const value = (drafts[key] ?? '').trim()
    const current = data.declarations?.[key] ?? ''
    if (value === current) {
      cancelEdit(key)
      return
    }
    setSavingFields((prev) => ({ ...prev, [key]: true }))
    try {
      const { data: updated } = await api.patch(`/api/inspect/${id}`, { overrides: { [key]: value } })
      setData(updated)
      setEditing((prev) => ({ ...prev, [key]: false }))
      setDrafts((prev) => {
        const next = { ...prev }
        delete next[key]
        return next
      })
      toast.success(`${FIELD_LABELS[key] ?? key} corrected`)
    } catch (err) {
      toast.error(apiError(err, 'Failed to save correction'))
    } finally {
      setSavingFields((prev) => ({ ...prev, [key]: false }))
    }
  }

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

        if (data.heatmaps?.length) {
          const hmUrls = await Promise.all(
            (data.heatmaps ?? []).map(async (h) => {
              try {
                const resp = await api.get(`/api/inspect/${id}/heatmap/${h.image_index}`, {
                  responseType: 'blob',
                  timeout: 60000,
                })
                return window.URL.createObjectURL(resp.data)
              } catch {
                return ''
              }
            }),
          )
          setHeatmapUrls(hmUrls)
        }
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

  const downloadCertificate = async () => {
    try {
      await downloadBlob(
        `/api/inspect/${id}/certificate`,
        `LegalMatrix-Certificate-${id}.pdf`,
      )
      toast.success('Certificate downloaded!')
    } catch {
      toast.error('Failed to download certificate')
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
              <h3 className="font-semibold text-gray-800 mb-1">Extracted Declarations</h3>
              {data.extraction_confidence && (
                <div className="mb-3 rounded-lg bg-indigo-50 border border-indigo-100 px-3 py-2 flex items-center gap-3">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-indigo-700">Extraction confidence</span>
                    <span
                      className={`text-sm font-bold ${
                        data.extraction_confidence.overall >= 70
                          ? 'text-green-600'
                          : data.extraction_confidence.overall >= 40
                            ? 'text-yellow-600'
                            : 'text-red-600'
                      }`}
                    >
                      {data.extraction_confidence.overall}%
                    </span>
                  </div>
                  <div className="flex-1 h-2 bg-white rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        data.extraction_confidence.overall >= 70
                          ? 'bg-green-500'
                          : data.extraction_confidence.overall >= 40
                            ? 'bg-yellow-500'
                            : 'bg-red-500'
                      }`}
                      style={{ width: `${data.extraction_confidence.overall}%` }}
                    />
                  </div>
                  <span className="text-[11px] text-indigo-600 whitespace-nowrap">
                    {data.extraction_confidence.fields_present}/
                    {data.extraction_confidence.fields_required} required fields
                  </span>
                </div>
              )}
              {canEdit ? (
                <p className="text-xs text-gray-500 mb-3">
                  Click a value to correct an AI reading. Corrections are saved to the
                  inspection, rules are re-evaluated, and the original value is kept for audit.
                </p>
              ) : (
                <p className="text-xs text-gray-500 mb-3">Read-only (ADMIN / INSPECTOR can correct values).</p>
              )}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {Object.entries(data.declarations ?? {}).map(([key, value]) => {
                  const overridden = data.manual_overrides?.[key]
                  const isEditing = !!(editing[key] && canEdit)
                  const isSaving = !!savingFields[key]
                  return (
                    <div
                      key={key}
                      className={`flex items-start gap-2 p-2 bg-gray-50 rounded-lg ${
                        overridden ? 'ring-1 ring-amber-300' : ''
                      }`}
                    >
                      <div className="min-w-[120px] shrink-0">
                        <span className="text-sm font-medium text-gray-600 capitalize block">
                          {FIELD_LABELS[key] ?? key.replace(/_/g, ' ')}:
                        </span>
                        {overridden && (
                          <span className="text-[10px] font-semibold text-amber-700 bg-amber-100 rounded px-1 py-0.5 inline-block mt-0.5">
                            MANUALLY CORRECTED
                          </span>
                        )}
                      </div>
                      {isEditing ? (
                        <div className="flex-1">
                          <input
                            value={drafts[key] ?? ''}
                            onChange={(e) => setDrafts((prev) => ({ ...prev, [key]: e.target.value }))}
                            disabled={isSaving}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') saveField(key)
                              if (e.key === 'Escape') cancelEdit(key)
                            }}
                            placeholder={value || 'Not detected — type a value'}
                            className="w-full text-sm px-2 py-1 border border-gray-300 rounded bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
                          />
                          <div className="flex gap-2 mt-1">
                            <button
                              onClick={() => saveField(key)}
                              disabled={isSaving}
                              className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                            >
                              <Save className="w-3 h-3" /> {isSaving ? 'Saving…' : 'Save'}
                            </button>
                            <button
                              onClick={() => cancelEdit(key)}
                              disabled={isSaving}
                              className="text-xs font-semibold px-2 py-1 rounded bg-white border border-gray-300 text-gray-600 hover:bg-gray-100"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex-1 min-w-0">
                          <span
                            className={`text-sm block break-words ${
                              value ? 'text-gray-900' : 'text-red-400 italic'
                            }`}
                          >
                            {value || 'Not detected'}
                          </span>
                          {overridden && (
                            <p className="text-[11px] text-gray-400 mt-0.5">
                              Original (AI): &quot;{overridden.original || ''}&quot;
                            </p>
                          )}
                          {(() => {
                            const ev = data.field_evidence?.[key]
                            if (!ev || !ev.text) return null
                            return (
                              <div className="mt-1 flex flex-wrap items-center gap-1">
                                <span
                                  className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                                    ev.source === 'vlm+regex'
                                      ? 'bg-purple-100 text-purple-700'
                                      : ev.source === 'regex'
                                        ? 'bg-blue-100 text-blue-700'
                                        : 'bg-teal-100 text-teal-700'
                                  }`}
                                >
                                  {ev.source}
                                </span>
                                <span className="text-[11px] text-gray-400 italic truncate max-w-full" title={ev.text}>
                                  “{ev.text}”
                                </span>
                              </div>
                            )
                          })()}
                        </div>
                      )}
                      {canEdit && !isEditing && (
                        <button
                          onClick={() => startEdit(key)}
                          title={`Correct ${FIELD_LABELS[key] ?? key}`}
                          className="shrink-0 p-1.5 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  )
                })}
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

            {data.compliance_radar && (
              <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                <h3 className="font-semibold text-gray-800 mb-3">Compliance Radar</h3>
                <RadarChart radar={data.compliance_radar} />
                <p className="mt-3 text-xs text-gray-400">
                  Font-size axis is excluded when no calibration reference (credit card /
                  barcode) is present — the axis is unknown, not a violation.
                </p>
              </section>
            )}

            {data.heatmaps && data.heatmaps.length > 0 && (
              <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                <h3 className="font-semibold text-gray-800 mb-1">Compliance Heat-Map</h3>
                <p className="text-xs text-gray-500 mb-3">
                  Verdicts drawn onto each photo — green = compliant, red = violation,
                  yellow = low confidence, cyan = calibration reference.
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {data.heatmaps.map((h, i) => (
                    <figure key={i} className="border border-gray-200 rounded-lg overflow-hidden bg-gray-50">
                      {heatmapUrls[i] ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={heatmapUrls[i]}
                          alt={`Compliance heat-map photo ${h.image_index + 1}`}
                          className="w-full object-contain bg-white"
                        />
                      ) : (
                        <div className="w-full h-48 flex items-center justify-center text-gray-400 text-sm">
                          Heat-map unavailable
                        </div>
                      )}
                      <figcaption className="px-3 py-2 text-xs text-gray-500 bg-white border-t border-gray-100">
                        Photo {h.image_index + 1} heat-map
                      </figcaption>
                    </figure>
                  ))}
                </div>
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
            <button
                onClick={downloadCertificate}
                className="flex-1 py-3 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 flex items-center justify-center gap-2 font-semibold"
              >
                <FileDown className="w-4 h-4" /> Certificate
              </button>
            </div>
          </>
        )}
      </main>
    </>
  )
}