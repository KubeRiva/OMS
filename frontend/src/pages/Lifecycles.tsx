import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  GitBranch, Plus, Trash2, Save, RotateCcw, ChevronRight,
  Check, X, Info, Download, Upload,
} from 'lucide-react'
import type { OrderStatus } from '../api/client'
import type { Lifecycle, LifecyclePayload } from '../api/client'
import { fetchLifecycles, createLifecycle, updateLifecycle, deleteLifecycle } from '../api/client'
import Modal from '../components/Modal'

// ─── Local Form Types ─────────────────────────────────────────────────────────

interface FormStep {
  status: OrderStatus
  label: string
  description: string
  color: string
  allowedNextStatuses: OrderStatus[]
  actionType?: string | null
  slaHours?: number | null
}

interface LifecycleForm {
  name: string
  description: string
  fulfillmentTypes: string[]
  channels: string[]
  steps: FormStep[]
}

// ─── Constants ─────────────────────────────────────────────────────────────────

const ALL_STATUSES: OrderStatus[] = [
  'PENDING', 'CONFIRMED', 'SOURCING', 'BACKORDERED', 'SOURCED',
  'PICKING', 'PACKING', 'READY_TO_SHIP', 'SHIPPED', 'PARTIALLY_SHIPPED',
  'OUT_FOR_DELIVERY', 'PARTIALLY_DELIVERED', 'DELIVERED', 'READY_FOR_PICKUP',
  'PICKED_UP', 'RETURNED', 'REFUNDED', 'CANCELLED', 'FAILED',
]

const STATUS_COLORS: Record<string, string> = {
  PENDING:             'bg-gray-100 text-gray-700 border-gray-300',
  CONFIRMED:           'bg-blue-100 text-blue-700 border-blue-300',
  SOURCING:            'bg-indigo-100 text-indigo-700 border-indigo-300',
  BACKORDERED:         'bg-amber-100 text-amber-700 border-amber-300',
  SOURCED:             'bg-violet-100 text-violet-700 border-violet-300',
  PICKING:             'bg-amber-100 text-amber-700 border-amber-300',
  PACKING:             'bg-orange-100 text-orange-700 border-orange-300',
  READY_TO_SHIP:       'bg-yellow-100 text-yellow-700 border-yellow-300',
  SHIPPED:             'bg-sky-100 text-sky-700 border-sky-300',
  PARTIALLY_SHIPPED:   'bg-sky-100 text-sky-700 border-sky-300',
  OUT_FOR_DELIVERY:    'bg-cyan-100 text-cyan-700 border-cyan-300',
  PARTIALLY_DELIVERED: 'bg-cyan-100 text-cyan-700 border-cyan-300',
  DELIVERED:           'bg-green-100 text-green-700 border-green-300',
  READY_FOR_PICKUP:    'bg-teal-100 text-teal-700 border-teal-300',
  PICKED_UP:           'bg-emerald-100 text-emerald-700 border-emerald-300',
  RETURNED:            'bg-amber-100 text-amber-700 border-amber-300',
  REFUNDED:            'bg-purple-100 text-purple-700 border-purple-300',
  CANCELLED:           'bg-red-100 text-red-700 border-red-300',
  FAILED:              'bg-rose-100 text-rose-700 border-rose-300',
}

const DEFAULT_LABELS: Record<string, string> = {
  PENDING:             'Pending',
  CONFIRMED:           'Confirmed',
  SOURCING:            'Sourcing',
  BACKORDERED:         'Backordered',
  SOURCED:             'Sourced',
  PICKING:             'Picking',
  PACKING:             'Packing',
  READY_TO_SHIP:       'Ready to Ship',
  SHIPPED:             'Shipped',
  PARTIALLY_SHIPPED:   'Partially Shipped',
  OUT_FOR_DELIVERY:    'Out for Delivery',
  PARTIALLY_DELIVERED: 'Partially Delivered',
  DELIVERED:           'Delivered',
  READY_FOR_PICKUP:    'Ready for Pickup',
  PICKED_UP:           'Picked Up',
  RETURNED:            'Returned',
  REFUNDED:            'Refunded',
  CANCELLED:           'Cancelled',
  FAILED:              'Failed',
}

