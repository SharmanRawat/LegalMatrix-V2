'use client'

import axios from 'axios'

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
}

export function clearSession() {
  window.localStorage.removeItem(TOKEN_KEY)
  window.localStorage.removeItem(USER_KEY)
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