import {
  createContext,
  useContext,
  useState,
  useEffect,
  useRef,
  useMemo,
  useCallback,
  ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'

export type TenantMode = 'B2C_ONLY' | 'B2B_ONLY' | 'HYBRID'

export interface Environment {
  id: string
  organization_id: string
  organization_name: string
  tenant_mode: TenantMode
  name: string
  slug: string
  env_type: 'DEV' | 'QA' | 'STAGING' | 'PROD'
  status: 'PROVISIONING' | 'ACTIVE' | 'SUSPENDED' | 'ARCHIVED'
  db_name: string
  mongo_events_db: string
  mongo_ai_db: string
  es_index_prefix: string
  base_url: string | null
  is_default: boolean
  provisioned_at: string | null
  created_at: string
  member_count: number
}

interface EnvironmentContextValue {
  currentEnv: Environment | null
  environments: Environment[]
  isLoading: boolean
  tenantMode: TenantMode
  isB2BEnabled: boolean
  isB2CEnabled: boolean
  switchEnvironment: (env: Environment) => void
  refreshEnvironments: () => void
}

const EnvironmentContext = createContext<EnvironmentContextValue | null>(null)

const ENV_STORAGE_KEY = 'oms_environment_id'

export const ENV_TYPE_COLORS: Record<string, string> = {
  DEV: 'bg-blue-500',
  QA: 'bg-yellow-500',
  STAGING: 'bg-orange-500',
  PROD: 'bg-red-500',
}

export const ENV_TYPE_TEXT_COLORS: Record<string, string> = {
  DEV: 'text-blue-700 bg-blue-50 border-blue-200',
  QA: 'text-yellow-700 bg-yellow-50 border-yellow-200',
  STAGING: 'text-orange-700 bg-orange-50 border-orange-200',
  PROD: 'text-red-700 bg-red-50 border-red-200',
}

export function EnvironmentProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [environments, setEnvironments] = useState<Environment[]>([])
  // Store only the selected ID — derive the full object via useMemo.
  // This avoids stale-object-reference races when fetchEnvironments refreshes the list.
  const [currentEnvId, setCurrentEnvId] = useState<string | null>(() =>
    localStorage.getItem(ENV_STORAGE_KEY),
  )
  const [isLoading, setIsLoading] = useState(true)

  // currentEnv is always derived from the latest environments list + selected ID.
  // Guaranteed to be consistent with no extra state synchronization needed.
  const currentEnv = useMemo(
    () => environments.find(e => e.id === currentEnvId) ?? null,
    [environments, currentEnvId],
  )

  const tenantMode: TenantMode = currentEnv?.tenant_mode ?? 'HYBRID'
  const isB2BEnabled = tenantMode !== 'B2C_ONLY'
  const isB2CEnabled = tenantMode !== 'B2B_ONLY'

  // Invalidate query cache AFTER React commits the currentEnvId change.
  // Moving this out of switchEnvironment prevents TanStack Query's
  // useSyncExternalStore from firing synchronously before the new currentEnvId
  // has been committed, which was causing the label to show the old environment.
  const prevEnvIdRef = useRef<string | null>(null)
  useEffect(() => {
    if (prevEnvIdRef.current !== null && prevEnvIdRef.current !== currentEnvId) {
      queryClient.invalidateQueries()
    }
    prevEnvIdRef.current = currentEnvId
  }, [currentEnvId, queryClient])

  const fetchEnvironments = useCallback(async () => {
    try {
      const userRaw = localStorage.getItem('oms_auth_user')
      if (!userRaw) {
        setIsLoading(false)
        return
      }
      const res = await fetch('/api/environments', {
        credentials: 'include',
      })
      if (!res.ok) return
      const data: Environment[] = await res.json()
      setEnvironments(data)

      // Only change the selected ID if the current selection is no longer valid.
      setCurrentEnvId(prev => {
        if (prev && data.some(e => e.id === prev && e.status === 'ACTIVE')) return prev
        const storedId = localStorage.getItem(ENV_STORAGE_KEY)
        const stored = data.find(e => e.id === storedId && e.status === 'ACTIVE')
        const defaultEnv = data.find(e => e.is_default && e.status === 'ACTIVE')
        const active = data.find(e => e.status === 'ACTIVE')
        const resolved = stored || defaultEnv || active || data[0] || null
        if (resolved) localStorage.setItem(ENV_STORAGE_KEY, resolved.id)
        return resolved?.id ?? null
      })
    } catch {
      // non-fatal
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchEnvironments()
  }, [fetchEnvironments])

  const switchEnvironment = useCallback(
    (env: Environment) => {
      // Cross-pod redirect: navigate to the environment's own deployment URL.
      if (env.base_url) {
        try {
          const targetOrigin = new URL(env.base_url).origin
          if (targetOrigin !== window.location.origin) {
            localStorage.setItem(ENV_STORAGE_KEY, env.id)
            const userRaw = localStorage.getItem('oms_auth_user') ?? ''
            const params = new URLSearchParams()
            if (userRaw) params.set('_oms_user', userRaw)
            const qs = params.toString()
            window.location.href = env.base_url + (qs ? '?' + qs : '')
            return
          }
        } catch {
          // Invalid URL — fall through to in-context switch
        }
      }

      // Update the selected ID. currentEnv (derived via useMemo) updates in the
      // same render cycle — no separate setCurrentEnv call needed.
      // Query cache invalidation happens in a useEffect after React commits,
      // so TanStack Query never sees stale state during the label re-render.
      setCurrentEnvId(env.id)
      localStorage.setItem(ENV_STORAGE_KEY, env.id)
    },
    [],
  )

  const refreshEnvironments = useCallback(() => {
    fetchEnvironments()
  }, [fetchEnvironments])

  return (
    <EnvironmentContext.Provider
      value={{ currentEnv, environments, isLoading, tenantMode, isB2BEnabled, isB2CEnabled, switchEnvironment, refreshEnvironments }}
    >
      {children}
    </EnvironmentContext.Provider>
  )
}

export function useEnvironment() {
  const ctx = useContext(EnvironmentContext)
  if (!ctx) throw new Error('useEnvironment must be used inside <EnvironmentProvider>')
  return ctx
}
