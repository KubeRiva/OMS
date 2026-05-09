import { useState } from 'react'
import type { ElementType } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { MapPin, RefreshCw, Warehouse, Store, Moon, Tag, Plus, Pencil, Trash2, X, Check } from 'lucide-react'
import {
  fetchNodes, createNode, updateNode, deactivateNode,
  getBrands, getBrandNodes,
  type FulfillmentNode, type Brand, type NodeCreatePayload, type NodeUpdatePayload,
} from '../api/client'
import { StatusBadge } from '../components/Badge'
import Modal from '../components/Modal'

const NODE_TYPE_ICONS: Record<string, ElementType> = {
  DISTRIBUTION_CENTER: Warehouse,
  STORE: Store,
  DARK_STORE: Moon,
}

const NODE_TYPE_COLORS: Record<string, string> = {
  DISTRIBUTION_CENTER: 'border-blue-200 bg-blue-50',
  STORE: 'border-green-200 bg-green-50',
  DARK_STORE: 'border-purple-200 bg-purple-50',
}

const NODE_ICON_COLORS: Record<string, string> = {
  DISTRIBUTION_CENTER: 'text-blue-600 bg-blue-100',
  STORE: 'text-green-600 bg-green-100',
  DARK_STORE: 'text-purple-600 bg-purple-100',
}

