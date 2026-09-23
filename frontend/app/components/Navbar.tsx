'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useState } from 'react'
import {
  Shield,
  LayoutDashboard,
  Scan,
  History,
  LogOut,
  ChevronDown,
  Languages,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { useSession, clearSession } from '@/app/lib/api'
import { useI18n } from '@/app/lib/i18n'

const NAV_LINKS: { href: string; label: string; Icon: LucideIcon; adminOnly?: boolean }[] = [
  { href: '/dashboard', label: 'Dashboard', Icon: LayoutDashboard },
  { href: '/', label: 'Inspect', Icon: Scan },
  { href: '/history', label: 'History', Icon: History },
  { href: '/admin', label: 'User Management', Icon: Users, adminOnly: true },
]

export default function Navbar() {
  const pathname = usePathname()
  const router = useRouter()
  const user = useSession()
  const { lang, setLang } = useI18n()
  const [menuOpen, setMenuOpen] = useState(false)

  const handleSignOut = () => {
    clearSession()
    router.push('/login')
  }

  const visibleLinks = NAV_LINKS.filter((l) => !l.adminOnly || user?.role === 'ADMIN')

  return (
    <nav
      className="sticky top-0 z-[var(--z-nav)] bg-brand-navy"
      role="navigation"
      aria-label="Main navigation"
    >
      <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
        {/* Logo */}
        <Link href="/dashboard" className="flex items-center gap-2.5 shrink-0">
          <Shield className="w-5 h-5 text-accent-bright" />
          <span className="text-base font-bold text-white tracking-tight">
            LegalMatrix
          </span>
          <span className="hidden lg:block text-[10px] text-white/60 uppercase tracking-wider border-l border-white/20 pl-2">
            Legal Metrology
          </span>
        </Link>

        {/* Desktop nav links */}
        <div className="hidden sm:flex items-center gap-1 ml-6">
          {visibleLinks.map(({ href, label, Icon }) => {
            const active = pathname === href || (href !== '/' && pathname.startsWith(href))
            return (
              <Link
                key={href}
                href={href}
                className={`relative flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  active
                    ? 'bg-white/10 text-white'
                    : 'text-white/70 hover:text-white hover:bg-white/5'
                }`}
                aria-current={active ? 'page' : undefined}
              >
                <Icon className="w-4 h-4" />
                {label}
                {active && (
                  <span className="absolute left-3 right-3 -bottom-[13px] h-0.5 bg-accent-bright rounded-full" />
                )}
              </Link>
            )
          })}
        </div>

        {/* User menu (desktop) */}
        {user ? (
          <div className="hidden sm:flex items-center gap-3 ml-auto">
            <button
              onClick={() => setLang(lang === 'en' ? 'hi' : 'en')}
              title={lang === 'en' ? 'हिंदी में देखें' : 'View in English'}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-xs font-semibold text-white transition-colors"
            >
              <Languages className="w-3.5 h-3.5" />
              {lang === 'en' ? 'हिंदी' : 'EN'}
            </button>
            <div className="text-right">
              <p className="text-xs font-medium text-white leading-tight">
                {user.name || user.username}
              </p>
              <p className="text-[10px] text-white/60 uppercase tracking-wider">
                {user.role}
              </p>
            </div>
            <div className="relative">
              <button
                onClick={() => setMenuOpen(!menuOpen)}
                className="flex items-center justify-center w-8 h-8 rounded-lg bg-white/10 hover:bg-white/20 transition-colors"
                aria-expanded={menuOpen}
                aria-haspopup="true"
                aria-label="User menu"
              >
                <ChevronDown className={`w-4 h-4 text-white transition-transform ${menuOpen ? 'rotate-180' : ''}`} />
              </button>
              {menuOpen && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                  <div className="absolute right-0 top-full mt-1 z-20 w-48 glass-card p-1 animate-fade-in shadow-glass-lg">
                    <div className="px-3 py-2 border-b border-surface-border mb-1">
                      <p className="text-sm font-semibold text-text-primary">{user.name || user.username}</p>
                      <p className="text-xs text-text-muted">{user.role}</p>
                    </div>
                    <button
                      onClick={handleSignOut}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm text-text-secondary hover:text-text-primary hover:bg-surface-hover rounded-lg transition-colors"
                    >
                      <LogOut className="w-4 h-4" />
                      Sign out
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        ) : (
          <div className="hidden sm:flex items-center gap-3 ml-auto">
            <button
              onClick={() => setLang(lang === 'en' ? 'hi' : 'en')}
              title={lang === 'en' ? 'हिंदी में देखें' : 'View in English'}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-xs font-semibold text-white transition-colors"
            >
              <Languages className="w-3.5 h-3.5" />
              {lang === 'en' ? 'हिंदी' : 'EN'}
            </button>
            <Link
              href="/login"
              className="text-sm font-medium text-accent-bright hover:text-white transition-colors"
            >
              Sign in
            </Link>
          </div>
        )}
      </div>
    </nav>
  )
}