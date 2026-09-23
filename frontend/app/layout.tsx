import type { Metadata, Viewport } from 'next'
import { IBM_Plex_Sans, IBM_Plex_Mono, IBM_Plex_Sans_Devanagari } from 'next/font/google'
import './globals.css'
import ServiceWorkerRegister from '@/app/components/ServiceWorkerRegister'

const ibmPlexSans = IBM_Plex_Sans({
  subsets: ['latin'],
  variable: '--font-sans',
  display: 'swap',
})

const ibmPlexMono = IBM_Plex_Mono({
  weight: ['400', '500', '600'],
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
})

// Devanagari fallback so Hindi legal-metrology copy never falls back to a system font
const ibmPlexSansDevanagari = IBM_Plex_Sans_Devanagari({
  weight: ['400', '500', '600'],
  subsets: ['devanagari', 'latin'],
  variable: '--font-sans-deva',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'MetrIQ — Legal Metrology Inspection',
  description: 'AI-powered compliance inspection for packaged commodities',
  manifest: '/manifest.json',
}

export const viewport: Viewport = {
  themeColor: '#14304F',
  width: 'device-width',
  initialScale: 1,
  maximumScale: 5,
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html
      lang="en"
      className={`${ibmPlexSans.variable} ${ibmPlexMono.variable} ${ibmPlexSansDevanagari.variable}`}
    >
      <body>
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:px-4 focus:py-2 focus:bg-accent focus:text-white focus:rounded-lg focus:outline-none"
        >
          Skip to content
        </a>
        <main id="main-content" className="min-h-screen bg-bg-primary text-text-primary">
          {children}
        </main>
        <ServiceWorkerRegister />
      </body>
    </html>
  )
}