const FULFILLMENT_TYPES = [
  'SHIP_TO_HOME', 'STORE_PICKUP', 'SHIP_FROM_STORE', 'CURBSIDE_PICKUP', 'SAME_DAY_DELIVERY',
]
const CHANNELS = ['WEB', 'MOBILE', 'POS', 'API', 'MARKETPLACE']

// Built-in templates (camelCase form format)
interface TemplateStep {
  status: OrderStatus
  label: string
  description: string
  color: string
  allowedNextStatuses: OrderStatus[]
}
interface LifecycleTemplate {
  name: string
  description: string
  fulfillmentTypes: string[]
  channels: string[]
  steps: TemplateStep[]
}

const TEMPLATES: LifecycleTemplate[] = [
  {
    name: 'Standard Ship-to-Home',
    description: 'Full forward-logistics flow for home delivery orders',
    fulfillmentTypes: ['SHIP_TO_HOME'],
    channels: [],
    steps: [
      { status: 'PENDING',          label: 'Pending',          description: 'Order received, awaiting confirmation', color: '', allowedNextStatuses: ['CONFIRMED', 'CANCELLED'] },
      { status: 'CONFIRMED',        label: 'Confirmed',        description: 'Payment verified and order accepted',   color: '', allowedNextStatuses: ['SOURCING', 'CANCELLED'] },
      { status: 'SOURCING',         label: 'Sourcing',         description: 'DOM engine finding optimal node',       color: '', allowedNextStatuses: ['SOURCED', 'FAILED'] },
      { status: 'SOURCED',          label: 'Sourced',          description: 'Fulfillment node assigned',             color: '', allowedNextStatuses: ['PICKING', 'CANCELLED'] },
      { status: 'PICKING',          label: 'Picking',          description: 'Items being picked at node',            color: '', allowedNextStatuses: ['PACKING'] },
      { status: 'PACKING',          label: 'Packing',          description: 'Items packed for shipment',             color: '', allowedNextStatuses: ['READY_TO_SHIP'] },
      { status: 'READY_TO_SHIP',    label: 'Ready to Ship',    description: 'Awaiting carrier pickup',               color: '', allowedNextStatuses: ['SHIPPED'] },
      { status: 'SHIPPED',          label: 'Shipped',          description: 'In transit with carrier',               color: '', allowedNextStatuses: ['OUT_FOR_DELIVERY'] },
      { status: 'OUT_FOR_DELIVERY', label: 'Out for Delivery', description: 'Last-mile delivery in progress',        color: '', allowedNextStatuses: ['DELIVERED', 'FAILED'] },
      { status: 'DELIVERED',        label: 'Delivered',        description: 'Successfully delivered to customer',    color: '', allowedNextStatuses: ['RETURNED'] },
    ],
  },
  {
    name: 'Buy Online Pickup In Store (BOPIS)',
    description: 'Store pickup lifecycle for click-and-collect orders',
    fulfillmentTypes: ['STORE_PICKUP', 'CURBSIDE_PICKUP'],
    channels: ['WEB', 'MOBILE'],
    steps: [
      { status: 'PENDING',          label: 'Pending',          description: 'Order received',                              color: '', allowedNextStatuses: ['CONFIRMED', 'CANCELLED'] },
      { status: 'CONFIRMED',        label: 'Confirmed',        description: 'Payment verified',                            color: '', allowedNextStatuses: ['SOURCING'] },
      { status: 'SOURCING',         label: 'Sourcing',         description: 'Routing to nearest store',                    color: '', allowedNextStatuses: ['SOURCED', 'FAILED'] },
      { status: 'SOURCED',          label: 'Store Assigned',   description: 'Store confirmed inventory availability',       color: '', allowedNextStatuses: ['PICKING'] },
      { status: 'PICKING',          label: 'Picking',          description: 'Store associate picking items',                color: '', allowedNextStatuses: ['PACKING'] },
      { status: 'PACKING',          label: 'Staging',          description: 'Items staged for customer pickup',             color: '', allowedNextStatuses: ['READY_FOR_PICKUP'] },
      { status: 'READY_FOR_PICKUP', label: 'Ready for Pickup', description: 'Customer notified, awaiting pickup',           color: '', allowedNextStatuses: ['PICKED_UP', 'CANCELLED'] },
      { status: 'PICKED_UP',        label: 'Picked Up',        description: 'Customer collected order',                     color: '', allowedNextStatuses: ['RETURNED'] },
    ],
  },
  {
    name: 'Return & Refund',
    description: 'Reverse logistics flow after delivery',
    fulfillmentTypes: [],
    channels: [],
    steps: [
      { status: 'RETURNED', label: 'Return Initiated', description: 'Return request approved, awaiting item receipt', color: '', allowedNextStatuses: ['REFUNDED'] },
      { status: 'REFUNDED', label: 'Refunded',         description: 'Refund issued to original payment method',        color: '', allowedNextStatuses: [] },
    ],
  },
]

