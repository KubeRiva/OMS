import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Zap, RefreshCw, ChevronUp, ChevronDown, ToggleLeft, ToggleRight,
  Info, Plus, Pencil, Trash2, X, Check,
} from 'lucide-react'
import {
  fetchSourcingRules, createSourcingRule, updateSourcingRule, deleteSourcingRule,
  fetchSourcingMetadata,
  type SourcingRule, type SourcingCondition, type SourcingRulePayload,
} from '../api/client'
import { StatusBadge } from '../components/Badge'
import Modal from '../components/Modal'

// ─── Constants ────────────────────────────────────────────────────────────────

const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  DISTANCE_OPTIMAL: 'Routes to the nearest fulfillment node based on haversine distance',
  COST_OPTIMAL: 'Minimizes total fulfillment cost including shipping and handling',
  STORE_NEAREST: 'Prefers physical store locations over distribution centers',
  INVENTORY_RESERVATION: 'Prioritizes nodes with the most available stock',
  LEAST_COST_SPLIT: 'Allows split shipments to minimize total cost',
  AI_ADAPTIVE: '🤖 KubeAI scores nodes using historical patterns and performance data (falls back to Distance Optimal when data is insufficient)',
  AI_HYBRID: '🤖 Blends KubeAI score (60%) with rule-based score (40%) for balanced decisions',
}

interface Metadata {
  strategies: string[]
  node_types: string[]
  operators: string[]
  capabilities: string[]
}

const emptyPayload = (): SourcingRulePayload => ({
  name: '',
  description: '',
  priority: 10,
  is_active: true,
  strategy: 'DISTANCE_OPTIMAL',
  conditions: [],
  allowed_node_types: [],
  excluded_node_ids: [],
  required_capabilities: [],
  max_split_nodes: 1,
  max_distance_km: undefined,
  cost_weight: 0.5,
  distance_weight: 0.5,
})

// ─── Condition Builder ─────────────────────────────────────────────────────────

