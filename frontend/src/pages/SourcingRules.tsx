import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Zap, RefreshCw, ChevronUp, ChevronDown, ToggleLeft, ToggleRight,
  Info, Plus, Pencil, Trash2, X, Check, Layers, GripVertical,
  ArrowUpDown,
} from 'lucide-react'
import {
  fetchSourcingRules, createSourcingRule, updateSourcingRule, deleteSourcingRule,
  fetchSourcingMetadata, getBrands, fetchNodes,
  fetchDistributionGroups, createDistributionGroup, updateDistributionGroup,
  deleteDistributionGroup, addDGMember, updateDGMemberPriority, removeDGMember,
  type SourcingRule, type SourcingCondition, type SourcingRulePayload,
  type SourcingConditionField, type SourcingTarget,
  type DistributionGroup, type DistributionGroupPayload,
} from '../api/client'
import { StatusBadge } from '../components/Badge'
import Modal from '../components/Modal'

// ─── Constants ────────────────────────────────────────────────────────────────

const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  DISTANCE_OPTIMAL:      'Routes to the nearest fulfillment node based on haversine distance',
  COST_OPTIMAL:          'Minimizes total fulfillment cost including shipping and handling',
  STORE_NEAREST:         'Prefers physical store locations over distribution centers',
  INVENTORY_RESERVATION: 'Prioritizes nodes with the most available stock',
  LEAST_COST_SPLIT:      'Allows split shipments to minimize total cost',
  AI_ADAPTIVE:           '🤖 KubeAI scores nodes using historical patterns (falls back to Distance Optimal when data is insufficient)',
  AI_HYBRID:             '🤖 Blends KubeAI score (60%) with rule-based score (40%) for balanced decisions',
}

interface Metadata {
  strategies: string[]
  node_types: string[]
  operators: string[]
  capabilities: string[]
  condition_fields: SourcingConditionField[]
}

const DEFAULT_META: Metadata = {
  strategies: ['DISTANCE_OPTIMAL', 'COST_OPTIMAL', 'STORE_NEAREST', 'INVENTORY_RESERVATION', 'LEAST_COST_SPLIT', 'AI_ADAPTIVE', 'AI_HYBRID'],
  node_types: ['DISTRIBUTION_CENTER', 'RETAIL_STORE', 'DARK_STORE', 'WAREHOUSE', 'PICKUP_POINT'],
  operators: ['EQUALS', 'NOT_EQUALS', 'GREATER_THAN', 'LESS_THAN', 'GREATER_THAN_OR_EQUAL', 'LESS_THAN_OR_EQUAL', 'IN', 'NOT_IN', 'CONTAINS', 'STARTS_WITH'],
  capabilities: ['can_ship', 'can_pickup', 'can_curbside', 'can_same_day'],
  condition_fields: [
    { field: 'channel',          label: 'Channel',              group: 'Order', values: ['WEB', 'MOBILE', 'POS', 'API', 'MARKETPLACE', 'B2B', 'EDI', 'WHOLESALE'] },
    { field: 'fulfillment_type', label: 'Fulfillment Type',     group: 'Order', values: ['SHIP_TO_HOME', 'STORE_PICKUP', 'SHIP_FROM_STORE', 'CURBSIDE_PICKUP', 'SAME_DAY_DELIVERY'] },
    { field: 'total_amount',     label: 'Order Total ($)',       group: 'Order', values: [] },
    { field: 'shipping_country', label: 'Shipping Country',     group: 'Order', values: ['US', 'CA', 'GB', 'AU'] },
    { field: 'shipping_state',   label: 'Shipping State',       group: 'Order', values: [] },
    { field: 'order_type',       label: 'Order Type',           group: 'B2B',   values: ['RETAIL', 'B2B', 'WHOLESALE'] },
    { field: 'payment_terms',    label: 'Payment Terms',        group: 'B2B',   values: ['PREPAID', 'NET15', 'NET30', 'NET60', 'NET90', 'COD'] },
    { field: 'approval_status',  label: 'Approval Status',      group: 'B2B',   values: ['NOT_REQUIRED', 'PENDING', 'APPROVED', 'REJECTED'] },
  ],
}

