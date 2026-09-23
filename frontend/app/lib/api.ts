'use client'

import axios from 'axios'
import { useSyncExternalStore } from 'react'

export interface SessionUser {
  id?: string
  uid?: string
  username: string
  name?: string
  role: string
}

const TOKEN_KEY = 'lm_token'
const USER_KEY = 'lm_user'

export function getToken(): string | null {
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem(TOKEN_KEY)
}

export function getUser(): SessionUser | null {
  if (typeof window === 'undefined') return null
  const raw = window.localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as SessionUser
  } catch {
    return null
  }
}

export function setSession(token: string, user: SessionUser) {
  window.localStorage.setItem(TOKEN_KEY, token)
  window.localStorage.setItem(USER_KEY, JSON.stringify(user))
  notifySession()
}

export function clearSession() {
  window.localStorage.removeItem(TOKEN_KEY)
  window.localStorage.removeItem(USER_KEY)
  notifySession()
}

let sessionCache: { raw: string | null; user: SessionUser | null } | null = null
const sessionListeners = new Set<() => void>()

function getSessionSnapshot(): SessionUser | null {
  if (typeof window === 'undefined') return null
  const raw = window.localStorage.getItem(USER_KEY)
  if (!sessionCache || sessionCache.raw !== raw) {
    let user: SessionUser | null = null
    if (raw) {
      try {
        user = JSON.parse(raw) as SessionUser
      } catch {
        user = null
      }
    }
    sessionCache = { raw, user }
  }
  return sessionCache.user
}

function subscribeSession(callback: () => void) {
  sessionListeners.add(callback)
  return () => {
    sessionListeners.delete(callback)
  }
}

function notifySession() {
  sessionCache = null
  sessionListeners.forEach((listener) => listener())
}

/** SSR-safe reactive session read. Server + first hydration render use `null`,
 * then React's post-hydration re-check swaps in the real user without a mismatch. */
export function useSession(): SessionUser | null {
  return useSyncExternalStore(subscribeSession, getSessionSnapshot, () => null)
}

export const api = axios.create({ timeout: 600000 })

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

interface ApiErrorShape {
  response?: { data?: { detail?: string; message?: string } }
}

export function apiError(err: unknown, fallback = 'Request failed'): string {
  if (err && typeof err === 'object' && 'response' in err) {
    const resp = (err as ApiErrorShape).response
    if (resp?.data?.detail) return resp.data.detail
    if (resp?.data?.message) return resp.data.message
  }
  if (err instanceof Error && err.message) return err.message
  return fallback
}

export interface RadarAxis {
  axis: string
  score: number | null
  weight: number
}

export interface RadarResult {
  overall: number
  grade: string
  grade_label: string
  axes: RadarAxis[]
}

export interface HeatmapInfo {
  filename: string
  image_index: number
  field_boxes: Record<string, [number, number, number, number]>
  calibration_box: [number, number, number, number] | null
}

const dateFmt = new Intl.DateTimeFormat(undefined, {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
})
const dateTimeFmt = new Intl.DateTimeFormat(undefined, {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

function toDate(value: string | Date): Date | null {
  const d = typeof value === 'string' ? new Date(value) : value
  return Number.isNaN(d.getTime()) ? null : d
}

/** Locale-aware date only: 21/09/2026 */
export function formatDate(value: string | Date): string {
  const d = toDate(value)
  return d ? dateFmt.format(d) : '—'
}

/** Locale-aware date + time: 21/09/2026, 20:01 */
export function formatDateTime(value: string | Date): string {
  const d = toDate(value)
  return d ? dateTimeFmt.format(d) : '—'
}

/** "mrp" / "net_quantity" → "Mrp" / "Net Quantity" (same rules as formatStatus) */
export function titleCaseField(key: string): string {
  return key
    .replace(/_/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

export async function downloadBlob(url: string, filename: string): Promise<void> {
  const resp = await api.get(url, { responseType: 'blob', timeout: 600000 })
  const blobUrl = window.URL.createObjectURL(new Blob([resp.data]))
  const a = document.createElement('a')
  a.href = blobUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  window.URL.revokeObjectURL(blobUrl)
  a.remove()
}