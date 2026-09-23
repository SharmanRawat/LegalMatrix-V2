'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Shield, Scan, FileCheck2 } from 'lucide-react'
import toast, { Toaster } from 'react-hot-toast'
import { api, apiError, setSession } from '@/app/lib/api'

export default function LoginPage() {
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [ringOffset, setRingOffset] = useState({ x: 0, y: 0 })
  const brandRef = useRef<HTMLElement | null>(null)

  // Desktop-only mouse parallax on decorative rings (depth = brand moment)
  useEffect(() => {
    const el = brandRef.current
    if (!el) return
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return

    const onMove = (e: MouseEvent) => {
      const rect = el.getBoundingClientRect()
      const nx = (e.clientX - rect.left) / rect.width - 0.5
      const ny = (e.clientY - rect.top) / rect.height - 0.5
      setRingOffset({ x: nx, y: ny })
    }
    const onLeave = () => setRingOffset({ x: 0, y: 0 })

    el.addEventListener('mousemove', onMove)
    el.addEventListener('mouseleave', onLeave)
    return () => {
      el.removeEventListener('mousemove', onMove)
      el.removeEventListener('mouseleave', onLeave)
    }
  }, [])

  const fillDemo = () => {
    setUsername('admin')
    setPassword('admin@123')
    setError('')
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!username || !password) {
      toast.error('Enter username and password')
      return
    }
    setLoading(true)
    try {
      const { data } = await api.post('/api/auth/login', { username, password })
      setSession(data.token, data.user)
      toast.success(`Welcome, ${data.user.name || data.user.username}!`)
      router.push('/dashboard')
    } catch (err: unknown) {
      const msg = apiError(err, 'Login failed')
      setError(msg)
      toast.error(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-bg-primary lg:grid lg:grid-cols-2">
      <Toaster position="top-right" />

      {/* ── Brand panel (desktop) ── */}
      <aside
        ref={brandRef}
        className="hidden lg:flex flex-col justify-between bg-brand-navy text-white p-12 relative overflow-hidden"
      >
        {/* Decorative rings — subtle mouse parallax */}
        <div
          className="absolute -right-40 -top-40 w-96 h-96 rounded-full border border-white/10 pointer-events-none"
          aria-hidden="true"
          style={{
            transform: `translate(${ringOffset.x * 14}px, ${ringOffset.y * 14}px)`,
            transition: 'transform 0.35s ease-out',
          }}
        />
        <div
          className="absolute -right-24 -top-24 w-64 h-64 rounded-full border border-white/10 pointer-events-none"
          aria-hidden="true"
          style={{
            transform: `translate(${ringOffset.x * 22}px, ${ringOffset.y * 22}px)`,
            transition: 'transform 0.35s ease-out',
          }}
        />
        <div
          className="absolute -bottom-32 -left-24 w-80 h-80 rounded-full border border-white/5 pointer-events-none"
          aria-hidden="true"
          style={{
            transform: `translate(${ringOffset.x * -10}px, ${ringOffset.y * -10}px)`,
            transition: 'transform 0.35s ease-out',
          }}
        />

        <div className="relative">
          <div className="flex items-center gap-3">
            <span className="flex items-center justify-center w-11 h-11 rounded-xl bg-accent-bright">
              <Shield className="w-6 h-6 text-brand-navy" />
            </span>
            <div>
              <p className="text-xl font-bold tracking-tight">MetrIQ</p>
              <p className="text-[11px] text-white/60 uppercase tracking-widest">
                Legal Metrology
              </p>
            </div>
          </div>
        </div>

        <div className="relative max-w-sm">
          <h2 className="text-3xl leading-tight font-bold">
            Every label, verified against the law.
          </h2>
          <p className="mt-3 text-white/70">
            Capture a product&rsquo;s packaging once and let the vision model check
            declarations against Legal Metrology rules — instantly.
          </p>

          <ul className="mt-8 space-y-4 text-sm text-white/80">
            <li className="flex items-center gap-3">
              <span className="flex items-center justify-center w-8 h-8 rounded-lg bg-white/10">
                <Scan className="w-4 h-4 text-accent-bright" />
              </span>
              Photograph front, back and side labels
            </li>
            <li className="flex items-center gap-3">
              <span className="flex items-center justify-center w-8 h-8 rounded-lg bg-white/10">
                <FileCheck2 className="w-4 h-4 text-accent-bright" />
              </span>
              AI extracts declarations and checks 10+ rules
            </li>
            <li className="flex items-center gap-3">
              <span className="flex items-center justify-center w-8 h-8 rounded-lg bg-white/10">
                <Shield className="w-4 h-4 text-accent-bright" />
              </span>
              Export JSON, CSV and compliance certificates
            </li>
          </ul>
        </div>

        <p className="relative text-xs text-white/50">
          Govt of India · Department of Consumer Affairs · Legal Metrology Division
        </p>
      </aside>

      {/* ── Form panel ── */}
      <main className="flex flex-col items-center justify-center p-6 bg-bg-primary">
        {/* Mobile brand header */}
        <div className="lg:hidden flex items-center gap-2.5 mb-10 mt-4">
          <span className="flex items-center justify-center w-10 h-10 rounded-xl bg-accent-soft">
            <Shield className="w-6 h-6 text-accent" />
          </span>
          <div>
            <p className="text-lg font-bold text-brand-navy tracking-tight">MetrIQ</p>
            <p className="text-[10px] text-text-muted uppercase tracking-widest">
              Legal Metrology
            </p>
          </div>
        </div>

        <div className="w-full max-w-sm animate-reveal">
          <header className="mb-6">
            <h1 className="text-2xl font-bold text-text-primary tracking-tight">Welcome back</h1>
            <p className="text-sm text-text-secondary mt-1">
              Authorised field officers and admin staff only.
            </p>
          </header>

          <form onSubmit={onSubmit} className="space-y-4 animate-reveal" style={{ animationDelay: '80ms' }} noValidate>
            {error && (
              <div
                className="flex items-center gap-2 px-3 py-2 rounded-lg bg-danger-subtle border border-danger/25 text-sm text-danger"
                role="alert"
              >
                <span className="shrink-0" aria-hidden="true">⚠</span>
                <span>{error}</span>
              </div>
            )}

            <div>
              <label htmlFor="login-username" className="block text-sm font-medium text-text-primary mb-1.5">
                Username
              </label>
              <input
                id="login-username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="glass-input w-full"
                placeholder="admin"
                autoComplete="username"
                autoFocus
              />
            </div>

            <div>
              <label htmlFor="login-password" className="block text-sm font-medium text-text-primary mb-1.5">
                Password
              </label>
              <input
                id="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="glass-input w-full"
                placeholder="••••••••"
                autoComplete="current-password"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full flex items-center justify-center gap-2"
            >
              {loading && (
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                </svg>
              )}
              {loading ? 'Signing in…' : 'Sign in'}
            </button>

            <div className="flex items-center justify-center gap-2 pt-1">
              <p className="text-[11px] text-text-secondary">
                Demo: <span className="mono">admin</span> / <span className="mono">admin@123</span>
              </p>
              <button
                type="button"
                onClick={fillDemo}
                className="text-[11px] font-semibold text-accent hover:text-accent-hover underline underline-offset-2"
              >
                Fill demo
              </button>
            </div>
          </form>
        </div>

        <p className="lg:hidden text-[10px] text-text-muted mt-12 text-center max-w-[240px]">
          Govt of India · Dept of Consumer Affairs · Legal Metrology
        </p>
      </main>
    </div>
  )
}