const emptyPayload = (): SourcingRulePayload => ({
  name: '',
  description: '',
  priority: 10,
  is_active: true,
  strategy: 'DISTANCE_OPTIMAL',
  conditions: [],
  sourcing_targets: [],
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
  conditions, onChange, operators, conditionFields,
}: {
  conditions: SourcingCondition[]
  onChange: (c: SourcingCondition[]) => void
  operators: string[]
  conditionFields: SourcingConditionField[]
}) {
  const add = () => onChange([...conditions, { field: 'channel', operator: 'EQUALS', value: 'WEB' }])
  const remove = (i: number) => onChange(conditions.filter((_, idx) => idx !== i))
  const update = (i: number, patch: Partial<SourcingCondition>) =>
    onChange(conditions.map((c, idx) => (idx === i ? { ...c, ...patch } : c)))

  const fieldMeta = (f: string) => conditionFields.find(cf => cf.field === f)
  const groups = conditionFields.reduce<Record<string, SourcingConditionField[]>>((acc, cf) => {
    if (!acc[cf.group]) acc[cf.group] = []
    acc[cf.group].push(cf)
    return acc
  }, {})
  const isNumericField = (f: string) => ['total_amount'].includes(f)

  return (
    <div className="space-y-2">
      {conditions.map((cond, i) => {
        const meta = fieldMeta(cond.field)
        const knownValues = meta?.values ?? []
        const isNumeric = isNumericField(cond.field)
        const isB2B = meta?.group === 'B2B'
        return (
          <div key={i} className="space-y-1">
            <div className="flex items-center gap-2">
              {conditionFields.length > 0 ? (
                <select className={`input flex-1 text-xs ${isB2B ? 'border-blue-300 bg-blue-50/30' : ''}`} value={cond.field}
                  onChange={e => { const nm = conditionFields.find(cf => cf.field === e.target.value); update(i, { field: e.target.value, value: nm?.values[0] ?? '' }) }}>
                  {Object.entries(groups).map(([group, fields]) => (
                    <optgroup key={group} label={group}>
                      {fields.map(f => <option key={f.field} value={f.field}>{f.label}</option>)}
                    </optgroup>
                  ))}
                </select>
              ) : (
                <input className="input flex-1 text-xs" value={cond.field} onChange={e => update(i, { field: e.target.value })} placeholder="field" />
              )}
              <select className="input text-xs w-40" value={cond.operator} onChange={e => update(i, { operator: e.target.value })}>
                {operators.filter(op => isNumeric ? true : !['GREATER_THAN', 'LESS_THAN', 'GREATER_THAN_OR_EQUAL', 'LESS_THAN_OR_EQUAL'].includes(op) || knownValues.length === 0)
                  .map(op => <option key={op} value={op}>{op.replace(/_/g, ' ')}</option>)}
              </select>
              {knownValues.length > 0 && !['IN', 'NOT_IN'].includes(cond.operator) ? (
                <select className={`input flex-1 text-xs ${isB2B ? 'border-blue-300' : ''}`} value={String(cond.value)} onChange={e => update(i, { value: e.target.value })}>
                  {knownValues.map(v => <option key={v} value={v}>{v}</option>)}
                </select>
              ) : (
                <input className="input flex-1 text-xs" value={String(cond.value)} onChange={e => update(i, { value: e.target.value })}
                  placeholder={['IN', 'NOT_IN'].includes(cond.operator) ? 'val1,val2,...' : isNumeric ? '0.00' : 'value'} type={isNumeric ? 'number' : 'text'} />
              )}
              <button type="button" onClick={() => remove(i)} className="text-red-400 hover:text-red-600 flex-shrink-0"><X className="w-4 h-4" /></button>
            </div>
            {isB2B && <p className="text-[10px] text-blue-500 pl-1">B2B field — only B2B orders carry this attribute</p>}
          </div>
        )
      })}
      <button type="button" onClick={add} className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1">
        <Plus className="w-3.5 h-3.5" /> Add condition
      </button>
    </div>
  )
}

// ─── Sourcing Targets Builder ──────────────────────────────────────────────────

