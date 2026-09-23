'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Camera, Upload, X, Scan, CheckCircle2, Loader2, ScanLine, FileText, FileCheck2,
  Tag, ClipboardList, Package, ArrowUpFromLine, Paperclip,
  type LucideIcon,
} from 'lucide-react'
import toast, { Toaster } from 'react-hot-toast'
import AppShell from '@/app/components/AppShell'
import Card from '@/app/components/ui/Card'
import { api, apiError } from '@/app/lib/api'

type LabelType = 'front' | 'back' | 'side' | 'top' | 'other'

const LABEL_TYPES: { id: LabelType; label: string; desc: string; icon: LucideIcon }[] = [
  { id: 'front', label: 'Front Label (PDP)', desc: 'Brand face & product name', icon: Tag },
  { id: 'back', label: 'Back Label', desc: 'MRP, net qty, manufacturer', icon: ClipboardList },
  { id: 'side', label: 'Side Label', desc: 'Nutrition / extra dates', icon: Package },
  { id: 'top', label: 'Top / Cap Label', desc: 'Batch no, use-by, MRP', icon: ArrowUpFromLine },
  { id: 'other', label: 'Other Packaging', desc: 'Seals, barcodes', icon: Paperclip },
]

const MAX_IMAGES = 6

const ANALYZE_STEPS: { label: string; desc: string; Icon: LucideIcon }[] = [
  { label: 'Uploading photos', desc: 'Validating images and format', Icon: Upload },
  { label: 'Reading label fields', desc: 'OCR extraction of declarations', Icon: ScanLine },
  { label: 'Verifying rules', desc: 'Checking against Legal Metrology rules', Icon: FileText },
  { label: 'Finalizing report', desc: 'Scoring and evidence pack', Icon: FileCheck2 },
]

