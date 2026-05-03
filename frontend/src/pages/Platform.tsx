import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Crown, Building2, Server, Users, Plus, Pencil, Check, X,
  Loader2, ChevronDown, ChevronRight, Download, Link,
} from 'lucide-react'
import api from '../api/client'
import Modal from '../components/Modal'
import { useEnvironment, ENV_TYPE_COLORS } from '../contexts/EnvironmentContext'

// ─── Types ───────────────────────────────────────────────────────────────────

interface Organization {
  id: string
  name: string
  slug: string
  description: string | null
  is_active: boolean
  environment_count: number
}

interface Environment {
  id: string
  organization_id: string
  organization_name: string
  name: string
  slug: string
  env_type: 'DEV' | 'QA' | 'STAGING' | 'PROD'
  status: string
  db_name: string
  base_url: string | null
  is_default: boolean
  member_count: number
}

interface PlatformUser {
  id: string
  email: string
  full_name: string | null
  is_active: boolean
  is_superadmin: boolean
  platform_role: string
  group_name: string | null
  created_at: string
}

const TABS = ['Organizations', 'Environments', 'Users'] as const
type Tab = typeof TABS[number]

const ENV_TYPE_LABEL: Record<string, string> = { DEV: 'Dev', QA: 'QA', STAGING: 'Staging', PROD: 'Prod' }

const PLATFORM_ROLE_CONFIG: Record<string, { label: string; color: string }> = {
  PLATFORM_OWNER: { label: 'Platform Owner', color: 'text-yellow-600 bg-yellow-50 border-yellow-200' },
  SUPERADMIN:     { label: 'Superadmin',     color: 'text-purple-600 bg-purple-50 border-purple-200' },
  USER:           { label: 'User',            color: 'text-gray-500 bg-gray-50 border-gray-200' },
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function Platform() {
  const [activeTab, setActiveTab] = useState<Tab>('Organizations')

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 bg-yellow-100 rounded-xl flex items-center justify-center">
          <Crown className="w-5 h-5 text-yellow-600" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Platform Console</h1>
          <p className="text-gray-500 text-sm">Manage organizations, environments, and platform-level access</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-gray-100 rounded-xl mb-6 w-fit">
        {TABS.map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === tab
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab === 'Organizations' && <Building2 className="w-3.5 h-3.5 inline mr-1.5 -mt-0.5" />}
            {tab === 'Environments' && <Server className="w-3.5 h-3.5 inline mr-1.5 -mt-0.5" />}
            {tab === 'Users' && <Users className="w-3.5 h-3.5 inline mr-1.5 -mt-0.5" />}
            {tab}
          </button>
        ))}
      </div>

      {activeTab === 'Organizations' && <OrganizationsTab />}
      {activeTab === 'Environments' && <EnvironmentsTab />}
      {activeTab === 'Users' && <UsersTab />}
    </div>
  )
}

// ─── Organizations Tab ────────────────────────────────────────────────────────

