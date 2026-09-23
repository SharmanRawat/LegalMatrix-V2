'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Search, KeyRound, FileSearch, ChevronLeft, Lock } from 'lucide-react'
import toast, { Toaster } from 'react-hot-toast'
import Navbar from '@/app/components/Navbar'
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
  ADMIN: 'bg-purple-50 text-purple-700 border-purple-200',
  INSPECTOR: 'bg-blue-50 text-blue-700 border-blue-200',
  VIEWER: 'bg-gray-50 text-gray-600 border-gray-200',
}

const statusColor: Record<string, string> = {
  COMPLIANT: 'text-green-600',
  REVIEW_REQUIRED: 'text-yellow-600',
  POTENTIAL_VIOLATION: 'text-red-600',
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
    <>
      <Navbar />
      <Toaster position="top-right" />
      <main className="max-w-5xl mx-auto p-4 sm:p-6 space-y-6">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{t('User Management')}</h1>
            <p className="text-sm text-gray-500">{t('Admin-only: search users, view their scans, reset passwords')}</p>
          </div>
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-purple-50 border border-purple-200 text-xs font-semibold text-purple-700">
            <ShieldMini />
            {t('Admin only')}
          </span>
        </header>

        {!isAdmin ? (
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-10 text-center">
            <p className="text-gray-500">{t('This page is restricted to administrators.')}</p>
            <Link href="/dashboard" className="inline-flex items-center gap-1 mt-3 text-sm text-blue-600 hover:underline">
              <ChevronLeft className="w-4 h-4" /> {t('Back to dashboard')}
            </Link>
          </div>
        ) : (
          <>
            {/* Search bar */}
            <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 space-y-3">
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && runSearch()}
                    placeholder={t('Search by username or name…')}
                    className="w-full pl-9 pr-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                  />
                </div>
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  className="px-3 py-2.5 border border-gray-300 rounded-lg text-sm bg-white"
                >
                  <option value="">{t('All roles')}</option>
                  <option value="ADMIN">ADMIN</option>
                  <option value="INSPECTOR">INSPECTOR</option>
                  <option value="VIEWER">VIEWER</option>
                </select>
                <button
                  onClick={runSearch}
                  disabled={loading}
                  className="px-5 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm font-semibold"
                >
                  {loading ? t('Searching') + '…' : t('Search')}
                </button>
              </div>
              <p className="text-xs text-gray-400">
                {t('Passwords are stored as one-way hashes and can never be viewed — an admin can only reset one.')}
              </p>
            </section>

            {/* Users table */}
            {loading ? (
              <div className="flex justify-center py-20">
                <div className="animate-spin rounded-full h-10 w-10 border-4 border-blue-500 border-t-transparent" />
              </div>
            ) : users.length === 0 ? (
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-10 text-center">
                <p className="text-gray-500">{t('No users found matching your filters.')}</p>
              </div>
            ) : (
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                    <tr>
                      <th className="px-4 py-3">{t('Username')}</th>
                      <th className="px-4 py-3">{t('Name')}</th>
                      <th className="px-4 py-3">{t('Role')}</th>
                      <th className="px-4 py-3 text-right">{t('Actions')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={String(u.id)} className="border-t border-gray-100 hover:bg-gray-50">
                        <td className="px-4 py-3 font-mono text-xs text-gray-700">{u.username}</td>
                        <td className="px-4 py-3 text-gray-800">{u.name || '—'}</td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${ROLE_BADGE[u.role] || 'bg-gray-50'}`}>
                            {u.role}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              onClick={() => openDetail(u.username, u.name || u.username)}
                              disabled={detailLoading}
                              className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-100"
                            >
                              <FileSearch className="w-3.5 h-3.5" /> {t('Scans')}
                            </button>
                            <button
                              onClick={() => {
                                setResetFor(u.username)
                                setNewPass('')
                              }}
                              className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-100"
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
              <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 space-y-3">
                <div className="flex items-center gap-2">
                  <Lock className="w-4 h-4 text-gray-400" />
                  <h3 className="text-sm font-semibold text-gray-800">
                    {t('Reset password for {username}', { username: resetFor })}
                  </h3>
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={newPass}
                    onChange={(e) => setNewPass(e.target.value)}
                    placeholder={t('New password')}
                    className="flex-1 px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                  />
                  <button
                    onClick={() => submitReset(resetFor)}
                    disabled={resetting}
                    className="px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm font-semibold"
                  >
                    {resetting ? t('Saving…') : t('Set password')}
                  </button>
                  <button
                    onClick={() => setResetFor(null)}
                    className="px-4 py-2.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-100 text-sm"
                  >
                    {t('Cancel')}
                  </button>
                </div>
                <p className="text-xs text-gray-400">
                  {t('The old password is unrecoverable (stored as a hash). The user must use the new one from now on.')}
                </p>
              </section>
            )}

            {/* Per-user scans drawer */}
            {detail && (
              <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 sm:p-6">
                <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                  <div>
                    <h3 className="text-base font-bold text-gray-900">
                      {t('Scans by {name}', { name: detail.name })}
                    </h3>
                    <p className="text-xs text-gray-500">
                      {detail.total} {t(detail.total === 1 ? 'result' : 'results')} · {detail.username}
                    </p>
                  </div>
                  <button
                    onClick={() => setDetail(null)}
                    className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-100"
                  >
                    {t('Close')}
                  </button>
                </div>
                {detail.scans.length === 0 ? (
                  <p className="text-sm text-gray-400">{t('No scans yet for this user.')}</p>
                ) : (
                  <ul className="space-y-2">
                    {detail.scans.map((s) => (
                      <li key={s.id}>
                        <Link
                          href={`/inspection/${s.id}`}
                          className="flex items-center justify-between p-3 rounded-lg border border-gray-100 hover:bg-gray-50 transition-colors"
                        >
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-gray-800 truncate">
                              {s.product_name || t('Unknown product')}
                            </p>
                            <p className="text-xs text-gray-500 truncate">
                              {s.id} • {new Date(s.created_at).toLocaleString()}
                              {s.manufacturer ? ` • ${s.manufacturer}` : ''}
                            </p>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <span className={`text-xs font-semibold ${statusColor[s.status] || 'text-gray-600'}`}>
                              {s.compliance_score}%
                            </span>
                            <span className="px-2 py-0.5 rounded text-[10px] font-semibold border bg-gray-50 text-gray-600">
                              {s.status.replace(/_/g, ' ')}
                            </span>
                          </div>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}
          </>
        )}
      </main>
    </>
  )
}

function ShieldMini() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.5 3.8 17 5 19 5a1 1 0 0 1 1 1z" />
    </svg>
  )
}