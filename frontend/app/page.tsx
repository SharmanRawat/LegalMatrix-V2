'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import {
  Camera, Upload, Shield, CheckCircle, AlertCircle,
  Clock, X, Download, Scan, AlertTriangle, Pencil, Save,
} from 'lucide-react'
import toast, { Toaster } from 'react-hot-toast'
import Navbar from '@/app/components/Navbar'
import RadarChart from '@/app/components/RadarChart'
import { api, apiError, downloadBlob, getUser } from '@/app/lib/api'
import type { HeatmapInfo, RadarResult, SessionUser } from '@/app/lib/api'

type LabelType = 'front' | 'back' | 'side' | 'top' | 'other'

const LABEL_TYPES: { id: LabelType; label: string; desc: string }[] = [
  { id: 'front', label: 'Front Label (PDP)', desc: 'Brand face & product name — strongest source for the name' },
  { id: 'back', label: 'Back Label (Declarations)', desc: 'MRP, net qty, manufacturer, dates, consumer care' },
  { id: 'side', label: 'Side Label', desc: 'Side panel: nutrition / extra dates / care' },
  { id: 'top', label: 'Top / Cap Label', desc: 'Cap or roof face: batch no, use-by, MRP/USP (EVEREST-style packs)' },
  { id: 'other', label: 'Other Packaging', desc: 'Seals, pack shots, barcodes' },
]

const MAX_IMAGES = 6

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

interface MisleadingCheck {
  check: string
  severity: string
  detail: string
  extracted_value?: string
}

interface InspectionResult {
  inspection_id: string
  timestamp?: string
  method?: string
  images_processed: number
  status: string
  declarations: {
    mrp: string | null
    usp: string | null
    net_quantity: string | null
    product_name: string | null
    manufacturer: string | null
    manufacturing_date: string | null
    expiry_date: string | null
    consumer_care: string | null
    dimensions: string | null
    edible: string | null
  }
  manual_overrides?: Record<string, { original: string; corrected: string }>
  extraction_confidence?: {
    overall: number
    coverage_ratio: number
    fields_present: number
    fields_required: number
  }
  missing_declarations: string[]
  compliance_score: number
  passed_count: number
  total_rules: number
  violations: Violation[]
  misleading_checks?: MisleadingCheck[]
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
  evidence?: {
    hash: string
  }
  message?: string
}

