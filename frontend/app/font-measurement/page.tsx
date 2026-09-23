'use client'

import Link from 'next/link'
import { Ruler, Scale, ShieldCheck, Eye, AlertTriangle, ArrowRight, Info, CheckCircle2 } from 'lucide-react'
import AppShell from '@/app/components/AppShell'
import Card from '@/app/components/ui/Card'
import { useI18n } from '@/app/lib/i18n'

export default function FontMeasurementPage() {
  const { t } = useI18n()

  const whatsThere = [
    {
      icon: Scale,
      title: t('Calibration chain (credit card → barcode → EXIF)'),
      body: t(
        'A physically traceable reference converts pixels to millimetres: an ISO/IEC 7810 card (85.60 × 53.98 mm) beside the product is the exact reference; a product barcode is coarser; phone EXIF camera-metrics is never an automated verdict.',
      ),
    },
    {
      icon: Eye,
      title: t('Honest measurement, never fabricated'),
      body: t(
        'When a calibration reference is present, numeral height is measured in millimetres with an explicit uncertainty band. When none is present, the axis is excluded from the score and reported as REVIEW_REQUIRED with an auditable reason — we never output a millimetre value we cannot defend.',
      ),
    },
    {
      icon: ShieldCheck,
      title: t('Defensibility gates on every reading'),
      body: t(
        'Each text region passes geometric and glyph sanity checks. A measured height outside the plausible range forces manual review, and the uncalibrated lower-half heuristic never produces an automated verdict.',
      ),
    },
  ]

  const planned = [
    t('Guided calibration-card capture flow in the capture UI — the inspector is told when a reference is missing.'),
    t('Per-field measured numeral height rendered on the PDF report and the compliance radar.'),
    t('Quantitative regression set of synthetic labels with known pixel heights to validate every change.'),
  ]

  return (
    <AppShell>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-6 space-y-6">
        {/* Hero */}
        <section className="bg-gradient-to-br from-brand-navy to-brand-navy-deep rounded-2xl text-white p-6 sm:p-10 shadow-glass-lg">
          <div className="flex items-center gap-2 mb-3">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-accent-bright/20 text-accent-bright text-xs font-semibold uppercase tracking-wide">
              <Ruler className="w-3.5 h-3.5" />
              {t('Roadmap · Coming soon')}
            </span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold">{t('Font Size Measurement')}</h1>
          <p className="mt-2 text-white/70 max-w-2xl text-sm sm:text-base">
            {t(
              'Legal Metrology (Packaged Commodities) Rules 2011 require minimum numeral heights that scale with net quantity (1–4 mm normal, 2–6 mm embossed). Measuring them reliably is the next engineering milestone.',
            )}
          </p>
          <Link
            href="/"
            className="mt-5 inline-flex items-center gap-2 btn-primary"
          >
            {t('Try a new inspection')}
            <ArrowRight className="w-4 h-4" />
          </Link>
        </section>

        {/* Current capability */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <CheckCircle2 className="w-5 h-5 text-success" />
            <h2 className="text-xl font-bold text-text-primary">{t('What the pipeline does today')}</h2>
          </div>
          <div className="grid sm:grid-cols-3 gap-4">
            {whatsThere.map(({ icon: Icon, title, body }) => (
              <Card key={title} className="space-y-3">
                <div className="flex items-center gap-2">
                  <Icon className="w-5 h-5 text-accent" />
                  <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
                </div>
                <p className="text-sm text-text-secondary leading-relaxed">{body}</p>
              </Card>
            ))}
          </div>
        </section>

        {/* Roadmap */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Ruler className="w-5 h-5 text-accent" />
            <h2 className="text-xl font-bold text-text-primary">{t("What's next")}</h2>
          </div>
          <Card className="space-y-4">
            <ul className="space-y-3">
              {planned.map((item) => (
                <li key={item} className="flex items-start gap-3 text-sm text-text-secondary">
                  <span className="mt-1.5 w-2 h-2 rounded-full bg-accent shrink-0" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
            <div className="flex items-start gap-3 bg-warning-subtle border border-warning/20 rounded-lg p-4">
              <AlertTriangle className="w-5 h-5 text-warning shrink-0 mt-0.5" />
              <p className="text-sm text-warning">
                {t(
                  'Until the calibration-card workflow ships, an uncalibrated font-size axis is reported as REVIEW_REQUIRED — never as a fabricated violation.',
                )}
              </p>
            </div>
          </Card>
        </section>

        {/* Note */}
        <section className="flex items-start gap-3 glass-card p-5">
          <Info className="w-5 h-5 text-text-muted shrink-0 mt-0.5" />
          <p className="text-sm text-text-muted">
            {t(
              'This page documents the roadmap. The working pipeline — rule engine, evidence chain, VLM extraction, offline PWA — is unchanged and submission-ready.',
            )}
          </p>
        </section>
      </div>
    </AppShell>
  )
}