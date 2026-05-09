import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Tag, Plus, ToggleLeft, ToggleRight, Trash2, RefreshCw,
  Copy, Settings, Network, ChevronRight, Info, AlertTriangle,
  Check,
} from 'lucide-react'
import {
  getBrands, createBrand, updateBrand, deleteBrand, toggleBrand,
  getBrandConfig, upsertBrandConfig, getBrandNodes, assignBrandNode,
  removeBrandNode, cloneBrand, fetchNodes,
  type Brand, type BrandUpdate, type BrandTenantMode,
  type BrandConfig, type BrandNode, type BrandCloneRequest, type FulfillmentNode,
} from '../api/client'
import Modal from '../components/Modal'

// ─── Constants ────────────────────────────────────────────────────────────────

const TENANT_MODES: BrandTenantMode[] = ['B2C_ONLY', 'B2B_ONLY', 'HYBRID']

const TENANT_MODE_LABELS: Record<BrandTenantMode, string> = {
  B2C_ONLY: 'B2C Only',
  B2B_ONLY: 'B2B Only',
  HYBRID: 'Hybrid',
}

const TENANT_MODE_DESC: Record<BrandTenantMode, string> = {
  B2C_ONLY: 'Brand only supports retail / consumer orders.',
  B2B_ONLY: 'Brand only supports business / wholesale orders.',
  HYBRID: 'Brand supports both B2C retail and B2B wholesale orders.',
}

const TENANT_MODE_CLASSES: Record<BrandTenantMode, string> = {
  B2C_ONLY: 'bg-blue-100 text-blue-700',
  B2B_ONLY: 'bg-amber-100 text-amber-700',
  HYBRID: 'bg-purple-100 text-purple-700',
}

const FULFILLMENT_TYPES = [
  'SHIP_TO_HOME',
  'STORE_PICKUP',
  'CURBSIDE_PICKUP',
  'SHIP_FROM_STORE',
  'DROPSHIP',
  'LOCKER_PICKUP',
  'SAME_DAY_DELIVERY',
]

const SLUG_RE = /^[a-z0-9-]+$/

// ─── Helpers ─────────────────────────────────────────────────────────────────

function getErrMsg(e: unknown): string {
  const err = e as { response?: { data?: { detail?: unknown } } }
  const detail = err.response?.data?.detail
  if (Array.isArray(detail)) return detail.map((d: { msg: string }) => d.msg).join(', ')
  if (typeof detail === 'string') return detail
  return 'An error occurred'
}

function slugError(slug: string): string | null {
  if (slug.length < 2) return 'Slug must be at least 2 characters'
  if (slug.length > 80) return 'Slug must be at most 80 characters'
  if (!SLUG_RE.test(slug)) return 'Slug may only contain lowercase letters, numbers and hyphens'
  return null
}

function toSlug(name: string) {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
}

// ─── Toggle Switch ────────────────────────────────────────────────────────────

function Toggle({
  checked,
  onChange,
  label,
  note,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label?: string
  note?: string
}) {
  return (
    <div className="flex items-start gap-3">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 ${checked ? 'bg-blue-600' : 'bg-gray-200'}`}
      >
        <span
          className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-4' : 'translate-x-0'}`}
        />
      </button>
      {label && (
        <div>
          <span className="text-sm font-medium text-gray-700">{label}</span>
          {note && <p className="text-xs text-gray-400 mt-0.5">{note}</p>}
        </div>
      )}
    </div>
  )
}

// ─── Brand List Item ──────────────────────────────────────────────────────────

function BrandListItem({
  brand,
  selected,
  onClick,
  onToggle,
  isToggling,
}: {
  brand: Brand
  selected: boolean
  onClick: () => void
  onToggle: (e: React.MouseEvent) => void
  isToggling: boolean
}) {
  return (
    <div
      className={`px-3 py-3 cursor-pointer border-l-4 transition-all flex items-center gap-2 rounded-r ${
        selected
          ? 'border-l-blue-500 bg-blue-50'
          : 'border-l-transparent hover:bg-gray-50'
      } ${!brand.is_active ? 'opacity-55' : ''}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') onClick() }}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="font-semibold text-gray-900 text-sm leading-tight">{brand.name}</span>
          <span
            className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${TENANT_MODE_CLASSES[brand.tenant_mode]}`}
          >
            {TENANT_MODE_LABELS[brand.tenant_mode]}
          </span>
        </div>
        <code className="text-[11px] text-gray-400 font-mono block mt-0.5">{brand.slug}</code>
        <div className="flex items-center gap-2 mt-1">
          <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${brand.is_active ? 'bg-green-500' : 'bg-gray-300'}`} />
          <span className="text-[10px] text-gray-400">{brand.is_active ? 'Active' : 'Inactive'}</span>
        </div>
      </div>
      <button
        onClick={onToggle}
        disabled={isToggling}
        className="flex-shrink-0 p-0.5 rounded transition-colors hover:bg-gray-200 disabled:opacity-50"
        title={brand.is_active ? 'Deactivate' : 'Activate'}
      >
        {brand.is_active
          ? <ToggleRight className="w-6 h-6 text-green-500" />
          : <ToggleLeft className="w-6 h-6 text-gray-300" />
        }
      </button>
      <ChevronRight className={`w-4 h-4 flex-shrink-0 transition-colors ${selected ? 'text-blue-500' : 'text-gray-300'}`} />
    </div>
  )
}

// ─── Tab Bar ─────────────────────────────────────────────────────────────────

type DetailTab = 'overview' | 'config' | 'nodes'

function TabBar({ active, onChange }: { active: DetailTab; onChange: (t: DetailTab) => void }) {
  const tabs: { key: DetailTab; label: string; icon: React.ReactNode }[] = [
    { key: 'overview', label: 'Overview', icon: <Tag className="w-3.5 h-3.5" /> },
    { key: 'config', label: 'Configuration', icon: <Settings className="w-3.5 h-3.5" /> },
    { key: 'nodes', label: 'Node Assignments', icon: <Network className="w-3.5 h-3.5" /> },
  ]
  return (
    <div className="flex border-b border-gray-200">
      {tabs.map(t => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            active === t.key
              ? 'border-blue-500 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
          }`}
        >
          {t.icon}
          {t.label}
        </button>
      ))}
    </div>
  )
}