// ─── Converters ───────────────────────────────────────────────────────────────

function apiToForm(lc: Lifecycle): LifecycleForm {
  return {
    name: lc.name,
    description: lc.description ?? '',
    fulfillmentTypes: lc.fulfillment_types ?? [],
    channels: lc.channels ?? [],
    steps: [...lc.steps]
      .sort((a, b) => a.step_order - b.step_order)
      .map(s => ({
        status: s.status as OrderStatus,
        label: s.label,
        description: s.description ?? '',
        color: '',
        allowedNextStatuses: (s.allowed_next_statuses ?? []) as OrderStatus[],
        actionType: s.action_type ?? null,
        slaHours: s.sla_hours ?? null,
      })),
  }
}

function formToPayload(form: LifecycleForm): LifecyclePayload {
  return {
    name: form.name,
    description: form.description,
    fulfillment_types: form.fulfillmentTypes,
    channels: form.channels,
    steps: form.steps.map((s, i) => ({
      status: s.status,
      label: s.label,
      description: s.description,
      step_order: i + 1,
      allowed_next_statuses: s.allowedNextStatuses,
      action_type: s.actionType ?? null,
      sla_hours: s.slaHours ?? null,
    })),
  }
}

function templateToPayload(tpl: LifecycleTemplate): LifecyclePayload {
  return {
    name: tpl.name,
    description: tpl.description,
    fulfillment_types: tpl.fulfillmentTypes,
    channels: tpl.channels,
    steps: tpl.steps.map((s, i) => ({
      status: s.status,
      label: s.label,
      description: s.description,
      step_order: i + 1,
      allowed_next_statuses: s.allowedNextStatuses,
      action_type: null,
      sla_hours: null,
    })),
  }
}

// ─── Step Editor ───────────────────────────────────────────────────────────────

