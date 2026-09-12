'use client'

import { useEffect, useRef, useState } from 'react'
import {
  Camera, Upload, Shield, CheckCircle, AlertCircle,
  Clock, X, Download, Scan, AlertTriangle,
} from 'lucide-react'
import toast, { Toaster } from 'react-hot-toast'
import Navbar from '@/app/components/Navbar'
import { api, apiError } from '@/app/lib/api'

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
  evidence?: {
    hash: string
  }
  message?: string
}

export default function Home() {
  const [selectedImages, setSelectedImages] = useState<File[]>([])
  const [imagePreviews, setImagePreviews] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [result, setResult] = useState<InspectionResult | null>(null)
  const [downloadingPdf, setDownloadingPdf] = useState(false)
  const [cameraActive, setCameraActive] = useState(false)
  const [sameProduct, setSameProduct] = useState(false)
  const [viewingPreview, setViewingPreview] = useState<number | null>(null)
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

  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } },
      })
      streamRef.current = stream
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
      if (selectedImages.length >= 3) {
        toast.error('Maximum 3 images allowed')
        return
      }
      const newImages = [...selectedImages, file]
      setSelectedImages(newImages)
      setSameProduct(false)
      const idx = newImages.length - 1
      createPreview(file, (dataUrl) => {
        setImagePreviews(prev => {
          const next = [...prev]
          next[idx] = dataUrl
          return next
        })
      })
      toast.success(`Photo ${newImages.length} captured!`)
    }, 'image/jpeg', 0.92)
  }

  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    if (files.length === 0) return
    if (selectedImages.length + files.length > 3) {
      toast.error('Maximum 3 images allowed')
      return
    }

    const newImages = [...selectedImages, ...files]
    setSelectedImages(newImages)
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
    setElapsed(0)

    if (timerRef.current) clearInterval(timerRef.current)
    timerRef.current = setInterval(() => setElapsed(s => s + 1), 1000)

    const formData = new FormData()
    selectedImages.forEach(image => formData.append('images', image))

    try {
      const response = await api.post('/api/inspect', formData, { timeout: 600000 })
      setResult(response.data)
      toast.success('Inspection completed!')
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

  const handleDownloadPdf = async () => {
    if (!result || selectedImages.length === 0) return
    setDownloadingPdf(true)
    const formData = new FormData()
    selectedImages.forEach(image => formData.append('images', image))
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
        <h2 className="text-lg font-semibold text-gray-800 mb-4">Capture or Upload Product Images</h2>
        <p className="text-sm text-gray-500 mb-4">Upload or take 1-3 photos of the product label</p>

        {/* Camera View */}
        {cameraActive && (
          <div className="mb-4 rounded-lg overflow-hidden border border-gray-300 relative">
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

        <div className="flex flex-col sm:flex-row gap-3">
          {!cameraActive && (
            <button
              onClick={startCamera}
              className="px-5 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors flex items-center justify-center gap-2"
            >
              <Camera className="w-4 h-4" /> Open Camera
            </button>
          )}

          <label className="flex-1 cursor-pointer">
            <div className="border-2 border-dashed border-gray-300 rounded-lg p-4 text-center hover:border-blue-500 transition-colors">
              <input
                type="file"
                accept="image/*"
                multiple
                onChange={handleImageSelect}
                className="hidden"
              />
              <Upload className="w-6 h-6 mx-auto text-gray-400 mb-1" />
              <p className="text-sm text-gray-600">
                {selectedImages.length === 0
                  ? 'Click to select images'
                  : `${selectedImages.length}/3 image${selectedImages.length !== 1 ? 's' : ''} selected`}
              </p>
              <p className="text-xs text-gray-400 mt-1">JPG, PNG supported</p>
            </div>
          </label>

          <button
            onClick={handleUpload}
            disabled={selectedImages.length === 0 || loading || !sameProduct}
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
        </div>

        {loading && (
          <p className="text-xs text-gray-500 mt-3">
            Vision-model inspection typically takes 1-3 min per image. The request is in flight.
          </p>
        )}

        {/* Image Previews */}
        {imagePreviews.length > 0 && (
          <div className="mt-6">
            <h3 className="text-sm font-medium text-gray-700 mb-1">
              Selected Images ({imagePreviews.length})
            </h3>
            <p className="text-xs text-amber-600 mb-3">
              Verify every photo shows the <span className="font-semibold">same product</span> before analyzing.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {imagePreviews.map((preview, index) => (
                <div key={index} className="relative rounded-lg border border-gray-200 overflow-hidden bg-white">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={preview || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="200" height="200"%3E%3Crect width="200" height="200" fill="%23f3f4f6"/%3E%3Ctext x="100" y="100" font-family="sans-serif" font-size="14" fill="%236b7280" text-anchor="middle" dy=".3em"%3ENo Image%3C/text%3E%3C/svg%3E'}
                    alt={`Product image ${index + 1}`}
                    title="Click to enlarge and verify"
                    onClick={() => preview && setViewingPreview(index)}
                    className="w-full h-48 object-contain bg-gray-50 cursor-pointer"
                  />
                  <span className="absolute top-2 left-2 text-xs font-bold px-2 py-0.5 rounded bg-black/60 text-white">
                    Photo {index + 1}
                  </span>
                  <div className="group absolute inset-0 hover:bg-black/20 transition-all flex items-center justify-center">
                    <button
                      onClick={() => removeImage(index)}
                      className="opacity-0 group-hover:opacity-100 transition-opacity bg-red-600 text-white p-2 rounded-full"
                      title="Remove image"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <label className="mt-4 flex items-start gap-3 bg-blue-50 border border-blue-200 rounded-lg p-4 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={sameProduct}
                onChange={(e) => setSameProduct(e.target.checked)}
                className="mt-0.5 w-4 h-4 accent-blue-600"
              />
              <span className="text-sm text-gray-800">
                I confirm all {imagePreviews.length} photo{imagePreviews.length !== 1 ? 's' : ''}{' '}
                show the <span className="font-semibold">same product</span> being inspected.
                <span className="block text-xs text-gray-500 mt-0.5">
                  Required before analyzing — mixing photos of different products gives a misleading compliance score.
                </span>
              </span>
            </label>
          </div>
        )}
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

          {/* Extracted Declarations */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h3 className="font-semibold text-gray-800 mb-4">Extracted Declarations</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {Object.entries(result.declarations ?? {}).map(([key, value]) => (
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
              onClick={() => {
                setResult(null)
                setSelectedImages([])
                setImagePreviews([])
                setSameProduct(false)
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