// ─── Overview Tab ─────────────────────────────────────────────────────────────

function OverviewTab({
  brand,
  onSaved,
}: {
  brand: Brand
  onSaved: () => void
}) {
  const qc = useQueryClient()

  const [name, setName] = useState(brand.name)
  const [tenantMode, setTenantMode] = useState<BrandTenantMode>(brand.tenant_mode)
  const [description, setDescription] = useState(brand.description ?? '')
  const [error, setError] = useState('')
  const [showClone, setShowClone] = useState(false)

  // Reset when brand changes
  useEffect(() => {
    setName(brand.name)
    setTenantMode(brand.tenant_mode)
    setDescription(brand.description ?? '')
    setError('')
  }, [brand.id])

  const updateMutation = useMutation({
    mutationFn: (data: BrandUpdate) => updateBrand(brand.id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['brands'] })
      onSaved()
    },
    onError: (e: unknown) => setError(getErrMsg(e)),
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteBrand(brand.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['brands'] })
      onSaved()
    },
    onError: (e: unknown) => setError(getErrMsg(e)),
  })

  const toggleMutation = useMutation({
    mutationFn: () => toggleBrand(brand.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['brands'] }),
    onError: (e: unknown) => setError(getErrMsg(e)),
  })

  const canDelete =
    brand.order_count === 0 && brand.rule_count === 0 && brand.account_count === 0

  const isPending = updateMutation.isPending || deleteMutation.isPending

  function handleSave() {
    setError('')
    if (!name.trim()) { setError('Name is required'); return }
    updateMutation.mutate({ name: name.trim(), tenant_mode: tenantMode, description: description || undefined })
  }

  function handleDelete() {
    if (!confirm(`Delete brand "${brand.name}"? This cannot be undone.`)) return
    deleteMutation.mutate()
  }

  return (
    <div className="p-6 space-y-5">
      {error && (
        <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" /> {error}
        </div>
      )}

      {/* Read-only meta */}
      <div className="grid grid-cols-2 gap-4 p-4 bg-gray-50 rounded-lg border border-gray-100">
        <div>
          <p className="text-xs text-gray-400 font-medium">Slug (immutable)</p>
          <code className="text-sm font-mono text-gray-700">{brand.slug}</code>
        </div>
        <div>
          <p className="text-xs text-gray-400 font-medium">Created</p>
          <p className="text-sm text-gray-700">{new Date(brand.created_at).toLocaleDateString()}</p>
        </div>
      </div>

      {/* Counts */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Orders', value: brand.order_count },
          { label: 'Sourcing Rules', value: brand.rule_count },
          { label: 'Accounts', value: brand.account_count },
        ].map(({ label, value }) => (
          <div key={label} className="card p-3 text-center">
            <p className="text-2xl font-bold text-gray-900">{value}</p>
            <p className="text-xs text-gray-500 mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Editable fields */}
      <div>
        <label className="label">Name *</label>
        <input
          className="input"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="e.g. RetailCo Consumer"
        />
      </div>

      <div>
        <label className="label">Tenant Mode *</label>
        <select
          className="select"
          value={tenantMode}
          onChange={e => setTenantMode(e.target.value as BrandTenantMode)}
        >
          {TENANT_MODES.map(m => (
            <option key={m} value={m}>{TENANT_MODE_LABELS[m]}</option>
          ))}
        </select>
        <p className="text-xs text-gray-400 mt-1">{TENANT_MODE_DESC[tenantMode]}</p>
      </div>

      <div>
        <label className="label">Description</label>
        <textarea
          className="input resize-none h-20"
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="Optional description"
        />
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between pt-3 border-t border-gray-100">
        <div className="flex items-center gap-2">
          <button
            className="btn-danger disabled:opacity-40 disabled:cursor-not-allowed"
            onClick={handleDelete}
            disabled={isPending || !canDelete}
            title={canDelete ? 'Delete brand' : 'Has linked orders, rules or accounts — cannot delete'}
          >
            <Trash2 className="w-4 h-4" /> Delete
          </button>
          <button
            className="btn-secondary"
            onClick={() => setShowClone(true)}
            disabled={isPending}
          >
            <Copy className="w-4 h-4" /> Clone Brand
          </button>
        </div>
        <div className="flex items-center gap-2">
          <button
            className="btn-secondary"
            onClick={() => toggleMutation.mutate()}
            disabled={toggleMutation.isPending}
          >
            {brand.is_active
              ? <><ToggleLeft className="w-4 h-4" /> Deactivate</>
              : <><ToggleRight className="w-4 h-4 text-green-600" /> Activate</>
            }
          </button>
          <button className="btn-primary" onClick={handleSave} disabled={isPending}>
            {isPending ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>

      {showClone && (
        <CloneModal brand={brand} onClose={() => setShowClone(false)} />
      )}
    </div>
  )
}

// ─── Clone Modal ──────────────────────────────────────────────────────────────

function CloneModal({ brand, onClose }: { brand: Brand; onClose: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState(`${brand.name} (Copy)`)
  const [slug, setSlug] = useState(`${brand.slug}-copy`)
  const [slugTouched, setSlugTouched] = useState(false)
  const [cloneConfig, setCloneConfig] = useState(true)
  const [cloneNodes, setCloneNodes] = useState(true)
  const [cloneRules, setCloneRules] = useState(false)
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: (data: BrandCloneRequest) => cloneBrand(brand.id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['brands'] })
      onClose()
    },
    onError: (e: unknown) => setError(getErrMsg(e)),
  })

  function handleNameChange(v: string) {
    setName(v)
    if (!slugTouched) setSlug(toSlug(v))
  }

  const slugErr = slug ? slugError(slug) : null

  function handleClone() {
    setError('')
    if (!name.trim()) { setError('Name is required'); return }
    const se = slugError(slug)
    if (se) { setError(se); return }
    mutation.mutate({
      name: name.trim(),
      slug,
      tenant_mode: brand.tenant_mode,
      clone_config: cloneConfig,
      clone_nodes: cloneNodes,
      clone_sourcing_rules: cloneRules,
    })
  }

  return (
    <Modal open title={`Clone "${brand.name}"`} onClose={onClose}>
      <div className="space-y-4 p-1">
        {error && (
          <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">{error}</div>
        )}
        <div>
          <label className="label">New Brand Name *</label>
          <input className="input" value={name} onChange={e => handleNameChange(e.target.value)} />
        </div>
        <div>
          <label className="label">New Slug *</label>
          <input
            className={`input font-mono text-sm ${slugErr ? 'border-red-400' : ''}`}
            value={slug}
            onChange={e => { setSlugTouched(true); setSlug(e.target.value) }}
          />
          {slugErr && <p className="text-xs text-red-500 mt-1">{slugErr}</p>}
        </div>
        <div className="space-y-3 pt-1">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">What to clone</p>
          {[
            { label: 'Configuration (SLA, currency, AI settings)', value: cloneConfig, onChange: setCloneConfig },
            { label: 'Node Assignments', value: cloneNodes, onChange: setCloneNodes },
            { label: 'Sourcing Rules (created as inactive copies)', value: cloneRules, onChange: setCloneRules },
          ].map(({ label, value, onChange }) => (
            <label key={label} className="flex items-center gap-2 cursor-pointer text-sm text-gray-700">
              <input
                type="checkbox"
                className="w-4 h-4 rounded text-blue-600"
                checked={value}
                onChange={e => onChange(e.target.checked)}
              />
              {label}
            </label>
          ))}
        </div>
        <div className="flex justify-end gap-2 pt-2 border-t border-gray-100">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={handleClone} disabled={mutation.isPending}>
            {mutation.isPending ? 'Cloning...' : 'Clone Brand'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ─── Configuration Tab ────────────────────────────────────────────────────────

function ConfigTab({ brand }: { brand: Brand }) {
  const qc = useQueryClient()

  const { data: config, isLoading } = useQuery({
    queryKey: ['brandConfig', brand.id],
    queryFn: () => getBrandConfig(brand.id),
  })

  const [form, setForm] = useState<Partial<BrandConfig>>({})
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  // Sync form when config loads
  useEffect(() => {
    if (config) {
      setForm({
        default_currency: config.default_currency,
        default_locale: config.default_locale,
        sla_ship_hours: config.sla_ship_hours,
        sla_deliver_days: config.sla_deliver_days,
        return_window_days: config.return_window_days,
        logo_url: config.logo_url ?? '',
        support_email: config.support_email ?? '',
        support_phone: config.support_phone ?? '',
        default_fulfillment_type: config.default_fulfillment_type ?? '',
        auto_approve_orders: config.auto_approve_orders,
        ai_sourcing_enabled: config.ai_sourcing_enabled,
      })
    }
  }, [config])

  // Reset when brand changes
  useEffect(() => {
    setError('')
    setSaved(false)
  }, [brand.id])

  const mutation = useMutation({
    mutationFn: (data: Partial<BrandConfig>) => upsertBrandConfig(brand.id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['brandConfig', brand.id] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    },
    onError: (e: unknown) => setError(getErrMsg(e)),
  })

  function setField<K extends keyof BrandConfig>(key: K, value: BrandConfig[K]) {
    setForm(prev => ({ ...prev, [key]: value }))
  }

  if (isLoading) {
    return (
      <div className="p-6 space-y-4 animate-pulse">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-10 bg-gray-100 rounded" />
        ))}
      </div>
    )
  }

  return (
    <div className="p-6 space-y-5">
      {error && (
        <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" /> {error}
        </div>
      )}

      {/* SLA */}
      <div>
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">SLA Targets</p>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Ship within (hours)</label>
            <input
              type="number"
              className="input"
              min={1}
              value={form.sla_ship_hours ?? ''}
              onChange={e => setField('sla_ship_hours', Number(e.target.value))}
            />
          </div>
          <div>
            <label className="label">Deliver within (days)</label>
            <input
              type="number"
              className="input"
              min={1}
              value={form.sla_deliver_days ?? ''}
              onChange={e => setField('sla_deliver_days', Number(e.target.value))}
            />
          </div>
        </div>
      </div>

      {/* Returns + Localization */}
      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className="label">Return window (days)</label>
          <input
            type="number"
            className="input"
            min={0}
            value={form.return_window_days ?? ''}
            onChange={e => setField('return_window_days', Number(e.target.value))}
          />
        </div>
        <div>
          <label className="label">Currency</label>
          <input
            className="input"
            maxLength={10}
            placeholder="USD"
            value={form.default_currency ?? ''}
            onChange={e => setField('default_currency', e.target.value)}
          />
        </div>
        <div>
          <label className="label">Locale</label>
          <input
            className="input"
            maxLength={20}
            placeholder="en-US"
            value={form.default_locale ?? ''}
            onChange={e => setField('default_locale', e.target.value)}
          />
        </div>
      </div>

      {/* Support */}
      <div>
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Support</p>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Support email</label>
            <input
              type="email"
              className="input"
              placeholder="support@brand.com"
              value={form.support_email ?? ''}
              onChange={e => setField('support_email', e.target.value)}
            />
          </div>
          <div>
            <label className="label">Support phone</label>
            <input
              className="input"
              placeholder="+1-800-000-0000"
              value={form.support_phone ?? ''}
              onChange={e => setField('support_phone', e.target.value)}
            />
          </div>
        </div>
        <div className="mt-3">
          <label className="label">Logo URL</label>
          <input
            className="input"
            placeholder="https://cdn.example.com/logo.png"
            value={form.logo_url ?? ''}
            onChange={e => setField('logo_url', e.target.value)}
          />
        </div>
      </div>

      {/* Fulfillment */}
      <div>
        <label className="label">Default Fulfillment Type</label>
        <select
          className="select"
          value={form.default_fulfillment_type ?? ''}
          onChange={e => setField('default_fulfillment_type', e.target.value)}
        >
          <option value="">-- None --</option>
          {FULFILLMENT_TYPES.map(ft => (
            <option key={ft} value={ft}>{ft.replace(/_/g, ' ')}</option>
          ))}
        </select>
      </div>

      {/* Toggles */}
      <div className="space-y-4 pt-2 border-t border-gray-100">
        <Toggle
          checked={!!form.ai_sourcing_enabled}
          onChange={v => setField('ai_sourcing_enabled', v)}
          label="AI Sourcing"
          note="Enables AI_ADAPTIVE and AI_HYBRID strategies for this brand. New brands start in learning mode."
        />
        <Toggle
          checked={!!form.auto_approve_orders}
          onChange={v => setField('auto_approve_orders', v)}
          label="Auto-approve B2B orders below credit threshold"
        />
      </div>

      <div className="flex items-center justify-end gap-3 pt-3 border-t border-gray-100">
        {saved && (
          <span className="text-sm text-green-600 flex items-center gap-1">
            <Check className="w-4 h-4" /> Saved
          </span>
        )}
        <button
          className="btn-primary"
          onClick={() => { setError(''); mutation.mutate(form) }}
          disabled={mutation.isPending}
        >
          {mutation.isPending ? 'Saving...' : 'Save Configuration'}
        </button>
      </div>
    </div>
  )
}