export default function Home() {
  const router = useRouter()
  const [selectedImages, setSelectedImages] = useState<File[]>([])
  const [imageTypes, setImageTypes] = useState<LabelType[]>([])
  const [imagePreviews, setImagePreviews] = useState<string[]>([])
  const [captureTarget, setCaptureTarget] = useState<LabelType>('front')
  const [loading, setLoading] = useState(false)
  const [elapsed, setElapsed] = useState(0)
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
        if (!dataUrl) toast.error(`Couldn't preview "${file.name}"`)
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
    setElapsed(0)

    if (timerRef.current) clearInterval(timerRef.current)
    timerRef.current = setInterval(() => setElapsed(s => s + 1), 1000)

    const formData = new FormData()
    selectedImages.forEach(image => formData.append('images', image))
    imageTypes.forEach(type => formData.append('label_types', type))

    try {
      const response = await api.post('/api/inspect', formData, { timeout: 600000 })
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
      toast.success('Inspection completed!')
      if (response.data?.inspection_id) {
        router.push(`/inspection/${response.data.inspection_id}`)
        return
      }
      toast.error('Inspection completed but no report ID was returned.')
      setLoading(false)
    } catch (error: unknown) {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
      console.error('Error:', error)
      const msg =
        (error as { code?: string } | null)?.code === 'ECONNABORTED'
          ? 'Request timed out. The vision model can take several minutes.'
          : apiError(error, 'Failed to inspect images.')
      toast.error(msg)
      setLoading(false)
    }
  }

  // Per-label-type bookkeeping
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

  // Analyzing checklist — advances roughly every 30s of processing time
  const activeStep = loading
    ? Math.min(ANALYZE_STEPS.length - 1, Math.floor(elapsed / 30))
    : -1

  return (
    <AppShell>
      <Toaster position="top-right" />
      <div className="max-w-md sm:max-w-lg lg:max-w-2xl mx-auto px-4 py-6 space-y-5">
        {/* Header */}
        <header className="text-center">
          <h1 className="text-xl font-bold text-text-primary tracking-tight">
            New Inspection
          </h1>
          <p className="text-sm text-text-secondary mt-1">
            Photograph the product labels for AI compliance analysis
          </p>
        </header>

        {/* Upload / Capture Section */}
        <Card>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-semibold text-text-primary">
                Product Photos
              </h2>
              <p className="text-xs text-text-secondary mt-0.5">
                Capture or upload up to {MAX_IMAGES} images
              </p>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-text-muted">
              <span
                className={`mono font-semibold ${
                  totalImages > 0 ? 'text-accent' : 'text-text-muted'
                }`}
              >
                {totalImages}
              </span>
              <span>/</span>
              <span className="mono">{MAX_IMAGES}</span>
            </div>
          </div>

          {/* Progress indicator */}
          <div className="h-1.5 bg-surface-hover rounded-full overflow-hidden mb-5">
            <div
              className="h-full bg-accent rounded-full transition-all duration-300"
              style={{ width: `${(totalImages / MAX_IMAGES) * 100}%` }}
              role="progressbar"
              aria-valuenow={totalImages}
              aria-valuemax={MAX_IMAGES}
              aria-label={`${totalImages} of ${MAX_IMAGES} images uploaded`}
            />
          </div>

          {/* Camera View */}
          {cameraActive && (
            <div className="mb-5 rounded-xl overflow-hidden border border-surface-border relative bg-black">
              <div className="absolute top-3 left-0 right-0 flex justify-center z-10">
                <span className="bg-black/70 text-white text-xs font-semibold px-3 py-1 rounded-full">
                  Capturing: {LABEL_TYPES.find(t => t.id === captureTarget)?.label}
                </span>
              </div>
              <video ref={videoRef} className="w-full max-h-[400px] object-contain" autoPlay playsInline muted />
              <canvas ref={canvasRef} className="hidden" />
              <div className="absolute bottom-3 left-0 right-0 flex justify-center gap-3 z-10">
                <button
                  onClick={capturePhoto}
                  className="btn-success btn-pill"
                >
                  <Camera className="w-5 h-5" /> Capture
                </button>
                <button
                  onClick={stopCamera}
                  className="btn-secondary btn-pill"
                >
                  <X className="w-5 h-5" /> Close
                </button>
              </div>
            </div>
          )}

          {/* Label type cards */}
          <div className="space-y-3">
            {LABEL_TYPES.map((lt, ltIndex) => {
              const { start, len } = typeRange(lt.id)
              const TypeIcon = lt.icon
              return (
                <div
                  key={lt.id}
                  className={`rounded-xl p-4 transition-all border animate-reveal ${
                    len > 0
                      ? 'border-accent/30 bg-accent-soft/60'
                      : 'border-surface-border bg-surface hover:bg-surface-hover hover:border-accent/35'
                  }`}
                  style={{ animationDelay: `${ltIndex * 50}ms` }}
                >
                  <div className="flex items-start justify-between gap-3 flex-wrap">
                    <div className="flex items-start gap-3 min-w-0">
                      <span className="flex items-center justify-center w-10 h-10 rounded-xl bg-surface border border-surface-border shrink-0">
                        <TypeIcon className="w-5 h-5 text-accent" aria-hidden="true" />
                      </span>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <h3 className="text-sm font-semibold text-text-primary">{lt.label}</h3>
                          {len > 0 && (
                            <span className="inline-flex items-center justify-center min-w-5 h-5 px-1 rounded-full bg-accent text-white text-[10px] font-bold mono">
                              {len}
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-text-muted mt-0.5">{lt.desc}</p>
                      </div>
                    </div>
                    <div className="flex gap-2 shrink-0">
                      {!cameraActive && (
                        <button
                          onClick={() => startCamera(lt.id)}
                          className="btn-success-soft btn-sm"
                        >
                          <Camera className="w-4 h-4" /> Capture
                        </button>
                      )}
                      <input
                        id={`upload-${lt.id}`}
                        type="file"
                        accept="image/*"
                        multiple
                        className="peer sr-only"
                        onChange={(e) => {
                          handleImageSelect(e, lt.id)
                          e.target.value = ''
                        }}
                      />
                      <label
                        htmlFor={`upload-${lt.id}`}
                        className="btn btn-secondary btn-sm cursor-pointer peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent"
                      >
                        <Upload className="w-4 h-4" aria-hidden="true" /> Upload
                      </label>
                    </div>
                  </div>

                  {/* Image previews */}
                  {len > 0 && (
                    <div className="grid grid-cols-2 gap-3 mt-3">
                      {imagePreviews.slice(start, start + len).map((preview, i) => {
                        const flatIdx = start + i
                        return (
                          <div key={flatIdx} className="relative rounded-lg border border-surface-border overflow-hidden bg-surface group">
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img
                              src={preview || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="200" height="200"%3E%3Crect width="200" height="200" fill="%23f0f3f8"/%3E%3Ctext x="100" y="100" font-family="sans-serif" font-size="14" fill="%238792a5" text-anchor="middle" dy=".3em"%3ENo Image%3C/text%3E%3C/svg%3E'}
                              alt={`${lt.label} photo ${i + 1}`}
                              onClick={() => preview && setViewingPreview(flatIdx)}
                              className="w-full h-32 object-contain cursor-pointer"
                            />
                            <span className="absolute top-2 left-2 text-[10px] font-bold px-2 py-0.5 rounded bg-black/60 text-white">
                              {lt.id} · {i + 1}
                            </span>
                            <button
                              onClick={() => removeImage(flatIdx)}
                              className="absolute top-2 right-2 bg-danger text-white p-1 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                              title="Remove image"
                            >
                              <X className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* Analyzing checklist */}
          {loading && (
            <div className="mt-5 p-4 rounded-xl bg-bg-secondary border border-surface-border" aria-live="polite">
              <div className="flex items-center gap-3 mb-2">
                <Loader2 className="w-5 h-5 text-accent animate-spin shrink-0" />
                <div>
                  <p className="text-sm font-semibold text-text-primary">Analyzing… {elapsed}s</p>
                  <p className="text-xs text-text-muted">Vision model typically takes 1–3 min per image</p>
                </div>
              </div>
              <div
                className="h-1.5 bg-surface rounded-full overflow-hidden mb-3"
                role="progressbar"
                aria-valuenow={activeStep + 1}
                aria-valuemin={1}
                aria-valuemax={ANALYZE_STEPS.length}
                aria-label="Analysis progress"
              >
                <div
                  className="h-full bg-accent rounded-full transition-all duration-700 ease-out"
                  style={{ width: `${((activeStep + 1) / ANALYZE_STEPS.length) * 100}%` }}
                />
              </div>
              <ul className="space-y-2.5">
                {ANALYZE_STEPS.map((step, i) => {
                  const { label, desc, Icon } = step
                  if (i < activeStep) {
                    return (
                      <li key={label} className="flex items-start gap-2.5">
                        <CheckCircle2 className="w-4 h-4 text-success shrink-0 mt-0.5" />
                        <div className="min-w-0">
                          <p className="text-sm text-text-primary">{label}</p>
                          <p className="text-[11px] text-text-muted">{desc}</p>
                        </div>
                      </li>
                    )
                  }
                  if (i === activeStep) {
                    return (
                      <li key={label} className="flex items-start gap-2.5 animate-[step-pulse_1.6s_ease-in-out_infinite]">
                        <Icon className="w-4 h-4 text-accent shrink-0 mt-0.5" />
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-text-primary">{label}</p>
                          <p className="text-[11px] text-text-muted">{desc}</p>
                        </div>
                      </li>
                    )
                  }
                  return (
                    <li key={label} className="flex items-start gap-2.5 opacity-50">
                      <Icon className="w-4 h-4 text-text-muted shrink-0 mt-0.5" />
                      <div className="min-w-0">
                        <p className="text-sm text-text-secondary">{label}</p>
                        <p className="text-[11px] text-text-muted">{desc}</p>
                      </div>
                    </li>
                  )
                })}
              </ul>
            </div>
          )}

          {/* Same-product confirmation */}
          {totalImages > 0 && !loading && (
            <label className="mt-4 flex items-start gap-3 p-4 rounded-xl bg-surface border border-surface-border cursor-pointer select-none hover:bg-surface-hover transition-colors">
              <input
                type="checkbox"
                checked={sameProduct}
                onChange={(e) => setSameProduct(e.target.checked)}
                className="mt-0.5 w-4 h-4 accent-accent"
              />
              <span className="text-sm text-text-primary">
                I confirm all {totalImages} photo{totalImages !== 1 ? 's' : ''} show the{' '}
                <span className="font-semibold">same product</span> being inspected.
                <span className="block text-xs text-text-muted mt-0.5">
                  Required before analyzing — mixing different products gives a misleading compliance score.
                </span>
              </span>
            </label>
          )}

          {/* Analyze button */}
          <div className="mt-4 flex flex-col gap-3">
            <button
              onClick={handleUpload}
              disabled={totalImages === 0 || loading || !sameProduct}
              className="btn-primary w-full flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Analyzing… {elapsed}s
                </>
              ) : (
                <>
                  <Scan className="w-4 h-4" />
                  Analyze
                </>
              )}
            </button>
            {totalImages > 0 && !sameProduct && !loading && (
              <p className="text-xs text-warning text-center">
                Confirm same product, then analyze.
              </p>
            )}
          </div>
        </Card>
      </div>

      {/* Full-size image viewer */}
      {viewingPreview !== null && (
        <div
          className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-4"
          onClick={() => setViewingPreview(null)}
          role="dialog"
          aria-label="Image preview"
        >
          <div className="relative max-h-full max-w-5xl" onClick={(e) => e.stopPropagation()}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={imagePreviews[viewingPreview]}
              alt={`Product image ${viewingPreview + 1} full view`}
              className="max-h-[85vh] max-w-full rounded-lg shadow-2xl object-contain"
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
                className="btn-overlay btn-sm"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  )
}