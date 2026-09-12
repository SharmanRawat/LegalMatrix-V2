
import type { Metadata, Viewport } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import ServiceWorkerRegister from '@/app/components/ServiceWorkerRegister'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'LegalMatrix - Legal Metrology Inspection',
  description: 'AI-powered compliance inspection for packaged commodities',
  manifest: '/manifest.json',
}

export const viewport: Viewport = {
  themeColor: '#2563eb',
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <main className="min-h-screen bg-gray-50">
          {children}
        </main>
        <ServiceWorkerRegister />
      </body>
    </html>
  )
}