// ─── Node Assignments Tab ─────────────────────────────────────────────────────

function NodesTab({ brand }: { brand: Brand }) {
  const qc = useQueryClient()

  const { data: brandNodes = [], isLoading: nodesLoading } = useQuery({
    queryKey: ['brandNodes', brand.id],
    queryFn: () => getBrandNodes(brand.id),
  })

  const { data: allNodesData } = useQuery({
    queryKey: ['nodes'],
    queryFn: () => fetchNodes({ page: 1, page_size: 100 }),
  })

  const allNodes: FulfillmentNode[] = allNodesData?.items ?? []

  // Assign form state
  const [assignNodeId, setAssignNodeId] = useState('')
  const [assignPriority, setAssignPriority] = useState('100')
  const [assignError, setAssignError] = useState('')

  const assignedNodeIds = new Set(brandNodes.map(bn => bn.node_id))
  const availableNodes = allNodes.filter(n => !assignedNodeIds.has(n.id))

  const assignMutation = useMutation({
    mutationFn: () =>
      assignBrandNode(brand.id, {
        node_id: assignNodeId,
        priority: Number(assignPriority) || 100,
        is_active: true,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['brandNodes', brand.id] })
      setAssignNodeId('')
      setAssignPriority('100')
      setAssignError('')
    },
    onError: (e: unknown) => setAssignError(getErrMsg(e)),
  })

  const removeMutation = useMutation({
    mutationFn: (nodeId: string) => removeBrandNode(brand.id, nodeId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['brandNodes', brand.id] }),
  })

  function handleAssign() {
    setAssignError('')
    if (!assignNodeId) { setAssignError('Please select a node'); return }
    assignMutation.mutate()
  }

  if (nodesLoading) {
    return (
      <div className="p-6 space-y-3 animate-pulse">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-12 bg-gray-100 rounded" />
        ))}
      </div>
    )
  }

  return (
    <div className="p-6 space-y-5">
      {brandNodes.length === 0 ? (
        <div className="flex items-start gap-2 px-4 py-3 bg-blue-50 border border-blue-100 rounded-lg text-sm text-blue-700">
          <Info className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <p>
            No nodes assigned. This brand will use all available fulfillment nodes (AI learning mode).
          </p>
        </div>
      ) : (
        <>
          <div className="flex items-start gap-2 px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-xs text-gray-500">
            <Info className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
            <span>
              Sourcing engine will only route orders for this brand to the assigned nodes, sorted by priority.
            </span>
          </div>

          <div className="card overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  {['Node', 'Code', 'Priority', 'Active', 'Max Daily Orders', ''].map(h => (
                    <th key={h} className="table-header">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {brandNodes.map(bn => (
                  <BrandNodeRow
                    key={bn.id}
                    brandNode={bn}
                    brandId={brand.id}
                    onRemove={() => removeMutation.mutate(bn.node_id)}
                    isRemoving={removeMutation.isPending && removeMutation.variables === bn.node_id}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Assign new node */}
      <div className="pt-3 border-t border-gray-100">
        <p className="text-sm font-semibold text-gray-700 mb-3">Assign Node</p>
        {assignError && (
          <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded mb-3">{assignError}</div>
        )}
        {availableNodes.length === 0 ? (
          <p className="text-sm text-gray-400 italic">All available nodes are already assigned.</p>
        ) : (
          <div className="flex items-end gap-3 flex-wrap">
            <div className="flex-1 min-w-48">
              <label className="label">Node</label>
              <select
                className="select"
                value={assignNodeId}
                onChange={e => setAssignNodeId(e.target.value)}
              >
                <option value="">-- Select node --</option>
                {availableNodes.map(n => (
                  <option key={n.id} value={n.id}>
                    {n.name} ({n.code})
                  </option>
                ))}
              </select>
            </div>
            <div className="w-28">
              <label className="label">Priority</label>
              <input
                type="number"
                className="input"
                min={1}
                value={assignPriority}
                onChange={e => setAssignPriority(e.target.value)}
              />
            </div>
            <button
              className="btn-primary"
              onClick={handleAssign}
              disabled={assignMutation.isPending || !assignNodeId}
            >
              <Plus className="w-4 h-4" />
              {assignMutation.isPending ? 'Assigning...' : 'Assign'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function BrandNodeRow({
  brandNode,
  brandId,
  onRemove,
  isRemoving,
}: {
  brandNode: BrandNode
  brandId: string
  onRemove: () => void
  isRemoving: boolean
}) {
  const qc = useQueryClient()
  const [priority, setPriority] = useState(String(brandNode.priority))
  const [maxOrders, setMaxOrders] = useState(
    brandNode.max_daily_orders != null ? String(brandNode.max_daily_orders) : '',
  )
  const [isActive, setIsActive] = useState(brandNode.is_active)
  const [dirty, setDirty] = useState(false)

  const updateMutation = useMutation({
    mutationFn: () =>
      assignBrandNode(brandId, {
        node_id: brandNode.node_id,
        priority: Number(priority) || 100,
        is_active: isActive,
        max_daily_orders: maxOrders ? Number(maxOrders) : undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['brandNodes', brandId] })
      setDirty(false)
    },
  })

  return (
    <tr className="hover:bg-gray-50">
      <td className="table-cell font-medium text-gray-900 text-sm">
        {brandNode.node_name ?? brandNode.node_id}
      </td>
      <td className="table-cell">
        <code className="text-xs font-mono text-gray-500">{brandNode.node_code ?? '—'}</code>
      </td>
      <td className="table-cell">
        <input
          type="number"
          className="input w-20 py-1 text-sm"
          min={1}
          value={priority}
          onChange={e => { setPriority(e.target.value); setDirty(true) }}
        />
      </td>
      <td className="table-cell">
        <Toggle
          checked={isActive}
          onChange={v => { setIsActive(v); setDirty(true) }}
        />
      </td>
      <td className="table-cell">
        <input
          type="number"
          className="input w-24 py-1 text-sm"
          min={1}
          placeholder="unlimited"
          value={maxOrders}
          onChange={e => { setMaxOrders(e.target.value); setDirty(true) }}
        />
      </td>
      <td className="table-cell">
        <div className="flex items-center gap-1">
          {dirty && (
            <button
              className="btn-primary py-1 px-2 text-xs"
              onClick={() => updateMutation.mutate()}
              disabled={updateMutation.isPending}
            >
              {updateMutation.isPending ? '...' : 'Save'}
            </button>
          )}
          <button
            className="btn-danger py-1 px-2 text-xs"
            onClick={onRemove}
            disabled={isRemoving}
            title="Remove node assignment"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </td>
    </tr>
  )
}

// ─── Brand Detail Panel ───────────────────────────────────────────────────────

function BrandDetail({ brand, onClosed }: { brand: Brand; onClosed: () => void }) {
  const [tab, setTab] = useState<DetailTab>('overview')

  // Reset tab when brand changes
  useEffect(() => {
    setTab('overview')
  }, [brand.id])

  return (
    <div className="card overflow-hidden flex flex-col h-full">
      {/* Header */}
      <div className="px-6 pt-5 pb-0 border-b border-gray-200">
        <div className="flex items-start justify-between mb-3">
          <div>
            <h2 className="text-base font-semibold text-gray-900">{brand.name}</h2>
            <div className="flex items-center gap-2 mt-1">
              <code className="text-xs font-mono text-gray-400">{brand.slug}</code>
              <span
                className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${TENANT_MODE_CLASSES[brand.tenant_mode]}`}
              >
                {TENANT_MODE_LABELS[brand.tenant_mode]}
              </span>
              <span
                className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${brand.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}
              >
                {brand.is_active ? 'Active' : 'Inactive'}
              </span>
            </div>
          </div>
        </div>
        <TabBar active={tab} onChange={setTab} />
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        {tab === 'overview' && <OverviewTab brand={brand} onSaved={onClosed} />}
        {tab === 'config' && <ConfigTab brand={brand} />}
        {tab === 'nodes' && <NodesTab brand={brand} />}
      </div>
    </div>
  )
}

// ─── Onboarding Wizard ────────────────────────────────────────────────────────

type InventoryMode = 'SHARED' | 'ISOLATED'

interface WizardState {
  // Step 1
  name: string
  slug: string
  slugTouched: boolean
  tenantMode: BrandTenantMode
  inventoryMode: InventoryMode
  // Step 2
  slaShipHours: number
  slaDeliverDays: number
  returnWindowDays: number
  currency: string
  locale: string
  supportEmail: string
  aiSourcingEnabled: boolean
  autoApproveOrders: boolean
  // Step 3
  selectedNodes: Record<string, number> // node_id → priority
  // Step 4
  cloneFromBrandId: string
  cloneConfig: boolean
  cloneNodes: boolean
  cloneRules: boolean
  skipClone: boolean
}

const WIZARD_DEFAULTS: WizardState = {
  name: '',
  slug: '',
  slugTouched: false,
  tenantMode: 'B2C_ONLY',
  inventoryMode: 'SHARED',
  slaShipHours: 24,
  slaDeliverDays: 5,
  returnWindowDays: 30,
  currency: 'USD',
  locale: 'en-US',
  supportEmail: '',
  aiSourcingEnabled: true,
  autoApproveOrders: false,
  selectedNodes: {},
  cloneFromBrandId: '',
  cloneConfig: true,
  cloneNodes: true,
  cloneRules: false,
  skipClone: true,
}

const WIZARD_STEPS = [
  'Entity Details',
  'Configuration',
  'Node Assignment',
  'Clone (Optional)',
  'Review & Create',
]

function WizardStepBar({ current }: { current: number }) {
  return (
    <div className="flex items-center gap-0 mb-6">
      {WIZARD_STEPS.map((label, i) => {
        const done = i < current
        const active = i === current
        return (
          <div key={label} className="flex items-center flex-1 min-w-0">
            <div className="flex flex-col items-center flex-shrink-0">
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-colors ${
                  done
                    ? 'bg-blue-600 border-blue-600 text-white'
                    : active
                    ? 'bg-white border-blue-500 text-blue-600'
                    : 'bg-white border-gray-200 text-gray-400'
                }`}
              >
                {done ? <Check className="w-3.5 h-3.5" /> : i + 1}
              </div>
              <span
                className={`text-[10px] mt-1 font-medium text-center leading-tight max-w-16 ${
                  active ? 'text-blue-600' : done ? 'text-blue-400' : 'text-gray-400'
                }`}
              >
                {label}
              </span>
            </div>
            {i < WIZARD_STEPS.length - 1 && (
              <div className={`flex-1 h-0.5 mx-1 mb-4 ${done ? 'bg-blue-400' : 'bg-gray-200'}`} />
            )}
          </div>
        )
      })}
    </div>
  )
}

function WizardStep1({
  state,
  setState,
}: {
  state: WizardState
  setState: React.Dispatch<React.SetStateAction<WizardState>>
}) {
  function handleName(v: string) {
    setState(prev => ({
      ...prev,
      name: v,
      slug: prev.slugTouched ? prev.slug : toSlug(v),
    }))
  }

  const slugErr = state.slug ? slugError(state.slug) : null

  const modeCards: { value: BrandTenantMode; label: string; desc: string }[] = [
    { value: 'B2C_ONLY', label: 'B2C Only', desc: 'Retail / consumer orders only' },
    { value: 'B2B_ONLY', label: 'B2B Only', desc: 'Business / wholesale orders only' },
    { value: 'HYBRID', label: 'Hybrid', desc: 'Both B2C retail and B2B wholesale' },
  ]

  const invCards: { value: InventoryMode; label: string; desc: string }[] = [
    { value: 'SHARED', label: 'Shared', desc: 'Draw from global node stock' },
    { value: 'ISOLATED', label: 'Isolated', desc: 'Brand owns its own inventory' },
  ]

  return (
    <div className="space-y-5">
      <div>
        <label className="label">Brand Name *</label>
        <input className="input" value={state.name} onChange={e => handleName(e.target.value)} placeholder="e.g. RetailCo Consumer" />
      </div>
      <div>
        <label className="label">Slug *</label>
        <input
          className={`input font-mono text-sm ${slugErr ? 'border-red-400' : ''}`}
          value={state.slug}
          onChange={e => setState(prev => ({ ...prev, slug: e.target.value, slugTouched: true }))}
          placeholder="e.g. retailco-consumer"
        />
        {slugErr
          ? <p className="text-xs text-red-500 mt-1">{slugErr}</p>
          : <p className="text-xs text-gray-400 mt-1">Lowercase letters, numbers and hyphens. Cannot be changed after creation.</p>
        }
      </div>

      <div>
        <label className="label">Tenant Mode *</label>
        <div className="grid grid-cols-3 gap-3 mt-1">
          {modeCards.map(({ value, label, desc }) => (
            <button
              key={value}
              type="button"
              onClick={() => setState(prev => ({ ...prev, tenantMode: value }))}
              className={`p-3 rounded-lg border-2 text-left transition-colors ${
                state.tenantMode === value
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-200 hover:border-gray-300 bg-white'
              }`}
            >
              <p className={`text-sm font-semibold ${state.tenantMode === value ? 'text-blue-700' : 'text-gray-700'}`}>
                {label}
              </p>
              <p className="text-xs text-gray-500 mt-0.5">{desc}</p>
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="label">Inventory Mode</label>
        <div className="grid grid-cols-2 gap-3 mt-1">
          {invCards.map(({ value, label, desc }) => (
            <button
              key={value}
              type="button"
              onClick={() => setState(prev => ({ ...prev, inventoryMode: value }))}
              className={`p-3 rounded-lg border-2 text-left transition-colors ${
                state.inventoryMode === value
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-200 hover:border-gray-300 bg-white'
              }`}
            >
              <p className={`text-sm font-semibold ${state.inventoryMode === value ? 'text-blue-700' : 'text-gray-700'}`}>
                {label}
              </p>
              <p className="text-xs text-gray-500 mt-0.5">{desc}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function WizardStep2({
  state,
  setState,
}: {
  state: WizardState
  setState: React.Dispatch<React.SetStateAction<WizardState>>
}) {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="label">Ship within (hours)</label>
          <input
            type="number" min={1} className="input"
            value={state.slaShipHours}
            onChange={e => setState(prev => ({ ...prev, slaShipHours: Number(e.target.value) }))}
          />
        </div>
        <div>
          <label className="label">Deliver within (days)</label>
          <input
            type="number" min={1} className="input"
            value={state.slaDeliverDays}
            onChange={e => setState(prev => ({ ...prev, slaDeliverDays: Number(e.target.value) }))}
          />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className="label">Return window (days)</label>
          <input
            type="number" min={0} className="input"
            value={state.returnWindowDays}
            onChange={e => setState(prev => ({ ...prev, returnWindowDays: Number(e.target.value) }))}
          />
        </div>
        <div>
          <label className="label">Currency</label>
          <input
            className="input" maxLength={10} placeholder="USD"
            value={state.currency}
            onChange={e => setState(prev => ({ ...prev, currency: e.target.value }))}
          />
        </div>
        <div>
          <label className="label">Locale</label>
          <input
            className="input" maxLength={20} placeholder="en-US"
            value={state.locale}
            onChange={e => setState(prev => ({ ...prev, locale: e.target.value }))}
          />
        </div>
      </div>

      <div>
        <label className="label">Support email</label>
        <input
          type="email" className="input" placeholder="support@brand.com"
          value={state.supportEmail}
          onChange={e => setState(prev => ({ ...prev, supportEmail: e.target.value }))}
        />
      </div>

      <div className="space-y-4 pt-2 border-t border-gray-100">
        <Toggle
          checked={state.aiSourcingEnabled}
          onChange={v => setState(prev => ({ ...prev, aiSourcingEnabled: v }))}
          label="AI Sourcing"
          note="Enables AI_ADAPTIVE and AI_HYBRID strategies. New brands start in learning mode."
        />
        <Toggle
          checked={state.autoApproveOrders}
          onChange={v => setState(prev => ({ ...prev, autoApproveOrders: v }))}
          label="Auto-approve B2B orders below credit threshold"
        />
      </div>
    </div>
  )
}

function WizardStep3({
  state,
  setState,
}: {
  state: WizardState
  setState: React.Dispatch<React.SetStateAction<WizardState>>
}) {
  const { data } = useQuery({
    queryKey: ['nodes'],
    queryFn: () => fetchNodes({ page: 1, page_size: 100 }),
  })
  const allNodes = data?.items ?? []

  function toggleNode(nodeId: string) {
    setState(prev => {
      const next = { ...prev.selectedNodes }
      if (next[nodeId] != null) {
        delete next[nodeId]
      } else {
        next[nodeId] = 100
      }
      return { ...prev, selectedNodes: next }
    })
  }

  function setPriority(nodeId: string, val: number) {
    setState(prev => ({ ...prev, selectedNodes: { ...prev.selectedNodes, [nodeId]: val } }))
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2 px-3 py-2.5 bg-blue-50 border border-blue-100 rounded-lg text-xs text-blue-700">
        <Info className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
        <span>Leave all unchecked to use all nodes. AI will learn optimal routing automatically.</span>
      </div>
      {allNodes.length === 0 ? (
        <p className="text-sm text-gray-400 italic">No fulfillment nodes available.</p>
      ) : (
        <div className="space-y-2">
          {allNodes.map(n => {
            const checked = state.selectedNodes[n.id] != null
            return (
              <div
                key={n.id}
                className={`flex items-center gap-3 p-3 rounded-lg border transition-colors ${checked ? 'border-blue-200 bg-blue-50' : 'border-gray-200 bg-white'}`}
              >
                <input
                  type="checkbox"
                  className="w-4 h-4 rounded text-blue-600 flex-shrink-0"
                  checked={checked}
                  onChange={() => toggleNode(n.id)}
                />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800">{n.name}</p>
                  <p className="text-xs text-gray-400">{n.code} · {n.city}</p>
                </div>
                {checked && (
                  <div className="flex items-center gap-1.5">
                    <label className="text-xs text-gray-500">Priority</label>
                    <input
                      type="number"
                      min={1}
                      className="input w-20 py-1 text-sm"
                      value={state.selectedNodes[n.id]}
                      onChange={e => setPriority(n.id, Number(e.target.value))}
                    />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function WizardStep4({
  state,
  setState,
  brands,
}: {
  state: WizardState
  setState: React.Dispatch<React.SetStateAction<WizardState>>
  brands: Brand[]
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => setState(prev => ({ ...prev, skipClone: true, cloneFromBrandId: '' }))}
          className={`px-4 py-2 rounded-lg border-2 text-sm font-medium transition-colors ${
            state.skipClone ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600 hover:border-gray-300'
          }`}
        >
          Skip this step
        </button>
        <button
          type="button"
          onClick={() => setState(prev => ({ ...prev, skipClone: false }))}
          className={`px-4 py-2 rounded-lg border-2 text-sm font-medium transition-colors ${
            !state.skipClone ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600 hover:border-gray-300'
          }`}
        >
          Clone from existing brand
        </button>
      </div>

      {!state.skipClone && (
        <div className="space-y-4 p-4 bg-gray-50 rounded-lg border border-gray-200">
          <div>
            <label className="label">Source Brand</label>
            <select
              className="select"
              value={state.cloneFromBrandId}
              onChange={e => setState(prev => ({ ...prev, cloneFromBrandId: e.target.value }))}
            >
              <option value="">-- Select brand --</option>
              {brands.map(b => (
                <option key={b.id} value={b.id}>{b.name} ({b.slug})</option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">What to clone</p>
            {[
              { label: 'Clone configuration (SLA, currency, AI settings)', key: 'cloneConfig' as const },
              { label: 'Clone node assignments', key: 'cloneNodes' as const },
              { label: 'Clone sourcing rules (created as inactive copies)', key: 'cloneRules' as const },
            ].map(({ label, key }) => (
              <label key={key} className="flex items-center gap-2 cursor-pointer text-sm text-gray-700">
                <input
                  type="checkbox"
                  className="w-4 h-4 rounded text-blue-600"
                  checked={state[key]}
                  onChange={e => setState(prev => ({ ...prev, [key]: e.target.checked }))}
                />
                {label}
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function WizardStep5({
  state,
  brands,
}: {
  state: WizardState
  brands: Brand[]
}) {
  const sourceBrand = brands.find(b => b.id === state.cloneFromBrandId)
  const nodeCount = Object.keys(state.selectedNodes).length

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">Review your selections before creating the brand.</p>

      <div className="space-y-3">
        {[
          { label: 'Name', value: state.name },
          { label: 'Slug', value: state.slug, mono: true },
          { label: 'Tenant Mode', value: TENANT_MODE_LABELS[state.tenantMode] },
          { label: 'Inventory Mode', value: state.inventoryMode },
          { label: 'Ship SLA', value: `${state.slaShipHours}h` },
          { label: 'Delivery SLA', value: `${state.slaDeliverDays} days` },
          { label: 'Return window', value: `${state.returnWindowDays} days` },
          { label: 'Currency / Locale', value: `${state.currency} / ${state.locale}` },
          { label: 'AI Sourcing', value: state.aiSourcingEnabled ? 'Enabled' : 'Disabled' },
          { label: 'Auto-approve', value: state.autoApproveOrders ? 'Yes' : 'No' },
          { label: 'Node assignments', value: nodeCount > 0 ? `${nodeCount} node(s)` : 'All nodes (AI routing)' },
          {
            label: 'Clone from',
            value: state.skipClone ? 'None' : (sourceBrand ? `${sourceBrand.name} (${sourceBrand.slug})` : 'Not selected'),
          },
        ].map(({ label, value, mono }) => (
          <div key={label} className="flex items-start gap-3 py-2 border-b border-gray-100">
            <span className="text-xs font-medium text-gray-500 w-36 flex-shrink-0 pt-0.5">{label}</span>
            <span className={`text-sm text-gray-900 ${mono ? 'font-mono' : ''}`}>{value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function OnboardingWizard({
  brands,
  onClose,
  onCreated,
}: {
  brands: Brand[]
  onClose: () => void
  onCreated: (brand: Brand) => void
}) {
  const qc = useQueryClient()
  const [step, setStep] = useState(0)
  const [state, setState] = useState<WizardState>(WIZARD_DEFAULTS)
  const [error, setError] = useState('')
  const [isCreating, setIsCreating] = useState(false)

  function validateStep(): string | null {
    if (step === 0) {
      if (!state.name.trim()) return 'Name is required'
      const se = slugError(state.slug)
      if (se) return se
    }
    if (step === 3 && !state.skipClone && !state.cloneFromBrandId) {
      return 'Please select a source brand or skip this step'
    }
    return null
  }

  function handleNext() {
    const err = validateStep()
    if (err) { setError(err); return }
    setError('')
    setStep(s => s + 1)
  }

  function handleBack() {
    setError('')
    setStep(s => s - 1)
  }

  async function handleCreate() {
    const err = validateStep()
    if (err) { setError(err); return }
    setError('')
    setIsCreating(true)

    try {
      let newBrand: Brand

      if (!state.skipClone && state.cloneFromBrandId) {
        // Use clone endpoint
        newBrand = await cloneBrand(state.cloneFromBrandId, {
          name: state.name.trim(),
          slug: state.slug,
          tenant_mode: state.tenantMode,
          clone_config: state.cloneConfig,
          clone_nodes: state.cloneNodes,
          clone_sourcing_rules: state.cloneRules,
        })
      } else {
        // Create brand
        newBrand = await createBrand({
          slug: state.slug,
          name: state.name.trim(),
          tenant_mode: state.tenantMode,
        })

        // Upsert config
        await upsertBrandConfig(newBrand.id, {
          default_currency: state.currency,
          default_locale: state.locale,
          sla_ship_hours: state.slaShipHours,
          sla_deliver_days: state.slaDeliverDays,
          return_window_days: state.returnWindowDays,
          support_email: state.supportEmail || undefined,
          ai_sourcing_enabled: state.aiSourcingEnabled,
          auto_approve_orders: state.autoApproveOrders,
        })

        // Assign nodes
        const nodeEntries = Object.entries(state.selectedNodes)
        for (const [nodeId, priority] of nodeEntries) {
          await assignBrandNode(newBrand.id, { node_id: nodeId, priority, is_active: true })
        }
      }

      qc.invalidateQueries({ queryKey: ['brands'] })
      onCreated(newBrand)
    } catch (e: unknown) {
      setError(getErrMsg(e))
    } finally {
      setIsCreating(false)
    }
  }

  return (
    <Modal open title="New Brand" onClose={onClose} size="lg">
      <div className="w-full max-w-2xl mx-auto px-1">
        <WizardStepBar current={step} />

        {error && (
          <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded mb-4 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" /> {error}
          </div>
        )}

        <div className="min-h-64">
          {step === 0 && <WizardStep1 state={state} setState={setState} />}
          {step === 1 && <WizardStep2 state={state} setState={setState} />}
          {step === 2 && <WizardStep3 state={state} setState={setState} />}
          {step === 3 && <WizardStep4 state={state} setState={setState} brands={brands} />}
          {step === 4 && <WizardStep5 state={state} brands={brands} />}
        </div>

        <div className="flex items-center justify-between pt-5 mt-5 border-t border-gray-100">
          <button className="btn-secondary" onClick={step === 0 ? onClose : handleBack} disabled={isCreating}>
            {step === 0 ? 'Cancel' : 'Back'}
          </button>
          {step < WIZARD_STEPS.length - 1 ? (
            <button className="btn-primary" onClick={handleNext}>
              Next <ChevronRight className="w-4 h-4" />
            </button>
          ) : (
            <button className="btn-primary" onClick={handleCreate} disabled={isCreating}>
              {isCreating ? 'Creating...' : 'Create Brand'}
            </button>
          )}
        </div>
      </div>
    </Modal>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function Brands() {
  const qc = useQueryClient()
  const [selectedBrand, setSelectedBrand] = useState<Brand | null>(null)
  const [showWizard, setShowWizard] = useState(false)

  const { data: brands = [], isLoading, refetch } = useQuery({
    queryKey: ['brands'],
    queryFn: () => getBrands(),
  })

  const toggleMutation = useMutation({
    mutationFn: (id: string) => toggleBrand(id),
    onSuccess: (_updated, id) => {
      qc.invalidateQueries({ queryKey: ['brands'] })
      // Keep selected brand in sync
      if (selectedBrand?.id === id) {
        setSelectedBrand(prev => prev ? { ...prev, is_active: !prev.is_active } : null)
      }
    },
  })

  function handleSelectBrand(brand: Brand) {
    setSelectedBrand(brand)
  }

  function handleDeselect() {
    setSelectedBrand(null)
  }

  function handleWizardCreated(brand: Brand) {
    setShowWizard(false)
    // Refresh brands then select new one
    refetch().then(() => setSelectedBrand(brand))
  }

  // Keep selected brand data fresh from the list
  const freshSelected = selectedBrand
    ? (brands.find(b => b.id === selectedBrand.id) ?? selectedBrand)
    : null

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Tag className="w-6 h-6 text-blue-600" />
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Brands</h1>
            <p className="text-sm text-gray-500">Manage brand entities, configuration and node assignments</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => refetch()} className="btn-secondary">
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
          <button onClick={() => setShowWizard(true)} className="btn-primary">
            <Plus className="w-4 h-4" /> New Brand
          </button>
        </div>
      </div>

      {/* Two-column layout */}
      <div className="flex gap-5 min-h-[70vh]">
        {/* Left — brand list (~320px) */}
        <div className="w-80 flex-shrink-0 space-y-1">
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="h-20 bg-gray-100 rounded-lg animate-pulse" />
              ))}
            </div>
          ) : brands.length === 0 ? (
            <div className="card p-8 text-center text-gray-400 text-sm">
              <Tag className="w-8 h-8 mx-auto mb-2 opacity-30" />
              No brands yet. Create your first brand.
            </div>
          ) : (
            <div className="card overflow-hidden divide-y divide-gray-100">
              {brands.map(brand => (
                <BrandListItem
                  key={brand.id}
                  brand={brand}
                  selected={freshSelected?.id === brand.id}
                  onClick={() => handleSelectBrand(brand)}
                  onToggle={e => { e.stopPropagation(); toggleMutation.mutate(brand.id) }}
                  isToggling={toggleMutation.isPending && toggleMutation.variables === brand.id}
                />
              ))}
            </div>
          )}
        </div>

        {/* Right — detail panel */}
        <div className="flex-1 min-w-0">
          {freshSelected ? (
            <BrandDetail
              brand={freshSelected}
              onClosed={handleDeselect}
            />
          ) : (
            <div className="card h-full flex flex-col items-center justify-center text-center text-gray-400 text-sm gap-2 p-10">
              <Tag className="w-10 h-10 opacity-20" />
              <p>Select a brand from the list to view details and configuration.</p>
              <button
                onClick={() => setShowWizard(true)}
                className="btn-primary mt-2"
              >
                <Plus className="w-4 h-4" /> New Brand
              </button>
            </div>
          )}
        </div>
      </div>

      {showWizard && (
        <OnboardingWizard
          brands={brands}
          onClose={() => setShowWizard(false)}
          onCreated={handleWizardCreated}
        />
      )}
    </div>
  )
}