function StepEditor({
  step,
  allStatuses,
  onUpdate,
  onRemove,
}: {
  step: FormStep
  allStatuses: OrderStatus[]
  onUpdate: (s: FormStep) => void
  onRemove: () => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border border-gray-100 rounded-xl p-3 bg-white">
      <div className="flex items-center gap-2">
        <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border flex-shrink-0 ${STATUS_COLORS[step.status] ?? 'bg-gray-100 text-gray-700 border-gray-300'}`}>
          {step.label || step.status}
        </span>
        <button type="button" onClick={() => setOpen(o => !o)} className="text-[10px] text-gray-400 hover:text-blue-500 ml-auto">
          {open ? 'collapse' : 'configure'}
        </button>
        <button type="button" onClick={onRemove} className="text-gray-300 hover:text-red-500">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {open && (
        <div className="mt-3 space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="label text-[10px]">Label</label>
              <input className="input text-xs" value={step.label} onChange={e => onUpdate({ ...step, label: e.target.value })} />
            </div>
            <div>
              <label className="label text-[10px]">Description</label>
              <input className="input text-xs" value={step.description} onChange={e => onUpdate({ ...step, description: e.target.value })} />
            </div>
          </div>
          <div>
            <label className="label text-[10px]">Allowed Next Statuses</label>
            <div className="flex flex-wrap gap-1.5">
              {allStatuses.filter(s => s !== step.status).map(s => (
                <label key={s} className="flex items-center gap-1 text-[10px] cursor-pointer">
                  <input
                    type="checkbox"
                    checked={step.allowedNextStatuses.includes(s)}
                    onChange={() => {
                      const curr = step.allowedNextStatuses
                      onUpdate({ ...step, allowedNextStatuses: curr.includes(s) ? curr.filter(x => x !== s) : [...curr, s] })
                    }}
                    className="rounded border-gray-300"
                  />
                  <span className={`px-1.5 py-0.5 rounded-full border ${STATUS_COLORS[s] ?? 'bg-gray-100 text-gray-700 border-gray-300'}`}>
                    {DEFAULT_LABELS[s] ?? s}
                  </span>
                </label>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Lifecycle Card ────────────────────────────────────────────────────────────

function LifecycleCard({
  lifecycle,
  onEdit,
  onDelete,
  onDuplicate,
}: {
  lifecycle: Lifecycle
  onEdit: () => void
  onDelete: () => void
  onDuplicate: () => void
}) {
  const steps = [...lifecycle.steps].sort((a, b) => a.step_order - b.step_order)
  return (
    <div className="card p-5 hover:shadow-md transition-all">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <GitBranch className="w-4 h-4 text-blue-500 flex-shrink-0" />
            <h3 className="font-semibold text-gray-900 text-sm">{lifecycle.name}</h3>
            {lifecycle.is_default && (
              <span className="px-1.5 py-0.5 bg-green-50 text-green-700 border border-green-200 rounded text-[10px] font-medium">default</span>
            )}
            {!lifecycle.is_active && (
              <span className="px-1.5 py-0.5 bg-gray-100 text-gray-500 border border-gray-200 rounded text-[10px] font-medium">inactive</span>
            )}
          </div>
          <p className="text-xs text-gray-500 mb-3">{lifecycle.description || 'No description'}</p>

          {/* Step flow visualization */}
          <div className="flex items-center gap-1 flex-wrap mb-3">
            {steps.map((step, i) => (
              <div key={step.status} className="flex items-center gap-1">
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${STATUS_COLORS[step.status] ?? 'bg-gray-100 text-gray-700 border-gray-300'}`}>
                  {step.label}
                </span>
                {i < steps.length - 1 && (
                  <ChevronRight className="w-3 h-3 text-gray-300 flex-shrink-0" />
                )}
              </div>
            ))}
          </div>

          {/* Tags */}
          <div className="flex flex-wrap gap-1.5">
            {lifecycle.fulfillment_types.map(ft => (
              <span key={ft} className="px-1.5 py-0.5 bg-blue-50 text-blue-700 rounded text-[10px] font-medium">
                {ft.replace(/_/g, ' ')}
              </span>
            ))}
            {lifecycle.channels.map(ch => (
              <span key={ch} className="px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded text-[10px] font-medium">
                {ch}
              </span>
            ))}
            <span className="text-[10px] text-gray-400 ml-auto">
              {steps.length} steps
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-1 flex-shrink-0">
          <button
            onClick={onEdit}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-blue-600 transition-colors"
            title="Edit"
          >
            <GitBranch className="w-4 h-4" />
          </button>
          <button
            onClick={onDuplicate}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-green-600 transition-colors"
            title="Duplicate"
          >
            <Download className="w-4 h-4" />
          </button>
          <button
            onClick={onDelete}
            className="p-1.5 rounded-lg hover:bg-red-50 text-gray-400 hover:text-red-600 transition-colors"
            title="Delete"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Lifecycle Editor Modal ────────────────────────────────────────────────────

