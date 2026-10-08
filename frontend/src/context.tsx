import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, getToken, setToken, setUnauthorizedHandler, type SiteSummary, type User } from './api'

interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  canWrite: boolean
}

const AuthCtx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [token, setTok] = useState<string | null>(getToken())
  const me = useQuery({ queryKey: ['me', token], queryFn: () => api.get<User>('/api/auth/me'), enabled: !!token, retry: false })

  const logout = useCallback(() => {
    setToken(null)
    setTok(null)
    qc.clear()
  }, [qc])

  useEffect(() => setUnauthorizedHandler(logout), [logout])

  const login = useCallback(async (email: string, password: string) => {
    const r = await api.login(email, password)
    setToken(r.access_token)
    setTok(r.access_token)
  }, [])

  const user = token ? (me.data ?? null) : null
  const value = useMemo<AuthState>(
    () => ({ user, loading: !!token && me.isLoading, login, logout, canWrite: !!user && user.role !== 'viewer' }),
    [user, token, me.isLoading, login, logout],
  )
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>
}

export function useAuth(): AuthState {
  const v = useContext(AuthCtx)
  if (!v) throw new Error('AuthProvider eksik')
  return v
}

// --- Seçili site -----------------------------------------------------------------------

const SITE_KEY = 'aidat_site'

interface SiteState {
  sites: SiteSummary[]
  siteId: number | null
  site: SiteSummary | null
  setSiteId: (id: number | null) => void
  loading: boolean
}

const SiteCtx = createContext<SiteState | null>(null)

export function SiteProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const sites = useQuery({ queryKey: ['sites'], queryFn: () => api.get<SiteSummary[]>('/api/sites'), enabled: !!user })
  const [siteId, setSiteIdState] = useState<number | null>(() => {
    try {
      const v = localStorage.getItem(SITE_KEY)
      return v ? Number(v) : null
    } catch {
      return null
    }
  })
  const setSiteId = useCallback((id: number | null) => {
    setSiteIdState(id)
    try {
      if (id) localStorage.setItem(SITE_KEY, String(id))
      else localStorage.removeItem(SITE_KEY)
    } catch {
      /* yok say */
    }
  }, [])

  const list = sites.data ?? []
  const effectiveId = list.some((s) => s.id === siteId) ? siteId : (list[0]?.id ?? null)
  const value = useMemo<SiteState>(
    () => ({ sites: list, siteId: effectiveId, site: list.find((s) => s.id === effectiveId) ?? null, setSiteId, loading: sites.isLoading }),
    [list, effectiveId, setSiteId, sites.isLoading],
  )
  return <SiteCtx.Provider value={value}>{children}</SiteCtx.Provider>
}

export function useSite(): SiteState {
  const v = useContext(SiteCtx)
  if (!v) throw new Error('SiteProvider eksik')
  return v
}
