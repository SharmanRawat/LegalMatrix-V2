'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { ShieldCheck, ShieldX, ShieldAlert, Loader2, ArrowRight, CheckCircle2, XCircle } from 'lucide-react'
import AppShell from '@/app/components/AppShell'
import Card from '@/app/components/ui/Card'
import { api } from '@/app/lib/api'
import { useI18n } from '@/app/lib/i18n'

interface VerifyResult {
  found: boolean
  inspection_id: string
  product_name: string | null
  manufacturer: string | null
  status: string | null
  compliance_score: number | null
  created_at: string | null
  evidence_hash: string
  hash_match: boolean
}

type State =
  | { phase: 'loading' }
  | { phase: 'error'; message: string }
  | { phase: 'done'; data: VerifyResult }
  | { phase: 'missing' }

export default function VerifyClient() {
  const { t } = useI18n()
  const searchParams = useSearchParams()
  const [state, setState] = useState<State | null>(null)

  useEffect(() => {
    let cancelled = false
    const raw = searchParams.get('inspection_id') ?? ''
    if (!raw) {
      setState({ phase: 'missing' })
      return
    }
    // QR payload is "<inspection_id>|<evidence_hash>" — split defensively.
    const parts = raw.split('|')
    const inspectionId = parts[0]
    const hash = parts[1] ?? ''
    const query = new URLSearchParams({ inspection_id: inspectionId })
    if (hash) query.set('hash', hash)

    api
      .get(`/api/inspect/verify?${query.toString()}`, { timeout: 30000 })
      .then(({ data }: { data: VerifyResult }) => {
        if (!cancelled) setState({ phase: 'done', data })
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const resp = (err as { response?: { status?: number } })?.response
        if (resp?.status === 404) {
          setState({ phase: 'error', message: t('No inspection matches this certificate code.') })
        } else {
          setState({ phase: 'error', message: t('Verification service unavailable. Try again later.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [searchParams, t])

  return (
    <AppShell>
      <div className="max-w-2xl mx-auto px-4 sm:px-6 py-6 space-y-6">
        <Card className="p-6 sm:p-8">
          {state?.phase === 'missing' && (
            <div className="text-center space-y-4">
              <ShieldAlert className="w-12 h-12 mx-auto text-warning" />
              <h1 className="text-xl font-bold text-text-primary">{t('Certificate verification')}</h1>
              <p className="text-sm text-text-secondary">
                {t('Open a certificate QR code link to verify a LegalMatrix compliance certificate.')}
              </p>
              <Link
                href="/"
                className="inline-flex items-center gap-2 btn-primary"
              >
                {t('Try a new inspection')}
                <ArrowRight className="w-4 h-4" />
              </Link>
            </div>
          )}

          {state?.phase === 'loading' && (
            <div className="text-center space-y-4 py-8">
              <Loader2 className="w-10 h-10 mx-auto text-accent animate-spin" />
              <p className="text-sm text-text-secondary">{t('Verifying certificate…')}</p>
            </div>
          )}

          {state?.phase === 'error' && (
            <div className="text-center space-y-4">
              <ShieldX className="w-12 h-12 mx-auto text-danger" />
              <h1 className="text-xl font-bold text-text-primary">{t('Unable to verify')}</h1>
              <p className="text-sm text-text-secondary">{state.message}</p>
              <Link
                href="/"
                className="inline-flex items-center gap-2 btn-primary"
              >
                {t('Try a new inspection')}
                <ArrowRight className="w-4 h-4" />
              </Link>
            </div>
          )}

          {state?.phase === 'done' && <VerificationResult data={state.data} />}
        </Card>
      </div>
    </AppShell>
  )
}

function VerificationResult({ data }: { data: VerifyResult }) {
  const { t } = useI18n()
  const verified = data.hash_match
  const Icon = verified ? CheckCircle2 : data.found ? ShieldAlert : XCircle
  const iconColor = verified ? 'text-success' : 'text-warning'
  const badgeVariant = verified
    ? 'badge badge-success'
    : 'badge badge-warning'
  const summary = verified ? t('Authentic — certificate and evidence hash match.') : t('Certificate found, but the evidence hash does not match the stored record.')

  return (
    <div className="space-y-5">
      <div className="text-center space-y-3">
        <Icon className={`w-12 h-12 mx-auto ${iconColor}`} />
        <h1 className="text-xl font-bold text-text-primary">
          {verified ? t('Certificate verified') : t('Verification warning')}
        </h1>
        <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold ${badgeVariant}`}>
          <ShieldCheck className="w-3.5 h-3.5" />
          {verified ? t('Authentic') : t('Hash mismatch')}
        </span>
        <p className="text-sm text-text-secondary">{summary}</p>
      </div>

      <dl className="grid sm:grid-cols-2 gap-3 text-sm">
        <div className="rounded-lg bg-bg-secondary border border-surface-border p-3">
          <dt className="text-xs text-text-muted">{t('Inspection ID')}</dt>
          <dd className="font-mono font-semibold text-text-primary break-all">{data.inspection_id}</dd>
        </div>
        <div className="rounded-lg bg-bg-secondary border border-surface-border p-3">
          <dt className="text-xs text-text-muted">{t('Product')}</dt>
          <dd className="font-semibold text-text-primary">{data.product_name || '—'}</dd>
        </div>
        <div className="rounded-lg bg-bg-secondary border border-surface-border p-3">
          <dt className="text-xs text-text-muted">{t('Manufacturer')}</dt>
          <dd className="font-semibold text-text-primary">{data.manufacturer || '—'}</dd>
        </div>
        <div className="rounded-lg bg-bg-secondary border border-surface-border p-3">
          <dt className="text-xs text-text-muted">{t('Status / Score')}</dt>
          <dd className="font-semibold text-text-primary">
            {data.status || '—'}
            {typeof data.compliance_score === 'number' ? ` · ${data.compliance_score}/100` : ''}
          </dd>
        </div>
        <div className="rounded-lg bg-bg-secondary border border-surface-border p-3 sm:col-span-2">
          <dt className="text-xs text-text-muted">{t('Issued')}</dt>
          <dd className="font-semibold text-text-primary">{data.created_at ? new Date(data.created_at).toLocaleString() : '—'}</dd>
        </div>
        <div className="rounded-lg bg-bg-secondary border border-surface-border p-3 sm:col-span-2">
          <dt className="text-xs text-text-muted">{t('Evidence SHA-256')}</dt>
          <dd className="font-mono text-xs text-text-secondary break-all">{data.evidence_hash || '—'}</dd>
        </div>
      </dl>

      <Link
        href="/"
        className="flex items-center justify-center gap-2 btn-primary"
      >
        {t('Try a new inspection')}
        <ArrowRight className="w-4 h-4" />
      </Link>
    </div>
  )
}