function OrganizationsTab() {
  const qc = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [editOrg, setEditOrg] = useState<Organization | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const { data: orgs = [], isLoading } = useQuery<Organization[]>({
    queryKey: ['platform-orgs'],
    queryFn: () => api.get('/organizations').then(r => r.data),
  })

  const { data: allEnvs = [] } = useQuery<Environment[]>({
    queryKey: ['platform-envs'],
    queryFn: () => api.get('/environments').then(r => r.data),
  })

  const toggleActiveMut = useMutation({
    mutationFn: (org: Organization) =>
      api.patch(`/organizations/${org.id}`, { is_active: !org.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['platform-orgs'] }),
  })

  if (isLoading) {
    return <div className="flex items-center gap-2 text-gray-500"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>
  }

  const envsByOrg = allEnvs.reduce<Record<string, Environment[]>>((acc, e) => {
    if (!acc[e.organization_id]) acc[e.organization_id] = []
    acc[e.organization_id].push(e)
    return acc
  }, {})

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button onClick={() => setCreateOpen(true)} className="btn-primary flex items-center gap-2">
          <Plus className="w-4 h-4" /> New Organization
        </button>
      </div>

      <div className="card p-0 overflow-hidden">
        {orgs.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            <Building2 className="w-10 h-10 mx-auto mb-3 opacity-30" />
            <p>No organizations yet.</p>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {orgs.map(org => {
              const orgEnvs = envsByOrg[org.id] || []
              const isExpanded = expanded === org.id
              return (
                <div key={org.id}>
                  <div
                    className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 cursor-pointer"
                    onClick={() => setExpanded(isExpanded ? null : org.id)}
                  >
                    <div className={`w-2 h-2 rounded-full flex-shrink-0 ${org.is_active ? 'bg-green-400' : 'bg-gray-300'}`} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-gray-800 text-sm">{org.name}</span>
                        <span className="font-mono text-gray-400 text-[11px]">/{org.slug}</span>
                        {!org.is_active && (
                          <span className="text-[10px] px-1.5 rounded bg-gray-100 text-gray-500 border border-gray-200">Inactive</span>
                        )}
                      </div>
                      {org.description && (
                        <p className="text-gray-400 text-[11px] mt-0.5 truncate">{org.description}</p>
                      )}
                    </div>
                    <span className="text-xs text-gray-500">{org.environment_count} env{org.environment_count !== 1 ? 's' : ''}</span>
                    {isExpanded ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
                  </div>

                  {isExpanded && (
                    <div className="bg-gray-50 px-4 py-3 border-t border-gray-100">
                      {/* Environments list */}
                      {orgEnvs.length > 0 ? (
                        <div className="mb-3 space-y-1">
                          {orgEnvs.map(env => (
                            <div key={env.id} className="flex items-center gap-2 text-xs text-gray-600">
                              <span className={`w-2 h-2 rounded-full ${ENV_TYPE_COLORS[env.env_type]}`} />
                              <span className="font-medium">{env.name}</span>
                              <span className="text-gray-400">{ENV_TYPE_LABEL[env.env_type]}</span>
                              <span className={`px-1.5 py-0 rounded text-[10px] border ${
                                env.status === 'ACTIVE' ? 'text-green-600 border-green-200 bg-green-50' : 'text-orange-500 border-orange-200 bg-orange-50'
                              }`}>{env.status}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-gray-400 mb-3">No environments yet.</p>
                      )}
                      <div className="flex gap-2">
                        <button
                          onClick={() => setEditOrg(org)}
                          className="btn-secondary text-xs py-1 px-3 flex items-center gap-1"
                        >
                          <Pencil className="w-3 h-3" /> Edit
                        </button>
                        <button
                          onClick={() => toggleActiveMut.mutate(org)}
                          disabled={toggleActiveMut.isPending}
                          className="btn-secondary text-xs py-1 px-3"
                        >
                          {org.is_active ? 'Deactivate' : 'Activate'}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {createOpen && (
        <OrgFormModal
          onClose={() => setCreateOpen(false)}
          onSaved={() => { qc.invalidateQueries({ queryKey: ['platform-orgs'] }); setCreateOpen(false) }}
        />
      )}
      {editOrg && (
        <OrgFormModal
          org={editOrg}
          onClose={() => setEditOrg(null)}
          onSaved={() => { qc.invalidateQueries({ queryKey: ['platform-orgs'] }); setEditOrg(null) }}
        />
      )}
    </div>
  )
}

function OrgFormModal({ org, onClose, onSaved }: { org?: Organization; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    name: org?.name || '',
    slug: org?.slug || '',
    description: org?.description || '',
  })
  const [error, setError] = useState('')

  const mut = useMutation({
    mutationFn: () =>
      org
        ? api.patch(`/organizations/${org.id}`, { name: form.name, description: form.description || null })
        : api.post('/organizations', form),
    onSuccess: onSaved,
    onError: (err: any) => {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail))
    },
  })

  return (
    <Modal open title={org ? 'Edit Organization' : 'New Organization'} onClose={onClose}>
      <div className="space-y-4">
        <div>
          <label className="label">Organization Name</label>
          <input
            className="input"
            placeholder="e.g. Acme Corp"
            value={form.name}
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
          />
        </div>
        {!org && (
          <div>
            <label className="label">Slug</label>
            <input
              className="input font-mono"
              placeholder="e.g. acme"
              value={form.slug}
              onChange={e => setForm(f => ({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '') }))}
            />
            <p className="text-xs text-gray-400 mt-1">Lowercase letters, numbers, hyphens. Used in database names.</p>
          </div>
        )}
        <div>
          <label className="label">Description <span className="text-gray-400">(optional)</span></label>
          <textarea
            className="input resize-none"
            rows={2}
            placeholder="What this organization is for…"
            value={form.description}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
          />
        </div>
        {error && <p className="text-red-600 text-sm">{error}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button
            className="btn-primary flex items-center gap-2"
            onClick={() => mut.mutate()}
            disabled={mut.isPending || !form.name || (!org && !form.slug)}
          >
            {mut.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            {org ? 'Save Changes' : 'Create Organization'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ─── Environments Tab ─────────────────────────────────────────────────────────

function EnvironmentsTab() {
  const qc = useQueryClient()
  const { refreshEnvironments } = useEnvironment()
  const [createOpen, setCreateOpen] = useState(false)

  const { data: orgs = [] } = useQuery<Organization[]>({
    queryKey: ['platform-orgs'],
    queryFn: () => api.get('/organizations').then(r => r.data),
  })

  const { data: envs = [], isLoading, refetch } = useQuery<Environment[]>({
    queryKey: ['platform-envs'],
    queryFn: () => api.get('/environments').then(r => r.data),
    refetchInterval: 5000,
  })

  // Group by org
  const byOrg: Record<string, { orgName: string; envs: Environment[] }> = {}
  for (const env of envs) {
    if (!byOrg[env.organization_id]) byOrg[env.organization_id] = { orgName: env.organization_name, envs: [] }
    byOrg[env.organization_id].envs.push(env)
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button onClick={() => setCreateOpen(true)} className="btn-primary flex items-center gap-2" disabled={orgs.length === 0}>
          <Plus className="w-4 h-4" /> New Environment
        </button>
      </div>

      {orgs.length === 0 && (
        <div className="card text-center py-8 text-gray-400">
          <p>Create an organization first before adding environments.</p>
        </div>
      )}

      {isLoading ? (
        <div className="flex items-center gap-2 text-gray-500"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>
      ) : (
        <div className="space-y-4">
          {Object.entries(byOrg).map(([orgId, { orgName, envs: orgEnvs }]) => (
            <div key={orgId} className="card overflow-hidden p-0">
              <div className="px-4 py-3 bg-gray-50 border-b border-gray-100">
                <h2 className="font-semibold text-gray-700 text-sm flex items-center gap-2">
                  <Building2 className="w-3.5 h-3.5 text-gray-400" />
                  {orgName}
                </h2>
              </div>
              <div className="divide-y divide-gray-100">
                {orgEnvs.map(env => (
                  <EnvCard key={env.id} env={env} onUpdated={refetch} />
                ))}
              </div>
            </div>
          ))}

          {envs.length === 0 && orgs.length > 0 && (
            <div className="text-center py-12 text-gray-400">
              <Server className="w-10 h-10 mx-auto mb-3 opacity-30" />
              <p>No environments yet.</p>
            </div>
          )}
        </div>
      )}

      {createOpen && (
        <CreateEnvModal
          orgs={orgs}
          onClose={() => setCreateOpen(false)}
          onCreated={() => {
            refetch()
            refreshEnvironments()
            qc.invalidateQueries({ queryKey: ['environments'] })
            setCreateOpen(false)
          }}
        />
      )}
    </div>
  )
}

// ─── Environment Card ─────────────────────────────────────────────────────────

function EnvCard({ env, onUpdated }: { env: Environment; onUpdated: () => void }) {
  const qc = useQueryClient()
  const [editingUrl, setEditingUrl] = useState(false)
  const [urlInput, setUrlInput] = useState(env.base_url || '')
  const [showInstructions, setShowInstructions] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const deleteMut = useMutation({
    mutationFn: () => api.delete(`/environments/${env.id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['platform-envs'] })
      qc.invalidateQueries({ queryKey: ['environments'] })
      onUpdated()
    },
  })

  const isProvisioning = env.status === 'PROVISIONING'

  const updateUrlMut = useMutation({
    mutationFn: (url: string) => api.patch(`/environments/${env.id}`, { base_url: url || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['platform-envs'] })
      qc.invalidateQueries({ queryKey: ['environments'] })
      onUpdated()
      setEditingUrl(false)
    },
  })

  const downloadConfig = async () => {
    const res = await fetch(`/api/environments/${env.id}/deployment-config`, {
      credentials: 'include',
    })
    if (!res.ok) { alert('Config not ready yet — wait for ACTIVE status'); return }
    const blob = await res.blob()
    const apiPort = res.headers.get('X-Api-Port') || '?'
    const frontendPort = res.headers.get('X-Frontend-Port') || '?'
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const cd = res.headers.get('Content-Disposition') || ''
    const match = cd.match(/filename="([^"]+)"/)
    a.download = match ? match[1] : 'docker-compose.yml'
    a.click()
    URL.revokeObjectURL(url)
    // Show instructions after download
    setUrlInput(`http://localhost:${frontendPort}`)
    setShowInstructions(true)
  }

  return (
    <div className="px-4 py-3 space-y-2">
      {/* Row 1: name + status */}
      <div className="flex items-center gap-3">
        <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${ENV_TYPE_COLORS[env.env_type]}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-gray-800 text-sm">{env.name}</span>
            <span className="text-[10px] font-semibold px-1.5 rounded border text-gray-500 border-gray-200 bg-gray-50">
              {ENV_TYPE_LABEL[env.env_type]}
            </span>
            {env.is_default && (
              <span className="text-[10px] px-1.5 rounded bg-blue-50 text-blue-500 border border-blue-200">Default</span>
            )}
          </div>
          <p className="text-gray-400 text-[11px] font-mono">{env.db_name}</p>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full border flex items-center gap-1 ${
          env.status === 'ACTIVE' ? 'text-green-600 border-green-200 bg-green-50' :
          isProvisioning ? 'text-blue-600 border-blue-200 bg-blue-50' :
          'text-gray-500 border-gray-200 bg-gray-50'
        }`}>
          {isProvisioning && <Loader2 className="w-2.5 h-2.5 animate-spin" />}
          {env.status}
        </span>
      </div>

      {/* Row 2: actions (only when ACTIVE) */}
      {env.status === 'ACTIVE' && (
        <div className="ml-5 space-y-2">
          {/* Deployment URL row */}
          {editingUrl ? (
            <div className="flex items-center gap-1.5">
              <input
                className="input text-xs py-1 flex-1"
                placeholder="https://acme-dev.youroms.com"
                value={urlInput}
                onChange={e => setUrlInput(e.target.value)}
                autoFocus
              />
              <button
                onClick={() => updateUrlMut.mutate(urlInput)}
                disabled={updateUrlMut.isPending}
                className="btn-primary text-xs py-1 px-2 flex items-center gap-1"
              >
                {updateUrlMut.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
              </button>
              <button onClick={() => setEditingUrl(false)} className="btn-secondary text-xs py-1 px-2">
                <X className="w-3 h-3" />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              {env.base_url ? (
                <a href={env.base_url} target="_blank" rel="noopener noreferrer"
                   className="text-blue-500 text-[11px] hover:underline truncate max-w-xs flex items-center gap-1">
                  <Link className="w-2.5 h-2.5 flex-shrink-0" />
                  {env.base_url}
                </a>
              ) : (
                <span className="text-gray-400 text-[11px]">No deployment URL set</span>
              )}
              <button
                onClick={() => { setUrlInput(env.base_url || ''); setEditingUrl(true) }}
                className="text-gray-400 hover:text-gray-600 transition-colors"
                title="Set deployment URL"
              >
                <Pencil className="w-3 h-3" />
              </button>
            </div>
          )}

          {/* Download config button */}
          <div className="flex items-center gap-2">
            <button
              onClick={downloadConfig}
              className="btn-secondary text-xs py-1 px-2 flex items-center gap-1.5"
            >
              <Download className="w-3 h-3" />
              Download Compose Config
            </button>
            {showInstructions && (
              <span className="text-[11px] text-gray-500">↓ Run the file, then set URL above</span>
            )}
          </div>

          {/* Inline instructions after download */}
          {showInstructions && (
            <div className="bg-gray-900 rounded-lg p-3 text-[11px] font-mono space-y-1">
              <p className="text-gray-400"># 1. Run the downloaded file:</p>
              <p className="text-green-400 select-all">docker-compose -f docker-compose.{env.db_name.replace('oms_', '')}.yml up -d</p>
              <p className="text-gray-400 mt-1"># 2. Set Deployment URL above to:</p>
              <p className="text-yellow-300 select-all">{urlInput}</p>
              <button
                onClick={() => setShowInstructions(false)}
                className="text-gray-500 hover:text-gray-300 mt-1 text-[10px]"
              >
                dismiss
              </button>
            </div>
          )}

          {/* Delete */}
          {!confirmDelete ? (
            <button
              onClick={() => setConfirmDelete(true)}
              className="text-[11px] text-red-400 hover:text-red-600 transition-colors"
            >
              Delete environment…
            </button>
          ) : (
            <div className="flex items-center gap-2 p-2 bg-red-50 border border-red-200 rounded-lg">
              <span className="text-xs text-red-700 flex-1">
                Delete <strong>{env.name}</strong>? This removes the record but does NOT drop the database.
                Stop the compose stack manually first.
              </span>
              <button
                onClick={() => deleteMut.mutate()}
                disabled={deleteMut.isPending}
                className="btn-danger text-xs py-1 px-2 flex items-center gap-1"
              >
                {deleteMut.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <X className="w-3 h-3" />}
                Delete
              </button>
              <button onClick={() => setConfirmDelete(false)} className="btn-secondary text-xs py-1 px-2">
                Cancel
              </button>
            </div>
          )}
        </div>
      )}

      {/* Provisioning message */}
      {isProvisioning && (
        <p className="ml-5 text-[11px] text-blue-500">
          Creating database and running migrations… refresh in a few seconds.
        </p>
      )}
    </div>
  )
}

function CreateEnvModal({ orgs, onClose, onCreated }: { orgs: Organization[]; onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState({
    organization_id: orgs[0]?.id || '',
    name: '',
    slug: '',
    env_type: 'DEV',
    base_url: '',
    is_default: false,
  })
  const [error, setError] = useState('')

  const selectedOrg = orgs.find(o => o.id === form.organization_id)

  const mut = useMutation({
    mutationFn: () => api.post('/environments', {
      ...form,
      base_url: form.base_url || null,
    }),
    onSuccess: onCreated,
    onError: (err: any) => {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail))
    },
  })

  return (
    <Modal open title="New Environment" onClose={onClose}>
      <div className="space-y-4">
        <div>
          <label className="label">Organization</label>
          <select
            className="select"
            value={form.organization_id}
            onChange={e => setForm(f => ({ ...f, organization_id: e.target.value }))}
          >
            {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Environment Name</label>
          <input
            className="input"
            placeholder="e.g. Production"
            value={form.name}
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
          />
        </div>
        <div>
          <label className="label">Slug</label>
          <input
            className="input font-mono"
            placeholder="e.g. prod"
            value={form.slug}
            onChange={e => setForm(f => ({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '') }))}
          />
          <p className="text-xs text-gray-400 mt-1">
            Database: oms_{selectedOrg?.slug || '<org>'}_{form.slug || '<slug>'}
          </p>
        </div>
        <div>
          <label className="label">Type</label>
          <select className="select" value={form.env_type} onChange={e => setForm(f => ({ ...f, env_type: e.target.value }))}>
            <option value="DEV">Development</option>
            <option value="QA">QA</option>
            <option value="STAGING">Staging</option>
            <option value="PROD">Production</option>
          </select>
        </div>
        <div>
          <label className="label">
            Deployment URL <span className="text-gray-400">(optional)</span>
          </label>
          <input
            className="input"
            placeholder="https://acme-dev.youroms.com"
            value={form.base_url}
            onChange={e => setForm(f => ({ ...f, base_url: e.target.value }))}
          />
          <p className="text-xs text-gray-400 mt-1">
            The URL of the K8s pod for this environment. Used by the switcher to redirect users.
          </p>
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

// ─── Users Tab ────────────────────────────────────────────────────────────────

function UsersTab() {
  const qc = useQueryClient()
  const [roleTarget, setRoleTarget] = useState<PlatformUser | null>(null)

  const { data: users = [], isLoading } = useQuery<PlatformUser[]>({
    queryKey: ['platform-users'],
    queryFn: () => api.get('/admin/users').then(r => r.data),
  })

  const roleMut = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      api.patch(`/admin/users/${userId}/platform-role`, { platform_role: role }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['platform-users'] }); setRoleTarget(null) },
  })

  if (isLoading) {
    return <div className="flex items-center gap-2 text-gray-500"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">
        Assign platform-level roles. <strong>Platform Owners</strong> can create organizations and environments.{' '}
        <strong>Superadmins</strong> can access the admin console but cannot create orgs/envs.
      </p>

      <div className="card p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100">
              <th className="table-header text-left">User</th>
              <th className="table-header text-left">Platform Role</th>
              <th className="table-header text-left">Group</th>
              <th className="table-header text-left">Status</th>
              <th className="table-header" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {users.map(u => {
              const roleCfg = PLATFORM_ROLE_CONFIG[u.platform_role] || PLATFORM_ROLE_CONFIG.USER
              return (
                <tr key={u.id} className="hover:bg-gray-50">
                  <td className="table-cell">
                    <div>
                      <p className="font-medium text-gray-800">{u.full_name || u.email}</p>
                      {u.full_name && <p className="text-gray-400 text-[11px]">{u.email}</p>}
                    </div>
                  </td>
                  <td className="table-cell">
                    <span className={`text-[11px] font-semibold px-2 py-0.5 rounded border ${roleCfg.color}`}>
                      {roleCfg.label}
                    </span>
                  </td>
                  <td className="table-cell text-gray-500">{u.group_name || '—'}</td>
                  <td className="table-cell">
                    <span className={`text-[11px] px-1.5 rounded border ${u.is_active ? 'text-green-600 border-green-200 bg-green-50' : 'text-gray-400 border-gray-200 bg-gray-50'}`}>
                      {u.is_active ? 'Active' : 'Disabled'}
                    </span>
                  </td>
                  <td className="table-cell">
                    <button
                      onClick={() => setRoleTarget(u)}
                      className="btn-secondary text-xs py-1 px-2"
                    >
                      Change Role
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {roleTarget && (
        <Modal open title={`Change Role — ${roleTarget.full_name || roleTarget.email}`} onClose={() => setRoleTarget(null)}>
          <div className="space-y-3">
            <p className="text-sm text-gray-600">Select the platform-level role for this user:</p>
            {(['PLATFORM_OWNER', 'SUPERADMIN', 'USER'] as const).map(role => {
              const cfg = PLATFORM_ROLE_CONFIG[role]
              const isCurrentRole = roleTarget.platform_role === role
              return (
                <button
                  key={role}
                  onClick={() => roleMut.mutate({ userId: roleTarget.id, role })}
                  disabled={roleMut.isPending || isCurrentRole}
                  className={`w-full flex items-center justify-between px-4 py-3 rounded-xl border text-left transition-colors ${
                    isCurrentRole
                      ? 'border-blue-300 bg-blue-50'
                      : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                  } disabled:opacity-50 disabled:cursor-not-allowed`}
                >
                  <div>
                    <p className="font-medium text-gray-800 text-sm">{cfg.label}</p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {role === 'PLATFORM_OWNER' && 'Create orgs, environments; assign platform roles'}
                      {role === 'SUPERADMIN' && 'Admin console access; cannot create orgs/environments'}
                      {role === 'USER' && 'Standard user; access only via environment roles'}
                    </p>
                  </div>
                  {isCurrentRole && <Check className="w-4 h-4 text-blue-500 flex-shrink-0" />}
                  {roleMut.isPending && !isCurrentRole && <Loader2 className="w-4 h-4 text-gray-400 animate-spin flex-shrink-0" />}
                </button>
              )
            })}
            <div className="flex justify-end pt-2">
              <button className="btn-secondary" onClick={() => setRoleTarget(null)}>Cancel</button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
