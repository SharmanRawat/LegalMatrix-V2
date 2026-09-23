'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import {
  CheckCircle, AlertCircle, FileJson, FileDown, ArrowLeft, AlertTriangle,
  Pencil, Save, Award,
} from 'lucide-react'
import toast, { Toaster } from 'react-hot-toast'
import AppShell from '@/app/components/AppShell'
import Card from '@/app/components/ui/Card'
import Badge, { statusToVariant, formatStatus } from '@/app/components/ui/Badge'
import RadarChart from '@/app/components/RadarChart'
import Skeleton, { InspectionDetailSkeleton } from '@/app/components/ui/Skeleton'
import { api, apiError, getUser, downloadBlob, formatDateTime, titleCaseField } from '@/app/lib/api'
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
  created_at: string
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
  COMPLIANT: 'text-success bg-success/10 border-success/20',
  REVIEW_REQUIRED: 'text-warning bg-warning/10 border-warning/20',
  POTENTIAL_VIOLATION: 'text-danger bg-danger/10 border-danger/20',
}

const statusIcon = (s: string) =>
  s === 'COMPLIANT' ? (
    <CheckCircle className="w-6 h-6 text-success" />
  ) : s === 'REVIEW_REQUIRED' ? (
    <AlertCircle className="w-6 h-6 text-warning" />
  ) : (
    <AlertCircle className="w-6 h-6 text-danger" />
  )

const sevStyle: Record<string, string> = {
  CRITICAL: 'bg-danger/10 text-danger border-danger/25',
  HIGH: 'bg-warning/10 text-warning border-warning/25',
  MEDIUM: 'bg-warning/10 text-warning border-warning/25',
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

const SOURCE_LABELS: Record<string, string> = {
  'llm+regex': 'LLM + pattern',
  'vlm+regex': 'Vision + pattern',
  regex: 'Pattern match',
  vlm: 'Vision model',
}

const CHECK_LABELS: Record<string, string> = {
  usp_missing_or_equal_mrp: 'Unit price missing or equals MRP',
}

function humanizeEvidence(text: string, fieldKey: string): string {
  const label = FIELD_LABELS[fieldKey] ?? titleCaseField(fieldKey)
  return text
    .replace(/^\[DEMO\]\s*/, 'Demo — ')
    .replace(new RegExp(`\\b${fieldKey}:`), `${label}:`)
}

function humanizeCalibration(value: string | null | undefined): string {
  if (!value) return '—'
  if (/credit[_\s-]?card/i.test(value)) return 'Credit-card reference'
  if (/barcode/i.test(value)) return 'Barcode reference'
  return value.replace(/_/g, ' ')
}

function humanizeMethod(value: string | null | undefined): string {
  if (!value) return '—'
  if (value === 'token-box') return 'Token-box measurement'
  return value.replace(/_/g, ' ')
}

/** Count-up score — confidence moment when a report settles in */
function ScoreCountUp({ value }: { value: number }) {
  const [display, setDisplay] = useState(0)

  useEffect(() => {
    const reduced =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduced) {
      const id = requestAnimationFrame(() => setDisplay(value))
      return () => cancelAnimationFrame(id)
    }
    const duration = 700
    const start = performance.now()
    let raf = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3)
      setDisplay(Math.round(value * eased))
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value])

  return <>{display}%</>
}

