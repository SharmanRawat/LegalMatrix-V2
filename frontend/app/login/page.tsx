'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Shield, Lock, User as UserIcon } from 'lucide-react'
import toast, { Toaster } from 'react-hot-toast'
import { api, apiError, setSession } from '@/app/lib/api'

export default function LoginPage() {
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
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
      toast.error(apiError(err, 'Login failed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <Toaster position="top-right" />
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="flex items-center justify-center gap-2 mb-3">
            <Shield className="w-9 h-9 text-blue-600" />
            <h1 className="text-2xl font-bold text-gray-900">LegalMatrix</h1>
          </div>
          <p className="text-sm text-gray-500">Legal Metrology Compliance Inspection</p>
        </div>

        <form onSubmit={onSubmit} className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
            <div className="relative">
              <UserIcon className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full pl-9 pr-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="admin"
                autoComplete="username"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <div className="relative">
              <Lock className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full pl-9 pr-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="••••••••"
                autoComplete="current-password"
              />
            </div>
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-semibold"
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
          <p className="text-[11px] text-gray-400 text-center">
            Default demo account: admin / admin@123
          </p>
        </form>
      </div>
    </div>
  )
}