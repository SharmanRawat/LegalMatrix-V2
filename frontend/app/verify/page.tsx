import { Suspense } from 'react'
import VerifyClient from './verify-client'

export const metadata = {
  title: 'Certificate Verification · LegalMatrix',
}

export default function VerifyPage() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center text-gray-500">Loading…</div>}>
      <VerifyClient />
    </Suspense>
  )
}