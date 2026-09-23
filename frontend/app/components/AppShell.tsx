'use client'

import Navbar from '@/app/components/Navbar'
import BottomNav, { MobileLogo } from '@/app/components/BottomNav'

interface AppShellProps {
  children: React.ReactNode
}

/**
 * Application shell — wraps authenticated pages with navigation.
 * Desktop: navy top navbar
 * Mobile: white logo header + bottom tab bar
 */
export default function AppShell({ children }: AppShellProps) {
  return (
    <div className="min-h-screen bg-bg-primary">
      {/* Desktop top nav */}
      <div className="hidden sm:block">
        <Navbar />
      </div>

      {/* Mobile header — same navy brand as desktop */}
      <div className="sm:hidden sticky top-0 z-[var(--z-nav)] bg-brand-navy">
        <MobileLogo />
      </div>

      {/* Page content — bottom padding on mobile for bottom nav clearance */}
      <main className="pb-20 sm:pb-0">
        {children}
      </main>

      {/* Mobile bottom nav */}
      <BottomNav />
    </div>
  )
}