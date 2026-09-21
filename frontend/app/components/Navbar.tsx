'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useState } from 'react'
import { Shield, LayoutDashboard, Scan, History, LogOut, Languages, type LucideIcon } from 'lucide-react'
import { getUser, clearSession } from '@/app/lib/api'
import { useI18n } from '@/app/lib/i18n'

export default function Navbar() {
  const pathname = usePathname()
  const router = useRouter()
  const [user] = useState(() => getUser())
  const { lang, setLang, t } = useI18n()

  const link = (href: string, label: string, Icon: LucideIcon) => {
    const active = pathname === href
    return (
      <Link
        href={href}
        className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
          active ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'
        }`}
      >
        <Icon className="w-4 h-4" />
        {label}
      </Link>
    )
  }

  return (
    <nav className="sticky top-0 z-20 bg-white border-b border-gray-200">
      <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <Link href="/dashboard" className="flex items-center gap-2">
            <Shield className="w-6 h-6 text-blue-600" />
            <span className="text-lg font-bold text-gray-900">LegalMatrix</span>
          </Link>
          <div className="hidden sm:flex items-center gap-1">
            {link('/dashboard', t('Dashboard'), LayoutDashboard)}
            {link('/', t('New Inspection'), Scan)}
            {link('/history', t('History'), History)}
          </div>
        </div>

        {user ? (
          <div className="flex items-center gap-3">
            <button
              onClick={() => setLang(lang === 'en' ? 'hi' : 'en')}
              title={lang === 'en' ? 'हिंदी में देखें' : 'View in English'}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-gray-300 text-xs font-semibold text-gray-600 hover:border-blue-500 hover:text-blue-600 transition-colors"
            >
              <Languages className="w-3.5 h-3.5" />
              {lang === 'en' ? 'हिंदी' : 'EN'}
            </button>
            <div className="text-right">
              <p className="text-xs font-semibold text-gray-800">{user.name || user.username}</p>
              <p className="text-[10px] text-gray-500 uppercase">{user.role}</p>
            </div>
            <button
              onClick={() => {
                clearSession()
                router.push('/login')
              }}
              className="flex items-center gap-1 px-2.5 py-2 rounded-lg text-sm text-gray-600 hover:bg-gray-100"
              title={t('Sign out')}
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <button
              onClick={() => setLang(lang === 'en' ? 'hi' : 'en')}
              title={lang === 'en' ? 'हिंदी में देखें' : 'View in English'}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-gray-300 text-xs font-semibold text-gray-600 hover:border-blue-500 hover:text-blue-600 transition-colors"
            >
              <Languages className="w-3.5 h-3.5" />
              {lang === 'en' ? 'हिंदी' : 'EN'}
            </button>
            <Link href="/login" className="text-sm font-medium text-blue-600 hover:underline">
              {t('Sign in')}
            </Link>
          </div>
        )}
      </div>
    </nav>
  )
}