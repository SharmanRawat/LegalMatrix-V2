'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LayoutDashboard, Scan, History, Shield } from 'lucide-react'

const TAB_LINKS = [
  { href: '/dashboard', label: 'Dashboard', Icon: LayoutDashboard },
  { href: '/', label: 'Inspect', Icon: Scan },
  { href: '/history', label: 'History', Icon: History },
]

export default function BottomNav() {
  const pathname = usePathname()

  return (
    <nav
      className="sm:hidden fixed bottom-0 inset-x-0 z-[var(--z-nav)] bg-white border-t border-surface-border"
      role="navigation"
      aria-label="Mobile navigation"
    >
      <div className="flex items-center justify-around h-16 px-2">
        {TAB_LINKS.map(({ href, label, Icon }) => {
          const active = pathname === href || (href !== '/' && pathname.startsWith(href))
          return (
            <Link
              key={href}
              href={href}
              className={`relative flex flex-col items-center gap-0.5 px-3 py-1.5 rounded-lg min-w-[64px] ${
                active
                  ? 'text-accent'
                  : 'text-text-muted hover:text-text-secondary'
              }`}
              aria-current={active ? 'page' : undefined}
            >
              <Icon className="w-5 h-5" />
              <span className="text-[10px] font-semibold">{label}</span>
              {active && (
                <span className="absolute -top-0 left-1/2 -translate-x-1/2 w-8 h-0.5 bg-accent rounded-full" />
              )}
            </Link>
          )
        })}
      </div>
    </nav>
  )
}

/** Compact logo for mobile header when bottom nav is active */
export function MobileLogo() {
  return (
    <Link href="/dashboard" className="sm:hidden flex items-center gap-2 px-4 h-12">
      <Shield className="w-5 h-5 text-accent-bright" />
      <span className="text-sm font-bold text-white tracking-tight">MetrIQ</span>
      <span className="text-[9px] text-white/60 uppercase tracking-wider border-l border-white/20 pl-2">
        Legal Metrology
      </span>
    </Link>
  )
}