export default function InspectionDetailPage() {
  const params = useParams<{ id: string }>()
  const id = params.id
  const router = useRouter()
  const [data, setData] = useState<InspectionDetail | null>(null)
  const [images, setImages] = useState<{ url: string; name: string }[]>([])
  const [imagesLoading, setImagesLoading] = useState(true)
  const [lightbox, setLightbox] = useState<number | null>(null)
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
        setImagesLoading(false)

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
      .finally(() => {
        setLoading(false)
        setImagesLoading(false)
      })
  }, [id, router])

  useEffect(() => {
    if (lightbox === null) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setLightbox(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [lightbox])

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

  const downloadReport = async () => {
    try {
      await downloadBlob(
        `/api/inspect/${id}/report`,
        `LegalMatrix-Report-${id}.pdf`,
      )
      toast.success('PDF report downloaded!')
    } catch {
      toast.error('Failed to download PDF report')
    }
  }

  const score = data?.compliance_score ?? 0

  return (
    <AppShell>
      <Toaster position="top-right" />
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-5">
        <Link href="/history" className="inline-flex items-center gap-1 text-sm text-text-secondary hover:text-text-primary transition-colors">
          <ArrowLeft className="w-4 h-4" /> Back to history
        </Link>

        {loading && <InspectionDetailSkeleton />}

        {!loading && data && (
          <>
            <header className={`rounded-xl border p-5 animate-reveal ${statusColor[data.status] || 'bg-surface border-surface-border'}`}>
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex items-start gap-3">
                  {statusIcon(data.status)}
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h1 className="text-xl font-bold text-text-primary truncate">
                        {data.declarations?.product_name || 'Inspection report'}
                      </h1>
                      <Badge variant={statusToVariant(data.status)}>
                        {formatStatus(data.status)}
                      </Badge>
                    </div>
                    <p className="text-sm text-text-secondary">
                      {data.inspection_id} • {formatDateTime(data.created_at)}
                      {data.method && <span> • Model: {humanizeMethod(data.method)}</span>}
                    </p>
                  </div>
                </div>
                <div className="text-center sm:text-right">
                  <p className="text-3xl font-bold text-text-primary">
                    <ScoreCountUp value={score} />
                  </p>
                  <p className="text-xs text-text-secondary">
                    {data.passed_count}/{data.total_rules} rules passed
                  </p>
                </div>
              </div>
            </header>

            <Card className="animate-reveal" style={{ animationDelay: '80ms' }}>
              <h2 className="font-semibold text-text-primary mb-3">Evidence Photos</h2>
              {imagesLoading ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {[0, 1].map((i) => (
                    <Skeleton key={i} className="w-full h-48" />
                  ))}
                </div>
              ) : images.length > 0 ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {images.map((img, i) => (
                    <figure
                      key={i}
                      className="border border-surface-border hover:border-accent/40 rounded-lg overflow-hidden bg-surface transition-colors group"
                    >
                      {img.url ? (
                        <button
                          type="button"
                          onClick={() => setLightbox(i)}
                          className="w-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                          aria-label={`View ${img.name} full size`}
                        >
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={img.url}
                            alt={img.name}
                            className="w-full h-48 object-contain bg-bg-primary transition-transform duration-300 group-hover:scale-[1.03]"
                          />
                        </button>
                      ) : (
                        <div className="w-full h-48 flex items-center justify-center text-text-muted text-sm">
                          Image unavailable
                        </div>
                      )}
                      <figcaption className="px-3 py-2 text-xs text-text-muted bg-surface border-t border-surface-border truncate">
                        {img.name}
                      </figcaption>
                    </figure>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-text-muted">No evidence images stored.</p>
              )}
              {data.evidence?.hash && (
                <p className="mt-3 text-[11px] text-text-muted break-all">
                  Evidence SHA-256: {data.evidence.hash}
                </p>
              )}
            </Card>

            <Card className="animate-reveal" style={{ animationDelay: '140ms' }}>
              <h2 className="font-semibold text-text-primary mb-1">Extracted Declarations</h2>
              {data.extraction_confidence && (
                <div className="mb-3 rounded-lg bg-accent/5 border border-accent/10 px-3 py-2 flex items-center gap-3">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-accent">Extraction confidence</span>
                    <span
                      className={`text-sm font-bold ${
                        data.extraction_confidence.overall >= 70
                          ? 'text-success'
                          : data.extraction_confidence.overall >= 40
                            ? 'text-warning'
                            : 'text-danger'
                      }`}
                    >
                      {data.extraction_confidence.overall}%
                    </span>
                  </div>
                  <div className="flex-1 h-2 bg-surface rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        data.extraction_confidence.overall >= 70
                          ? 'bg-success'
                          : data.extraction_confidence.overall >= 40
                            ? 'bg-warning'
                            : 'bg-danger'
                      }`}
                      style={{ width: `${data.extraction_confidence.overall}%` }}
                    />
                  </div>
                  <span className="text-[11px] text-accent whitespace-nowrap">
                    {data.extraction_confidence.fields_present}/
                    {data.extraction_confidence.fields_required} required fields
                  </span>
                </div>
              )}
              {canEdit ? (
                <p className="text-xs text-text-muted mb-3">
                  Use the edit button next to a value to correct an AI reading. Corrections are
                  saved to the inspection, rules are re-evaluated, and the original value is kept
                  for audit.
                </p>
              ) : (
                <p className="text-xs text-text-muted mb-3">Read-only (ADMIN / INSPECTOR can correct values).</p>
              )}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {Object.entries(data.declarations ?? {}).map(([key, value]) => {
                  const overridden = data.manual_overrides?.[key]
                  const isEditing = !!(editing[key] && canEdit)
                  const isSaving = !!savingFields[key]
                  return (
                    <div
                      key={key}
                      className={`flex items-start gap-2 p-2 bg-surface rounded-lg ${
                        overridden ? 'ring-1 ring-warning/40' : ''
                      }`}
                    >
                      <div className="min-w-[120px] shrink-0">
                        <span className="text-sm font-medium text-text-secondary capitalize block">
                          {FIELD_LABELS[key] ?? key.replace(/_/g, ' ')}:
                        </span>
                        {overridden && (
                          <span className="text-[10px] font-semibold text-warning bg-warning/10 rounded px-1 py-0.5 inline-block mt-0.5">
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
                            className="w-full text-sm px-2 py-1 glass-input"
                          />
                          <div className="flex gap-2 mt-1">
                            <button
                              onClick={() => saveField(key)}
                              disabled={isSaving}
                              className="btn-primary btn-sm"
                            >
                              <Save className="w-3 h-3 inline mr-1" /> {isSaving ? 'Saving…' : 'Save'}
                            </button>
                            <button
                              onClick={() => cancelEdit(key)}
                              disabled={isSaving}
                              className="btn-ghost btn-sm"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex-1 min-w-0">
                          <span
                            className={`text-sm block break-words ${
                              value ? 'text-text-primary' : 'text-text-muted italic'
                            }`}
                          >
                            {value || 'Not detected'}
                          </span>
                          {overridden && (
                            <p className="text-[11px] text-text-muted mt-0.5">
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
                                      ? 'bg-purple-500/10 text-purple-500'
                                      : ev.source === 'regex'
                                        ? 'bg-accent/10 text-accent'
                                        : 'bg-success/10 text-success'
                                  }`}
                                >
                                  {SOURCE_LABELS[ev.source] ?? titleCaseField(ev.source)}
                                </span>
                                <span className="text-[11px] text-text-muted italic truncate max-w-full" title={ev.text}>
                                  &ldquo;{humanizeEvidence(ev.text, key)}&rdquo;
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
                          className="shrink-0 p-1.5 rounded text-text-muted hover:text-accent hover:bg-accent/10 transition-colors"
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
            </Card>

            {data.font_measurement && (
              <Card className="animate-reveal" style={{ animationDelay: '200ms' }}>
                <h2 className="font-semibold text-text-primary mb-3">Font Size &amp; Readability</h2>
                {data.font_measurement.status === 'CANNOT_MEASURE' ? (
                  <div className="rounded-lg bg-surface border border-surface-border p-3">
                    <p className="text-sm font-medium text-text-primary">
                      Cannot measure — manual review required.
                    </p>
                    {data.font_measurement.calibration_rejected_reason && (
                      <p className="mt-1 text-xs text-text-muted">
                        Reason: {data.font_measurement.calibration_rejected_reason}
                      </p>
                    )}
                  </div>
                ) : (
                  <>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                      <div>
                        <p className="text-xs text-text-muted">Measured</p>
                        <p className="text-lg font-semibold text-text-primary">
                          {data.font_measurement.measured_mm ?? '—'} mm
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-text-muted">Required</p>
                        <p className="text-lg font-semibold text-text-primary">
                          {data.font_measurement.required_mm ?? '—'} mm
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-text-muted">Uncertainty</p>
                        <p className="text-lg font-semibold text-text-primary">
                          ±{data.font_measurement.uncertainty ?? '—'} mm
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-text-muted">Status</p>
                        <Badge variant={statusToVariant(data.font_measurement.status)} className="mt-1">
                          {formatStatus(data.font_measurement.status)}
                        </Badge>
                      </div>
                    </div>
                    {data.font_measurement.implausible && (
                      <p className="mt-2 text-xs text-warning bg-warning/10 border border-warning/20 rounded px-2 py-1">
                        Reading flagged implausible relative to the legal minimum — box may have
                        hit the wrong text. Manual review.
                      </p>
                    )}
                    {data.font_measurement.box_rejected_reason && (
                      <p className="mt-2 text-xs text-text-muted">
                        VLM text box rejected ({data.font_measurement.box_rejected_reason}) —
                        value is informational only.
                      </p>
                    )}
                    <p className="mt-2 text-[11px] text-text-muted">
                      Calibration: {humanizeCalibration(data.font_measurement.calibration)}
                      {data.font_measurement.ppm != null && ` at ${data.font_measurement.ppm} px/mm`}
                      {' · '}Method: {humanizeMethod(data.font_measurement.method)}
                      {data.font_measurement.image_index != null &&
                        ` · Measured from photo #${data.font_measurement.image_index + 1}`}
                    </p>
                  </>
                )}
              </Card>
            )}

            {data.compliance_radar && (
              <Card className="animate-reveal" style={{ animationDelay: '240ms' }}>
                <h2 className="font-semibold text-text-primary mb-3">Compliance Radar</h2>
                <RadarChart radar={data.compliance_radar} />
                <p className="mt-3 text-xs text-text-muted">
                  Font-size axis is excluded when no calibration reference (credit card /
                  barcode) is present — the axis is unknown, not a violation.
                </p>
              </Card>
            )}

            {(data.heatmaps?.length ?? 0) > 0 ? (
              <Card className="animate-reveal" style={{ animationDelay: '280ms' }}>
                <h2 className="font-semibold text-text-primary mb-1">Compliance Heat-Map</h2>
                <p className="text-xs text-text-muted mb-3">
                  Verdicts drawn onto each photo — green = compliant, red = violation,
                  yellow = low confidence, cyan = calibration reference.
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {(data.heatmaps ?? []).map((h, i) => (
                    <figure key={i} className="border border-surface-border rounded-lg overflow-hidden bg-surface">
                      {heatmapUrls[i] ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={heatmapUrls[i]}
                          alt={`Compliance heat-map photo ${h.image_index + 1}`}
                          className="w-full object-contain bg-bg-primary"
                        />
                      ) : (
                        <div className="w-full h-48 flex items-center justify-center text-text-muted text-sm">
                          Heat-map unavailable
                        </div>
                      )}
                      <figcaption className="px-3 py-2 text-xs text-text-muted bg-surface border-t border-surface-border">
                        Photo {h.image_index + 1} heat-map
                      </figcaption>
                    </figure>
                  ))}
                </div>
              </Card>
            ) : !imagesLoading && images.length > 0 ? (
              <Card>
                <h2 className="font-semibold text-text-primary mb-1">Compliance Heat-Map</h2>
                <p className="text-xs text-text-muted">
                  No heat-map overlays were generated for this inspection. Verdicts are listed under Rule Violations.
                </p>
              </Card>
            ) : null}

            <Card className="animate-reveal" style={{ animationDelay: '320ms' }}>
              <h2 className="font-semibold text-text-primary mb-3 flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-warning" />
                Rule Violations ({data.violations?.length ?? 0})
              </h2>
              {data.violations && data.violations.length > 0 ? (
                <div className="space-y-3">
                  {data.violations.map((v, idx) => (
                    <div key={idx} className={`border rounded-lg p-4 ${sevStyle[v.severity] || 'bg-surface'}`}>
                      <div className="flex items-center gap-2 mb-1">
                        <Badge variant={v.severity === 'CRITICAL' ? 'danger' : v.severity === 'HIGH' ? 'warning' : 'info'}>
                          {v.severity}
                        </Badge>
                        <span className="text-xs font-mono font-semibold text-text-primary">{v.rule_no}</span>
                        <span className="text-xs text-text-muted">({formatStatus(v.status)})</span>
                      </div>
                      <p className="text-sm font-medium text-text-primary">{v.description}</p>
                      {v.extracted_value && (
                        <p className="text-xs mt-1 text-text-muted">Extracted: &quot;{v.extracted_value}&quot;</p>
                      )}
                      {v.remediation && (
                        <p className="text-xs mt-1 italic text-text-secondary">
                          <span className="font-semibold">Fix:</span> {v.remediation}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-6 bg-success/5 rounded-lg border border-success/20">
                  <CheckCircle className="w-8 h-8 text-success mx-auto mb-1" />
                  <p className="font-semibold text-success">All rules passed</p>
                </div>
              )}
            </Card>

            {data.misleading_checks && data.misleading_checks.length > 0 && (
              <Card className="animate-reveal" style={{ animationDelay: '360ms' }}>
                <h2 className="font-semibold text-text-primary mb-3 flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-warning" />
                  Consistency Checks ({data.misleading_checks.length})
                </h2>
                <div className="space-y-3">
                  {data.misleading_checks.map((c, idx) => (
                    <div key={idx} className="border rounded-lg p-4 bg-warning/5 border-warning/20">
                      <div className="flex items-center gap-2 mb-1">
                        <Badge variant="warning">{c.severity}</Badge>
                        <span className="text-xs font-mono font-semibold text-text-primary">
                          {CHECK_LABELS[c.check] ?? titleCaseField(c.check)}
                        </span>
                      </div>
                      <p className="text-sm font-medium text-text-primary">{c.detail}</p>
                      {c.extracted_value && (
                        <p className="text-xs mt-1 text-text-muted">Extracted: &quot;{c.extracted_value}&quot;</p>
                      )}
                    </div>
                  ))}
                </div>
              </Card>
            )}

            <div className="flex flex-col sm:flex-row gap-3 animate-reveal" style={{ animationDelay: '400ms' }}>
              <button
                onClick={downloadReport}
                className="flex-1 btn-primary flex items-center justify-center gap-2 font-semibold min-h-[44px]"
              >
                <FileDown className="w-4 h-4" /> Download PDF Report
              </button>
              <button
                onClick={downloadCertificate}
                className="flex-1 btn-secondary flex items-center justify-center gap-2 font-semibold min-h-[44px]"
              >
                <Award className="w-4 h-4" /> QR Certificate
              </button>
              <button
                onClick={() => downloadExport('json')}
                className="flex-1 btn-secondary flex items-center justify-center gap-2 font-semibold min-h-[44px]"
              >
                <FileJson className="w-4 h-4" /> Export JSON
              </button>
              <button
                onClick={() => downloadExport('csv')}
                className="flex-1 btn-secondary flex items-center justify-center gap-2 font-semibold min-h-[44px]"
              >
                <FileDown className="w-4 h-4" /> Export CSV
              </button>
            </div>
          </>
        )}

        {lightbox !== null && images[lightbox]?.url && (
          <div
            className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label={`Full size: ${images[lightbox].name}`}
            onClick={() => setLightbox(null)}
          >
            <div
              className="relative max-h-full max-w-5xl w-full animate-fade-scale"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                type="button"
                onClick={() => setLightbox(null)}
                className="absolute -top-10 right-0 btn-overlay btn-sm"
              >
                Close (Esc)
              </button>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={images[lightbox].url}
                alt={images[lightbox].name}
                className="max-h-[85vh] w-full rounded-lg shadow-2xl object-contain"
              />
              <p className="text-center text-xs text-white/80 mt-2">{images[lightbox].name}</p>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}
