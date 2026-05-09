import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  GitBranch, Plus, Trash2, Save, RotateCcw, ChevronRight,
  Check, X, Info, Download, Upload, RotateCw, Tag,
} from 'lucide-react'
import type { OrderStatus, PipelineType, CustomStatusDef } from '../api/client'
import type { Lifecycle, LifecyclePayload } from '../api/client'
import {
  fetchLifecycles, createLifecycle, updateLifecycle, deleteLifecycle, getBrands,
} from '../api/client'
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
  pipelineType: PipelineType
  orderType: string
  brandId: string
  customStatuses: CustomStatusDef[]
  steps: FormStep[]
}

// ─── Constants ─────────────────────────────────────────────────────────────────

const ORDER_STATUSES: OrderStatus[] = [
  'PENDING', 'CONFIRMED', 'SOURCING', 'BACKORDERED', 'SOURCED',
  'PICKING', 'PACKING', 'READY_TO_SHIP', 'SHIPPED', 'PARTIALLY_SHIPPED',
  'OUT_FOR_DELIVERY', 'PARTIALLY_DELIVERED', 'DELIVERED', 'READY_FOR_PICKUP',
  'PICKED_UP', 'RETURNED', 'REFUNDED', 'CANCELLED', 'FAILED',
]

const RETURN_STATUSES: OrderStatus[] = [
  'PENDING', 'CONFIRMED', 'RETURNED', 'REFUNDED', 'CANCELLED',
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
const CHANNELS = ['WEB', 'MOBILE', 'POS', 'API', 'MARKETPLACE', 'B2B', 'EDI']

const ORDER_TYPES = [
  { value: '', label: 'Any (all order types)' },
  { value: 'RETAIL',    label: 'Retail / B2C' },
  { value: 'B2B',       label: 'B2B' },
  { value: 'WHOLESALE', label: 'Wholesale' },
]

const PIPELINE_TYPE_LABELS: Record<PipelineType, string> = {
  ORDER: 'Order',
  RETURN: 'Return / RMA',
}

// ─── Templates ────────────────────────────────────────────────────────────────

interface TemplateStep {
  status: OrderStatus
  label: string
  description: string
  allowedNextStatuses: OrderStatus[]
}
interface LifecycleTemplate {
  name: string
  description: string
  pipeline_type: PipelineType
  order_type?: string
  fulfillmentTypes: string[]
  channels: string[]
  steps: TemplateStep[]
}

const TEMPLATES: LifecycleTemplate[] = [
  {
    name: 'Standard Ship-to-Home (B2C)',
    description: 'Full forward-logistics flow for home delivery — retail & B2C',
    pipeline_type: 'ORDER',
    order_type: 'RETAIL',
    fulfillmentTypes: ['SHIP_TO_HOME'],
    channels: ['WEB', 'MOBILE'],
    steps: [
      { status: 'PENDING',          label: 'Pending',          description: 'Order received, awaiting confirmation', allowedNextStatuses: ['CONFIRMED', 'CANCELLED'] },
      { status: 'CONFIRMED',        label: 'Confirmed',        description: 'Payment verified and order accepted',   allowedNextStatuses: ['SOURCING', 'CANCELLED'] },
      { status: 'SOURCING',         label: 'Sourcing',         description: 'DOM engine finding optimal node',       allowedNextStatuses: ['SOURCED', 'FAILED'] },
      { status: 'SOURCED',          label: 'Sourced',          description: 'Fulfillment node assigned',             allowedNextStatuses: ['PICKING', 'CANCELLED'] },
      { status: 'PICKING',          label: 'Picking',          description: 'Items being picked at node',            allowedNextStatuses: ['PACKING'] },
      { status: 'PACKING',          label: 'Packing',          description: 'Items packed for shipment',             allowedNextStatuses: ['READY_TO_SHIP'] },
      { status: 'READY_TO_SHIP',    label: 'Ready to Ship',    description: 'Awaiting carrier pickup',               allowedNextStatuses: ['SHIPPED'] },
      { status: 'SHIPPED',          label: 'Shipped',          description: 'In transit with carrier',               allowedNextStatuses: ['OUT_FOR_DELIVERY'] },
      { status: 'OUT_FOR_DELIVERY', label: 'Out for Delivery', description: 'Last-mile delivery in progress',        allowedNextStatuses: ['DELIVERED', 'FAILED'] },
      { status: 'DELIVERED',        label: 'Delivered',        description: 'Successfully delivered to customer',    allowedNextStatuses: ['RETURNED'] },
    ],
  },
  {
    name: 'B2B Standard Order',
    description: 'Wholesale/B2B order flow with approval and net-terms handling',
    pipeline_type: 'ORDER',
    order_type: 'B2B',
    fulfillmentTypes: ['SHIP_TO_HOME'],
    channels: ['B2B', 'EDI', 'API'],
    steps: [
      { status: 'PENDING',       label: 'PO Received',      description: 'B2B PO received, awaiting credit check',  allowedNextStatuses: ['CONFIRMED', 'CANCELLED'] },
      { status: 'CONFIRMED',     label: 'Approved',         description: 'Credit and terms verified',               allowedNextStatuses: ['SOURCING', 'BACKORDERED', 'CANCELLED'] },
      { status: 'BACKORDERED',   label: 'Backordered',      description: 'Inventory insufficient, pending restock',  allowedNextStatuses: ['SOURCING', 'CANCELLED'] },
      { status: 'SOURCING',      label: 'Sourcing',         description: 'DOM routing to B2B warehouse',             allowedNextStatuses: ['SOURCED', 'FAILED'] },
      { status: 'SOURCED',       label: 'Allocated',        description: 'Inventory allocated and reserved',         allowedNextStatuses: ['PICKING'] },
      { status: 'PICKING',       label: 'Picking',          description: 'Warehouse picking in progress',            allowedNextStatuses: ['PACKING'] },
      { status: 'PACKING',       label: 'Packing',          description: 'Items consolidated and packed',            allowedNextStatuses: ['READY_TO_SHIP'] },
      { status: 'READY_TO_SHIP', label: 'Ready to Ship',    description: 'Awaiting freight pickup',                  allowedNextStatuses: ['SHIPPED'] },
      { status: 'SHIPPED',       label: 'Shipped',          description: 'In transit to buyer',                      allowedNextStatuses: ['PARTIALLY_SHIPPED', 'DELIVERED'] },
      { status: 'DELIVERED',     label: 'Delivered',        description: 'Received and confirmed by buyer',          allowedNextStatuses: ['RETURNED'] },
    ],
  },
  {
    name: 'BOPIS — Buy Online Pickup In Store',
    description: 'Store pickup lifecycle for click-and-collect',
    pipeline_type: 'ORDER',
    fulfillmentTypes: ['STORE_PICKUP', 'CURBSIDE_PICKUP'],
    channels: ['WEB', 'MOBILE'],
    steps: [
      { status: 'PENDING',          label: 'Pending',          description: 'Order received',                           allowedNextStatuses: ['CONFIRMED', 'CANCELLED'] },
      { status: 'CONFIRMED',        label: 'Confirmed',        description: 'Payment verified',                         allowedNextStatuses: ['SOURCING'] },
      { status: 'SOURCING',         label: 'Routing',          description: 'Routing to nearest store',                 allowedNextStatuses: ['SOURCED', 'FAILED'] },
      { status: 'SOURCED',          label: 'Store Assigned',   description: 'Store confirmed inventory availability',    allowedNextStatuses: ['PICKING'] },
      { status: 'PICKING',          label: 'Picking',          description: 'Store associate picking items',             allowedNextStatuses: ['PACKING'] },
      { status: 'PACKING',          label: 'Staging',          description: 'Items staged for customer pickup',          allowedNextStatuses: ['READY_FOR_PICKUP'] },
      { status: 'READY_FOR_PICKUP', label: 'Ready for Pickup', description: 'Customer notified, awaiting pickup',        allowedNextStatuses: ['PICKED_UP', 'CANCELLED'] },
      { status: 'PICKED_UP',        label: 'Picked Up',        description: 'Customer collected order',                  allowedNextStatuses: ['RETURNED'] },
    ],
  },
  {
    name: 'B2C Return & Refund',
    description: 'Consumer reverse logistics flow — RMA to refund',
    pipeline_type: 'RETURN',
    order_type: 'RETAIL',
    fulfillmentTypes: [],
    channels: ['WEB', 'MOBILE'],
    steps: [
      { status: 'PENDING',   label: 'RMA Requested',   description: 'Return request received, awaiting approval',        allowedNextStatuses: ['CONFIRMED', 'CANCELLED'] },
      { status: 'CONFIRMED', label: 'RMA Approved',    description: 'Return authorised, shipping label issued',           allowedNextStatuses: ['RETURNED', 'CANCELLED'] },
      { status: 'RETURNED',  label: 'Item Received',   description: 'Returned item received and inspected at warehouse',  allowedNextStatuses: ['REFUNDED'] },
      { status: 'REFUNDED',  label: 'Refunded',        description: 'Refund issued to original payment method',           allowedNextStatuses: [] },
    ],
  },
  {
    name: 'B2B Return / Credit Note',
    description: 'B2B reverse logistics with credit memo instead of direct refund',
    pipeline_type: 'RETURN',
    order_type: 'B2B',
    fulfillmentTypes: [],
    channels: ['B2B', 'EDI'],
    steps: [
      { status: 'PENDING',   label: 'Return Claim',    description: 'B2B return claim submitted',                        allowedNextStatuses: ['CONFIRMED', 'CANCELLED'] },
      { status: 'CONFIRMED', label: 'Claim Approved',  description: 'Return authorised by account manager',              allowedNextStatuses: ['RETURNED', 'CANCELLED'] },
      { status: 'RETURNED',  label: 'Goods Received',  description: 'Returned goods received and quality inspected',     allowedNextStatuses: ['REFUNDED'] },
      { status: 'REFUNDED',  label: 'Credit Issued',   description: 'Credit memo or net-terms credit applied to account', allowedNextStatuses: [] },
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
    pipelineType: lc.pipeline_type ?? 'ORDER',
    orderType: lc.order_type ?? '',
    brandId: lc.brand_id ?? '',
    customStatuses: lc.custom_statuses ?? [],
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
    description: form.description || undefined,
    fulfillment_types: form.fulfillmentTypes,
    channels: form.channels,
    pipeline_type: form.pipelineType,
    order_type: form.orderType || null,
    brand_id: form.brandId || null,
    custom_statuses: form.customStatuses,
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
    pipeline_type: tpl.pipeline_type,
    order_type: tpl.order_type ?? null,
    brand_id: null,
    custom_statuses: [],
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
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="label text-[10px]">Action Type</label>
              <select className="select text-xs" value={step.actionType ?? ''} onChange={e => onUpdate({ ...step, actionType: e.target.value || null })}>
                <option value="">None</option>
                <option value="notify_customer">notify_customer</option>
                <option value="trigger_sourcing">trigger_sourcing</option>
                <option value="initiate_return">initiate_return</option>
                <option value="reserve_inventory">reserve_inventory</option>
                <option value="release_inventory">release_inventory</option>
              </select>
            </div>
            <div>
              <label className="label text-[10px]">SLA Hours</label>
              <input className="input text-xs" type="number" min={0} value={step.slaHours ?? ''} onChange={e => onUpdate({ ...step, slaHours: e.target.value ? Number(e.target.value) : null })} placeholder="e.g. 24" />
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

// ─── Custom Status Creator ─────────────────────────────────────────────────────

function CustomStatusEditor({
  statuses,
  onChange,
}: {
  statuses: CustomStatusDef[]
  onChange: (s: CustomStatusDef[]) => void
}) {
  const [key, setKey] = useState('')
  const [label, setLabel] = useState('')
  const [color, setColor] = useState('#6366f1')

  const add = () => {
    const k = key.toUpperCase().replace(/\s+/g, '_').replace(/[^A-Z_]/g, '')
    if (!k || !label || statuses.some(s => s.key === k)) return
    onChange([...statuses, { key: k, label, color }])
    setKey(''); setLabel(''); setColor('#6366f1')
  }

  return (
    <div className="space-y-2">
      {statuses.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {statuses.map(s => (
            <span key={s.key} className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border" style={{ borderColor: s.color, color: s.color, background: s.color + '18' }}>
              <Tag className="w-2.5 h-2.5" />
              {s.label} ({s.key})
              <button type="button" onClick={() => onChange(statuses.filter(x => x.key !== s.key))} className="ml-0.5 opacity-60 hover:opacity-100">
                <X className="w-2.5 h-2.5" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <label className="label text-[10px]">Key (auto-uppercased)</label>
          <input className="input text-xs" placeholder="e.g. QUALITY_CHECK" value={key} onChange={e => setKey(e.target.value.toUpperCase().replace(/\s+/g, '_').replace(/[^A-Z_]/g, ''))} />
        </div>
        <div className="flex-1">
          <label className="label text-[10px]">Display Label</label>
          <input className="input text-xs" placeholder="e.g. Quality Check" value={label} onChange={e => setLabel(e.target.value)} />
        </div>
        <div>
          <label className="label text-[10px]">Color</label>
          <input type="color" className="h-9 w-10 rounded border border-gray-200 cursor-pointer" value={color} onChange={e => setColor(e.target.value)} />
        </div>
        <button type="button" onClick={add} disabled={!key || !label} className="btn-secondary h-9 px-3 text-xs flex-shrink-0">
          <Plus className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  )
}

// ─── Lifecycle Card ────────────────────────────────────────────────────────────

function LifecycleCard({
  lifecycle,
  brandName,
  onEdit,
  onDelete,
  onDuplicate,
}: {
  lifecycle: Lifecycle
  brandName?: string
  onEdit: () => void
  onDelete: () => void
  onDuplicate: () => void
}) {
  const steps = [...lifecycle.steps].sort((a, b) => a.step_order - b.step_order)
  const isReturn = lifecycle.pipeline_type === 'RETURN'
  return (
    <div className={`card p-5 hover:shadow-md transition-all border-l-4 ${isReturn ? 'border-l-purple-400' : 'border-l-blue-400'}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <GitBranch className={`w-4 h-4 flex-shrink-0 ${isReturn ? 'text-purple-500' : 'text-blue-500'}`} />
            <h3 className="font-semibold text-gray-900 text-sm">{lifecycle.name}</h3>
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isReturn ? 'bg-purple-50 text-purple-700 border border-purple-200' : 'bg-blue-50 text-blue-700 border border-blue-200'}`}>
              {PIPELINE_TYPE_LABELS[lifecycle.pipeline_type ?? 'ORDER']}
            </span>
            {lifecycle.order_type && (
              <span className="px-1.5 py-0.5 bg-indigo-50 text-indigo-700 border border-indigo-200 rounded text-[10px] font-medium">
                {lifecycle.order_type}
              </span>
            )}
            {brandName && (
              <span className="px-1.5 py-0.5 bg-green-50 text-green-700 border border-green-200 rounded text-[10px] font-medium">
                {brandName}
              </span>
            )}
            {lifecycle.is_default && (
              <span className="px-1.5 py-0.5 bg-gray-100 text-gray-600 border border-gray-200 rounded text-[10px] font-medium">default</span>
            )}
            {!lifecycle.is_active && (
              <span className="px-1.5 py-0.5 bg-gray-100 text-gray-400 border border-gray-200 rounded text-[10px] font-medium">inactive</span>
            )}
          </div>
          <p className="text-xs text-gray-500 mb-3">{lifecycle.description || 'No description'}</p>

          {/* Step flow */}
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

          {/* Custom statuses */}
          {(lifecycle.custom_statuses ?? []).length > 0 && (
            <div className="flex flex-wrap gap-1 mb-2">
              {lifecycle.custom_statuses.map(cs => (
                <span key={cs.key} className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border" style={{ borderColor: cs.color, color: cs.color, background: (cs.color ?? '#6366f1') + '18' }}>
                  <Tag className="w-2 h-2" /> {cs.label}
                </span>
              ))}
            </div>
          )}

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
            <span className="text-[10px] text-gray-400 ml-auto">{steps.length} steps</span>
          </div>
        </div>

        <div className="flex flex-col gap-1 flex-shrink-0">
          <button onClick={onEdit} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-blue-600 transition-colors" title="Edit">
            <GitBranch className="w-4 h-4" />
          </button>
          <button onClick={onDuplicate} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-green-600 transition-colors" title="Duplicate">
            <Download className="w-4 h-4" />
          </button>
          <button onClick={onDelete} className="p-1.5 rounded-lg hover:bg-red-50 text-gray-400 hover:text-red-600 transition-colors" title="Delete">
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
  brands,
  onSave,
  onClose,
  isSaving,
}: {
  initial: LifecycleForm
  brands: Array<{ id: string; name: string }>
  onSave: (form: LifecycleForm) => void
  onClose: () => void
  isSaving?: boolean
}) {
  const [form, setForm] = useState<LifecycleForm>(initial)

  const setField = <K extends keyof LifecycleForm>(k: K, v: LifecycleForm[K]) =>
    setForm(f => ({ ...f, [k]: v }))

  const toggleArr = (arr: string[], item: string) =>
    arr.includes(item) ? arr.filter(x => x !== item) : [...arr, item]

  const ALL_STATUSES = form.pipelineType === 'RETURN' ? RETURN_STATUSES : ORDER_STATUSES

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
          <input className="input" value={form.name} onChange={e => setField('name', e.target.value)} placeholder="e.g. B2C Express, B2B Wholesale Return" />
        </div>
        <div>
          <label className="label">Description</label>
          <input className="input" value={form.description} onChange={e => setField('description', e.target.value)} placeholder="Brief description" />
        </div>
      </div>

      {/* Pipeline type + order type + brand */}
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="label">Pipeline Type *</label>
          <div className="flex gap-2 mt-1">
            {(['ORDER', 'RETURN'] as PipelineType[]).map(pt => (
              <label key={pt} className={`flex items-center gap-1.5 px-3 py-2 rounded-lg border cursor-pointer text-xs font-medium transition-all ${form.pipelineType === pt ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600 hover:border-gray-300'}`}>
                <input type="radio" className="sr-only" checked={form.pipelineType === pt} onChange={() => { setField('pipelineType', pt); setForm(f => ({ ...f, pipelineType: pt, steps: [] })) }} />
                {pt === 'RETURN' ? <RotateCw className="w-3.5 h-3.5" /> : <GitBranch className="w-3.5 h-3.5" />}
                {PIPELINE_TYPE_LABELS[pt]}
              </label>
            ))}
          </div>
        </div>
        <div>
          <label className="label">Order Type Scope</label>
          <select className="select" value={form.orderType} onChange={e => setField('orderType', e.target.value)}>
            {ORDER_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Brand Scope</label>
          <select className="select" value={form.brandId} onChange={e => setField('brandId', e.target.value)}>
            <option value="">Global (all brands)</option>
            {brands.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>
      </div>

      {/* Fulfillment types */}
      <div>
        <label className="label">Fulfillment Types <span className="text-gray-400">(empty = all)</span></label>
        <div className="flex flex-wrap gap-2">
          {FULFILLMENT_TYPES.map(ft => (
            <label key={ft} className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input type="checkbox" checked={form.fulfillmentTypes.includes(ft)} onChange={() => setField('fulfillmentTypes', toggleArr(form.fulfillmentTypes, ft))} className="rounded border-gray-300" />
              {ft.replace(/_/g, ' ')}
            </label>
          ))}
        </div>
      </div>

      {/* Channels */}
      <div>
        <label className="label">Channels <span className="text-gray-400">(empty = all)</span></label>
        <div className="flex gap-3 flex-wrap">
          {CHANNELS.map(ch => (
            <label key={ch} className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input type="checkbox" checked={form.channels.includes(ch)} onChange={() => setField('channels', toggleArr(form.channels, ch))} className="rounded border-gray-300" />
              {ch}
            </label>
          ))}
        </div>
      </div>

      {/* Custom statuses */}
      <div>
        <label className="label">Custom Statuses <span className="text-gray-400">(optional — extend built-in statuses)</span></label>
        <CustomStatusEditor statuses={form.customStatuses} onChange={s => setField('customStatuses', s)} />
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
                <button type="button" onClick={() => moveStep(i, 'up')} disabled={i === 0} className="text-gray-300 hover:text-gray-500 disabled:opacity-30 text-xs px-1">▲</button>
                <button type="button" onClick={() => moveStep(i, 'down')} disabled={i === form.steps.length - 1} className="text-gray-300 hover:text-gray-500 disabled:opacity-30 text-xs px-1">▼</button>
              </div>
              <div className="flex-1">
                <StepEditor step={step} allStatuses={ALL_STATUSES} onUpdate={s => updateStep(i, s)} onRemove={() => removeStep(i)} />
              </div>
            </div>
          ))}
        </div>

        {unusedStatuses.length > 0 && (
          <div>
            <p className="text-[11px] text-gray-400 mb-1.5">Add status to lifecycle:</p>
            <div className="flex flex-wrap gap-1.5">
              {unusedStatuses.map(s => (
                <button key={s} type="button" onClick={() => addStep(s)}
                  className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border cursor-pointer hover:opacity-80 transition-opacity flex items-center gap-1 ${STATUS_COLORS[s] ?? 'bg-gray-100 text-gray-700 border-gray-300'}`}>
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
        <button className="btn-primary" disabled={!form.name || form.steps.length === 0 || isSaving} onClick={() => onSave(form)}>
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
  const [pipelineFilter, setPipelineFilter] = useState<'ALL' | PipelineType>('ALL')

  const { data: lifecycles = [], isLoading, error } = useQuery({
    queryKey: ['lifecycles'],
    queryFn: () => fetchLifecycles({ active_only: false }),
  })

  const { data: brands = [] } = useQuery({
    queryKey: ['brands-active'],
    queryFn: () => getBrands({ is_active: true }),
  })

  const brandById = Object.fromEntries(brands.map(b => [b.id, b.name]))

  const onSuccess = (closeAction: () => void) => () => {
    queryClient.invalidateQueries({ queryKey: ['lifecycles'] })
    closeAction()
  }

  const createMutation = useMutation({
    mutationFn: createLifecycle,
    onSuccess: onSuccess(() => setShowCreate(false)),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: LifecyclePayload }) => updateLifecycle(id, data),
    onSuccess: onSuccess(() => setEditingId(null)),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteLifecycle,
    onSuccess: onSuccess(() => setDeletingId(null)),
  })

  const handleSave = (form: LifecycleForm, id?: string) => {
    const payload = formToPayload(form)
    if (id) updateMutation.mutate({ id, data: payload })
    else createMutation.mutate(payload)
  }

  const handleDuplicate = (lc: Lifecycle) => {
    const form = apiToForm(lc)
    createMutation.mutate(formToPayload({ ...form, name: `${form.name} (Copy)` }))
  }

  const editingLifecycle = editingId ? lifecycles.find(x => x.id === editingId) : null
  const isMutating = createMutation.isPending || updateMutation.isPending

  const filtered = lifecycles.filter(lc =>
    pipelineFilter === 'ALL' || (lc.pipeline_type ?? 'ORDER') === pipelineFilter
  )

  const orderCount = lifecycles.filter(lc => (lc.pipeline_type ?? 'ORDER') === 'ORDER').length
  const returnCount = lifecycles.filter(lc => lc.pipeline_type === 'RETURN').length

  const emptyForm: LifecycleForm = {
    name: '', description: '', fulfillmentTypes: [], channels: [],
    pipelineType: 'ORDER', orderType: '', brandId: '', customStatuses: [], steps: [],
  }

  return (
    <div className="p-6 space-y-5 max-w-5xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Lifecycle Configurator</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Define order and return pipeline flows scoped by pipeline type, brand, and order type
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

      {/* Info */}
      <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 text-xs text-blue-700 flex gap-3">
        <Info className="w-4 h-4 flex-shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p className="font-semibold">Pipeline scoping</p>
          <p>
            <strong>Order pipelines</strong> govern forward fulfilment flows.
            <strong className="ml-1">Return pipelines</strong> govern reverse-logistics (RMA/refund) flows.
            Scope each lifecycle to a specific <strong>brand</strong> and/or <strong>order type</strong> (Retail, B2B, Wholesale)
            so the DOM engine applies the right rules for each segment.
          </p>
        </div>
      </div>

      {/* Pipeline filter tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-xl p-1 w-fit">
        {([
          { key: 'ALL', label: `All (${lifecycles.length})` },
          { key: 'ORDER', label: `Order Pipelines (${orderCount})` },
          { key: 'RETURN', label: `Return Pipelines (${returnCount})` },
        ] as const).map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setPipelineFilter(key)}
            className={`px-4 py-1.5 rounded-lg text-xs font-medium transition-all ${pipelineFilter === key ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* All available statuses reference */}
      <div className="card p-4">
        <h2 className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-3">All Available Statuses</h2>
        <div className="flex flex-wrap gap-1.5">
          {ORDER_STATUSES.map(s => (
            <span key={s} className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${STATUS_COLORS[s] ?? 'bg-gray-100 text-gray-700 border-gray-300'}`}>
              {DEFAULT_LABELS[s] ?? s}
            </span>
          ))}
        </div>
      </div>

      {/* Errors */}
      {error && (
        <div className="bg-red-50 border border-red-100 rounded-xl p-4 text-xs text-red-700">
          Failed to load lifecycles. Please refresh.
        </div>
      )}
      {(createMutation.error || updateMutation.error || deleteMutation.error) && (
        <div className="bg-red-50 border border-red-100 rounded-xl p-4 text-xs text-red-700">
          {String((createMutation.error as Error || updateMutation.error as Error || deleteMutation.error as Error)?.message ?? 'Operation failed')}
        </div>
      )}

      {/* List */}
      {isLoading ? (
        <div className="card p-12 text-center text-sm text-gray-400">Loading lifecycles…</div>
      ) : filtered.length === 0 ? (
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
          {filtered.map(lc => (
            <LifecycleCard
              key={lc.id}
              lifecycle={lc}
              brandName={lc.brand_id ? brandById[lc.brand_id] : undefined}
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
            <div key={i} className={`border rounded-xl p-4 hover:shadow-sm transition-all ${tpl.pipeline_type === 'RETURN' ? 'border-purple-100 hover:border-purple-200 hover:bg-purple-50/30' : 'border-gray-100 hover:border-blue-200 hover:bg-blue-50/30'}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <p className="font-semibold text-sm text-gray-900">{tpl.name}</p>
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${tpl.pipeline_type === 'RETURN' ? 'bg-purple-50 text-purple-700' : 'bg-blue-50 text-blue-700'}`}>
                      {PIPELINE_TYPE_LABELS[tpl.pipeline_type]}
                    </span>
                    {tpl.order_type && (
                      <span className="px-1.5 py-0.5 bg-indigo-50 text-indigo-700 rounded text-[10px] font-medium">{tpl.order_type}</span>
                    )}
                  </div>
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
          brands={brands}
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
            brands={brands}
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
          <button className="btn-danger" disabled={deleteMutation.isPending} onClick={() => deletingId && deleteMutation.mutate(deletingId)}>
            <Trash2 className="w-4 h-4" /> {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </Modal>

      {lifecycles.length > 0 && (
        <p className="text-[10px] text-gray-400 flex items-center gap-1">
          <RotateCcw className="w-3 h-3" />
          Lifecycles are server-side. Use the delete button on each card to remove them.
        </p>
      )}
    </div>
  )
}
