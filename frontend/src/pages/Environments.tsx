import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Server, Plus, Users, CheckCircle2, Clock, XCircle,
  Archive, RefreshCw, ChevronDown, ChevronRight, Loader2,
} from 'lucide-react'
import api from '../api/client'
import Modal from '../components/Modal'
import { useAuth } from '../context/AuthContext'
import { useEnvironment, ENV_TYPE_COLORS, ENV_TYPE_TEXT_COLORS } from '../contexts/EnvironmentContext'
import type { Environment } from '../contexts/EnvironmentContext'

interface Organization {
  id: string
  name: string
  slug: string
  environment_count: number
  is_active: boolean
}

const STATUS_ICON = {
  ACTIVE: <CheckCircle2 className="w-4 h-4 text-green-500" />,
  PROVISIONING: <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />,
  SUSPENDED: <XCircle className="w-4 h-4 text-orange-500" />,
  ARCHIVED: <Archive className="w-4 h-4 text-gray-400" />,
}

const ENV_LABEL: Record<string, string> = { DEV: 'Dev', QA: 'QA', STAGING: 'Staging', PROD: 'Prod' }

export default function Environments() {
  const { user } = useAuth()
  const { currentEnv, switchEnvironment, refreshEnvironments } = useEnvironment()
  const qc = useQueryClient()

  const [createOpen, setCreateOpen] = useState(false)
  const [expandedEnv, setExpandedEnv] = useState<string | null>(null)

  const { data: envs = [], isLoading: envsLoading, refetch: refetchEnvs } = useQuery<Environment[]>({
    queryKey: ['environments'],
    queryFn: () => api.get('/environments').then(r => r.data),
    refetchInterval: 5000, // poll for PROVISIONING status changes
  })

  const { data: orgs = [] } = useQuery<Organization[]>({
    queryKey: ['organizations'],
    queryFn: () => api.get('/organizations').then(r => r.data),
    enabled: !!user?.is_superadmin,
  })

  const reprovisionMut = useMutation({
    mutationFn: (envId: string) => api.post(`/environments/${envId}/provision`),
    onSuccess: () => { refetchEnvs(); refreshEnvironments() },
  })

  const setDefaultMut = useMutation({
    mutationFn: ({ envId, isDefault }: { envId: string; isDefault: boolean }) =>
      api.patch(`/environments/${envId}`, { is_default: isDefault }),
    onSuccess: () => { refetchEnvs(); refreshEnvironments() },
  })

  // Group by org
  const byOrg: Record<string, { orgName: string; envs: Environment[] }> = {}
  for (const env of envs) {
    if (!byOrg[env.organization_id]) byOrg[env.organization_id] = { orgName: env.organization_name, envs: [] }
    byOrg[env.organization_id].envs.push(env)
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Server className="w-6 h-6 text-blue-600" />
            Environments
          </h1>
          <p className="text-gray-500 text-sm mt-1">
            Manage isolated environments with their own databases and integrations
          </p>
        </div>
        <button
          onClick={() => setCreateOpen(true)}
          className="btn-primary flex items-center gap-2"
        >
          <Plus className="w-4 h-4" />
          New Environment
        </button>
      </div>

      {envsLoading ? (
        <div className="flex items-center gap-2 text-gray-500 py-8">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading environments…
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(byOrg).map(([orgId, { orgName, envs: orgEnvs }]) => (
            <div key={orgId} className="card overflow-hidden p-0">
              <div className="px-4 py-3 bg-gray-50 border-b border-gray-100">
                <h2 className="font-semibold text-gray-700 text-sm">{orgName}</h2>
              </div>
              <div className="divide-y divide-gray-100">
                {orgEnvs.map(env => (
                  <div key={env.id}>
                    <div
                      className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 cursor-pointer"
                      onClick={() => setExpandedEnv(expandedEnv === env.id ? null : env.id)}
                    >
                      {/* Type dot */}
                      <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${ENV_TYPE_COLORS[env.env_type]}`} />

                      {/* Name */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium text-gray-800 text-sm">{env.name}</span>
                          <span className={`text-[10px] font-semibold px-1.5 py-0 rounded border ${ENV_TYPE_TEXT_COLORS[env.env_type]}`}>
                            {ENV_LABEL[env.env_type]}
                          </span>
                          {env.is_default && (
                            <span className="text-[10px] font-semibold px-1.5 py-0 rounded bg-gray-100 text-gray-500 border border-gray-200">
                              Default
                            </span>
                          )}
                          {currentEnv?.id === env.id && (
                            <span className="text-[10px] font-semibold px-1.5 py-0 rounded bg-green-50 text-green-600 border border-green-200">
                              Active
                            </span>
                          )}
                        </div>
                        <p className="text-gray-400 text-[11px] mt-0.5">{env.db_name}</p>
                      </div>

                      {/* Status */}
                      <div className="flex items-center gap-1 text-xs text-gray-500">
                        {STATUS_ICON[env.status as keyof typeof STATUS_ICON]}
                        <span>{env.status}</span>
                      </div>

                      {/* Member count */}
                      <div className="flex items-center gap-1 text-xs text-gray-500">
                        <Users className="w-3.5 h-3.5" />
                        <span>{env.member_count}</span>
                      </div>

                      {/* Expand toggle */}
                      {expandedEnv === env.id
                        ? <ChevronDown className="w-4 h-4 text-gray-400" />
                        : <ChevronRight className="w-4 h-4 text-gray-400" />}
                    </div>

                    {/* Expanded detail */}
                    {expandedEnv === env.id && (
                      <div className="bg-gray-50 px-4 py-3 border-t border-gray-100 space-y-3">
                        <div className="grid grid-cols-2 gap-3 text-xs">
                          <div>
                            <p className="text-gray-400 font-medium">PostgreSQL DB</p>
                            <p className="font-mono text-gray-700">{env.db_name}</p>
                          </div>
                          <div>
                            <p className="text-gray-400 font-medium">MongoDB Events</p>
                            <p className="font-mono text-gray-700">{env.mongo_events_db}</p>
                          </div>
                          <div>
                            <p className="text-gray-400 font-medium">MongoDB AI</p>
                            <p className="font-mono text-gray-700">{env.mongo_ai_db}</p>
                          </div>
                          <div>
                            <p className="text-gray-400 font-medium">ES Prefix</p>
                            <p className="font-mono text-gray-700">{env.es_index_prefix}</p>
                          </div>
                          {env.provisioned_at && (
                            <div>
                              <p className="text-gray-400 font-medium">Provisioned</p>
                              <p className="text-gray-700">{new Date(env.provisioned_at).toLocaleString()}</p>
                            </div>
                          )}
                        </div>

                        {/* Actions */}
                        <div className="flex items-center gap-2 flex-wrap">
                          {env.status === 'ACTIVE' && currentEnv?.id !== env.id && (
                            <button
                              onClick={() => switchEnvironment(env)}
                              className="btn-primary text-xs py-1 px-3"
                            >
                              Switch to this environment
                            </button>
                          )}
                          {user?.is_superadmin && env.status === 'PROVISIONING' && (
                            <button
                              onClick={() => reprovisionMut.mutate(env.id)}
                              disabled={reprovisionMut.isPending}
                              className="btn-secondary text-xs py-1 px-3 flex items-center gap-1"
                            >
                              <RefreshCw className="w-3 h-3" />
                              Re-provision
                            </button>
                          )}
                          {env.status === 'ACTIVE' && !env.is_default && (
                            <button
                              onClick={() => setDefaultMut.mutate({ envId: env.id, isDefault: true })}
                              className="btn-secondary text-xs py-1 px-3"
                            >
                              Set as default
                            </button>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}

          {envs.length === 0 && (
            <div className="text-center py-12 text-gray-400">
              <Server className="w-10 h-10 mx-auto mb-3 opacity-30" />
              <p>No environments yet. Create your first one above.</p>
            </div>
          )}
        </div>
      )}

      {createOpen && (
        <CreateEnvironmentModal
          orgs={orgs}
          onClose={() => setCreateOpen(false)}
          onCreated={() => { refetchEnvs(); refreshEnvironments(); setCreateOpen(false) }}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Create modal
// ---------------------------------------------------------------------------

function CreateEnvironmentModal({
  orgs,
  onClose,
  onCreated,
}: {
  orgs: Organization[]
  onClose: () => void
  onCreated: () => void
}) {
  const { user } = useAuth()
  const { data: allOrgs = [] } = useQuery<Organization[]>({
    queryKey: ['organizations'],
    queryFn: () => api.get('/organizations').then(r => r.data),
  })

  const [form, setForm] = useState({
    organization_id: orgs[0]?.id || '',
    name: '',
    slug: '',
    env_type: 'DEV',
    is_default: false,
  })
  const [error, setError] = useState('')

  const mut = useMutation({
    mutationFn: () => api.post('/environments', form),
    onSuccess: onCreated,
    onError: (err: any) => {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail))
    },
  })

  const availableOrgs = user?.is_superadmin ? allOrgs : orgs

  return (
    <Modal open title="Create Environment" onClose={onClose}>
      <div className="space-y-4">
        {availableOrgs.length > 1 && (
          <div>
            <label className="label">Organization</label>
            <select
              className="select"
              value={form.organization_id}
              onChange={e => setForm(f => ({ ...f, organization_id: e.target.value }))}
            >
              {availableOrgs.map(o => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </select>
          </div>
        )}

        <div>
          <label className="label">Name</label>
          <input
            className="input"
            placeholder="e.g. Development"
            value={form.name}
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
          />
        </div>

        <div>
          <label className="label">Slug</label>
          <input
            className="input font-mono"
            placeholder="e.g. dev"
            value={form.slug}
            onChange={e => setForm(f => ({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '') }))}
          />
          <p className="text-xs text-gray-400 mt-1">
            Will create database: oms_{'{org_slug}'}_{form.slug || '<slug>'}
          </p>
        </div>

        <div>
          <label className="label">Type</label>
          <select
            className="select"
            value={form.env_type}
            onChange={e => setForm(f => ({ ...f, env_type: e.target.value }))}
          >
            <option value="DEV">Development</option>
            <option value="QA">QA</option>
            <option value="STAGING">Staging</option>
            <option value="PROD">Production</option>
          </select>
        </div>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={form.is_default}
            onChange={e => setForm(f => ({ ...f, is_default: e.target.checked }))}
            className="w-4 h-4"
          />
          <span className="text-sm text-gray-700">Set as default for this organization</span>
        </label>

        {error && <p className="text-red-600 text-sm">{error}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button
            className="btn-primary flex items-center gap-2"
            onClick={() => mut.mutate()}
            disabled={mut.isPending || !form.name || !form.slug || !form.organization_id}
          >
            {mut.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            Create Environment
          </button>
        </div>
      </div>
    </Modal>
  )
}