function SourcingTargetsBuilder({
  targets, onChange, dgs, nodes,
}: {
  targets: SourcingTarget[]
  onChange: (t: SourcingTarget[]) => void
  dgs: DistributionGroup[]
  nodes: Array<{ id: string; name: string; code: string; node_type: string }>
}) {
  const [addType, setAddType] = useState<'DISTRIBUTION_GROUP' | 'NODE'>('DISTRIBUTION_GROUP')
  const [addId, setAddId] = useState('')

  const usedIds = new Set(targets.map(t => t.id))

  const availableDGs = dgs.filter(d => d.is_active && !usedIds.has(d.id))
  const availableNodes = nodes.filter(n => !usedIds.has(n.id))

  const add = () => {
    if (!addId) return
    const next = targets.length + 1
    onChange([...targets, { type: addType, id: addId, priority: next }])
    setAddId('')
  }

  const remove = (i: number) => onChange(targets.filter((_, idx) => idx !== i).map((t, idx) => ({ ...t, priority: idx + 1 })))

  const move = (i: number, dir: 'up' | 'down') => {
    const ts = [...targets]
    const j = dir === 'up' ? i - 1 : i + 1
    if (j < 0 || j >= ts.length) return
    ;[ts[i], ts[j]] = [ts[j], ts[i]]
    onChange(ts.map((t, idx) => ({ ...t, priority: idx + 1 })))
  }

  const dgName = (id: string) => dgs.find(d => d.id === id)?.name ?? id
  const nodeName = (id: string) => {
    const n = nodes.find(x => x.id === id)
    return n ? `${n.name} (${n.code})` : id
  }

  return (
    <div className="space-y-2">
      {targets.length === 0 && (
        <p className="text-xs text-gray-400 italic">No targets configured — rule will consider all eligible nodes</p>
      )}
      {targets.map((t, i) => (
        <div key={i} className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2 text-xs">
          <div className="flex flex-col gap-0.5 flex-shrink-0">
            <button type="button" onClick={() => move(i, 'up')} disabled={i === 0} className="text-gray-300 hover:text-gray-500 disabled:opacity-30 leading-none">▲</button>
            <button type="button" onClick={() => move(i, 'down')} disabled={i === targets.length - 1} className="text-gray-300 hover:text-gray-500 disabled:opacity-30 leading-none">▼</button>
          </div>
          <span className="font-semibold text-gray-500 w-4 text-center">{i + 1}</span>
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium flex-shrink-0 ${t.type === 'DISTRIBUTION_GROUP' ? 'bg-blue-50 text-blue-700' : 'bg-green-50 text-green-700'}`}>
            {t.type === 'DISTRIBUTION_GROUP' ? 'DG' : 'Node'}
          </span>
          <span className="flex-1 font-medium text-gray-800 truncate">
            {t.type === 'DISTRIBUTION_GROUP' ? dgName(t.id) : nodeName(t.id)}
          </span>
          <button type="button" onClick={() => remove(i)} className="text-red-400 hover:text-red-600 flex-shrink-0"><X className="w-3.5 h-3.5" /></button>
        </div>
      ))}

      <div className="flex items-end gap-2 pt-1">
        <div>
          <label className="label text-[10px]">Add</label>
          <select className="select text-xs" value={addType} onChange={e => { setAddType(e.target.value as 'DISTRIBUTION_GROUP' | 'NODE'); setAddId('') }}>
            <option value="DISTRIBUTION_GROUP">Distribution Group</option>
            <option value="NODE">Individual Node</option>
          </select>
        </div>
        <div className="flex-1">
          <label className="label text-[10px]">{addType === 'DISTRIBUTION_GROUP' ? 'Group' : 'Node'}</label>
          <select className="select text-xs" value={addId} onChange={e => setAddId(e.target.value)}>
            <option value="">Select…</option>
            {addType === 'DISTRIBUTION_GROUP'
              ? availableDGs.map(d => <option key={d.id} value={d.id}>{d.name} ({d.members.length} nodes)</option>)
              : availableNodes.map(n => <option key={n.id} value={n.id}>{n.name} ({n.code})</option>)
            }
          </select>
        </div>
        <button type="button" onClick={add} disabled={!addId} className="btn-secondary h-9 px-3 text-xs flex-shrink-0">
          <Plus className="w-3.5 h-3.5" />
        </button>
      </div>

      {targets.length === 0 && dgs.length === 0 && (
        <p className="text-[11px] text-amber-600 bg-amber-50 rounded-lg px-3 py-2">
          Create Distribution Groups in the <strong>Distribution Groups</strong> tab first to use them as targets.
        </p>
      )}
    </div>
  )
}

// ─── Rule Form ─────────────────────────────────────────────────────────────────

function RuleForm({
  value, onChange, metadata, dgs, nodes,
}: {
  value: SourcingRulePayload
  onChange: (v: SourcingRulePayload) => void
  metadata: Metadata
  dgs: DistributionGroup[]
  nodes: Array<{ id: string; name: string; code: string; node_type: string }>
}) {
  const set = <K extends keyof SourcingRulePayload>(k: K, v: SourcingRulePayload[K]) => onChange({ ...value, [k]: v })
  const toggleArr = (arr: string[], item: string) => arr.includes(item) ? arr.filter(x => x !== item) : [...arr, item]

  return (
    <div className="space-y-4 text-sm">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Rule Name *</label>
          <input className="input" value={value.name} onChange={e => set('name', e.target.value)} placeholder="e.g. West-coast stores first" />
        </div>
        <div>
          <label className="label">Priority <span className="text-gray-400 text-xs">(lower = evaluated first)</span></label>
          <input type="number" min={1} max={999} className="input" value={value.priority} onChange={e => set('priority', Number(e.target.value))} />
        </div>
      </div>
      <div>
        <label className="label">Description</label>
        <input className="input" value={value.description ?? ''} onChange={e => set('description', e.target.value)} placeholder="Optional description" />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Strategy *</label>
          <select className="input" value={value.strategy} onChange={e => set('strategy', e.target.value)}>
            {metadata.strategies.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
          </select>
          {STRATEGY_DESCRIPTIONS[value.strategy] && (
            <p className="text-xs text-blue-600 mt-1 italic">{STRATEGY_DESCRIPTIONS[value.strategy]}</p>
          )}
        </div>
        <div>
          <label className="label">Status</label>
          <button type="button" onClick={() => set('is_active', !value.is_active)}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-medium transition-colors w-full ${value.is_active ? 'bg-green-50 border-green-200 text-green-700' : 'bg-gray-50 border-gray-200 text-gray-500'}`}>
            {value.is_active ? <ToggleRight className="w-4 h-4" /> : <ToggleLeft className="w-4 h-4" />}
            {value.is_active ? 'Active' : 'Inactive'}
          </button>
        </div>
      </div>

      {/* Conditions */}
      <div>
        <label className="label">Matching Conditions</label>
        <ConditionBuilder conditions={value.conditions} onChange={c => set('conditions', c)} operators={metadata.operators} conditionFields={metadata.condition_fields ?? []} />
      </div>

      {/* Sourcing Targets */}
      <div>
        <label className="label">Sourcing Targets <span className="text-gray-400">(priority-ordered DGs and/or nodes — replaces node-type filters when set)</span></label>
        <SourcingTargetsBuilder targets={value.sourcing_targets ?? []} onChange={t => set('sourcing_targets', t)} dgs={dgs} nodes={nodes} />
      </div>

      {/* Node types (fallback filter) */}
      <div>
        <label className="label">Allowed Node Types <span className="text-gray-400">(secondary filter, empty = all)</span></label>
        <div className="flex gap-3 flex-wrap">
          {metadata.node_types.map(nt => (
            <label key={nt} className="flex items-center gap-1.5 cursor-pointer text-xs">
              <input type="checkbox" checked={value.allowed_node_types.includes(nt)} onChange={() => set('allowed_node_types', toggleArr(value.allowed_node_types, nt))} className="rounded border-gray-300" />
              {nt.replace(/_/g, ' ')}
            </label>
          ))}
        </div>
      </div>

      {/* Capabilities */}
      <div>
        <label className="label">Required Capabilities <span className="text-gray-400">(empty = any)</span></label>
        <div className="flex gap-3 flex-wrap">
          {metadata.capabilities.map(cap => (
            <label key={cap} className="flex items-center gap-1.5 cursor-pointer text-xs">
              <input type="checkbox" checked={value.required_capabilities.includes(cap)} onChange={() => set('required_capabilities', toggleArr(value.required_capabilities, cap))} className="rounded border-gray-300" />
              {cap.replace(/_/g, ' ')}
            </label>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="label">Max Split Nodes</label>
          <input type="number" min={1} max={10} className="input" value={value.max_split_nodes} onChange={e => set('max_split_nodes', Number(e.target.value))} />
        </div>
        <div>
          <label className="label">Max Distance (km)</label>
          <input type="number" min={0} className="input" value={value.max_distance_km ?? ''} onChange={e => set('max_distance_km', e.target.value ? Number(e.target.value) : undefined)} placeholder="Unlimited" />
        </div>
        <div />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="label">Cost Weight: <span className="font-bold">{value.cost_weight.toFixed(2)}</span></label>
          <input type="range" min={0} max={1} step={0.05} className="w-full accent-blue-600" value={value.cost_weight} onChange={e => set('cost_weight', Number(e.target.value))} />
        </div>
        <div>
          <label className="label">Distance Weight: <span className="font-bold">{value.distance_weight.toFixed(2)}</span></label>
          <input type="range" min={0} max={1} step={0.05} className="w-full accent-blue-600" value={value.distance_weight} onChange={e => set('distance_weight', Number(e.target.value))} />
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
  rule, brandName, dgNames, onToggle, onPriorityChange, onEdit, onDelete, isPending,
}: {
  rule: SourcingRule
  brandName?: string
  dgNames: Record<string, string>
  onToggle: () => void
  onPriorityChange: (dir: 'up' | 'down') => void
  onEdit: () => void
  onDelete: () => void
  isPending: boolean
}) {
  const [showDesc, setShowDesc] = useState(false)
  const targets = rule.sourcing_targets ?? []

  return (
    <div className={`card p-5 border-l-4 transition-all ${rule.is_active ? 'border-l-green-500' : 'border-l-gray-300 opacity-60'}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="flex flex-col items-center gap-0.5">
            <button onClick={() => onPriorityChange('up')} className="p-0.5 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600" disabled={isPending}><ChevronUp className="w-4 h-4" /></button>
            <span className="text-xs font-bold text-gray-500 w-5 text-center">{rule.priority}</span>
            <button onClick={() => onPriorityChange('down')} className="p-0.5 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600" disabled={isPending}><ChevronDown className="w-4 h-4" /></button>
          </div>

          <div className="space-y-1.5 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-semibold text-gray-900 text-sm">{rule.name}</h3>
              <StatusBadge value={rule.strategy} />
              {brandName && (
                <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-purple-50 text-purple-700 font-mono">{brandName}</span>
              )}
            </div>
            <p className="text-xs text-gray-500">{rule.description || 'No description'}</p>

            {STRATEGY_DESCRIPTIONS[rule.strategy] && (
              <div className="flex items-start gap-1">
                <button onClick={() => setShowDesc(s => !s)} className="text-blue-400 hover:text-blue-600 mt-0.5"><Info className="w-3.5 h-3.5" /></button>
                {showDesc && <p className="text-xs text-blue-600 italic">{STRATEGY_DESCRIPTIONS[rule.strategy]}</p>}
              </div>
            )}

            {rule.conditions?.length > 0 && (
              <div>
                <p className="text-xs text-gray-400 font-medium mb-1">Conditions</p>
                <ConditionTag conditions={rule.conditions} />
              </div>
            )}

            {/* Sourcing targets */}
            {targets.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {targets.map((t, i) => (
                  <span key={i} className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium ${t.type === 'DISTRIBUTION_GROUP' ? 'bg-blue-50 text-blue-700' : 'bg-green-50 text-green-700'}`}>
                    <ArrowUpDown className="w-2.5 h-2.5" />
                    {t.priority}. {t.type === 'DISTRIBUTION_GROUP' ? (dgNames[t.id] ?? 'DG') : 'Node'}
                  </span>
                ))}
              </div>
            )}

            <div className="flex flex-wrap gap-1.5">
              {rule.allowed_node_types.map(t => (
                <span key={t} className="px-1.5 py-0.5 bg-blue-50 text-blue-700 rounded text-[10px] font-medium">{t.replace(/_/g, ' ')}</span>
              ))}
              {rule.required_capabilities.map(c => (
                <span key={c} className="px-1.5 py-0.5 bg-purple-50 text-purple-700 rounded text-[10px] font-medium">{c.replace(/_/g, ' ')}</span>
              ))}
              {rule.max_distance_km && (
                <span className="px-1.5 py-0.5 bg-amber-50 text-amber-700 rounded text-[10px] font-medium">≤{rule.max_distance_km}km</span>
              )}
              {rule.max_split_nodes > 1 && (
                <span className="px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded text-[10px] font-medium">Split ≤{rule.max_split_nodes}</span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1 flex-shrink-0">
          <button onClick={onEdit} disabled={isPending} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-blue-600" title="Edit"><Pencil className="w-4 h-4" /></button>
          <button onClick={onDelete} disabled={isPending} className="p-1.5 rounded-lg hover:bg-red-50 text-gray-400 hover:text-red-600" title="Delete"><Trash2 className="w-4 h-4" /></button>
          <button onClick={onToggle} disabled={isPending} className={`p-1 rounded-lg transition-colors ${isPending ? 'opacity-50' : 'hover:bg-gray-100'}`}>
            {rule.is_active ? <ToggleRight className="w-7 h-7 text-green-500" /> : <ToggleLeft className="w-7 h-7 text-gray-400" />}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Distribution Groups Tab ───────────────────────────────────────────────────

function DGMemberRow({
  member, onRemove, onPriorityChange,
}: {
  member: { id: string; node_id: string; priority: number; node_name?: string; node_code?: string; node_type?: string }
  onRemove: () => void
  onPriorityChange: (priority: number) => void
}) {
  return (
    <div className="flex items-center gap-3 py-2 border-b border-gray-100 last:border-0">
      <GripVertical className="w-3.5 h-3.5 text-gray-300 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-gray-800">{member.node_name ?? member.node_id}</p>
        <p className="text-[10px] text-gray-400">{member.node_code} · {member.node_type?.replace(/_/g, ' ')}</p>
      </div>
      <div className="flex items-center gap-1">
        <label className="text-[10px] text-gray-400">Priority</label>
        <input type="number" min={1} max={99} className="input text-xs w-14" value={member.priority}
          onChange={e => onPriorityChange(Number(e.target.value))} />
      </div>
      <button onClick={onRemove} className="text-red-400 hover:text-red-600 flex-shrink-0"><X className="w-3.5 h-3.5" /></button>
    </div>
  )
}

function DGCard({
  dg, brandName, onEdit, onDelete,
}: {
  dg: DistributionGroup
  brandName?: string
  onEdit: () => void
  onDelete: () => void
}) {
  const members = [...dg.members].sort((a, b) => a.priority - b.priority)
  return (
    <div className={`card p-5 border-l-4 ${dg.is_active ? 'border-l-blue-400' : 'border-l-gray-200 opacity-60'}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <Layers className="w-4 h-4 text-blue-500 flex-shrink-0" />
            <h3 className="font-semibold text-sm text-gray-900">{dg.name}</h3>
            {brandName && <span className="px-1.5 py-0.5 bg-purple-50 text-purple-700 rounded text-[10px] font-medium">{brandName}</span>}
            {!dg.is_active && <span className="px-1.5 py-0.5 bg-gray-100 text-gray-400 rounded text-[10px]">inactive</span>}
          </div>
          {dg.description && <p className="text-xs text-gray-500 mb-2">{dg.description}</p>}
          <div className="flex flex-wrap gap-1.5">
            {members.map((m, i) => (
              <span key={m.id} className="flex items-center gap-1 px-2 py-0.5 bg-blue-50 text-blue-700 rounded text-[10px] font-medium">
                {i + 1}. {m.node_name ?? m.node_code ?? m.node_id}
              </span>
            ))}
            {members.length === 0 && <span className="text-[11px] text-gray-400">No members yet</span>}
          </div>
        </div>
        <div className="flex gap-1 flex-shrink-0">
          <button onClick={onEdit} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-blue-600"><Pencil className="w-4 h-4" /></button>
          <button onClick={onDelete} className="p-1.5 rounded-lg hover:bg-red-50 text-gray-400 hover:text-red-600"><Trash2 className="w-4 h-4" /></button>
        </div>
      </div>
    </div>
  )
}

interface DGEditorInitial {
  id?: string
  name: string
  description?: string
  brand_id?: string
  is_active?: boolean
  members?: Array<{ id?: string; node_id: string; priority: number; node_name?: string; node_code?: string; node_type?: string }>
}

function DGEditor({
  initial, nodes, brands, onSave, onClose, isSaving,
}: {
  initial: DGEditorInitial
  nodes: Array<{ id: string; name: string; code: string; node_type: string }>
  brands: Array<{ id: string; name: string }>
  onSave: (data: DistributionGroupPayload & { members?: Array<{ node_id: string; priority: number }> }) => void
  onClose: () => void
  isSaving?: boolean
}) {
  const [name, setName] = useState(initial.name)
  const [description, setDescription] = useState(initial.description ?? '')
  const [brandId, setBrandId] = useState(initial.brand_id ?? '')
  const [isActive, setIsActive] = useState(initial.is_active ?? true)
  const [members, setMembers] = useState<Array<{ node_id: string; priority: number; node_name?: string; node_code?: string; node_type?: string }>>(
    (initial.members ?? []).map(m => ({ node_id: m.node_id, priority: m.priority, node_name: m.node_name, node_code: m.node_code, node_type: m.node_type }))
  )
  const [addNodeId, setAddNodeId] = useState('')

  const usedNodeIds = new Set(members.map(m => m.node_id))
  const availableNodes = nodes.filter(n => !usedNodeIds.has(n.id))

  const addMember = () => {
    if (!addNodeId) return
    const node = nodes.find(n => n.id === addNodeId)
    setMembers(ms => [...ms, { node_id: addNodeId, priority: ms.length + 1, node_name: node?.name, node_code: node?.code, node_type: node?.node_type }])
    setAddNodeId('')
  }

  const removeMember = (nodeId: string) =>
    setMembers(ms => ms.filter(m => m.node_id !== nodeId).map((m, i) => ({ ...m, priority: i + 1 })))

  const updatePriority = (nodeId: string, priority: number) =>
    setMembers(ms => ms.map(m => m.node_id === nodeId ? { ...m, priority } : m))

  return (
    <div className="space-y-4 text-sm">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Group Name *</label>
          <input className="input" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. West Coast DCs, US East Stores" />
        </div>
        <div>
          <label className="label">Description</label>
          <input className="input" value={description} onChange={e => setDescription(e.target.value)} placeholder="Optional description" />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Brand Scope</label>
          <select className="select" value={brandId} onChange={e => setBrandId(e.target.value)}>
            <option value="">Global (all brands)</option>
            {brands.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Status</label>
          <button type="button" onClick={() => setIsActive(a => !a)}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-medium w-full ${isActive ? 'bg-green-50 border-green-200 text-green-700' : 'bg-gray-50 border-gray-200 text-gray-500'}`}>
            {isActive ? <ToggleRight className="w-4 h-4" /> : <ToggleLeft className="w-4 h-4" />}
            {isActive ? 'Active' : 'Inactive'}
          </button>
        </div>
      </div>

      <div>
        <label className="label">Member Nodes <span className="text-gray-400">(ordered by priority — lower number = tried first)</span></label>
        {members.length === 0 && (
          <p className="text-xs text-gray-400 py-2 text-center border border-dashed border-gray-200 rounded-lg">No members yet — add nodes below</p>
        )}
        <div className="border border-gray-100 rounded-lg divide-y divide-gray-100">
          {[...members].sort((a, b) => a.priority - b.priority).map(m => (
            <DGMemberRow key={m.node_id} member={{ id: m.node_id, ...m }} onRemove={() => removeMember(m.node_id)} onPriorityChange={p => updatePriority(m.node_id, p)} />
          ))}
        </div>

        <div className="flex gap-2 mt-2">
          <select className="select flex-1 text-xs" value={addNodeId} onChange={e => setAddNodeId(e.target.value)}>
            <option value="">Add node…</option>
            {availableNodes.map(n => <option key={n.id} value={n.id}>{n.name} ({n.code}) — {n.node_type}</option>)}
          </select>
          <button type="button" onClick={addMember} disabled={!addNodeId} className="btn-secondary px-3 text-xs">
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" disabled={!name || isSaving}
          onClick={() => onSave({ name, description: description || undefined, brand_id: brandId || undefined, is_active: isActive, members: members.map(m => ({ node_id: m.node_id, priority: m.priority })) })}>
          <Save className="w-4 h-4" /> {isSaving ? 'Saving…' : 'Save Group'}
        </button>
      </div>
    </div>
  )
}

// Missing Save import — add inline workaround
const Save = ({ className }: { className?: string }) => (
  <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
  </svg>
)

// ─── Distribution Groups Tab Content ──────────────────────────────────────────

function DistributionGroupsTab({
  dgs, brands, nodes, isLoading,
}: {
  dgs: DistributionGroup[]
  brands: Array<{ id: string; name: string }>
  nodes: Array<{ id: string; name: string; code: string; node_type: string }>
  isLoading: boolean
}) {
  const qc = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [editingDG, setEditingDG] = useState<DistributionGroup | null>(null)
  const [deletingDG, setDeletingDG] = useState<DistributionGroup | null>(null)
  const brandById = Object.fromEntries(brands.map(b => [b.id, b.name]))

  const invalidate = () => qc.invalidateQueries({ queryKey: ['distributionGroups'] })

  const createMutation = useMutation({
    mutationFn: (data: DistributionGroupPayload) => createDistributionGroup(data),
    onSuccess: () => { invalidate(); setShowCreate(false) },
  })

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: string; data: DistributionGroupPayload & { members?: Array<{ node_id: string; priority: number }> } }) => {
      const { members, ...rest } = data
      const updated = await updateDistributionGroup(id, rest)
      if (members !== undefined) {
        const current = editingDG?.members ?? []
        const currentNodeIds = new Set(current.map(m => m.node_id.toString()))
        const targetNodeIds = new Set(members.map(m => m.node_id))
        for (const m of current) {
          if (!targetNodeIds.has(m.node_id.toString())) await removeDGMember(id, m.node_id.toString())
        }
        for (const m of members) {
          const existing = current.find(c => c.node_id.toString() === m.node_id)
          if (!existing) await addDGMember(id, m)
          else if (existing.priority !== m.priority) await updateDGMemberPriority(id, m.node_id, m.priority)
        }
        void updated
      }
      return updated
    },
    onSuccess: () => { invalidate(); setEditingDG(null) },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteDistributionGroup(id),
    onSuccess: () => { invalidate(); setDeletingDG(null) },
  })

  const emptyDG: DistributionGroupPayload & { members: [] } = { name: '', description: '', is_active: true, brand_id: '', members: [] }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">
          Logical groups of fulfillment nodes with per-member priority. Reference DGs in sourcing rules to route orders to named node pools.
        </p>
        <button onClick={() => setShowCreate(true)} className="btn-primary flex-shrink-0">
          <Plus className="w-4 h-4" /> New Group
        </button>
      </div>

      <div className="bg-blue-50 border border-blue-100 rounded-xl p-3 text-xs text-blue-700 flex gap-2">
        <Info className="w-4 h-4 flex-shrink-0 mt-0.5" />
        <span>
          When a sourcing rule has DG targets, the engine expands each DG into its member nodes (ordered by priority) before scoring.
          Effective node priority = <code className="font-mono bg-blue-100 px-1 rounded">target_priority × 100 + member_priority</code>.
        </span>
      </div>

      {isLoading ? (
        <div className="card p-8 text-center text-gray-400 text-sm">Loading…</div>
      ) : dgs.length === 0 ? (
        <div className="card p-12 text-center">
          <Layers className="w-12 h-12 mx-auto mb-3 text-gray-300" />
          <p className="font-medium text-gray-500">No distribution groups yet</p>
          <p className="text-xs text-gray-400 mt-1 mb-5">Create a group to pool warehouses or stores by region or capability</p>
          <button onClick={() => setShowCreate(true)} className="btn-primary mx-auto"><Plus className="w-4 h-4" /> Create Group</button>
        </div>
      ) : (
        <div className="space-y-3">
          {dgs.map(dg => (
            <DGCard key={dg.id} dg={dg} brandName={dg.brand_id ? brandById[dg.brand_id] : undefined}
              onEdit={() => setEditingDG(dg)} onDelete={() => setDeletingDG(dg)} />
          ))}
        </div>
      )}

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Distribution Group" size="lg">
        <DGEditor initial={emptyDG} nodes={nodes} brands={brands} onSave={data => createMutation.mutate(data)} onClose={() => setShowCreate(false)} isSaving={createMutation.isPending} />
        {createMutation.isError && <p className="text-xs text-red-600 mt-2">Failed to create group.</p>}
      </Modal>

      {editingDG && (
        <Modal open={!!editingDG} onClose={() => setEditingDG(null)} title={`Edit: ${editingDG.name}`} size="lg">
          <DGEditor
            initial={{ ...editingDG, brand_id: editingDG.brand_id ?? '', members: editingDG.members.map(m => ({ id: m.id, node_id: m.node_id.toString(), priority: m.priority, node_name: m.node_name, node_code: m.node_code, node_type: m.node_type })) }}
            nodes={nodes} brands={brands}
            onSave={data => updateMutation.mutate({ id: editingDG.id, data })}
            onClose={() => setEditingDG(null)} isSaving={updateMutation.isPending}
          />
          {updateMutation.isError && <p className="text-xs text-red-600 mt-2">Failed to save changes.</p>}
        </Modal>
      )}

      <Modal open={!!deletingDG} onClose={() => setDeletingDG(null)} title="Delete Distribution Group" size="sm">
        <p className="text-sm text-gray-600">
          Delete <span className="font-semibold">{deletingDG?.name}</span>? Any sourcing rules referencing this group will need to be updated.
        </p>
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-secondary" onClick={() => setDeletingDG(null)}>Cancel</button>
          <button className="btn-danger" disabled={deleteMutation.isPending} onClick={() => deletingDG && deleteMutation.mutate(deletingDG.id)}>
            <Trash2 className="w-4 h-4" /> {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </Modal>
    </div>
  )
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function SourcingRules() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<'rules' | 'dgs'>('rules')
  const [showCreate, setShowCreate] = useState(false)
  const [editingRule, setEditingRule] = useState<SourcingRule | null>(null)
  const [deletingRule, setDeletingRule] = useState<SourcingRule | null>(null)
  const [form, setForm] = useState<SourcingRulePayload>(emptyPayload())
  const [brandFilter, setBrandFilter] = useState('')

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['sourcingRules', brandFilter],
    queryFn: () => fetchSourcingRules({ page: 1, page_size: 50, brand_id: brandFilter || undefined }),
  })

  const { data: brandsData = [] } = useQuery({
    queryKey: ['brands', 'active'],
    queryFn: () => getBrands({ is_active: true }),
  })

  const { data: metadata } = useQuery({
    queryKey: ['sourcingMetadata'],
    queryFn: fetchSourcingMetadata,
    staleTime: Infinity,
  })

  const { data: dgsData, isLoading: dgsLoading } = useQuery({
    queryKey: ['distributionGroups'],
    queryFn: () => fetchDistributionGroups({ page_size: 200 }),
  })

  const { data: nodesData } = useQuery({
    queryKey: ['nodes-for-sourcing'],
    queryFn: () => fetchNodes({ page_size: 200, status: 'ACTIVE' }),
    staleTime: 60_000,
  })

  const meta: Metadata = metadata ?? DEFAULT_META
  const dgs = dgsData?.items ?? []
  const nodes: Array<{ id: string; name: string; code: string; node_type: string }> = (nodesData?.items ?? []).map(n => ({ id: n.id, name: n.name, code: n.code, node_type: n.node_type }))
  const dgNames = Object.fromEntries(dgs.map(d => [d.id, d.name]))
  const brandById = Object.fromEntries(brandsData.map(b => [b.id, b.name]))

  const invalidate = () => qc.invalidateQueries({ queryKey: ['sourcingRules'] })

  const createMutation = useMutation({
    mutationFn: createSourcingRule,
    onSuccess: () => { invalidate(); setShowCreate(false) },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<SourcingRulePayload> }) => updateSourcingRule(id, payload),
    onSuccess: () => { invalidate(); setEditingRule(null) },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteSourcingRule(id),
    onSuccess: () => { invalidate(); setDeletingRule(null) },
  })

  const rules = [...(data?.items ?? [])].sort((a, b) => a.priority - b.priority)
  const activeCount = rules.filter(r => r.is_active).length
  const anyPending = createMutation.isPending || updateMutation.isPending || deleteMutation.isPending

  const openCreate = () => { setForm(emptyPayload()); setShowCreate(true) }

  const openEdit = (rule: SourcingRule) => {
    setForm({
      name: rule.name,
      description: rule.description ?? '',
      priority: rule.priority,
      is_active: rule.is_active,
      strategy: rule.strategy,
      conditions: rule.conditions ?? [],
      sourcing_targets: rule.sourcing_targets ?? [],
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
        <div className="flex items-center gap-2">
          {brandsData.length > 0 && (
            <select className="select max-w-44 text-xs" value={brandFilter} onChange={e => setBrandFilter(e.target.value)}>
              <option value="">All Brands</option>
              {brandsData.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          )}
          <button onClick={() => refetch()} className="btn-secondary"><RefreshCw className="w-4 h-4" /> Refresh</button>
          {tab === 'rules' && (
            <button onClick={openCreate} className="btn-primary"><Plus className="w-4 h-4" /> New Rule</button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-xl p-1 w-fit">
        {([
          { key: 'rules', label: `Rules (${rules.length})`, icon: <Zap className="w-3.5 h-3.5" /> },
          { key: 'dgs', label: `Distribution Groups (${dgs.length})`, icon: <Layers className="w-3.5 h-3.5" /> },
        ] as const).map(({ key, label, icon }) => (
          <button key={key} onClick={() => setTab(key)}
            className={`flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium transition-all ${tab === key ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
            {icon} {label}
          </button>
        ))}
      </div>

      {/* ── Rules Tab ── */}
      {tab === 'rules' && (
        <>
          <div className="card p-4">
            <div className="flex items-center gap-2 mb-3">
              <Zap className="w-4 h-4 text-amber-500" />
              <h2 className="text-xs font-semibold text-gray-600 uppercase tracking-wider">Strategies</h2>
            </div>
            <div className="flex flex-wrap gap-2">
              {meta.strategies.map(s => <StatusBadge key={s} value={s} />)}
            </div>
          </div>

          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="card p-5 animate-pulse">
                  <div className="flex gap-3"><div className="w-5 h-16 bg-gray-200 rounded" /><div className="flex-1 space-y-2"><div className="h-4 bg-gray-200 rounded w-48" /><div className="h-3 bg-gray-200 rounded w-64" /></div></div>
                </div>
              ))}
            </div>
          ) : rules.length === 0 ? (
            <div className="card p-12 text-center text-gray-400 text-sm">
              <Zap className="w-10 h-10 mx-auto mb-3 opacity-30" />
              <p className="font-medium text-gray-500">No sourcing rules configured</p>
              <p className="text-xs mt-1 mb-4">Create your first rule to control how orders are fulfilled</p>
              <button onClick={openCreate} className="btn-primary mx-auto"><Plus className="w-4 h-4" /> Create First Rule</button>
            </div>
          ) : (
            <div className="space-y-3">
              {rules.map(rule => (
                <RuleCard key={rule.id} rule={rule} brandName={rule.brand_id ? brandById[rule.brand_id] : undefined}
                  dgNames={dgNames}
                  onToggle={() => updateMutation.mutate({ id: rule.id, payload: { is_active: !rule.is_active } })}
                  onPriorityChange={dir => {
                    const p = dir === 'up' ? rule.priority - 1 : rule.priority + 1
                    if (p >= 1) updateMutation.mutate({ id: rule.id, payload: { priority: p } })
                  }}
                  onEdit={() => openEdit(rule)}
                  onDelete={() => setDeletingRule(rule)}
                  isPending={anyPending}
                />
              ))}
            </div>
          )}

          <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 text-xs text-blue-700 space-y-1">
            <p className="font-semibold">How sourcing rules work</p>
            <p>Rules are evaluated top-down by priority. The first matching active rule determines the sourcing strategy. Use Distribution Groups to define reusable node pools that can be referenced across multiple rules.</p>
          </div>
        </>
      )}

      {/* ── Distribution Groups Tab ── */}
      {tab === 'dgs' && (
        <DistributionGroupsTab dgs={dgs} brands={brandsData} nodes={nodes} isLoading={dgsLoading} />
      )}

      {/* ── Create Rule Modal ── */}
      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Sourcing Rule" size="xl">
        <RuleForm value={form} onChange={setForm} metadata={meta} dgs={dgs} nodes={nodes} />
        {createMutation.isError && <p className="text-xs text-red-600 mt-3">Failed to create rule. Check all required fields.</p>}
        <div className="flex justify-end gap-2 mt-6">
          <button className="btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button>
          <button className="btn-primary" disabled={!form.name || createMutation.isPending} onClick={() => createMutation.mutate(form)}>
            {createMutation.isPending ? 'Creating…' : <><Check className="w-4 h-4" /> Create Rule</>}
          </button>
        </div>
      </Modal>

      {/* ── Edit Rule Modal ── */}
      <Modal open={!!editingRule} onClose={() => setEditingRule(null)} title={`Edit Rule: ${editingRule?.name}`} size="xl">
        <RuleForm value={form} onChange={setForm} metadata={meta} dgs={dgs} nodes={nodes} />
        {updateMutation.isError && <p className="text-xs text-red-600 mt-3">Failed to save changes.</p>}
        <div className="flex justify-end gap-2 mt-6">
          <button className="btn-secondary" onClick={() => setEditingRule(null)}>Cancel</button>
          <button className="btn-primary" disabled={!form.name || updateMutation.isPending}
            onClick={() => editingRule && updateMutation.mutate({ id: editingRule.id, payload: form })}>
            {updateMutation.isPending ? 'Saving…' : <><Check className="w-4 h-4" /> Save Changes</>}
          </button>
        </div>
      </Modal>

      {/* ── Delete Rule Modal ── */}
      <Modal open={!!deletingRule} onClose={() => setDeletingRule(null)} title="Delete Rule" size="sm">
        <p className="text-sm text-gray-600">Delete <span className="font-semibold">{deletingRule?.name}</span>? This cannot be undone.</p>
        {deleteMutation.isError && <p className="text-xs text-red-600 mt-2">Failed to delete rule.</p>}
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-secondary" onClick={() => setDeletingRule(null)}>Cancel</button>
          <button className="btn-danger" disabled={deleteMutation.isPending} onClick={() => deletingRule && deleteMutation.mutate(deletingRule.id)}>
            {deleteMutation.isPending ? 'Deleting…' : <><Trash2 className="w-4 h-4" /> Delete Rule</>}
          </button>
        </div>
      </Modal>
    </div>
  )
}