function ConditionBuilder({
  conditions,
  onChange,
  operators,
}: {
  conditions: SourcingCondition[]
  onChange: (c: SourcingCondition[]) => void
  operators: string[]
}) {
  const add = () => onChange([...conditions, { field: 'channel', operator: 'EQUALS', value: '' }])
  const remove = (i: number) => onChange(conditions.filter((_, idx) => idx !== i))
  const update = (i: number, patch: Partial<SourcingCondition>) =>
    onChange(conditions.map((c, idx) => (idx === i ? { ...c, ...patch } : c)))

  return (
    <div className="space-y-2">
      {conditions.map((cond, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            className="input flex-1 text-xs"
            value={cond.field}
            onChange={e => update(i, { field: e.target.value })}
            placeholder="field (e.g. channel)"
          />
          <select
            className="input text-xs w-44"
            value={cond.operator}
            onChange={e => update(i, { operator: e.target.value })}
          >
            {operators.map(op => (
              <option key={op} value={op}>{op.replace(/_/g, ' ')}</option>
            ))}
          </select>
          <input
            className="input flex-1 text-xs"
            value={String(cond.value)}
            onChange={e => update(i, { value: e.target.value })}
            placeholder="value"
          />
          <button
            type="button"
            onClick={() => remove(i)}
            className="text-red-400 hover:text-red-600 transition-colors flex-shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1 transition-colors"
      >
        <Plus className="w-3.5 h-3.5" /> Add condition
      </button>
    </div>
  )
}

// ─── Rule Form (shared by Create & Edit) ───────────────────────────────────────

function RuleForm({
  value,
  onChange,
  metadata,
}: {
  value: SourcingRulePayload
  onChange: (v: SourcingRulePayload) => void
  metadata: Metadata
}) {
  const set = <K extends keyof SourcingRulePayload>(k: K, v: SourcingRulePayload[K]) =>
    onChange({ ...value, [k]: v })

  const toggleArr = (arr: string[], item: string) =>
    arr.includes(item) ? arr.filter(x => x !== item) : [...arr, item]

  return (
    <div className="space-y-4 text-sm">
      {/* Name + Description */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Rule Name *</label>
          <input className="input" value={value.name} onChange={e => set('name', e.target.value)} placeholder="e.g. Store-first west coast" />
        </div>
        <div>
          <label className="label">Priority</label>
          <input type="number" min={1} max={999} className="input" value={value.priority} onChange={e => set('priority', Number(e.target.value))} />
        </div>
      </div>
      <div>
        <label className="label">Description</label>
        <input className="input" value={value.description ?? ''} onChange={e => set('description', e.target.value)} placeholder="Optional description" />
      </div>

      {/* Strategy + Active */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Strategy *</label>
          <select className="input" value={value.strategy} onChange={e => set('strategy', e.target.value)}>
            {metadata.strategies.map(s => (
              <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
            ))}
          </select>
          {STRATEGY_DESCRIPTIONS[value.strategy] && (
            <p className="text-xs text-blue-600 mt-1 italic">{STRATEGY_DESCRIPTIONS[value.strategy]}</p>
          )}
        </div>
        <div>
          <label className="label">Status</label>
          <button
            type="button"
            onClick={() => set('is_active', !value.is_active)}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-medium transition-colors w-full ${
              value.is_active
                ? 'bg-green-50 border-green-200 text-green-700'
                : 'bg-gray-50 border-gray-200 text-gray-500'
            }`}
          >
            {value.is_active ? <ToggleRight className="w-4 h-4" /> : <ToggleLeft className="w-4 h-4" />}
            {value.is_active ? 'Active' : 'Inactive'}
          </button>
        </div>
      </div>

      {/* Conditions */}
      <div>
        <label className="label">Matching Conditions</label>
        <ConditionBuilder
          conditions={value.conditions}
          onChange={c => set('conditions', c)}
          operators={metadata.operators}
        />
      </div>

      {/* Node types */}
      <div>
        <label className="label">Allowed Node Types <span className="text-gray-400">(empty = all)</span></label>
        <div className="flex gap-3 flex-wrap">
          {metadata.node_types.map(nt => (
            <label key={nt} className="flex items-center gap-1.5 cursor-pointer text-xs">
              <input
                type="checkbox"
                checked={value.allowed_node_types.includes(nt)}
                onChange={() => set('allowed_node_types', toggleArr(value.allowed_node_types, nt))}
                className="rounded border-gray-300"
              />
              {nt.replace(/_/g, ' ')}
            </label>
          ))}
        </div>
      </div>

      {/* Required capabilities */}
      <div>
        <label className="label">Required Capabilities <span className="text-gray-400">(empty = any)</span></label>
        <div className="flex gap-3 flex-wrap">
          {metadata.capabilities.map(cap => (
            <label key={cap} className="flex items-center gap-1.5 cursor-pointer text-xs">
              <input
                type="checkbox"
                checked={value.required_capabilities.includes(cap)}
                onChange={() => set('required_capabilities', toggleArr(value.required_capabilities, cap))}
                className="rounded border-gray-300"
              />
              {cap.replace(/_/g, ' ')}
            </label>
          ))}
        </div>
      </div>

      {/* Numeric params */}
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="label">Max Split Nodes</label>
          <input type="number" min={1} max={10} className="input" value={value.max_split_nodes} onChange={e => set('max_split_nodes', Number(e.target.value))} />
        </div>
        <div>
          <label className="label">Max Distance (km)</label>
          <input
            type="number"
            min={0}
            className="input"
            value={value.max_distance_km ?? ''}
            onChange={e => set('max_distance_km', e.target.value ? Number(e.target.value) : undefined)}
            placeholder="Unlimited"
          />
        </div>
        <div />
      </div>

      {/* Weights */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="label">Cost Weight: <span className="font-bold">{value.cost_weight.toFixed(2)}</span></label>
          <input
            type="range" min={0} max={1} step={0.05}
            className="w-full accent-blue-600"
            value={value.cost_weight}
            onChange={e => set('cost_weight', Number(e.target.value))}
          />
        </div>
        <div>
          <label className="label">Distance Weight: <span className="font-bold">{value.distance_weight.toFixed(2)}</span></label>
          <input
            type="range" min={0} max={1} step={0.05}
            className="w-full accent-blue-600"
            value={value.distance_weight}
            onChange={e => set('distance_weight', Number(e.target.value))}
          />
        </div>
      </div>
    </div>
  )
}

// ─── Condition Tag Display ─────────────────────────────────────────────────────

function ConditionTag({ conditions }: { conditions: SourcingCondition[] }) {
  if (!conditions.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {conditions.map((cond, i) => (
        <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs bg-gray-100 text-gray-600 font-mono">
          {cond.field} <span className="text-gray-400">{cond.operator}</span>{' '}
          <span className="font-semibold text-gray-800">{String(cond.value)}</span>
        </span>
      ))}
    </div>
  )
}

// ─── Rule Card ─────────────────────────────────────────────────────────────────

function RuleCard({
  rule,
  onToggle,
  onPriorityChange,
  onEdit,
  onDelete,
  isPending,
}: {
  rule: SourcingRule
  onToggle: () => void
  onPriorityChange: (dir: 'up' | 'down') => void
  onEdit: () => void
  onDelete: () => void
  isPending: boolean
}) {
  const [showDesc, setShowDesc] = useState(false)

  return (
    <div className={`card p-5 border-l-4 transition-all ${
      rule.is_active ? 'border-l-green-500' : 'border-l-gray-300 opacity-60'
    }`}>
      <div className="flex items-start justify-between gap-4">
        {/* Left: priority + name */}
        <div className="flex items-start gap-3">
          {/* Priority controls */}
          <div className="flex flex-col items-center gap-0.5">
            <button
              onClick={() => onPriorityChange('up')}
              className="p-0.5 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
              disabled={isPending}
            >
              <ChevronUp className="w-4 h-4" />
            </button>
            <span className="text-xs font-bold text-gray-500 w-5 text-center">{rule.priority}</span>
            <button
              onClick={() => onPriorityChange('down')}
              className="p-0.5 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
              disabled={isPending}
            >
              <ChevronDown className="w-4 h-4" />
            </button>
          </div>

          {/* Name + strategy */}
          <div className="space-y-1.5 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-semibold text-gray-900 text-sm">{rule.name}</h3>
              <StatusBadge value={rule.strategy} />
            </div>
            <p className="text-xs text-gray-500">{rule.description || 'No description'}</p>

            {/* Strategy info */}
            {STRATEGY_DESCRIPTIONS[rule.strategy] && (
              <div className="flex items-start gap-1">
                <button
                  onClick={() => setShowDesc(s => !s)}
                  className="text-blue-400 hover:text-blue-600 transition-colors mt-0.5"
                >
                  <Info className="w-3.5 h-3.5" />
                </button>
                {showDesc && (
                  <p className="text-xs text-blue-600 italic">{STRATEGY_DESCRIPTIONS[rule.strategy]}</p>
                )}
              </div>
            )}

            {/* Conditions */}
            {rule.conditions && rule.conditions.length > 0 && (
              <div>
                <p className="text-xs text-gray-400 font-medium mb-1">Conditions</p>
                <ConditionTag conditions={rule.conditions} />
              </div>
            )}

            {/* Node types + capabilities badges */}
            <div className="flex flex-wrap gap-1.5">
              {rule.allowed_node_types.map(t => (
                <span key={t} className="px-1.5 py-0.5 bg-blue-50 text-blue-700 rounded text-[10px] font-medium">
                  {t.replace(/_/g, ' ')}
                </span>
              ))}
              {rule.required_capabilities.map(c => (
                <span key={c} className="px-1.5 py-0.5 bg-purple-50 text-purple-700 rounded text-[10px] font-medium">
                  {c.replace(/_/g, ' ')}
                </span>
              ))}
              {rule.max_distance_km && (
                <span className="px-1.5 py-0.5 bg-amber-50 text-amber-700 rounded text-[10px] font-medium">
                  ≤{rule.max_distance_km}km
                </span>
              )}
              {rule.max_split_nodes > 1 && (
                <span className="px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded text-[10px] font-medium">
                  Split ≤{rule.max_split_nodes} nodes
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Right: actions */}
        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            onClick={onEdit}
            disabled={isPending}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-blue-600 transition-colors"
            title="Edit rule"
          >
            <Pencil className="w-4 h-4" />
          </button>
          <button
            onClick={onDelete}
            disabled={isPending}
            className="p-1.5 rounded-lg hover:bg-red-50 text-gray-400 hover:text-red-600 transition-colors"
            title="Delete rule"
          >
            <Trash2 className="w-4 h-4" />
          </button>
          <button
            onClick={onToggle}
            disabled={isPending}
            className={`p-1 rounded-lg transition-colors ${
              isPending ? 'opacity-50' : 'hover:bg-gray-100'
            }`}
            title={rule.is_active ? 'Disable rule' : 'Enable rule'}
          >
            {rule.is_active ? (
              <ToggleRight className="w-7 h-7 text-green-500" />
            ) : (
              <ToggleLeft className="w-7 h-7 text-gray-400" />
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function SourcingRules() {
  const qc = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [editingRule, setEditingRule] = useState<SourcingRule | null>(null)
  const [deletingRule, setDeletingRule] = useState<SourcingRule | null>(null)
  const [form, setForm] = useState<SourcingRulePayload>(emptyPayload())

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['sourcingRules'],
    queryFn: () => fetchSourcingRules({ page: 1, page_size: 50 }),
  })

  const { data: metadata } = useQuery({
    queryKey: ['sourcingMetadata'],
    queryFn: fetchSourcingMetadata,
    staleTime: Infinity, // enum values don't change at runtime
  })

  // Fallback while metadata loads
  const meta: Metadata = metadata ?? {
    strategies: ['DISTANCE_OPTIMAL', 'COST_OPTIMAL', 'STORE_NEAREST', 'INVENTORY_RESERVATION', 'LEAST_COST_SPLIT', 'AI_ADAPTIVE', 'AI_HYBRID'],
    node_types: ['DISTRIBUTION_CENTER', 'RETAIL_STORE', 'DARK_STORE', 'WAREHOUSE', 'PICKUP_POINT'],
    operators: ['EQUALS', 'NOT_EQUALS', 'GREATER_THAN', 'LESS_THAN', 'GREATER_THAN_OR_EQUAL', 'LESS_THAN_OR_EQUAL', 'IN', 'NOT_IN', 'CONTAINS', 'STARTS_WITH'],
    capabilities: ['can_ship', 'can_pickup', 'can_curbside', 'can_same_day'],
  }

  const invalidate = () => qc.invalidateQueries({ queryKey: ['sourcingRules'] })

  const createMutation = useMutation({
    mutationFn: createSourcingRule,
    onSuccess: () => { invalidate(); setShowCreate(false) },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<SourcingRulePayload> }) =>
      updateSourcingRule(id, payload),
    onSuccess: () => { invalidate(); setEditingRule(null) },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteSourcingRule(id),
    onSuccess: () => { invalidate(); setDeletingRule(null) },
  })

  const rules = [...(data?.items ?? [])].sort((a, b) => a.priority - b.priority)

  const openCreate = () => {
    setForm(emptyPayload())
    setShowCreate(true)
  }

  const openEdit = (rule: SourcingRule) => {
    setForm({
      name: rule.name,
      description: rule.description ?? '',
      priority: rule.priority,
      is_active: rule.is_active,
      strategy: rule.strategy,
      conditions: rule.conditions ?? [],
      allowed_node_types: rule.allowed_node_types ?? [],
      excluded_node_ids: rule.excluded_node_ids ?? [],
      required_capabilities: rule.required_capabilities ?? [],
      max_split_nodes: rule.max_split_nodes,
      max_distance_km: rule.max_distance_km,
      cost_weight: rule.cost_weight,
      distance_weight: rule.distance_weight,
    })
    setEditingRule(rule)
  }

  const handleToggle = (rule: SourcingRule) => {
    updateMutation.mutate({ id: rule.id, payload: { is_active: !rule.is_active } })
  }

  const handlePriorityChange = (rule: SourcingRule, dir: 'up' | 'down') => {
    const newPriority = dir === 'up' ? rule.priority - 1 : rule.priority + 1
    if (newPriority < 1) return
    updateMutation.mutate({ id: rule.id, payload: { priority: newPriority } })
  }

  const anyPending =
    createMutation.isPending || updateMutation.isPending || deleteMutation.isPending

  const activeCount = rules.filter(r => r.is_active).length

  return (
    <div className="p-6 space-y-5 max-w-4xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Sourcing Rules</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {activeCount} of {rules.length} rules active — evaluated in priority order
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => refetch()} className="btn-secondary">
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
          <button onClick={openCreate} className="btn-primary">
            <Plus className="w-4 h-4" /> New Rule
          </button>
        </div>
      </div>

      {/* Strategy Legend */}
      <div className="card p-4">
        <div className="flex items-center gap-2 mb-3">
          <Zap className="w-4 h-4 text-amber-500" />
          <h2 className="text-xs font-semibold text-gray-600 uppercase tracking-wider">Strategies</h2>
        </div>
        <div className="flex flex-wrap gap-2">
          {meta.strategies.map(s => <StatusBadge key={s} value={s} />)}
        </div>
      </div>

      {/* Rules */}
      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="card p-5 animate-pulse">
              <div className="flex gap-3">
                <div className="w-5 h-16 bg-gray-200 rounded" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 bg-gray-200 rounded w-48" />
                  <div className="h-3 bg-gray-200 rounded w-64" />
                  <div className="h-6 bg-gray-200 rounded w-32" />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : rules.length === 0 ? (
        <div className="card p-12 text-center text-gray-400 text-sm">
          <Zap className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="font-medium text-gray-500">No sourcing rules configured</p>
          <p className="text-xs mt-1 mb-4">Create your first rule to control how orders are fulfilled</p>
          <button onClick={openCreate} className="btn-primary mx-auto">
            <Plus className="w-4 h-4" /> Create First Rule
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {rules.map(rule => (
            <RuleCard
              key={rule.id}
              rule={rule}
              onToggle={() => handleToggle(rule)}
              onPriorityChange={dir => handlePriorityChange(rule, dir)}
              onEdit={() => openEdit(rule)}
              onDelete={() => setDeletingRule(rule)}
              isPending={anyPending}
            />
          ))}
        </div>
      )}

      {/* Info box */}
      <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 text-xs text-blue-700 space-y-1">
        <p className="font-semibold">How sourcing rules work</p>
        <p>Rules are evaluated top-down by priority. The first matching active rule determines the sourcing strategy for a new order. Use the arrows to reorder priorities, the toggle to enable/disable, and the pencil to edit all fields.</p>
      </div>

      {/* ── Create Modal ── */}
      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Sourcing Rule" size="lg">
        <RuleForm value={form} onChange={setForm} metadata={meta} />
        {createMutation.isError && (
          <p className="text-xs text-red-600 mt-3">Failed to create rule. Check all required fields.</p>
        )}
        <div className="flex justify-end gap-2 mt-6">
          <button className="btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button>
          <button
            className="btn-primary"
            disabled={!form.name || createMutation.isPending}
            onClick={() => createMutation.mutate(form)}
          >
            {createMutation.isPending ? 'Creating…' : <><Check className="w-4 h-4" /> Create Rule</>}
          </button>
        </div>
      </Modal>

      {/* ── Edit Modal ── */}
      <Modal open={!!editingRule} onClose={() => setEditingRule(null)} title={`Edit Rule: ${editingRule?.name}`} size="lg">
        <RuleForm value={form} onChange={setForm} metadata={meta} />
        {updateMutation.isError && (
          <p className="text-xs text-red-600 mt-3">Failed to save changes.</p>
        )}
        <div className="flex justify-end gap-2 mt-6">
          <button className="btn-secondary" onClick={() => setEditingRule(null)}>Cancel</button>
          <button
            className="btn-primary"
            disabled={!form.name || updateMutation.isPending}
            onClick={() => editingRule && updateMutation.mutate({ id: editingRule.id, payload: form })}
          >
            {updateMutation.isPending ? 'Saving…' : <><Check className="w-4 h-4" /> Save Changes</>}
          </button>
        </div>
      </Modal>

      {/* ── Delete Confirmation Modal ── */}
      <Modal open={!!deletingRule} onClose={() => setDeletingRule(null)} title="Delete Rule" size="sm">
        <p className="text-sm text-gray-600">
          Are you sure you want to delete{' '}
          <span className="font-semibold text-gray-900">{deletingRule?.name}</span>?
          This action cannot be undone.
        </p>
        {deleteMutation.isError && (
          <p className="text-xs text-red-600 mt-2">Failed to delete rule.</p>
        )}
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-secondary" onClick={() => setDeletingRule(null)}>Cancel</button>
          <button
            className="btn-danger"
            disabled={deleteMutation.isPending}
            onClick={() => deletingRule && deleteMutation.mutate(deletingRule.id)}
          >
            {deleteMutation.isPending ? 'Deleting…' : <><Trash2 className="w-4 h-4" /> Delete Rule</>}
          </button>
        </div>
      </Modal>
    </div>
  )
}