const TENANT_MODE_CLASSES: Record<string, string> = {
  B2C_ONLY: 'bg-blue-100 text-blue-700',
  B2B_ONLY: 'bg-amber-100 text-amber-700',
  HYBRID: 'bg-purple-100 text-purple-700',
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function CapacityBar({ used, total }: { used: number; total: number }) {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0
  const color =
    pct >= 90 ? 'bg-red-500' :
    pct >= 70 ? 'bg-amber-500' :
    'bg-green-500'
  return (
    <div>
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span>{used.toLocaleString()} used</span>
        <span>{pct.toFixed(0)}%</span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs text-gray-400 mt-0.5">{total.toLocaleString()} capacity</p>
    </div>
  )
}

function NodeCard({ node, onEdit, onDelete }: { node: FulfillmentNode; onEdit: () => void; onDelete: () => void }) {
  const Icon = NODE_TYPE_ICONS[node.node_type] ?? MapPin
  const borderColor = NODE_TYPE_COLORS[node.node_type] ?? 'border-gray-200 bg-gray-50'
  const iconStyle = NODE_ICON_COLORS[node.node_type] ?? 'text-gray-600 bg-gray-100'

  return (
    <div className={`card p-5 border-2 ${borderColor} flex flex-col gap-4`}>
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${iconStyle}`}>
            <Icon className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900 text-sm leading-tight">{node.name}</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              {node.city}{node.state ? `, ${node.state}` : ''} · {node.country}
            </p>
            <code className="text-[10px] text-gray-400 font-mono">{node.code}</code>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <StatusBadge value={node.node_type} />
          {node.status === 'ACTIVE' ? (
            <span className="flex items-center gap-1 text-xs text-green-600">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
              Active
            </span>
          ) : (
            <span className="text-xs text-gray-400">{node.status}</span>
          )}
        </div>
      </div>

      {/* Location */}
      {(node.latitude && node.longitude) ? (
        <div className="flex items-center gap-1.5 text-xs text-gray-400">
          <MapPin className="w-3 h-3" />
          <span>{Number(node.latitude).toFixed(4)}°, {Number(node.longitude).toFixed(4)}°</span>
        </div>
      ) : null}

      {/* Capacity */}
      <CapacityBar used={node.current_daily_orders} total={node.daily_order_capacity} />

      {/* Metrics */}
      <div className="grid grid-cols-3 gap-2 text-center">
        {[
          { label: 'Can Ship', value: node.can_ship ? 'Yes' : 'No' },
          { label: 'Processing', value: `${node.avg_processing_hours}h` },
          { label: 'Can Pickup', value: node.can_pickup ? 'Yes' : 'No' },
        ].map(({ label, value }) => (
          <div key={label} className="bg-white/60 rounded-lg p-2">
            <p className="text-xs text-gray-500">{label}</p>
            <p className="text-sm font-bold text-gray-800 mt-0.5">{value}</p>
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className="flex gap-2 pt-1 border-t border-gray-100/80">
        <button onClick={onEdit} className="flex-1 btn-secondary text-xs py-1.5"><Pencil className="w-3.5 h-3.5" /> Edit</button>
        <button onClick={onDelete} className="btn-danger text-xs py-1.5 px-3"><Trash2 className="w-3.5 h-3.5" /></button>
      </div>
    </div>
  )
}

// ─── Node Form ────────────────────────────────────────────────────────────────

const NODE_TYPES = ['DISTRIBUTION_CENTER', 'RETAIL_STORE', 'DARK_STORE', 'WAREHOUSE', 'PICKUP_POINT']
const NODE_STATUSES = ['ACTIVE', 'INACTIVE', 'MAINTENANCE', 'CLOSED']

function NodeForm({
  value,
  onChange,
  isEdit,
}: {
  value: NodeCreatePayload
  onChange: (v: NodeCreatePayload) => void
  isEdit: boolean
}) {
  const set = <K extends keyof NodeCreatePayload>(k: K, v: NodeCreatePayload[K]) =>
    onChange({ ...value, [k]: v })

  return (
    <div className="space-y-4 text-sm">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Code * <span className="text-gray-400 text-xs">(unique identifier)</span></label>
          <input className="input font-mono" value={value.code} onChange={e => set('code', e.target.value.toUpperCase())} placeholder="e.g. DC-LA-01" disabled={isEdit} />
        </div>
        <div>
          <label className="label">Name *</label>
          <input className="input" value={value.name} onChange={e => set('name', e.target.value)} placeholder="e.g. Los Angeles DC" />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Node Type *</label>
          <select className="select" value={value.node_type} onChange={e => set('node_type', e.target.value)}>
            {NODE_TYPES.map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Status</label>
          <select className="select" value={value.status ?? 'ACTIVE'} onChange={e => set('status', e.target.value)}>
            {NODE_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="label">City</label>
          <input className="input" value={value.city ?? ''} onChange={e => set('city', e.target.value)} placeholder="Los Angeles" />
        </div>
        <div>
          <label className="label">State</label>
          <input className="input" value={value.state ?? ''} onChange={e => set('state', e.target.value)} placeholder="CA" />
        </div>
        <div>
          <label className="label">Country</label>
          <input className="input" value={value.country ?? 'US'} onChange={e => set('country', e.target.value)} placeholder="US" />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Latitude *</label>
          <input className="input" type="number" step="0.0001" value={value.latitude} onChange={e => set('latitude', Number(e.target.value))} placeholder="34.0522" />
        </div>
        <div>
          <label className="label">Longitude *</label>
          <input className="input" type="number" step="0.0001" value={value.longitude} onChange={e => set('longitude', Number(e.target.value))} placeholder="-118.2437" />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="label">Daily Capacity</label>
          <input className="input" type="number" min={1} value={value.daily_order_capacity ?? 500} onChange={e => set('daily_order_capacity', Number(e.target.value))} />
        </div>
        <div>
          <label className="label">Avg Processing (hrs)</label>
          <input className="input" type="number" min={0} step={0.5} value={value.avg_processing_hours ?? 24} onChange={e => set('avg_processing_hours', Number(e.target.value))} />
        </div>
        <div>
          <label className="label">Cost Multiplier</label>
          <input className="input" type="number" min={0} step={0.1} value={value.shipping_cost_multiplier ?? 1.0} onChange={e => set('shipping_cost_multiplier', Number(e.target.value))} />
        </div>
      </div>

      <div>
        <label className="label">Capabilities</label>
        <div className="flex flex-wrap gap-3">
          {([
            { key: 'can_ship', label: 'Ship to Home' },
            { key: 'can_pickup', label: 'Store Pickup' },
            { key: 'can_curbside', label: 'Curbside' },
            { key: 'can_same_day', label: 'Same Day' },
          ] as const).map(({ key, label }) => (
            <label key={key} className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input type="checkbox" checked={!!(value as unknown as Record<string, unknown>)[key]} onChange={e => set(key, e.target.checked)} className="rounded border-gray-300" />
              {label}
            </label>
          ))}
        </div>
      </div>
    </div>
  )
}

// ─── Brand Assignments Tab ────────────────────────────────────────────────────

function BrandAssignmentsTab({ nodes }: { nodes: FulfillmentNode[] }) {
  const { data: brands = [], isLoading: brandsLoading } = useQuery({
    queryKey: ['brands'],
    queryFn: () => getBrands(),
  })

  // Fetch all brand node assignments in parallel — one query per brand
  // We collect them into a map: node_id → Brand[]
  const brandNodeQueries = useQuery({
    queryKey: ['allBrandNodes', brands.map(b => b.id).join(',')],
    queryFn: async () => {
      if (brands.length === 0) return {} as Record<string, Brand[]>
      const results = await Promise.all(
        brands.map(async (brand: Brand) => {
          try {
            const bnodes = await getBrandNodes(brand.id)
            return { brand, bnodes }
          } catch {
            return { brand, bnodes: [] }
          }
        }),
      )
      // Build node_id → Brand[]
      const map: Record<string, Brand[]> = {}
      for (const { brand, bnodes } of results) {
        for (const bn of bnodes) {
          if (!map[bn.node_id]) map[bn.node_id] = []
          map[bn.node_id].push(brand)
        }
      }
      return map
    },
    enabled: brands.length > 0,
  })

  const nodeTobrands = brandNodeQueries.data ?? {}
  const isLoading = brandsLoading || brandNodeQueries.isLoading

  if (isLoading) {
    return (
      <div className="space-y-3 animate-pulse">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-14 bg-gray-100 rounded-lg" />
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2 px-3 py-2.5 bg-blue-50 border border-blue-100 rounded-lg text-xs text-blue-700">
        <Tag className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
        <span>
          Shows which brands have explicitly assigned each node. Nodes with no brand assignments are
          available to all brands. To configure assignments, go to <strong>Brands</strong> and open
          the Node Assignments tab for a brand.
        </span>
      </div>

      <div className="card overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              {['Node', 'Type', 'Status', 'Assigned Brands'].map(h => (
                <th key={h} className="table-header">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {nodes.map(node => {
              const assignedBrands = nodeTobrands[node.id] ?? []
              return (
                <tr key={node.id} className="hover:bg-gray-50">
                  <td className="table-cell">
                    <p className="font-medium text-gray-900 text-sm">{node.name}</p>
                    <code className="text-[11px] text-gray-400 font-mono">{node.code}</code>
                  </td>
                  <td className="table-cell">
                    <span className="text-xs text-gray-600">{node.node_type.replace(/_/g, ' ')}</span>
                  </td>
                  <td className="table-cell">
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                        node.status === 'ACTIVE'
                          ? 'bg-green-100 text-green-700'
                          : 'bg-gray-100 text-gray-500'
                      }`}
                    >
                      {node.status}
                    </span>
                  </td>
                  <td className="table-cell">
                    {assignedBrands.length === 0 ? (
                      <span className="text-xs text-gray-400 italic">All brands (unassigned)</span>
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        {assignedBrands.map(b => (
                          <span
                            key={b.id}
                            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium ${TENANT_MODE_CLASSES[b.tenant_mode] ?? 'bg-gray-100 text-gray-600'}`}
                          >
                            {b.name}
                            <code className="opacity-60 font-mono">{b.slug}</code>
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

const emptyNodeForm = (): NodeCreatePayload => ({
  code: '', name: '', node_type: 'DISTRIBUTION_CENTER', status: 'ACTIVE',
  latitude: 0, longitude: 0, country: 'US',
  can_ship: true, can_pickup: false, can_curbside: false, can_same_day: false,
  daily_order_capacity: 500, avg_processing_hours: 24, shipping_cost_multiplier: 1.0,
})

type PageTab = 'nodes' | 'brands'

export default function Nodes() {
  const qc = useQueryClient()
  const [typeFilter, setTypeFilter] = useState('')
  const [pageTab, setPageTab] = useState<PageTab>('nodes')
  const [showCreate, setShowCreate] = useState(false)
  const [editingNode, setEditingNode] = useState<FulfillmentNode | null>(null)
  const [deletingNode, setDeletingNode] = useState<FulfillmentNode | null>(null)
  const [form, setForm] = useState<NodeCreatePayload>(emptyNodeForm())

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['nodes'],
    queryFn: () => fetchNodes({ page: 1, page_size: 100 }),
  })

  const nodes = data?.items ?? []
  const filtered = typeFilter ? nodes.filter(n => n.node_type === typeFilter) : nodes
  const types = [...new Set(nodes.map(n => n.node_type))]
  const active = nodes.filter(n => n.status === 'ACTIVE').length
  const avgLoad = nodes.length > 0
    ? nodes.reduce((s, n) => s + (n.daily_order_capacity > 0 ? n.current_daily_orders / n.daily_order_capacity : 0), 0) / nodes.length * 100
    : 0

  const invalidate = () => qc.invalidateQueries({ queryKey: ['nodes'] })

  const createMutation = useMutation({
    mutationFn: createNode,
    onSuccess: () => { invalidate(); setShowCreate(false) },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: NodeUpdatePayload }) => updateNode(id, data),
    onSuccess: () => { invalidate(); setEditingNode(null) },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deactivateNode(id),
    onSuccess: () => { invalidate(); setDeletingNode(null) },
  })

  const openEdit = (node: FulfillmentNode) => {
    setForm({
      code: node.code,
      name: node.name,
      node_type: node.node_type,
      status: node.status,
      city: node.city,
      state: node.state,
      country: node.country,
      latitude: node.latitude,
      longitude: node.longitude,
      can_ship: node.can_ship,
      can_pickup: node.can_pickup,
      can_curbside: node.can_curbside,
      can_same_day: node.can_same_day,
      daily_order_capacity: node.daily_order_capacity,
      avg_processing_hours: node.avg_processing_hours,
      shipping_cost_multiplier: node.shipping_cost_multiplier,
    })
    setEditingNode(node)
  }

  return (
    <div className="p-6 space-y-5 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Fulfillment Nodes</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {active} of {nodes.length} nodes active
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => refetch()} className="btn-secondary">
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
          <button onClick={() => { setForm(emptyNodeForm()); setShowCreate(true) }} className="btn-primary">
            <Plus className="w-4 h-4" /> New Node
          </button>
        </div>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Total Nodes', value: nodes.length, color: 'text-gray-900' },
          { label: 'Active', value: active, color: 'text-green-600' },
          { label: 'Avg Load', value: `${avgLoad.toFixed(1)}%`, color: avgLoad >= 80 ? 'text-red-600' : 'text-blue-600' },
        ].map(({ label, value, color }) => (
          <div key={label} className="card p-4">
            <p className="text-xs text-gray-500 font-medium">{label}</p>
            <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Brand-neutral callout */}
      <div className="flex items-start gap-2 px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-xs text-gray-500">
        <span>Fulfillment nodes are shared across all brands. Brand-specific routing is configured in Sourcing Rules.</span>
      </div>

      {/* Page tabs */}
      <div className="flex border-b border-gray-200">
        {([
          { key: 'nodes' as PageTab, label: 'Nodes' },
          { key: 'brands' as PageTab, label: 'Brand Assignments' },
        ]).map(t => (
          <button
            key={t.key}
            onClick={() => setPageTab(t.key)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              pageTab === t.key
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {pageTab === 'brands' ? (
        <BrandAssignmentsTab nodes={nodes} />
      ) : (
        <>
          {/* Type Filter */}
          {types.length > 1 && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => setTypeFilter('')}
                className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                  !typeFilter ? 'bg-gray-900 text-white' : 'bg-white text-gray-600 border border-gray-200 hover:bg-gray-50'
                }`}
              >
                All
              </button>
              {types.map(t => (
                <button
                  key={t}
                  onClick={() => setTypeFilter(t === typeFilter ? '' : t)}
                  className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                    typeFilter === t
                      ? 'bg-gray-900 text-white'
                      : 'bg-white text-gray-600 border border-gray-200 hover:bg-gray-50'
                  }`}
                >
                  {t.replace(/_/g, ' ')}
                </button>
              ))}
            </div>
          )}

          {/* Cards Grid */}
          {isLoading ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="card p-5 animate-pulse space-y-3">
                  <div className="flex gap-3">
                    <div className="w-10 h-10 bg-gray-200 rounded-xl" />
                    <div className="flex-1 space-y-2">
                      <div className="h-4 bg-gray-200 rounded w-32" />
                      <div className="h-3 bg-gray-200 rounded w-24" />
                    </div>
                  </div>
                  <div className="h-2 bg-gray-200 rounded-full" />
                </div>
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <div className="card p-12 text-center text-gray-400 text-sm">
              No nodes found.
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
              {filtered.map(node => (
                <NodeCard key={node.id} node={node} onEdit={() => openEdit(node)} onDelete={() => setDeletingNode(node)} />
              ))}
            </div>
          )}
        </>
      )}

      {/* ── Create Modal ── */}
      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Fulfillment Node" size="lg">
        <NodeForm value={form} onChange={setForm} isEdit={false} />
        {createMutation.isError && (
          <p className="text-xs text-red-600 mt-3">
            {(createMutation.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to create node.'}
          </p>
        )}
        <div className="flex justify-end gap-2 mt-6">
          <button className="btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button>
          <button className="btn-primary" disabled={!form.code || !form.name || createMutation.isPending} onClick={() => createMutation.mutate(form)}>
            {createMutation.isPending ? 'Creating…' : <><Check className="w-4 h-4" /> Create Node</>}
          </button>
        </div>
      </Modal>

      {/* ── Edit Modal ── */}
      {editingNode && (
        <Modal open={!!editingNode} onClose={() => setEditingNode(null)} title={`Edit: ${editingNode.name}`} size="lg">
          <NodeForm value={form} onChange={setForm} isEdit={true} />
          {updateMutation.isError && <p className="text-xs text-red-600 mt-3">Failed to save changes.</p>}
          <div className="flex justify-end gap-2 mt-6">
            <button className="btn-secondary" onClick={() => setEditingNode(null)}>Cancel</button>
            <button className="btn-primary" disabled={!form.name || updateMutation.isPending}
              onClick={() => {
                const { code: _code, node_type: _nt, latitude: _lat, longitude: _lng, ...updateFields } = form
                updateMutation.mutate({ id: editingNode.id, data: updateFields })
              }}>
              {updateMutation.isPending ? 'Saving…' : <><Check className="w-4 h-4" /> Save Changes</>}
            </button>
          </div>
        </Modal>
      )}

      {/* ── Delete (deactivate) Confirmation ── */}
      <Modal open={!!deletingNode} onClose={() => setDeletingNode(null)} title="Deactivate Node" size="sm">
        <p className="text-sm text-gray-600">
          Deactivate <span className="font-semibold">{deletingNode?.name}</span>? The node will be set to INACTIVE and removed from sourcing. This can be reversed by editing the node status.
        </p>
        {deleteMutation.isError && <p className="text-xs text-red-600 mt-2">Failed to deactivate node.</p>}
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-secondary" onClick={() => setDeletingNode(null)}>Cancel</button>
          <button className="btn-danger" disabled={deleteMutation.isPending} onClick={() => deletingNode && deleteMutation.mutate(deletingNode.id)}>
            <Trash2 className="w-4 h-4" /> {deleteMutation.isPending ? 'Deactivating…' : 'Deactivate'}
          </button>
        </div>
      </Modal>
    </div>
  )
}