export default function Home() {
  const [selectedImages, setSelectedImages] = useState<File[]>([])
  const [imageTypes, setImageTypes] = useState<LabelType[]>([])
  const [imagePreviews, setImagePreviews] = useState<string[]>([])
  const [captureTarget, setCaptureTarget] = useState<LabelType>('front')
  const [loading, setLoading] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [result, setResult] = useState<InspectionResult | null>(null)
  const [downloadingPdf, setDownloadingPdf] = useState(false)
  const [downloadingCert, setDownloadingCert] = useState(false)
  const [heatmapUrls, setHeatmapUrls] = useState<string[]>([])
  const [cameraActive, setCameraActive] = useState(false)
  const [sameProduct, setSameProduct] = useState(false)
  const [viewingPreview, setViewingPreview] = useState<number | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [editing, setEditing] = useState<Record<string, boolean>>({})
  const [savingFields, setSavingFields] = useState<Record<string, boolean>>({})
  const user: SessionUser | null = getUser()
  const canEdit = !!user && (user.role === 'ADMIN' || user.role === 'INSPECTOR')
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)

  const stopCamera = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop())
      streamRef.current = null
    }
    setCameraActive(false)
  }

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
      stopCamera()
    }
  }, [])

  const startCamera = async (type: LabelType = 'front') => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } },
      })
      streamRef.current = stream
      setCaptureTarget(type)
      setCameraActive(true)
      setTimeout(() => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream
          videoRef.current.play()
        }
      }, 100)
} catch (err: unknown) {
      console.error('Camera access failed:', err)
      toast.error('Camera access denied. Use file upload instead.')
  }
  }

  const createPreview = (file: File, onDone: (dataUrl: string) => void) => {
    const reader = new FileReader()
    reader.onerror = () => onDone('')
    reader.onload = () => {
      const img = new Image()
      img.onerror = () => onDone('')
      img.onload = () => {
        try {
          const MAX = 480
          const scale = Math.min(1, MAX / Math.max(img.naturalWidth, img.naturalHeight))
          const w = Math.max(1, Math.round(img.naturalWidth * scale))
          const h = Math.max(1, Math.round(img.naturalHeight * scale))
          const canvas = document.createElement('canvas')
          canvas.width = w
          canvas.height = h
          const ctx = canvas.getContext('2d')
          if (!ctx) return onDone('')
          ctx.fillStyle = '#ffffff'
          ctx.fillRect(0, 0, w, h)
          ctx.drawImage(img, 0, 0, w, h)
          onDone(canvas.toDataURL('image/jpeg', 0.82))
        } catch {
          onDone('')
        }
      }
      img.src = reader.result as string
    }
    reader.readAsDataURL(file)
  }

  const capturePhoto = () => {
    if (!videoRef.current || !canvasRef.current) return
    const video = videoRef.current
    const canvas = canvasRef.current
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const ctx = canvas.getContext('2d')!
    ctx.drawImage(video, 0, 0)
    canvas.toBlob((blob) => {
      if (!blob) return
      const file = new File([blob], `capture_${Date.now()}.jpg`, { type: 'image/jpeg' })
      if (selectedImages.length >= MAX_IMAGES) {
        toast.error(`Maximum ${MAX_IMAGES} images allowed`)
        return
      }
      const newImages = [...selectedImages, file]
      setSelectedImages(newImages)
      setImageTypes(prev => [...prev, captureTarget])
      setSameProduct(false)
      const idx = newImages.length - 1
      createPreview(file, (dataUrl) => {
        setImagePreviews(prev => {
          const next = [...prev]
          next[idx] = dataUrl
          return next
        })
      })
      toast.success(
        `Photo ${newImages.length} captured for ${LABEL_TYPES.find(t => t.id === captureTarget)?.label ?? captureTarget}`,
      )
    }, 'image/jpeg', 0.92)
  }

  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>, type: LabelType) => {
    const files = Array.from(e.target.files || [])
    if (files.length === 0) return
    if (selectedImages.length + files.length > MAX_IMAGES) {
      toast.error(`Maximum ${MAX_IMAGES} images allowed`)
      return
    }

    const newImages = [...selectedImages, ...files]
    setSelectedImages(newImages)
    setImageTypes(prev => [...prev, ...files.map(() => type)])
    setSameProduct(false)

    files.forEach((file, j) => {
      const idx = imagePreviews.length + j
      createPreview(file, (dataUrl) => {
        if (!dataUrl) toast.error(`Couldn't preview "${file.name}" (unsupported image format?)`)
        setImagePreviews(prev => {
          const next = [...prev]
          next[idx] = dataUrl
          return next
        })
      })
    })
  }

  const removeImage = (index: number) => {
    setSelectedImages(prev => prev.filter((_, i) => i !== index))
    setImageTypes(prev => prev.filter((_, i) => i !== index))
    setImagePreviews(prev => prev.filter((_, i) => i !== index))
    setSameProduct(false)
    if (viewingPreview === index) setViewingPreview(null)
  }

  const handleUpload = async () => {
    if (selectedImages.length === 0) {
      toast.error('Please select or capture at least one image')
      return
    }

    setLoading(true)
    setResult(null)
    setDrafts({})
    setEditing({})
    setSavingFields({})
    setElapsed(0)

    if (timerRef.current) clearInterval(timerRef.current)
    timerRef.current = setInterval(() => setElapsed(s => s + 1), 1000)

    const formData = new FormData()
    selectedImages.forEach(image => formData.append('images', image))
    imageTypes.forEach(type => formData.append('label_types', type))

    try {
      const response = await api.post('/api/inspect', formData, { timeout: 600000 })
      setResult(response.data)
      toast.success('Inspection completed!')
      if (response.data?.inspection_id && response.data?.heatmaps?.length) {
        const urls = await Promise.all(
          (response.data.heatmaps as HeatmapInfo[]).map(async (h) => {
            try {
              const resp = await api.get(`/api/inspect/${response.data.inspection_id}/heatmap/${h.image_index}`, {
                responseType: 'blob',
                timeout: 60000,
              })
              return window.URL.createObjectURL(resp.data)
            } catch {
              return ''
            }
          }),
        )
        setHeatmapUrls(urls)
      }
    } catch (error: unknown) {
      console.error('Error:', error)
      const msg =
        (error as { code?: string } | null)?.code === 'ECONNABORTED'
          ? 'Request timed out. The vision model can take several minutes.'
          : apiError(error, 'Failed to inspect images.')
      toast.error(msg)
    } finally {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
      setLoading(false)
    }
  }

  const startEdit = (key: string) => {
    setEditing((prev) => ({ ...prev, [key]: true }))
    setDrafts((prev) => ({
      ...prev,
      [key]: (result?.declarations as Record<string, string | null> | undefined)?.[key] ?? '',
    }))
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
    if (!result) return
    const value = (drafts[key] ?? '').trim()
    const current = (result.declarations as Record<string, string | null>)[key] ?? ''
    if (value === (current ?? '')) {
      cancelEdit(key)
      return
    }
    setSavingFields((prev) => ({ ...prev, [key]: true }))
    try {
      const { data: updated } = await api.patch(`/api/inspect/${result.inspection_id}`, {
        overrides: { [key]: value },
      })
      setResult((prev) =>
        prev
          ? {
              ...prev,
              declarations: updated.declarations ?? prev.declarations,
              missing_declarations: updated.missing_declarations ?? prev.missing_declarations,
              status: updated.status ?? prev.status,
              compliance_score: updated.compliance_score ?? prev.compliance_score,
              passed_count: updated.passed_count ?? prev.passed_count,
              total_rules: updated.total_rules ?? prev.total_rules,
              violations: updated.violations ?? prev.violations,
              misleading_checks: updated.misleading_checks ?? prev.misleading_checks,
              compliance_radar: updated.compliance_radar ?? prev.compliance_radar,
              grade: updated.grade ?? prev.grade,
              manual_overrides: updated.manual_overrides ?? prev.manual_overrides,
            }
          : prev,
      )
      setEditing((prev) => ({ ...prev, [key]: false }))
      setDrafts((prev) => {
        const next = { ...prev }
        delete next[key]
        return next
      })
      toast.success(`${FIELD_LABELS[key] ?? key} corrected — score recalculated`)
    } catch (err) {
      toast.error(apiError(err, 'Failed to save correction'))
    } finally {
      setSavingFields((prev) => ({ ...prev, [key]: false }))
    }
  }

  const handleDownloadPdf = async () => {
    if (!result || selectedImages.length === 0) return
    setDownloadingPdf(true)
    const formData = new FormData()
    selectedImages.forEach(image => formData.append('images', image))
    imageTypes.forEach(type => formData.append('label_types', type))
    try {
      const resp = await api.post('/api/inspect/report', formData, {
        responseType: 'blob',
        timeout: 600000,
      })
      const url = window.URL.createObjectURL(new Blob([resp.data]))
      const a = document.createElement('a')
      a.href = url
      a.download = `LegalMatrix-Report-${result.inspection_id}.pdf`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      a.remove()
      toast.success('PDF report downloaded!')
    } catch (err) {
      console.error('PDF download failed:', err)
      toast.error('Failed to download PDF report')
    } finally {
      setDownloadingPdf(false)
    }
  }

  const handleDownloadCertificate = async () => {
    if (!result) return
    setDownloadingCert(true)
    try {
      await downloadBlob(
        `/api/inspect/${result.inspection_id}/certificate`,
        `LegalMatrix-Certificate-${result.inspection_id}.pdf`,
      )
      toast.success('Certificate downloaded!')
    } catch (err) {
      console.error('Certificate download failed:', err)
      toast.error('Failed to download certificate')
    } finally {
      setDownloadingCert(false)
    }
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

  const getScoreColor = (score: number) => {
    if (score >= 80) return 'text-green-600'
    if (score >= 50) return 'text-yellow-600'
    return 'text-red-600'
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'COMPLIANT': return 'text-green-600 bg-green-50 border-green-200'
      case 'REVIEW_REQUIRED': return 'text-yellow-600 bg-yellow-50 border-yellow-200'
      case 'POTENTIAL_VIOLATION': return 'text-red-600 bg-red-50 border-red-200'
      default: return 'text-gray-600 bg-gray-50 border-gray-200'
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'COMPLIANT': return <CheckCircle className="w-6 h-6 text-green-600" />
      case 'REVIEW_REQUIRED': return <Clock className="w-6 h-6 text-yellow-600" />
      case 'POTENTIAL_VIOLATION': return <AlertCircle className="w-6 h-6 text-red-600" />
      default: return null
    }
  }

  const getSeverityStyle = (sev: string) => {
    switch (sev) {
      case 'CRITICAL': return 'bg-red-100 text-red-800 border-red-300'
      case 'HIGH': return 'bg-orange-100 text-orange-800 border-orange-300'
      case 'MEDIUM': return 'bg-yellow-100 text-yellow-800 border-yellow-300'
      default: return 'bg-gray-100 text-gray-600 border-gray-300'
    }
  }

  const score = result?.compliance_score ?? 0
  const circumference = 2 * Math.PI * 45
  const dashoffset = circumference - (score / 100) * circumference

  // Per-label-type bookkeeping over the flat image list (order = append order).
  const counts: Record<LabelType, number> = { front: 0, back: 0, side: 0, top: 0, other: 0 }
  imageTypes.forEach((t) => { counts[t] = (counts[t] || 0) + 1 })
  const totalImages = selectedImages.length
  const typeRange = (type: LabelType) => {
    let start = 0
    for (const t of LABEL_TYPES) {
      if (t.id === type) return { start, len: counts[t.id] }
      start += counts[t.id]
    }
    return { start: 0, len: 0 }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <div className="max-w-4xl mx-auto p-4 sm:p-6">
      <Toaster position="top-right" />

      <header className="text-center mb-8">
        <div className="flex items-center justify-center gap-3 mb-2">
          <Shield className="w-8 h-8 text-blue-600" />
          <h1 className="text-3xl font-bold text-gray-900">LegalMatrix</h1>
        </div>
        <p className="text-gray-600">AI-Powered Legal Metrology Inspection</p>
      </header>

      {/* Upload / Capture Section */}
      <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-6">
        <h2 className="text-lg font-semibold text-gray-800 mb-1">Capture or Upload Product Images</h2>
        <p className="text-sm text-gray-500 mb-4">
          Add photos per label type (up to {MAX_IMAGES} total · {totalImages} added). The inspection routes each
          field to the right photo — product name from the <span className="font-medium text-gray-700">front</span>,
          declarations from the <span className="font-medium text-gray-700">back</span>.
        </p>

        {/* Camera View */}
        {cameraActive && (
          <div className="mb-4 rounded-lg overflow-hidden border border-gray-300 relative">
            <div className="absolute top-3 left-0 right-0 flex justify-center">
              <span className="bg-black/70 text-white text-xs font-semibold px-3 py-1 rounded-full">
                Capturing for: {LABEL_TYPES.find(t => t.id === captureTarget)?.label ?? captureTarget}
              </span>
            </div>
            <video ref={videoRef} className="w-full max-h-[400px] object-contain bg-black" autoPlay playsInline muted />
            <canvas ref={canvasRef} className="hidden" />
            <div className="absolute bottom-3 left-0 right-0 flex justify-center gap-3">
              <button
                onClick={capturePhoto}
                className="px-6 py-3 bg-green-600 text-white rounded-full hover:bg-green-700 shadow-lg flex items-center gap-2 font-semibold"
              >
                <Camera className="w-5 h-5" /> Capture
              </button>
              <button
                onClick={stopCamera}
                className="px-4 py-3 bg-gray-700 text-white rounded-full hover:bg-gray-800 shadow-lg flex items-center gap-2"
              >
                <X className="w-5 h-5" /> Close
              </button>
            </div>
          </div>
        )}

        {/* Per-label-type capture cards */}
        <div className="space-y-3">
          {LABEL_TYPES.map((lt) => {
            const { start, len } = typeRange(lt.id)
            return (
              <div
                key={lt.id}
                className={`border rounded-xl p-4 transition-colors ${
                  len > 0 ? 'border-blue-300 bg-blue-50/50' : 'border-gray-200 bg-white'
                }`}
              >
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <h3 className="text-sm font-semibold text-gray-800">{lt.label}</h3>
                    <p className="text-xs text-gray-500">{lt.desc}</p>
                    <p className={`text-xs mt-0.5 ${len > 0 ? 'text-blue-600 font-medium' : 'text-gray-400'}`}>
                      {len} photo{len !== 1 ? 's' : ''}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    {!cameraActive && (
                      <button
                        onClick={() => startCamera(lt.id)}
                        className="px-3 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-xs flex items-center gap-1.5 font-semibold"
                      >
                        <Camera className="w-4 h-4" /> Capture
                      </button>
                    )}
                    <label className="cursor-pointer">
                      <div className="px-3 py-2 border border-gray-300 bg-white text-gray-700 rounded-lg hover:border-blue-500 hover:text-blue-600 text-xs flex items-center gap-1.5 font-semibold">
                        <Upload className="w-4 h-4" /> Upload
                      </div>
                      <input
                        type="file"
                        accept="image/*"
                        multiple
                        className="hidden"
                        onChange={(e) => handleImageSelect(e, lt.id)}
                      />
                    </label>
                  </div>
                </div>

                {len > 0 && (
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 mt-3">
                    {imagePreviews.slice(start, start + len).map((preview, i) => {
                      const flatIdx = start + i
                      return (
                        <div key={flatIdx} className="relative rounded-lg border border-gray-200 overflow-hidden bg-white">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={preview || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="200" height="200"%3E%3Crect width="200" height="200" fill="%23f3f4f6"/%3E%3Ctext x="100" y="100" font-family="sans-serif" font-size="14" fill="%236b7280" text-anchor="middle" dy=".3em"%3ENo Image%3C/text%3E%3C/svg%3E'}
                            alt={`${lt.label} photo ${i + 1}`}
                            title="Click to enlarge and verify"
                            onClick={() => preview && setViewingPreview(flatIdx)}
                            className="w-full h-32 object-contain bg-gray-50 cursor-pointer"
                          />
                          <span className="absolute top-2 left-2 text-[10px] font-bold px-2 py-0.5 rounded bg-black/60 text-white">
                            {lt.id} · {i + 1}
                          </span>
                          <div className="group absolute inset-0 hover:bg-black/20 transition-all flex items-center justify-center">
                            <button
                              onClick={() => removeImage(flatIdx)}
                              className="opacity-0 group-hover:opacity-100 transition-opacity bg-red-600 text-white p-1.5 rounded-full"
                              title="Remove image"
                            >
                              <X className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {loading && (
          <p className="text-xs text-gray-500 mt-3">
            Vision-model inspection typically takes 1-3 min per image. The request is in flight.
          </p>
        )}

        {/* Same-product confirmation */}
        {totalImages > 0 && (
          <label className="mt-4 flex items-start gap-3 bg-blue-50 border border-blue-200 rounded-lg p-4 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={sameProduct}
              onChange={(e) => setSameProduct(e.target.checked)}
              className="mt-0.5 w-4 h-4 accent-blue-600"
            />
            <span className="text-sm text-gray-800">
              I confirm all {totalImages} photo{totalImages !== 1 ? 's' : ''} show the{' '}
              <span className="font-semibold">same product</span> being inspected.
              <span className="block text-xs text-gray-500 mt-0.5">
                Required before analyzing — mixing photos of different products gives a misleading compliance score.
              </span>
            </span>
          </label>
        )}

        {/* Analyze */}
        <div className="mt-4 flex items-center gap-3 flex-wrap">
          <button
            onClick={handleUpload}
            disabled={totalImages === 0 || loading || !sameProduct}
            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 min-w-[140px]"
          >
            {loading ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent" />
                Analyzing... {elapsed}s
              </>
            ) : (
              <>
                <Scan className="w-4 h-4" />
                Analyze
              </>
            )}
          </button>
          {totalImages > 0 && !sameProduct && (
            <p className="text-xs text-amber-600">Confirm the photos show the same product, then analyze.</p>
          )}
        </div>
      </section>

      {/* Results Section */}
      {result && (
        <section className="space-y-4">
          {/* Status + Compliance Score Row */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Status Card */}
            <div className={`md:col-span-2 rounded-xl border p-6 ${getStatusColor(result.status)}`}>
              <div className="flex items-center gap-3">
                {getStatusIcon(result.status)}
                <div>
                  <h3 className="font-semibold text-lg">Status: {result.status.replace(/_/g, ' ')}</h3>
                  <p className="text-sm opacity-80">
                    ID: {result.inspection_id} | {result.images_processed} image(s) processed
                    {result.method && <span className="ml-1">| Model: {result.method}</span>}
                  </p>
                </div>
              </div>
            </div>

            {/* Compliance Score Circle */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 flex flex-col items-center justify-center">
              <svg width="100" height="100" className="transform -rotate-90">
                <circle cx="50" cy="50" r="45" fill="none" stroke="#e5e7eb" strokeWidth="8" />
                <circle
                  cx="50" cy="50" r="45" fill="none"
                  stroke={score >= 80 ? '#22c55e' : score >= 50 ? '#eab308' : '#dc2626'}
                  strokeWidth="8"
                  strokeDasharray={circumference}
                  strokeDashoffset={dashoffset}
                  strokeLinecap="round"
                  className="transition-all duration-1000"
                />
              </svg>
              <div className="absolute flex flex-col items-center justify-center" style={{ marginTop: '10px' }}>
                <span className={`text-2xl font-bold ${getScoreColor(score)}`}>{score}%</span>
                <span className="text-[10px] text-gray-500">Compliance</span>
              </div>
              <p className="text-xs text-gray-500 mt-2">
                {result.passed_count}/{result.total_rules} rules passed
              </p>
            </div>
          </div>

          {/* Compliance Radar */}
          {result.compliance_radar && (
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
              <h3 className="font-semibold text-gray-800 mb-4">Compliance Radar</h3>
              <RadarChart radar={result.compliance_radar} />
              <p className="mt-3 text-xs text-gray-400 leading-relaxed">
                Axes weighed by legal impact (declarations 30%, pricing 20%, dates 10%,
                consumer care 10%, font size 20%, readability 10%). The font-size axis is
                excluded when no calibration reference (credit card / barcode) is present.
              </p>
            </div>
          )}

          {/* Compliance heat-map overlay */}
          {result.heatmaps && result.heatmaps.length > 0 && (
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
              <h3 className="font-semibold text-gray-800 mb-1">Compliance Heat-Map</h3>
              <p className="text-xs text-gray-500 mb-4">
                Verdicts drawn back onto the photo — green = compliant, red = violation,
                yellow = low confidence, cyan = calibration reference.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {result.heatmaps.map((h, i) => (
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
            </div>
          )}

          {/* Extracted Declarations (editable — corrections re-score instantly) */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h3 className="font-semibold text-gray-800 mb-1">Extracted Declarations</h3>
            {result.extraction_confidence != null && (
              <div className="mb-3 flex items-center gap-2 text-xs">
                <span className="font-medium text-gray-500">Extraction confidence</span>
                <span
                  className={`font-bold ${
                    result.extraction_confidence.overall >= 70
                      ? 'text-green-600'
                      : result.extraction_confidence.overall >= 40
                        ? 'text-yellow-600'
                        : 'text-red-600'
                  }`}
                >
                  {result.extraction_confidence.overall}%
                </span>
                <span className="text-gray-400">
                  ({result.extraction_confidence.fields_present}/
                  {result.extraction_confidence.fields_required} required fields)
                </span>
              </div>
            )}
            {canEdit ? (
              <p className="text-xs text-gray-500 mb-3">
                Click the pencil icon to correct a misread value. Saving re-runs the
                compliance check and score immediately, and the correction is stored
                with the inspection (original AI value kept for audit).
              </p>
            ) : (
              <p className="text-xs text-gray-500 mb-3">
                Sign in as ADMIN / INSPECTOR to correct misread values.
              </p>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {Object.entries(result.declarations ?? {}).map(([key, value]) => {
                const overridden = result.manual_overrides?.[key]
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
                          CORRECTED
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
                        <span className={`text-sm block break-words ${value ? 'text-gray-900' : 'text-red-400 italic'}`}>
                          {value || 'Not detected'}
                        </span>
                        {overridden && (
                          <p className="text-[11px] text-gray-400 mt-0.5">
                            Original (AI): &quot;{overridden.original || ''}&quot;
                          </p>
                        )}
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
            <p className="mt-3 text-xs text-gray-500">
              Corrections save automatically to inspection{' '}
              <span className="font-mono">{result.inspection_id}</span> —{' '}
              <Link href={`/inspection/${result.inspection_id}`} className="text-blue-600 hover:underline font-medium">
                open the full report
              </Link>{' '}
              for evidence photos, heat-maps and exports.
            </p>
          </div>

          {/* Rule Violations */}
          {result.violations && result.violations.length > 0 && (
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
              <h3 className="font-semibold text-gray-800 mb-4 flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-orange-500" />
                Rule Violations ({result.violations.length})
              </h3>
              <div className="space-y-3">
                {result.violations.map((v, idx) => (
                  <div key={idx} className={`border rounded-lg p-4 ${getSeverityStyle(v.severity)}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs font-bold px-2 py-0.5 rounded bg-white/60 border">
                            {v.severity}
                          </span>
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
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* No violations */}
          {result.violations && result.violations.length === 0 && (
            <div className="bg-green-50 rounded-xl border border-green-200 p-6 text-center">
              <CheckCircle className="w-10 h-10 text-green-600 mx-auto mb-2" />
              <p className="font-semibold text-green-800">All Rules Passed</p>
              <p className="text-sm text-green-600">No compliance violations detected.</p>
            </div>
          )}

          {/* Consistency checks (possible misleading declarations) */}
          {result.misleading_checks && result.misleading_checks.length > 0 && (
            <div className="bg-white rounded-xl shadow-sm border border-amber-200 p-6">
              <h3 className="font-semibold text-gray-800 mb-4 flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-amber-600" />
                Consistency Checks ({result.misleading_checks.length})
              </h3>
              <div className="space-y-3">
                {result.misleading_checks.map((c, idx) => (
                  <div key={idx} className="border rounded-lg p-4 bg-amber-50 border-amber-200">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-bold px-2 py-0.5 rounded bg-white/60 border">
                        {c.severity}
                      </span>
                      <span className="text-xs font-mono font-semibold">{c.check}</span>
                    </div>
                    <p className="text-sm font-medium">{c.detail}</p>
                    {c.extracted_value && (
                      <p className="text-xs mt-1 opacity-70">Extracted: &quot;{c.extracted_value}&quot;</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Font Measurement */}
          {result.font_measurement && result.font_measurement.status !== 'CANNOT_MEASURE' && (
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
              <h3 className="font-semibold text-gray-800 mb-4">Font Measurement</h3>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                <div>
                  <p className="text-xs text-gray-500">Measured</p>
                  <p className="text-lg font-semibold">{result.font_measurement.measured_mm ?? '—'} mm</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Required</p>
                  <p className="text-lg font-semibold">{result.font_measurement.required_mm ?? '—'} mm</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Uncertainty</p>
                  <p className="text-lg font-semibold">±{result.font_measurement.uncertainty ?? '—'} mm</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Status</p>
                  <p className={`text-lg font-semibold ${
                    result.font_measurement.status === 'COMPLIANT' ? 'text-green-600' :
                    result.font_measurement.status === 'REVIEW_REQUIRED' ? 'text-yellow-600' :
                    'text-red-600'
                  }`}>
                    {result.font_measurement.status.replace(/_/g, ' ')}
                  </p>
                </div>
              </div>
              {result.font_measurement.implausible && (
                <p className="mt-2 text-xs text-yellow-700 bg-yellow-50 border border-yellow-200 rounded px-2 py-1">
                  Reading flagged implausible relative to the legal minimum — manual review.
                </p>
              )}
              <p className="mt-2 text-[11px] text-gray-400">
                Calibration: {result.font_measurement.calibration ?? '—'}
                {result.font_measurement.ppm != null && ` at ${result.font_measurement.ppm} px/mm`}
                {' · '}Method: {result.font_measurement.method ?? '—'}
                {result.font_measurement.image_index != null &&
                  ` · Measured from photo #${result.font_measurement.image_index + 1}`}
</p>
            </div>
          )}

          {result.font_measurement && result.font_measurement.status === 'CANNOT_MEASURE' && (
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
              <h3 className="font-semibold text-gray-800 mb-2">Font Measurement</h3>
              <p className="text-sm text-gray-700">
                Cannot measure — manual review required.
              </p>
              {result.font_measurement.calibration_rejected_reason && (
                <p className="mt-1 text-xs text-gray-500">
                  Reason: {result.font_measurement.calibration_rejected_reason}
                </p>
              )}
            </div>
          )}

          {/* Evidence Hash */}
          {result.evidence?.hash && (
            <div className="bg-gray-50 rounded-xl border border-gray-200 p-4">
              <h3 className="font-semibold text-gray-700 text-sm mb-2">Evidence Hash</h3>
              <div className="flex flex-col sm:flex-row gap-2 text-xs text-gray-500 break-all">
                <span className="font-medium">SHA-256:</span>
                <span>{result.evidence.hash}</span>
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div className="flex gap-3">
            <button
              onClick={handleDownloadPdf}
              disabled={downloadingPdf}
              className="flex-1 py-3 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-2 font-semibold"
            >
              {downloadingPdf ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent" />
                  Generating PDF...
                </>
              ) : (
                <>
                  <Download className="w-4 h-4" />
                  Download PDF Report
                </>
              )}
            </button>
            <button
              onClick={handleDownloadCertificate}
              disabled={downloadingCert}
              className="flex-1 py-3 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-2 font-semibold"
            >
              {downloadingCert ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent" />
                  Generating Certificate...
                </>
              ) : (
                <>
                  <Shield className="w-4 h-4" />
                  Certificate
                </>
              )}
            </button>
            <button
              onClick={() => {
                setResult(null)
                setSelectedImages([])
                setImagePreviews([])
                setDrafts({})
                setEditing({})
                setSavingFields({})
                setSameProduct(false)
                setHeatmapUrls([])
              }}
              className="flex-1 py-3 text-sm text-gray-600 hover:text-gray-800 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors flex items-center justify-center gap-2"
            >
              New Inspection
            </button>
          </div>
        </section>
      )}
      </div>

      {/* Full-size image viewer (verify same product before analysing) */}
      {viewingPreview !== null && (
        <div
          className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-4"
          onClick={() => setViewingPreview(null)}
        >
          <div className="relative max-h-full max-w-5xl" onClick={(e) => e.stopPropagation()}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={imagePreviews[viewingPreview]}
              alt={`Product image ${viewingPreview + 1} full view`}
              className="max-h-[85vh] max-w-full rounded-lg shadow-2xl bg-white object-contain"
            />
            <div className="mt-3 flex items-center justify-between gap-3">
              <p className="text-white/90 text-sm">
                Photo {viewingPreview + 1}
                {selectedImages[viewingPreview] && (
                  <span className="opacity-70"> — {selectedImages[viewingPreview].name}</span>
                )}
              </p>
              <button
                onClick={() => setViewingPreview(null)}
                className="px-4 py-2 bg-white text-gray-900 rounded-lg font-semibold text-sm hover:bg-gray-200"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
