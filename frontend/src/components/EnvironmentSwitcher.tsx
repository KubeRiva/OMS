import { useState, useRef, useEffect } from 'react'
import { ChevronDown, CheckCircle2, Loader2, Server } from 'lucide-react'
import { useEnvironment, Environment, ENV_TYPE_COLORS, ENV_TYPE_TEXT_COLORS } from '../contexts/EnvironmentContext'

const ENV_LABELS: Record<string, string> = {
  DEV: 'Dev',
  QA: 'QA',
  STAGING: 'Staging',
  PROD: 'Prod',
}

export default function EnvironmentSwitcher() {
  const { currentEnv, environments, isLoading, switchEnvironment } = useEnvironment()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  if (isLoading) {
    return (
      <div className="flex items-center gap-1.5 text-gray-400 text-xs">
        <Loader2 className="w-3 h-3 animate-spin" />
        <span>Loading...</span>
      </div>
    )
  }

  if (!currentEnv) return null

  // Group environments by organization
  const byOrg: Record<string, { orgName: string; envs: Environment[] }> = {}
  for (const env of environments) {
    if (!byOrg[env.organization_id]) {
      byOrg[env.organization_id] = { orgName: env.organization_name, envs: [] }
    }
    byOrg[env.organization_id].envs.push(env)
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 transition-colors"
      >
        {/* Dot */}
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${ENV_TYPE_COLORS[currentEnv.env_type]}`} />
        <div className="text-left min-w-0">
          <p className="text-white text-xs font-medium leading-tight truncate max-w-28">{currentEnv.name}</p>
          <p className="text-gray-400 text-[10px] leading-tight truncate">{currentEnv.organization_name}</p>
        </div>
        <ChevronDown className={`w-3 h-3 text-gray-400 flex-shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1 w-64 bg-white rounded-xl shadow-2xl border border-gray-100 z-50 overflow-hidden">
          {Object.entries(byOrg).map(([orgId, { orgName, envs }]) => (
            <div key={orgId}>
              <div className="px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase tracking-wider bg-gray-50 border-b border-gray-100">
                {orgName}
              </div>
              {envs.map(env => (
                <button
                  key={env.id}
                  onClick={() => { switchEnvironment(env); setOpen(false) }}
                  disabled={env.status !== 'ACTIVE'}
                  className="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${ENV_TYPE_COLORS[env.env_type]}`} />
                  <div className="flex-1 text-left min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-gray-800 text-xs font-medium">{env.name}</span>
                      <span className={`text-[9px] font-semibold px-1 py-0 rounded border ${ENV_TYPE_TEXT_COLORS[env.env_type]}`}>
                        {ENV_LABELS[env.env_type]}
                      </span>
                    </div>
                    {env.status !== 'ACTIVE' && (
                      <p className="text-[10px] text-orange-500">{env.status}</p>
                    )}
                  </div>
                  {currentEnv.id === env.id && (
                    <CheckCircle2 className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />
                  )}
                </button>
              ))}
            </div>
          ))}
          <div className="border-t border-gray-100">
            <a
              href="/environments"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 px-3 py-2 hover:bg-gray-50 transition-colors text-xs text-gray-500"
            >
              <Server className="w-3.5 h-3.5" />
              <span>Manage Environments</span>
            </a>
          </div>
        </div>
      )}
    </div>
  )
}
