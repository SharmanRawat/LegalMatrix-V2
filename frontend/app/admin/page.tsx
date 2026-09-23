'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Search, KeyRound, FileSearch, ChevronLeft, Lock, Shield, Users } from 'lucide-react'
import toast, { Toaster } from 'react-hot-toast'
import AppShell from '@/app/components/AppShell'
import Card from '@/app/components/ui/Card'
import { api, apiError, getUser } from '@/app/lib/api'
import { useI18n } from '@/app/lib/i18n'

interface UserRow {
  id: number | string
  username: string
  name: string
  role: string
  is_active: number
  created_at: string
}

interface ScanRow {
  id: string
  product_name: string | null
  manufacturer: string | null
  status: string
  compliance_score: number
  created_at: string
}

const ROLE_BADGE: Record<string, string> = {
  ADMIN: 'badge badge-info',
  INSPECTOR: 'badge badge-success',
  VIEWER: 'badge badge-warning',
}

const statusColor: Record<string, string> = {
  COMPLIANT: 'text-success',
  REVIEW_REQUIRED: 'text-warning',
  POTENTIAL_VIOLATION: 'text-danger',
}

export default function AdminUsersPage() {
  const router = useRouter()
  const { t } = useI18n()
  const [me] = useState(() => {
    try {
      return getUser()
    } catch {
      return null
    }
  })
  const [q, setQ] = useState('')
  const [role, setRole] = useState('')
  const [users, setUsers] = useState<UserRow[]>([])
  const [loading, setLoading] = useState(false)

  // Detail drawer state
  const [detail, setDetail] = useState<{ username: string; name: string; scans: ScanRow[]; total: number } | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // Reset-password state
  const [resetFor, setResetFor] = useState<string | null>(null)
  const [newPass, setNewPass] = useState('')
  const [resetting, setResetting] = useState(false)

  useEffect(() => {
    if (!me) {
      router.replace('/login')
      return
    }
    if (me.role !== 'ADMIN') {
      router.replace('/dashboard')
      return
    }
    runSearch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router])

  const runSearch = async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (q) params.q = q
      if (role) params.role = role
      const { data } = await api.get('/api/auth/users', { params })
      setUsers(Array.isArray(data) ? data : [])
    } catch (err: unknown) {
      toast.error(apiError(err, t('Search failed')))
    } finally {
      setLoading(false)
    }
  }

  const openDetail = async (username: string, name: string) => {
    setDetailLoading(true)
    try {
      const { data } = await api.get(`/api/auth/users/${username}/inspections`)
      setDetail({ username, name, scans: data.scans ?? [], total: data.total ?? 0 })
    } catch (err: unknown) {
      toast.error(apiError(err, t('Failed to load scans')))
    } finally {
      setDetailLoading(false)
    }
  }

  const submitReset = async (username: string) => {
    if (!newPass) {
      toast.error(t('Enter a new password'))
      return
    }
    setResetting(true)
    try {
      await api.post(`/api/auth/users/${username}/reset-password`, { password: newPass })
      toast.success(t('Password reset for {username}', { username }))
      setResetFor(null)
      setNewPass('')
    } catch (err: unknown) {
      toast.error(apiError(err, t('Reset failed')))
    } finally {
      setResetting(false)
    }
  }

  const isAdmin = !!me && me.role === 'ADMIN'

  return (
    <AppShell>
      <Toaster position="top-right" />
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-6">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-text-primary">
              {t('User Management')}
            </h1>
            <p className="text-sm text-text-secondary mt-1">
              {t('Admin-only: search users, view their scans, reset passwords')}
            </p>
          </div>
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-info-subtle border border-info/20 text-xs font-semibold text-info">
            <Shield className="w-3.5 h-3.5" />
            {t('Admin only')}
          </span>
        </header>

        {!isAdmin ? (
          <Card>
            <div className="text-center py-10">
              <p className="text-text-secondary">{t('This page is restricted to administrators.')}</p>
              <Link href="/dashboard" className="inline-flex items-center gap-1 mt-3 text-sm text-accent hover:text-accent-hover">
                <ChevronLeft className="w-4 h-4" /> {t('Back to dashboard')}
              </Link>
            </div>
          </Card>
        ) : (
          <>
            {/* Search bar */}
            <Card className="space-y-3">
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Search className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && runSearch()}
                    placeholder={t('Search by username or name…')}
                    className="glass-input w-full pl-9"
                  />
                </div>
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  className="glass-input px-3"
                >
                  <option value="">{t('All roles')}</option>
                  <option value="ADMIN">ADMIN</option>
                  <option value="INSPECTOR">INSPECTOR</option>
                  <option value="VIEWER">VIEWER</option>
                </select>
                <button
                  onClick={runSearch}
                  disabled={loading}
                  className="btn-primary"
                >
                  {loading ? t('Searching') + '…' : t('Search')}
                </button>
              </div>
              <p className="text-xs text-text-muted">
                {t('Passwords are stored as one-way hashes and can never be viewed — an admin can only reset one.')}
              </p>
            </Card>

            {/* Users table */}
            {loading ? (
              <div className="flex justify-center py-20">
                <div className="animate-spin rounded-full h-10 w-10 border-4 border-accent border-t-transparent" />
              </div>
            ) : users.length === 0 ? (
              <Card>
                <div className="text-center py-10">
                  <Users className="w-10 h-10 mx-auto text-text-muted mb-2" />
                  <p className="text-text-secondary">{t('No users found matching your filters.')}</p>
                </div>
              </Card>
            ) : (
              <div className="glass-card overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-bg-secondary text-left text-xs uppercase tracking-wide text-text-muted">
                    <tr>
                      <th className="px-4 py-3">{t('Username')}</th>
                      <th className="px-4 py-3">{t('Name')}</th>
                      <th className="px-4 py-3">{t('Role')}</th>
                      <th className="px-4 py-3 text-right">{t('Actions')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={String(u.id)} className="border-t border-surface-border hover:bg-surface-hover">
                        <td className="px-4 py-3 font-mono text-xs text-text-secondary">{u.username}</td>
                        <td className="px-4 py-3 text-text-primary">{u.name || '—'}</td>
                        <td className="px-4 py-3">
                          <span className={ROLE_BADGE[u.role] || 'badge'}>
                            {u.role}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              onClick={() => openDetail(u.username, u.name || u.username)}
                              disabled={detailLoading}
                              className="btn-ghost btn-sm"
                            >
                              <FileSearch className="w-3.5 h-3.5" /> {t('Scans')}
                            </button>
                            <button
                              onClick={() => {
                                setResetFor(u.username)
                                setNewPass('')
                              }}
                              className="btn-ghost btn-sm"
                            >
                              <KeyRound className="w-3.5 h-3.5" /> {t('Reset password')}
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Reset password inline form */}
            {resetFor && (
              <Card className="space-y-3">
                <div className="flex items-center gap-2">
                  <Lock className="w-4 h-4 text-text-muted" />
                  <h3 className="text-sm font-semibold text-text-primary">
                    {t('Reset password for {username}', { username: resetFor })}
                  </h3>
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={newPass}
                    onChange={(e) => setNewPass(e.target.value)}
                    placeholder={t('New password')}
                    className="glass-input flex-1"
                  />
                  <button
                    onClick={() => submitReset(resetFor)}
                    disabled={resetting}
                    className="btn-primary"
                  >
                    {resetting ? t('Saving…') : t('Set password')}
                  </button>
                  <button
                    onClick={() => setResetFor(null)}
                    className="btn-ghost"
                  >
                    {t('Cancel')}
                  </button>
                </div>
                <p className="text-xs text-text-muted">
                  {t('The old password is unrecoverable (stored as a hash). The user must use the new one from now on.')}
                </p>
              </Card>
            )}

            {/* Per-user scans drawer */}
            {detail && (
              <Card className="space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-base font-bold text-text-primary">
                      {t('Scans by {name}', { name: detail.name })}
                    </h3>
                    <p className="text-xs text-text-muted">
                      {detail.total} {t(detail.total === 1 ? 'result' : 'results')} · {detail.username}
                    </p>
                  </div>
                  <button
                    onClick={() => setDetail(null)}
                    className="btn-ghost btn-sm"
                  >
                    {t('Close')}
                  </button>
                </div>
                {detail.scans.length === 0 ? (
                  <p className="text-sm text-text-muted">{t('No scans yet for this user.')}</p>
                ) : (
                  <ul className="space-y-2">
                    {detail.scans.map((s) => (
                      <li key={s.id}>
                        <Link
                          href={`/inspection/${s.id}`}
                          className="flex items-center justify-between p-3 rounded-lg bg-surface hover:bg-surface-hover hover:shadow-glass-lg hover:-translate-y-0.5 transition-all"
                        >
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-text-primary truncate">
                              {s.product_name || t('Unknown product')}
                            </p>
                            <p className="text-xs text-text-muted truncate">
                              {s.id} • {new Date(s.created_at).toLocaleString()}
                              {s.manufacturer ? ` • ${s.manufacturer}` : ''}
                            </p>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <span className={`text-xs font-semibold ${statusColor[s.status] || 'text-text-secondary'}`}>
                              {s.compliance_score}%
                            </span>
                            <span className="badge">
                              {s.status.replace(/_/g, ' ')}
                            </span>
                          </div>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            )}
          </>
        )}
      </div>
    </AppShell>
  )
}