function LifecycleEditor({
  initial,
  onSave,
  onClose,
  isSaving,
}: {
  initial: LifecycleForm
  onSave: (form: LifecycleForm) => void
  onClose: () => void
  isSaving?: boolean
}) {
  const [form, setForm] = useState<LifecycleForm>(initial)

  const setField = <K extends keyof LifecycleForm>(k: K, v: LifecycleForm[K]) =>
    setForm(f => ({ ...f, [k]: v }))

  const toggleArr = (arr: string[], item: string) =>
    arr.includes(item) ? arr.filter(x => x !== item) : [...arr, item]

  const addStep = (status: OrderStatus) => {
    if (form.steps.some(s => s.status === status)) return
    setForm(f => ({
      ...f,
      steps: [...f.steps, {
        status,
        label: DEFAULT_LABELS[status] ?? status,
        description: '',
        color: '',
        allowedNextStatuses: [],
      }],
    }))
  }

  const updateStep = (i: number, step: FormStep) =>
    setForm(f => ({ ...f, steps: f.steps.map((s, idx) => idx === i ? step : s) }))

  const removeStep = (i: number) =>
    setForm(f => ({ ...f, steps: f.steps.filter((_, idx) => idx !== i) }))

  const moveStep = (i: number, dir: 'up' | 'down') => {
    const steps = [...form.steps]
    const j = dir === 'up' ? i - 1 : i + 1
    if (j < 0 || j >= steps.length) return
    ;[steps[i], steps[j]] = [steps[j], steps[i]]
    setForm(f => ({ ...f, steps }))
  }

  const unusedStatuses = ALL_STATUSES.filter(s => !form.steps.some(st => st.status === s))

  return (
    <div className="space-y-4 text-sm">
      {/* Basic info */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Lifecycle Name *</label>
          <input className="input" value={form.name} onChange={e => setField('name', e.target.value)} placeholder="e.g. Standard Ship-to-Home" />
        </div>
        <div>
          <label className="label">Description</label>
          <input className="input" value={form.description} onChange={e => setField('description', e.target.value)} placeholder="Brief description" />
        </div>
      </div>

      {/* Fulfillment types */}
      <div>
        <label className="label">Applies to Fulfillment Types <span className="text-gray-400">(empty = all)</span></label>
        <div className="flex flex-wrap gap-2">
          {FULFILLMENT_TYPES.map(ft => (
            <label key={ft} className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input
                type="checkbox"
                checked={form.fulfillmentTypes.includes(ft)}
                onChange={() => setField('fulfillmentTypes', toggleArr(form.fulfillmentTypes, ft))}
                className="rounded border-gray-300"
              />
              {ft.replace(/_/g, ' ')}
            </label>
          ))}
        </div>
      </div>

      {/* Channels */}
      <div>
        <label className="label">Applies to Channels <span className="text-gray-400">(empty = all)</span></label>
        <div className="flex gap-3 flex-wrap">
          {CHANNELS.map(ch => (
            <label key={ch} className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input
                type="checkbox"
                checked={form.channels.includes(ch)}
                onChange={() => setField('channels', toggleArr(form.channels, ch))}
                className="rounded border-gray-300"
              />
              {ch}
            </label>
          ))}
        </div>
      </div>

      {/* Steps */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="label mb-0">Lifecycle Steps <span className="text-gray-400">({form.steps.length} configured)</span></label>
        </div>

        {form.steps.length === 0 && (
          <p className="text-xs text-gray-400 py-3 text-center border border-dashed border-gray-200 rounded-xl">
            No steps yet — add statuses below
          </p>
        )}

        <div className="space-y-2 mb-3">
          {form.steps.map((step, i) => (
            <div key={step.status} className="flex gap-2">
              <div className="flex flex-col gap-0.5 flex-shrink-0">
                <button
                  type="button"
                  onClick={() => moveStep(i, 'up')}
                  disabled={i === 0}
                  className="text-gray-300 hover:text-gray-500 disabled:opacity-30 text-xs px-1"
                >▲</button>
                <button
                  type="button"
                  onClick={() => moveStep(i, 'down')}
                  disabled={i === form.steps.length - 1}
                  className="text-gray-300 hover:text-gray-500 disabled:opacity-30 text-xs px-1"
                >▼</button>
              </div>
              <div className="flex-1">
                <StepEditor
                  step={step}
                  allStatuses={ALL_STATUSES}
                  onUpdate={s => updateStep(i, s)}
                  onRemove={() => removeStep(i)}
                />
              </div>
            </div>
          ))}
        </div>

        {unusedStatuses.length > 0 && (
          <div>
            <p className="text-[11px] text-gray-400 mb-1.5">Add status to lifecycle:</p>
            <div className="flex flex-wrap gap-1.5">
              {unusedStatuses.map(s => (
                <button
                  key={s}
                  type="button"
                  onClick={() => addStep(s)}
                  className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border cursor-pointer hover:opacity-80 transition-opacity flex items-center gap-1 ${STATUS_COLORS[s] ?? 'bg-gray-100 text-gray-700 border-gray-300'}`}
                >
                  <Plus className="w-2.5 h-2.5" />
                  {DEFAULT_LABELS[s] ?? s}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button
          className="btn-primary"
          disabled={!form.name || form.steps.length === 0 || isSaving}
          onClick={() => onSave(form)}
        >
          <Save className="w-4 h-4" /> {isSaving ? 'Saving…' : 'Save Lifecycle'}
        </button>
      </div>
    </div>
  )
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function Lifecycles() {
  const queryClient = useQueryClient()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [showTemplates, setShowTemplates] = useState(false)
  const [showCreate, setShowCreate] = useState(false)

  const { data: lifecycles = [], isLoading, error } = useQuery({
    queryKey: ['lifecycles'],
    queryFn: () => fetchLifecycles({ active_only: false }),
  })

  const onSuccess = (queryKey: string, closeAction: () => void) => () => {
    queryClient.invalidateQueries({ queryKey: [queryKey] })
    closeAction()
  }

  const createMutation = useMutation({
    mutationFn: createLifecycle,
    onSuccess: onSuccess('lifecycles', () => setShowCreate(false)),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: LifecyclePayload }) =>
      updateLifecycle(id, data),
    onSuccess: onSuccess('lifecycles', () => setEditingId(null)),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteLifecycle,
    onSuccess: onSuccess('lifecycles', () => setDeletingId(null)),
  })

  const handleSave = (form: LifecycleForm, id?: string) => {
    const payload = formToPayload(form)
    if (id) {
      updateMutation.mutate({ id, data: payload })
    } else {
      createMutation.mutate(payload)
    }
  }

  const handleDuplicate = (lc: Lifecycle) => {
    const form = apiToForm(lc)
    const payload = formToPayload({ ...form, name: `${form.name} (Copy)` })
    createMutation.mutate(payload)
  }

  const editingLifecycle = editingId ? lifecycles.find(x => x.id === editingId) : null
  const isMutating = createMutation.isPending || updateMutation.isPending

  const emptyForm: LifecycleForm = { name: '', description: '', fulfillmentTypes: [], channels: [], steps: [] }

  return (
    <div className="p-6 space-y-5 max-w-5xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Lifecycle Configurator</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Define custom order lifecycle flows — specify which statuses are active and what transitions are valid
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setShowTemplates(true)} className="btn-secondary">
            <Upload className="w-4 h-4" /> Templates
          </button>
          <button onClick={() => setShowCreate(true)} className="btn-primary">
            <Plus className="w-4 h-4" /> New Lifecycle
          </button>
        </div>
      </div>

      {/* Info box */}
      <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 text-xs text-blue-700 flex gap-3">
        <Info className="w-4 h-4 flex-shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p className="font-semibold">About lifecycle configuration</p>
          <p>Lifecycles define the valid statuses and allowed transitions for different order flows. Each lifecycle can be scoped to specific fulfillment types and channels. The KubeRiva engine validates transitions against these rules when the UI sends status updates. Configurations are stored server-side and applied in real time.</p>
        </div>
      </div>

      {/* Status Reference */}
      <div className="card p-4">
        <h2 className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-3">All Available Statuses</h2>
        <div className="flex flex-wrap gap-1.5">
          {ALL_STATUSES.map(s => (
            <span key={s} className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${STATUS_COLORS[s] ?? 'bg-gray-100 text-gray-700 border-gray-300'}`}>
              {DEFAULT_LABELS[s] ?? s}
            </span>
          ))}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-100 rounded-xl p-4 text-xs text-red-700">
          Failed to load lifecycles. Please refresh.
        </div>
      )}

      {/* Mutation error */}
      {(createMutation.error || updateMutation.error || deleteMutation.error) && (
        <div className="bg-red-50 border border-red-100 rounded-xl p-4 text-xs text-red-700">
          {String((createMutation.error as Error || updateMutation.error as Error || deleteMutation.error as Error)?.message ?? 'Operation failed')}
        </div>
      )}

      {/* Lifecycle List */}
      {isLoading ? (
        <div className="card p-12 text-center text-sm text-gray-400">Loading lifecycles…</div>
      ) : lifecycles.length === 0 ? (
        <div className="card p-12 text-center">
          <GitBranch className="w-12 h-12 mx-auto mb-3 text-gray-300" />
          <p className="font-medium text-gray-500">No lifecycle configurations yet</p>
          <p className="text-xs text-gray-400 mt-1 mb-5">Start from a template or create a custom lifecycle from scratch</p>
          <div className="flex gap-3 justify-center">
            <button onClick={() => setShowTemplates(true)} className="btn-secondary">
              <Upload className="w-4 h-4" /> Load Template
            </button>
            <button onClick={() => setShowCreate(true)} className="btn-primary">
              <Plus className="w-4 h-4" /> Create Custom
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {lifecycles.map(lc => (
            <LifecycleCard
              key={lc.id}
              lifecycle={lc}
              onEdit={() => setEditingId(lc.id)}
              onDelete={() => setDeletingId(lc.id)}
              onDuplicate={() => handleDuplicate(lc)}
            />
          ))}
        </div>
      )}

      {/* ── Template Picker Modal ── */}
      <Modal open={showTemplates} onClose={() => setShowTemplates(false)} title="Load from Template" size="lg">
        <div className="space-y-3">
          {TEMPLATES.map((tpl, i) => (
            <div key={i} className="border border-gray-100 rounded-xl p-4 hover:border-blue-200 hover:bg-blue-50/30 transition-all">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-semibold text-sm text-gray-900">{tpl.name}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{tpl.description}</p>
                  <div className="flex flex-wrap gap-1 mt-2">
                    {tpl.steps.map((s, j) => (
                      <div key={s.status} className="flex items-center gap-0.5">
                        <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-semibold border ${STATUS_COLORS[s.status] ?? 'bg-gray-100 text-gray-700 border-gray-300'}`}>
                          {s.label}
                        </span>
                        {j < tpl.steps.length - 1 && <ChevronRight className="w-2.5 h-2.5 text-gray-300" />}
                      </div>
                    ))}
                  </div>
                </div>
                <button
                  className="btn-primary flex-shrink-0 text-xs"
                  disabled={createMutation.isPending}
                  onClick={() => { createMutation.mutate(templateToPayload(tpl)); setShowTemplates(false) }}
                >
                  <Check className="w-3.5 h-3.5" /> Use
                </button>
              </div>
            </div>
          ))}
        </div>
        <div className="flex justify-end mt-4">
          <button className="btn-secondary" onClick={() => setShowTemplates(false)}>Close</button>
        </div>
      </Modal>

      {/* ── Create Modal ── */}
      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Lifecycle" size="xl">
        <LifecycleEditor
          initial={emptyForm}
          onSave={form => handleSave(form)}
          onClose={() => setShowCreate(false)}
          isSaving={createMutation.isPending}
        />
      </Modal>

      {/* ── Edit Modal ── */}
      {editingLifecycle && (
        <Modal open={!!editingId} onClose={() => setEditingId(null)} title={`Edit: ${editingLifecycle.name}`} size="xl">
          <LifecycleEditor
            initial={apiToForm(editingLifecycle)}
            onSave={form => handleSave(form, editingLifecycle.id)}
            onClose={() => setEditingId(null)}
            isSaving={updateMutation.isPending}
          />
        </Modal>
      )}

      {/* ── Delete Confirmation ── */}
      <Modal open={!!deletingId} onClose={() => setDeletingId(null)} title="Delete Lifecycle" size="sm">
        <p className="text-sm text-gray-600">
          Are you sure you want to delete{' '}
          <span className="font-semibold">{lifecycles.find(x => x.id === deletingId)?.name}</span>?
          This cannot be undone.
        </p>
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-secondary" onClick={() => setDeletingId(null)}>Cancel</button>
          <button
            className="btn-danger"
            disabled={deleteMutation.isPending}
            onClick={() => deletingId && deleteMutation.mutate(deletingId)}
          >
            <Trash2 className="w-4 h-4" /> {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </Modal>

      {/* Reset all */}
      {lifecycles.length > 0 && (
        <p className="text-[10px] text-gray-400 flex items-center gap-1">
          <RotateCcw className="w-3 h-3" />
          Lifecycles are now server-side. Use the delete button on each card to remove them.
        </p>
      )}
    </div>
  )
}
