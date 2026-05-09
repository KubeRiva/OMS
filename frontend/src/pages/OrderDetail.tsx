import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Package, Truck, Clock, CheckCircle, XCircle,
  ChevronRight, RotateCcw, RefreshCw, AlertCircle, GitBranch,
  MapPin, DollarSign, Layers, ChevronDown, ChevronUp, Play, Zap,
  Building2, ThumbsUp,
} from 'lucide-react'
import { fetchOrder, fetchOrderEvents, cancelOrder, updateOrderStatus, triggerOrderWorker, resolveLifecycle, approveOrder, fetchOrderReturns, createReturn, createReturnRefund, type OrderStatus, type Order, type OrderReturn } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { StatusBadge } from '../components/Badge'
import { useState } from 'react'
import Modal from '../components/Modal'
import EmptyState from '../components/EmptyState'

// ─── Status transition map ────────────────────────────────────────────────────

const STATUS_TRANSITIONS: Record<OrderStatus, OrderStatus[]> = {
  PENDING:            ['CONFIRMED', 'CANCELLED'],
  CONFIRMED:          ['SOURCING', 'CANCELLED'],
  SOURCING:           ['SOURCED', 'BACKORDERED', 'FAILED'],
  SOURCED:            ['PICKING', 'CANCELLED'],
  PICKING:            ['PACKING'],
  PACKING:            ['READY_TO_SHIP', 'READY_FOR_PICKUP'],
  READY_TO_SHIP:      ['SHIPPED', 'PARTIALLY_SHIPPED'],
  SHIPPED:            ['OUT_FOR_DELIVERY'],
  PARTIALLY_SHIPPED:  ['SHIPPED', 'OUT_FOR_DELIVERY', 'PARTIALLY_DELIVERED'],
  OUT_FOR_DELIVERY:   ['DELIVERED', 'PARTIALLY_DELIVERED', 'FAILED'],
  PARTIALLY_DELIVERED: ['DELIVERED'],
  BACKORDERED:        ['SOURCING', 'CANCELLED'],
  DELIVERED:          ['RETURNED'],
  READY_FOR_PICKUP:   ['PICKED_UP', 'CANCELLED'],
  PICKED_UP:          ['RETURNED'],
  RETURNED:           ['REFUNDED'],
  CANCELLED:          [],
  REFUNDED:           [],
  FAILED:             ['SOURCING', 'CANCELLED'],
}

const FORWARD_FLOW: OrderStatus[] = [
  'PENDING', 'CONFIRMED', 'SOURCING', 'SOURCED',
  'PICKING', 'PACKING', 'READY_TO_SHIP', 'SHIPPED',
  'OUT_FOR_DELIVERY', 'DELIVERED',
]

const PICKUP_FLOW: OrderStatus[] = [
  'PENDING', 'CONFIRMED', 'SOURCING', 'SOURCED',
  'PICKING', 'PACKING', 'READY_FOR_PICKUP', 'PICKED_UP',
]

const RETURN_FLOW: OrderStatus[] = ['RETURNED', 'REFUNDED']

const STATUS_LABELS: Partial<Record<OrderStatus, string>> = {
  PENDING: 'Pending',
  CONFIRMED: 'Confirmed',
  SOURCING: 'Sourcing',
  SOURCED: 'Sourced',
  PICKING: 'Picking',
  PACKING: 'Packing',
  READY_TO_SHIP: 'Ready to Ship',
  SHIPPED: 'Shipped',
  PARTIALLY_SHIPPED: 'Partially Shipped',
  OUT_FOR_DELIVERY: 'Out for Delivery',
  PARTIALLY_DELIVERED: 'Partially Delivered',
  DELIVERED: 'Delivered',
  READY_FOR_PICKUP: 'Ready for Pickup',
  PICKED_UP: 'Picked Up',
  BACKORDERED: 'Backordered',
  RETURNED: 'Returned',
  REFUNDED: 'Refunded',
  CANCELLED: 'Cancelled',
  FAILED: 'Failed',
}

function getDisplayFlow(order: { fulfillment_type: string; status: OrderStatus }): OrderStatus[] {
  const isPickup =
    order.fulfillment_type === 'STORE_PICKUP' ||
    order.fulfillment_type === 'CURBSIDE_PICKUP' ||
    PICKUP_FLOW.includes(order.status)
  return isPickup ? PICKUP_FLOW : FORWARD_FLOW
}

// ─── Status Stepper ───────────────────────────────────────────────────────────

function StatusStepper({ status, fulfillmentType, lifecycleSteps }: {
  status: OrderStatus
  fulfillmentType: string
  lifecycleSteps?: Array<{ status: string; label: string; step_order: number }>
}) {
  const flow: OrderStatus[] = lifecycleSteps
    ? [...lifecycleSteps].sort((a, b) => a.step_order - b.step_order).map(s => s.status as OrderStatus)
    : getDisplayFlow({ fulfillment_type: fulfillmentType, status })
  const currentIdx = flow.indexOf(status)
  const isTerminal = ['CANCELLED', 'FAILED', 'RETURNED', 'REFUNDED'].includes(status)

  if (isTerminal && !flow.includes(status)) {
    return (
      <div className="flex items-center gap-2">
        <div className={`px-3 py-1.5 rounded-full text-xs font-semibold ${
          status === 'CANCELLED' ? 'bg-red-100 text-red-700' :
          status === 'FAILED' ? 'bg-orange-100 text-orange-700' :
          status === 'RETURNED' ? 'bg-amber-100 text-amber-700' :
          'bg-purple-100 text-purple-700'
        }`}>
          {STATUS_LABELS[status] ?? status}
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1 flex-wrap">
      {flow.map((s, idx) => {
        const done = currentIdx >= 0 && idx < currentIdx
        const active = s === status
        const future = currentIdx < 0 || idx > currentIdx
        return (
          <div key={s} className="flex items-center gap-1">
            <div className={`px-2.5 py-1 rounded-full text-[11px] font-semibold whitespace-nowrap transition-all ${
              active  ? 'bg-blue-600 text-white shadow-sm' :
              done    ? 'bg-green-100 text-green-700' :
              future  ? 'bg-gray-100 text-gray-400' : 'bg-gray-100 text-gray-400'
            }`}>
              {STATUS_LABELS[s] ?? s}
            </div>
            {idx < flow.length - 1 && (
              <ChevronRight className={`w-3 h-3 flex-shrink-0 ${done ? 'text-green-400' : 'text-gray-300'}`} />
            )}
          </div>
        )
      })}
    </div>
  )
}

// ─── Lifecycle Action Panel ────────────────────────────────────────────────────

function LifecyclePanel({
  order,
  onTransition,
  isPending,
  allowedNextStatuses: overrideNext,
}: {
  order: { status: OrderStatus; fulfillment_type: string }
  onTransition: (status: OrderStatus, notes?: string) => void
  isPending: boolean
  allowedNextStatuses?: OrderStatus[]
}) {
  const [notes, setNotes] = useState('')
  const nextStatuses = overrideNext ?? STATUS_TRANSITIONS[order.status] ?? []

  if (nextStatuses.length === 0) return null

  const isReturn = nextStatuses.some(s => RETURN_FLOW.includes(s))

  const buttonStyle = (s: OrderStatus) => {
    if (s === 'CANCELLED' || s === 'FAILED') return 'btn-danger'
    if (s === 'RETURNED') return 'bg-amber-500 hover:bg-amber-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors'
    if (s === 'REFUNDED') return 'bg-purple-600 hover:bg-purple-700 text-white px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors'
    return 'btn-primary'
  }

  return (
    <div className="card p-4 border border-blue-100 bg-blue-50/30">
      <div className="flex items-center gap-2 mb-3">
        <RefreshCw className="w-4 h-4 text-blue-500" />
        <h3 className="text-sm font-semibold text-gray-700">Advance Lifecycle</h3>
      </div>

      {isReturn && (
        <div className="mb-3 flex items-start gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg p-2.5">
          <RotateCcw className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
          <span>This order is eligible for a return. Initiating return will begin the reverse logistics flow.</span>
        </div>
      )}

      <div className="mb-3">
        <label className="label">Notes (optional)</label>
        <input
          className="input text-xs"
          value={notes}
          onChange={e => setNotes(e.target.value)}
          placeholder="Add a note for this status change…"
        />
      </div>

      <div className="flex flex-wrap gap-2">
        {nextStatuses.map(s => (
          <button
            key={s}
            disabled={isPending}
            className={`${buttonStyle(s)} ${isPending ? 'opacity-50 cursor-not-allowed' : ''}`}
            onClick={() => { onTransition(s, notes || undefined); setNotes('') }}
          >
            {s === 'RETURNED' && <RotateCcw className="w-3.5 h-3.5" />}
            {s === 'CANCELLED' && <XCircle className="w-3.5 h-3.5" />}
            {s === 'FAILED' && <AlertCircle className="w-3.5 h-3.5" />}
            → {STATUS_LABELS[s] ?? s}
          </button>
        ))}
      </div>
    </div>
  )
}

// ─── Worker Action Panel ─────────────────────────────────────────────────────

type WorkerAction = { action: 'source' | 'pick' | 'pack' | 'ship'; label: string; hint: string }

const WORKER_ACTIONS: Partial<Record<OrderStatus, WorkerAction[]>> = {
  PENDING:        [{ action: 'source', label: 'Trigger Sourcing',        hint: 'Enqueue source_order → allocate inventory' }],
  CONFIRMED:      [{ action: 'source', label: 'Trigger Sourcing',        hint: 'Enqueue source_order → allocate inventory' }],
  SOURCING:       [{ action: 'source', label: 'Re-trigger Sourcing',     hint: 'Retry source_order if stuck in SOURCING' }],
  SOURCED:        [{ action: 'pick',   label: 'Trigger Picking',         hint: 'Enqueue start_picking → move to PICKING' }],
  PICKING:        [{ action: 'pack',   label: 'Trigger Packing',         hint: 'Enqueue complete_packing → READY_TO_SHIP' }],
  PACKING:        [{ action: 'ship',   label: 'Trigger Carrier Booking', hint: 'Enqueue book_shipment → create label & SHIPPED' }],
  READY_TO_SHIP:  [{ action: 'ship',   label: 'Trigger Carrier Booking', hint: 'Enqueue book_shipment → create label & SHIPPED' }],
  FAILED:         [{ action: 'source', label: 'Re-trigger Sourcing',     hint: 'Retry source_order after failure' }],
}

function WorkerActionsPanel({
  status,
  onTrigger,
  isPending,
  lastResult,
}: {
  status: OrderStatus
  onTrigger: (action: 'source' | 'pick' | 'pack' | 'ship') => void
  isPending: boolean
  lastResult?: string | null
}) {
  const actions = WORKER_ACTIONS[status]
  if (!actions?.length) return null

  return (
    <div className="card p-4 border border-violet-100 bg-violet-50/30">
      <div className="flex items-center gap-2 mb-3">
        <Zap className="w-4 h-4 text-violet-500" />
        <h3 className="text-sm font-semibold text-gray-700">Manual Worker Trigger</h3>
        <span className="text-xs text-gray-400">— dispatch Celery task directly</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {actions.map(({ action, label, hint }) => (
          <button
            key={action}
            disabled={isPending}
            title={hint}
            onClick={() => onTrigger(action)}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
              bg-violet-600 hover:bg-violet-700 text-white
              ${isPending ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            <Play className="w-3.5 h-3.5" />
            {label}
          </button>
        ))}
      </div>
      {lastResult && (
        <p className="mt-2 text-xs text-violet-700 bg-violet-100 rounded px-2 py-1">{lastResult}</p>
      )}
    </div>
  )
}

// ─── Backorder Re-sourcing Panel ──────────────────────────────────────────────

function BackorderResourcingPanel({
  order,
  onTrigger,
  isPending,
  lastResult,
}: {
  order: Order
  onTrigger: () => void
  isPending: boolean
  lastResult?: string | null
}) {
  // Check if order is in a backordered state OR has individual items with backordered quantities
  const hasBackorders = 
    order.status === 'BACKORDERED' || 
    order.status === 'PARTIALLY_DELIVERED' ||
    order.line_items.some(item => item.quantity_backordered > 0)
  
  const backordered = order.line_items
    .filter(item => item.quantity_backordered > 0)
    .map(item => `${item.sku} (${item.quantity_backordered})`)
    .join(', ')

  if (hasBackorders) {
    const backorderMsg = backordered 
      ? `Re-source to find available inventory: ${backordered}`
      : `Order is in ${order.status} state. Items may need to be re-sourced to find additional inventory.`
    
    return (
      <div className="card p-4 border border-amber-100 bg-amber-50/30">
        <div className="flex items-center gap-2 mb-3">
          <AlertCircle className="w-4 h-4 text-amber-500" />
          <h3 className="text-sm font-semibold text-gray-700">Items Backordered</h3>
          <span className="text-xs text-gray-400">— inventory shortage detected</span>
        </div>
        <p className="text-xs text-amber-700 mb-3">
          {backorderMsg}
        </p>
        <button
          disabled={isPending}
          onClick={onTrigger}
          title="Trigger sourcing to find available inventory for backordered items"
          className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium transition-colors
            bg-amber-600 hover:bg-amber-700 text-white
            ${isPending ? 'opacity-50 cursor-not-allowed' : ''}`}
        >
          <Zap className="w-3.5 h-3.5" />
          Re-Source Backordered Items
        </button>
        {lastResult && (
          <p className="mt-2 text-xs text-amber-700 bg-amber-100 rounded px-2 py-1">{lastResult}</p>
        )}
      </div>
    )
  }

  // Show info panel when no backordered items
  return (
    <div className="card p-4 border border-emerald-100 bg-emerald-50/30">
      <div className="flex items-center gap-2">
        <CheckCircle className="w-4 h-4 text-emerald-500" />
        <h3 className="text-sm font-semibold text-gray-700">Sourcing Status</h3>
        <span className="text-xs text-gray-400">— all items fulfilled</span>
      </div>
      <p className="text-xs text-emerald-700 mt-2">
        All line items have been sourced and are either allocated, shipped, or delivered. No manual re-sourcing needed.
      </p>
    </div>
  )
}

// ─── Audit Event helpers ──────────────────────────────────────────────────────

interface AuditEvent {
  event_type: string
  timestamp: string
  data?: Record<string, unknown>
}

function eventDotColor(eventType: string): string {
  if (eventType === 'order.created')         return 'bg-blue-500'
  if (eventType === 'order.sourced')         return 'bg-emerald-500'
  if (eventType === 'order.sourcing_failed') return 'bg-orange-500'
  if (eventType === 'order.picking')         return 'bg-violet-500'
  if (eventType === 'order.packing')         return 'bg-indigo-500'
  if (eventType === 'order.ready_to_ship')   return 'bg-cyan-500'
  if (eventType === 'order.shipped')         return 'bg-sky-500'
  if (eventType === 'order.delivered')       return 'bg-green-600'
  if (eventType.includes('cancelled'))       return 'bg-red-500'
  if (eventType.includes('failed'))          return 'bg-orange-500'
  if (eventType.includes('returned'))        return 'bg-amber-500'
  if (eventType.includes('refunded'))        return 'bg-purple-500'
  return 'bg-gray-400'
}

function eventLabel(eventType: string): string {
  const map: Record<string, string> = {
    'order.created':         'Order Created',
    'order.confirmed':       'Order Confirmed',
    'order.sourcing':        'Sourcing Started',
    'order.sourced':         'Sourcing Completed',
    'order.sourcing_failed': 'Sourcing Failed',
    'order.picking':         'Picking Started',
    'order.packing':         'Packing Completed',
    'order.ready_to_ship':   'Ready to Ship',
    'order.shipped':         'Shipped',
    'order.out_for_delivery':'Out for Delivery',
    'order.delivered':       'Delivered',
    'order.cancelled':       'Order Cancelled',
    'order.failed':          'Order Failed',
    'order.returned':        'Return Initiated',
    'order.refunded':        'Refunded',
    'order.ready_for_pickup':'Ready for Pickup',
    'order.picked_up':       'Picked Up',
  }
  return map[eventType] ?? eventType.replace(/\./g, ' → ')
}

function EventDataSummary({ event }: { event: AuditEvent }) {
  const d = event.data || {}
  const type = event.event_type

  if (type === 'order.created') {
    return (
      <div className="flex flex-wrap gap-2 mt-1">
        {!!d.channel && <span className="inline-flex items-center gap-1 text-[10px] bg-blue-50 text-blue-700 rounded px-1.5 py-0.5">Channel: {String(d.channel)}</span>}
        {d.total_amount != null && <span className="inline-flex items-center gap-1 text-[10px] bg-gray-100 text-gray-600 rounded px-1.5 py-0.5">Total: ${String(d.total_amount)}</span>}
      </div>
    )
  }

  if (type === 'order.sourced') {
    return (
      <div className="flex flex-wrap gap-2 mt-1">
        {!!d.rule_applied && <span className="text-[10px] bg-emerald-50 text-emerald-700 rounded px-1.5 py-0.5">Rule: {String(d.rule_applied)}</span>}
        {!!d.strategy && <span className="text-[10px] bg-emerald-50 text-emerald-700 rounded px-1.5 py-0.5">Strategy: {String(d.strategy)}</span>}
        {d.total_nodes != null && <span className="text-[10px] bg-gray-100 text-gray-600 rounded px-1.5 py-0.5">{String(d.total_nodes)} node{Number(d.total_nodes) !== 1 ? 's' : ''}</span>}
        {d.sourcing_score != null && <span className="text-[10px] bg-gray-100 text-gray-600 rounded px-1.5 py-0.5">Score: {Number(d.sourcing_score).toFixed(3)}</span>}
        {d.processing_time_ms != null && <span className="text-[10px] bg-gray-100 text-gray-600 rounded px-1.5 py-0.5">{Number(d.processing_time_ms).toFixed(0)}ms</span>}
      </div>
    )
  }

  if (type === 'order.picking') {
    return (
      <div className="flex flex-wrap gap-2 mt-1">
        {d.allocations_count != null && <span className="text-[10px] bg-violet-50 text-violet-700 rounded px-1.5 py-0.5">{String(d.allocations_count)} allocation{Number(d.allocations_count) !== 1 ? 's' : ''} in picking</span>}
      </div>
    )
  }

  if (type === 'order.packing') {
    return (
      <div className="flex flex-wrap gap-2 mt-1">
        {d.allocations_packed != null && <span className="text-[10px] bg-indigo-50 text-indigo-700 rounded px-1.5 py-0.5">{String(d.allocations_packed)} packed</span>}
      </div>
    )
  }

  if (type === 'order.cancelled') {
    return (
      <div className="flex flex-wrap gap-2 mt-1">
        {!!d.reason && <span className="text-[10px] bg-red-50 text-red-700 rounded px-1.5 py-0.5">Reason: {String(d.reason)}</span>}
      </div>
    )
  }

  // Generic: show old_status → new_status and notes
  const hasTransition = !!(d.old_status && d.new_status)
  const hasNotes = !!d.notes
  if (hasTransition || hasNotes) {
    return (
      <div className="flex flex-wrap gap-2 mt-1">
        {hasTransition && (
          <span className="text-[10px] bg-gray-100 text-gray-600 rounded px-1.5 py-0.5">
            {String(d.old_status)} → {String(d.new_status)}
          </span>
        )}
        {hasNotes && <span className="text-[10px] bg-yellow-50 text-yellow-700 rounded px-1.5 py-0.5 max-w-xs truncate">{String(d.notes)}</span>}
      </div>
    )
  }

  return null
}

// ─── Sourcing Decision Trail ──────────────────────────────────────────────────

function SourcingDecisionTrail({ event }: { event: AuditEvent }) {
  const [expanded, setExpanded] = useState(false)
  const d = event.data || {}
  const ruleDetails = d.rule_details as Record<string, unknown> | undefined
  const candidates = (d.candidates_evaluated as Array<Record<string, unknown>>) || []
  const allocations = (d.allocations as Array<Record<string, unknown>>) || []

  const selectedNodes = candidates.filter(c => c.selected)
  const rejectedNodes = candidates.filter(c => !c.selected)

  return (
    <div className="card overflow-hidden">
      <button
        className="w-full px-5 py-3 border-b border-gray-100 flex items-center justify-between hover:bg-gray-50 transition-colors"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="flex items-center gap-2">
          <GitBranch className="w-4 h-4 text-emerald-500" />
          <h2 className="text-sm font-semibold text-gray-700">Sourcing Decision Trail</h2>
          <span className="text-xs text-gray-400">
            · {candidates.length} candidate{candidates.length !== 1 ? 's' : ''} evaluated · {selectedNodes.length} selected
          </span>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
      </button>

      {expanded && (
        <div className="p-5 space-y-5">
          {/* Rule that fired */}
          {ruleDetails && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Sourcing Rule Triggered</p>
              <div className="bg-emerald-50 border border-emerald-100 rounded-lg p-3 space-y-2">
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="text-sm font-semibold text-emerald-800">{String(ruleDetails.name ?? '—')}</span>
                  {ruleDetails.priority != null && (
                    <span className="text-xs bg-white border border-emerald-200 text-emerald-700 rounded px-2 py-0.5">Priority {String(ruleDetails.priority)}</span>
                  )}
                  <span className="text-xs bg-emerald-100 text-emerald-800 rounded px-2 py-0.5 font-mono">{String(ruleDetails.strategy ?? '—')}</span>
                </div>
                {/* Conditions */}
                {Array.isArray(ruleDetails.conditions) && ruleDetails.conditions.length > 0 && (
                  <div>
                    <p className="text-xs text-emerald-600 mb-1">Matching conditions:</p>
                    <div className="flex flex-wrap gap-1.5">
                      {(ruleDetails.conditions as Array<Record<string, unknown>>).map((cond, i) => (
                        <span key={i} className="text-xs bg-white border border-emerald-200 text-gray-700 rounded px-2 py-0.5 font-mono">
                          {String(cond.field)} {String(cond.operator)} {JSON.stringify(cond.value)}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {Array.isArray(ruleDetails.conditions) && ruleDetails.conditions.length === 0 && (
                  <p className="text-xs text-emerald-600 italic">No conditions — catch-all rule</p>
                )}
                {/* Rule params */}
                <div className="flex flex-wrap gap-2 pt-1">
                  {ruleDetails.max_split_nodes != null && (
                    <span className="text-[10px] bg-white border border-emerald-200 text-gray-600 rounded px-1.5 py-0.5">Max split: {String(ruleDetails.max_split_nodes)} nodes</span>
                  )}
                  {ruleDetails.max_distance_km != null && (
                    <span className="text-[10px] bg-white border border-emerald-200 text-gray-600 rounded px-1.5 py-0.5">Max distance: {(Number(ruleDetails.max_distance_km) * 0.621371).toFixed(0)} mi</span>
                  )}
                  {Array.isArray(ruleDetails.allowed_node_types) && ruleDetails.allowed_node_types.length > 0 && (
                    <span className="text-[10px] bg-white border border-emerald-200 text-gray-600 rounded px-1.5 py-0.5">
                      Node types: {(ruleDetails.allowed_node_types as string[]).join(', ')}
                    </span>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Node evaluation table */}
          {candidates.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                Nodes Evaluated ({candidates.length})
              </p>
              <div className="overflow-x-auto rounded-lg border border-gray-100">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50">
                    <tr>
                      {['Node', 'Type', 'Distance', 'Est. Cost', 'Inventory', 'Score', 'Decision'].map(h => (
                        <th key={h} className="px-3 py-2 text-left font-semibold text-gray-500 whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {candidates
                      .sort((a, b) => Number(b.score ?? 0) - Number(a.score ?? 0))
                      .map((c, i) => (
                        <tr key={i} className={c.selected ? 'bg-emerald-50' : 'bg-white'}>
                          <td className="px-3 py-2">
                            <p className="font-semibold font-mono text-gray-800">{String(c.node_code ?? '—')}</p>
                            <p className="text-[10px] text-gray-400">{String(c.node_name ?? '')}</p>
                          </td>
                          <td className="px-3 py-2 text-gray-500">{String(c.node_type ?? '—').replace(/_/g, ' ')}</td>
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-1">
                              <MapPin className="w-3 h-3 text-gray-400" />
                              {c.distance_miles != null ? `${Number(c.distance_miles).toFixed(1)} mi` : (c.distance_km != null ? `${(Number(c.distance_km) * 0.621371).toFixed(1)} mi` : '—')}
                            </div>
                          </td>
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-1">
                              <DollarSign className="w-3 h-3 text-gray-400" />
                              {c.estimated_cost != null ? `$${Number(c.estimated_cost).toFixed(2)}` : '—'}
                            </div>
                          </td>
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-1">
                              <Layers className="w-3 h-3 text-gray-400" />
                              {c.inventory_available != null ? String(c.inventory_available) : '—'}
                            </div>
                          </td>
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-1">
                              <div
                                className="h-1.5 rounded-full bg-emerald-400"
                                style={{ width: `${Math.round(Number(c.score ?? 0) * 40)}px`, minWidth: '4px' }}
                              />
                              <span className="font-mono">{c.score != null ? Number(c.score).toFixed(3) : '—'}</span>
                            </div>
                          </td>
                          <td className="px-3 py-2">
                            {c.selected ? (
                              <span className="inline-flex items-center gap-1 text-[10px] bg-emerald-100 text-emerald-700 rounded-full px-2 py-0.5 font-semibold">
                                <CheckCircle className="w-3 h-3" /> Selected
                              </span>
                            ) : (
                              <span className="text-[10px] text-gray-400">Not selected</span>
                            )}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Final allocation decisions */}
          {allocations.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                Allocation Decisions ({allocations.length})
              </p>
              <div className="space-y-2">
                {allocations.map((alloc, i) => (
                  <div key={i} className="flex items-center gap-3 p-2.5 bg-gray-50 rounded-lg border border-gray-100 text-xs">
                    <CheckCircle className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0" />
                    <span className="font-mono font-semibold text-gray-700">{String(alloc.sku ?? '—')}</span>
                    <span className="text-gray-400">×{String(alloc.quantity ?? '—')}</span>
                    <ChevronRight className="w-3 h-3 text-gray-300" />
                    <span className="font-mono text-gray-600">{String(alloc.node_code ?? '—')}</span>
                    {!!alloc.metadata && ((alloc.metadata as Record<string, unknown>).distance_miles != null || (alloc.metadata as Record<string, unknown>).distance_km != null) && (
                      <span className="text-gray-400 ml-auto">
                        {(alloc.metadata as Record<string, unknown>).distance_miles != null
                          ? `${Number((alloc.metadata as Record<string, unknown>).distance_miles).toFixed(1)} mi`
                          : `${(Number((alloc.metadata as Record<string, unknown>).distance_km) * 0.621371).toFixed(1)} mi`}
                        · ${Number((alloc.metadata as Record<string, unknown>).estimated_cost).toFixed(2)}
                      </span>
                    )}
                    <span className="text-emerald-600 font-mono font-semibold ml-1">
                      {alloc.score != null ? `score: ${Number(alloc.score).toFixed(3)}` : ''}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {candidates.length === 0 && (
            <p className="text-xs text-gray-400 italic">No candidate data available for this sourcing run.</p>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Main Component ────────────────────────────────────────────────────────────

export default function OrderDetail() {
  const { id } = useParams<{ id: string }>()
  const nav = useNavigate()
  const qc = useQueryClient()
  const { user } = useAuth()
  const [showCancel, setShowCancel] = useState(false)
  const [cancelReason, setCancelReason] = useState('')
  const [workerResult, setWorkerResult] = useState<string | null>(null)
  const [backorderResult, setBackorderResult] = useState<string | null>(null)
  const [showInitiateReturn, setShowInitiateReturn] = useState(false)
  const [returnRefundTarget, setReturnRefundTarget] = useState<OrderReturn | null>(null)

  const TERMINAL_STATUSES = ['DELIVERED', 'CANCELLED', 'REFUNDED', 'RETURNED']

  const { data: order, isLoading } = useQuery({
    queryKey: ['order', id],
    queryFn: () => fetchOrder(id!),
    enabled: !!id,
    refetchInterval: (data) => data && TERMINAL_STATUSES.includes((data as any).status) ? false : 5000,
  })

  const { data: events } = useQuery({
    queryKey: ['orderEvents', id],
    queryFn: () => fetchOrderEvents(id!),
    enabled: !!id,
    refetchInterval: order && TERMINAL_STATUSES.includes(order.status) ? false : 5000,
  })

  const { data: lifecycleData } = useQuery({
    queryKey: ['lifecycle-resolve', order?.fulfillment_type, order?.channel],
    queryFn: () => resolveLifecycle(order!.fulfillment_type, order!.channel),
    enabled: !!order,
  })
  const resolvedLifecycle = lifecycleData?.lifecycle ?? null

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['order', id] })
    qc.invalidateQueries({ queryKey: ['orders'] })
    qc.invalidateQueries({ queryKey: ['orderEvents', id] })
  }

  const statusMutation = useMutation({
    mutationFn: ({ status, notes }: { status: OrderStatus; notes?: string }) =>
      updateOrderStatus(id!, status, notes),
    onSuccess: invalidate,
  })

  const cancelMutation = useMutation({
    mutationFn: () => cancelOrder(id!, cancelReason),
    onSuccess: () => { invalidate(); setShowCancel(false) },
  })

  const workerMutation = useMutation({
    mutationFn: (action: 'source' | 'pick' | 'pack' | 'ship') => triggerOrderWorker(id!, action),
    onSuccess: (data) => {
      setWorkerResult(`✓ Queued "${data.action}" task — worker will process shortly`)
      setTimeout(() => setWorkerResult(null), 6000)
      setTimeout(invalidate, 2000)
    },
    onError: () => setWorkerResult('✗ Failed to queue task — check API logs'),
  })

  const backorderMutation = useMutation({
    mutationFn: () => triggerOrderWorker(id!, 'source'),
    onSuccess: () => {
      setBackorderResult('✓ Sourcing task queued — finding inventory for backordered items...')
      setTimeout(() => setBackorderResult(null), 6000)
      setTimeout(invalidate, 2000)
    },
    onError: () => setBackorderResult('✗ Failed to queue sourcing task — check API logs'),
  })

  const approveMutation = useMutation({
    mutationFn: () => approveOrder(id!),
    onSuccess: invalidate,
  })

  const { data: returnsData, refetch: refetchReturns } = useQuery({
    queryKey: ['order-returns', id],
    queryFn: () => fetchOrderReturns(id!),
    enabled: !!id,
  })
  const orderReturns: OrderReturn[] = returnsData?.items ?? []

  const [returnReason, setReturnReason] = useState('DEFECTIVE')
  const [returnNotes, setReturnNotes] = useState('')
  const [returnItemQtys, setReturnItemQtys] = useState<Record<string, number>>({})
  const [returnItemRestock, setReturnItemRestock] = useState<Record<string, boolean>>({})

  const returnMutation = useMutation({
    mutationFn: () => {
      if (!order) throw new Error('No order')
      const items = order.line_items
        .filter(li => (returnItemQtys[li.id] ?? 0) > 0)
        .map(li => ({
          sku: li.sku,
          description: li.product_name,
          quantity_requested: returnItemQtys[li.id] ?? 0,
          order_item_id: li.id,
          restock: returnItemRestock[li.id] ?? true,
        }))
      return createReturn({
        order_id: order.id,
        reason: returnReason,
        customer_notes: returnNotes || undefined,
        items,
      })
    },
    onSuccess: () => {
      refetchReturns()
      setShowInitiateReturn(false)
      setReturnReason('DEFECTIVE')
      setReturnNotes('')
      setReturnItemQtys({})
      setReturnItemRestock({})
    },
  })

  // Refund from order detail
  const [orderDetailRefundMethod, setOrderDetailRefundMethod] = useState('ORIGINAL_PAYMENT')
  const [orderDetailRefundAmount, setOrderDetailRefundAmount] = useState('')
  const [orderDetailRefundReason, setOrderDetailRefundReason] = useState('')
  const [orderDetailRefundTxId, setOrderDetailRefundTxId] = useState('')
  const [orderDetailRefundNotes, setOrderDetailRefundNotes] = useState('')

  const returnRefundMutation = useMutation({
    mutationFn: () => {
      if (!returnRefundTarget) throw new Error('No return selected')
      return createReturnRefund(returnRefundTarget.id, {
        refund_method: orderDetailRefundMethod,
        amount: orderDetailRefundAmount,
        reason: orderDetailRefundReason,
        transaction_id: orderDetailRefundTxId || undefined,
        notes: orderDetailRefundNotes || undefined,
      })
    },
    onSuccess: () => {
      refetchReturns()
      setReturnRefundTarget(null)
      setOrderDetailRefundMethod('ORIGINAL_PAYMENT')
      setOrderDetailRefundAmount('')
      setOrderDetailRefundReason('')
      setOrderDetailRefundTxId('')
      setOrderDetailRefundNotes('')
    },
  })

  if (isLoading) {
    return (
      <div className="p-6 animate-pulse space-y-4">
        <div className="h-8 bg-gray-200 rounded w-64" />
        <div className="h-40 bg-gray-200 rounded" />
      </div>
    )
  }

  if (!order) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Package}
          title="Order Not Found"
          description="The order you are looking for does not exist or may have been removed."
          action={
            <button className="btn-secondary" onClick={() => nav('/orders')}>
              Back to Orders
            </button>
          }
        />
      </div>
    )
  }

  const canCancel = !['SHIPPED', 'DELIVERED', 'CANCELLED', 'RETURNED', 'REFUNDED', 'PICKED_UP'].includes(order.status)
  const anyPending = statusMutation.isPending || cancelMutation.isPending

  // Find the sourcing event for the decision trail
  const sourcingEvent = events?.find(e => e.event_type === 'order.sourced')

  // Sort events chronologically for the timeline (oldest → newest)
  const sortedEvents = events ? [...events].sort((a, b) =>
    new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  ) : []

  return (
    <div className="p-6 space-y-5 max-w-5xl">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => nav('/orders')} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400">
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-gray-900 font-mono">{order.order_number}</h1>
              <StatusBadge value={order.status} />
              {order.payment_status && order.payment_status !== 'CAPTURED' && (
                <span className="inline-flex items-center gap-1">
                  <span className="text-xs text-gray-500">Payment:</span>
                  <StatusBadge value={order.payment_status} />
                </span>
              )}
            </div>
            <p className="text-xs text-gray-500 mt-0.5">
              Created {order.created_at.slice(0, 16).replace('T', ' ')} UTC
              {order.delivered_at && ` · Delivered ${order.delivered_at.slice(0, 16).replace('T', ' ')}`}
            </p>
          </div>
        </div>
        {canCancel && (
          <button className="btn-danger" onClick={() => setShowCancel(true)}>
            <XCircle className="w-4 h-4" /> Cancel Order
          </button>
        )}
      </div>

      {/* Status Stepper */}
      <div className="card p-4">
        <p className="text-xs text-gray-400 font-medium mb-2 uppercase tracking-wider">Order Lifecycle</p>
        <StatusStepper
          status={order.status}
          fulfillmentType={order.fulfillment_type}
          lifecycleSteps={resolvedLifecycle?.steps}
        />
        {['RETURNED', 'REFUNDED'].includes(order.status) && (
          <div className="mt-3 pt-3 border-t border-gray-100 flex items-center gap-2">
            <span className="text-xs text-gray-400">Return flow:</span>
            {RETURN_FLOW.map((s, i) => (
              <div key={s} className="flex items-center gap-1">
                <div className={`px-2.5 py-1 rounded-full text-[11px] font-semibold whitespace-nowrap ${
                  s === order.status ? 'bg-amber-500 text-white' :
                  RETURN_FLOW.indexOf(order.status) > i ? 'bg-amber-100 text-amber-700' :
                  'bg-gray-100 text-gray-400'
                }`}>
                  {STATUS_LABELS[s] ?? s}
                </div>
                {i < RETURN_FLOW.length - 1 && <ChevronRight className="w-3 h-3 text-gray-300" />}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* B2B Banner — shown for B2B orders */}
      {order.order_type === 'B2B' && (
        <div className={`card p-4 border ${
          order.approval_status === 'PENDING'
            ? 'border-amber-200 bg-amber-50/40'
            : order.approval_status === 'REJECTED'
            ? 'border-red-200 bg-red-50/40'
            : 'border-blue-100 bg-blue-50/20'
        }`}>
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-2 flex-wrap">
              <Building2 className="w-4 h-4 text-blue-500 flex-shrink-0" />
              <span className="text-sm font-semibold text-gray-700">B2B Order</span>
              {order.po_number && (
                <span className="text-xs bg-gray-100 text-gray-600 rounded px-2 py-0.5 font-mono">PO: {order.po_number}</span>
              )}
              <span className="text-xs bg-white border border-gray-200 text-gray-600 rounded px-2 py-0.5">
                Terms: {order.payment_terms.replace('_', ' ')}
              </span>
              {order.payment_due_date && (
                <span className="text-xs bg-white border border-gray-200 text-gray-600 rounded px-2 py-0.5 flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  Due: {order.payment_due_date.slice(0, 10)}
                </span>
              )}
              <StatusBadge value={order.approval_status} />
            </div>
            {order.approval_status === 'PENDING' && (
              <button
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-green-600 hover:bg-green-700 text-white flex-shrink-0"
                disabled={approveMutation.isPending}
                onClick={() => approveMutation.mutate()}
              >
                <ThumbsUp className="w-3.5 h-3.5" />
                {approveMutation.isPending ? 'Approving...' : 'Approve Order'}
              </button>
            )}
          </div>
          {order.approval_status === 'PENDING' && (
            <p className="text-xs text-amber-700 mt-2">
              This order is awaiting approval. It will not be sourced or fulfilled until approved.
            </p>
          )}
          {approveMutation.isError && (
            <p className="text-xs text-red-600 mt-2">Failed to approve — check your permissions.</p>
          )}
        </div>
      )}

      {/* Lifecycle Action Panel */}
      <LifecyclePanel
        order={order}
        onTransition={(status, notes) => statusMutation.mutate({ status, notes })}
        isPending={anyPending}
        allowedNextStatuses={
          resolvedLifecycle?.steps
            .find(s => s.status === order.status)
            ?.allowed_next_statuses as OrderStatus[] | undefined
        }
      />

      {/* Worker Actions Panel */}
      <WorkerActionsPanel
        status={order.status}
        onTrigger={(action) => workerMutation.mutate(action)}
        isPending={workerMutation.isPending}
        lastResult={workerResult}
      />

      {/* Backorder Re-sourcing Panel */}
      <BackorderResourcingPanel
        order={order}
        onTrigger={() => backorderMutation.mutate()}
        isPending={backorderMutation.isPending}
        lastResult={backorderResult}
      />

      {statusMutation.isError && (
        <div className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
          Failed to update status. The transition may not be supported by the backend.
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left column */}
        <div className="lg:col-span-2 space-y-4">
          {/* Order Info */}
          <div className="card p-5">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <p className="text-xs text-gray-500 font-medium">Channel</p>
                <StatusBadge value={order.channel} className="mt-1" />
              </div>
              <div>
                <p className="text-xs text-gray-500 font-medium">Fulfillment Type</p>
                <p className="font-medium mt-0.5">{order.fulfillment_type.replace(/_/g, ' ')}</p>
              </div>
              <div>
                <p className="text-xs text-gray-500 font-medium">Customer</p>
                <p className="font-medium mt-0.5">{order.customer_name || '—'}</p>
                <p className="text-xs text-gray-400">{order.customer_email}</p>
              </div>
              <div>
                <p className="text-xs text-gray-500 font-medium">Shipping Address</p>
                {order.shipping_address1 ? (
                  <p className="mt-0.5 text-xs leading-relaxed">
                    {order.shipping_address1}<br />
                    {order.shipping_city}, {order.shipping_state} {order.shipping_country}
                  </p>
                ) : <p className="text-gray-400 text-xs">—</p>}
              </div>
            </div>
          </div>

          {/* Line Items */}
          <div className="card overflow-hidden">
            <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-2">
              <Package className="w-4 h-4 text-gray-400" />
              <h2 className="text-sm font-semibold text-gray-700">Line Items</h2>
              <span className="text-xs text-gray-400">({order.line_items.length})</span>
            </div>
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  {['SKU', 'Product', 'Qty', 'Fulfillment Breakdown', 'Status', 'Unit Price', 'Total'].map(h => (
                    <th key={h} className="table-header">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {order.line_items.map(item => {
                  // Build breakdown text
                  const parts: string[] = []
                  if (item.quantity_delivered > 0) parts.push(`${item.quantity_delivered} delivered`)
                  if (item.quantity_allocated > 0) parts.push(`${item.quantity_allocated} allocated`)
                  if (item.quantity_backordered > 0) parts.push(`${item.quantity_backordered} backordered`)
                  const breakdownText = parts.length > 0 ? parts.join(', ') : 'pending'
                  
                  return (
                    <tr key={item.id}>
                      <td className="table-cell font-mono text-xs text-gray-600">{item.sku}</td>
                      <td className="table-cell font-medium">{item.product_name}</td>
                      <td className="table-cell">{item.quantity}</td>
                      <td className="table-cell text-sm">
                        <div className="flex flex-col gap-1">
                          <div className="text-xs font-medium text-gray-700">{breakdownText}</div>
                          <div className="flex gap-2 flex-wrap">
                            {item.quantity_delivered > 0 && (
                              <span className="px-2 py-0.5 bg-green-50 text-green-700 text-xs rounded border border-green-200">
                                {item.quantity_delivered}✓
                              </span>
                            )}
                            {item.quantity_shipped > item.quantity_delivered && (
                              <span className="px-2 py-0.5 bg-sky-50 text-sky-700 text-xs rounded border border-sky-200">
                                {item.quantity_shipped - item.quantity_delivered}→
                              </span>
                            )}
                            {item.quantity_allocated > 0 && (
                              <span className="px-2 py-0.5 bg-amber-50 text-amber-700 text-xs rounded border border-amber-200">
                                {item.quantity_allocated}⏳
                              </span>
                            )}
                            {item.quantity_backordered > 0 && (
                              <span className="px-2 py-0.5 bg-red-50 text-red-700 text-xs rounded border border-red-200">
                                {item.quantity_backordered}⚠
                              </span>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="table-cell">
                        {item.status ? (
                          <StatusBadge value={item.status} />
                        ) : (
                          <span className="text-xs text-gray-400">—</span>
                        )}
                      </td>
                      <td className="table-cell">${item.unit_price}</td>
                      <td className="table-cell font-semibold">${item.total_price}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Allocations */}
          {order.fulfillment_allocations.length > 0 && (
            <div className="card overflow-hidden">
              <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-2">
                <CheckCircle className="w-4 h-4 text-gray-400" />
                <h2 className="text-sm font-semibold text-gray-700">Fulfillment Allocations</h2>
              </div>
              <table className="w-full">
                <thead className="bg-gray-50">
                  <tr>
                    {['SKU', 'Node', 'Qty', 'Status', 'Score', 'Allocated At'].map(h => (
                      <th key={h} className="table-header">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {order.fulfillment_allocations.map(a => (
                    <tr key={a.id}>
                      <td className="table-cell font-mono text-xs">{a.sku}</td>
                      <td className="table-cell text-xs">
                        {a.node_code
                          ? <><span className="font-mono font-semibold text-gray-700">{a.node_code}</span>{a.node_name && <span className="block text-gray-400 text-[10px]">{a.node_name}</span>}</>
                          : <span className="text-gray-400">{a.node_id.slice(0, 8)}…</span>
                        }
                      </td>
                      <td className="table-cell">{a.quantity_allocated}</td>
                      <td className="table-cell"><StatusBadge value={a.status} /></td>
                      <td className="table-cell text-xs">{a.sourcing_score?.toFixed(3) ?? '—'}</td>
                      <td className="table-cell text-xs text-gray-500">{a.allocated_at.slice(0, 16).replace('T', ' ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Sourcing Decision Trail — shown when sourcing has completed */}
          {sourcingEvent && <SourcingDecisionTrail event={sourcingEvent} />}

          {/* Shipments */}
          {order.shipments.length > 0 && (
            <div className="card overflow-hidden">
              <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-2">
                <Truck className="w-4 h-4 text-gray-400" />
                <h2 className="text-sm font-semibold text-gray-700">Shipments</h2>
              </div>

              {order.shipments.map((s, index) => {
                const linkedById = s.allocation_id
                  ? order.fulfillment_allocations.find(a => a.id === s.allocation_id)
                  : undefined
                const linkedByIndex =
                  !linkedById && order.shipments.length === order.fulfillment_allocations.length
                    ? order.fulfillment_allocations[index]
                    : undefined
                const linkedAllocation = linkedById ?? linkedByIndex
                // Only show the single allocation directly linked to this shipment —
                // not all allocations from the same node (that inflates quantities).
                const linkedAllocations = linkedAllocation ? [linkedAllocation] : []
                const shipmentNode = linkedAllocation

                return (
                <div key={s.id} className="p-5 grid grid-cols-3 gap-4 text-sm">
                  <div>
                    <p className="text-xs text-gray-500">Carrier</p>
                    <p className="font-semibold mt-0.5">{s.carrier ?? '—'}</p>
                    <p className="text-xs text-gray-400">{s.service_level}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">Tracking</p>
                    <p className="font-mono text-xs font-semibold mt-0.5">{s.tracking_number ?? '—'}</p>
                    <StatusBadge value={s.status} className="mt-1" />
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">Est. Delivery</p>
                    <p className="mt-0.5">{s.estimated_delivery_at?.slice(0, 10) ?? '—'}</p>
                    {s.actual_delivery_at && (
                      <p className="text-xs text-green-600">Delivered {s.actual_delivery_at.slice(0, 10)}</p>
                    )}
                  </div>

                  <div className="col-span-3 mt-1 rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
                    <p className="text-[11px] text-gray-500 uppercase tracking-wider mb-1">Items in this shipment</p>
                    {s.line_items && s.line_items.length > 0 ? (
                      <>
                        <div className="space-y-0.5">
                          {[...s.line_items]
                            .sort((a, b) => a.sku.localeCompare(b.sku))
                            .map((item, i) => (
                              <p key={item.allocation_id ?? i} className="text-xs text-gray-700 font-mono">
                                {item.sku} × {item.quantity}
                              </p>
                            ))}
                        </div>
                        <p className="text-[11px] text-gray-500 mt-0.5">
                          Node: {shipmentNode?.node_code ?? shipmentNode?.node_name ?? shipmentNode?.node_id?.slice(0, 8) ?? '—'}
                        </p>
                      </>
                    ) : linkedAllocations.length > 0 ? (
                      <>
                        <div className="space-y-0.5">
                          {linkedAllocations
                            .sort((a, b) => a.sku.localeCompare(b.sku))
                            .map(a => (
                              <p key={a.id} className="text-xs text-gray-700 font-mono">
                                {a.sku} × {a.quantity_allocated}
                              </p>
                            ))}
                        </div>
                        <p className="text-[11px] text-gray-500 mt-0.5">
                          Node: {shipmentNode?.node_code ?? shipmentNode?.node_name ?? shipmentNode?.node_id?.slice(0, 8)}
                        </p>
                      </>
                    ) : (
                      <p className="text-xs text-gray-500">Item mapping unavailable for this shipment</p>
                    )}
                  </div>
                </div>
                )
              })}
            </div>
          )}

          {/* Returns */}
          <div className="card overflow-hidden">
            <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <RotateCcw className="w-4 h-4 text-amber-500" />
                <h2 className="text-sm font-semibold text-gray-700">Returns</h2>
                {orderReturns.length > 0 && (
                  <span className="text-xs text-gray-400">({orderReturns.length})</span>
                )}
              </div>
              {(['DELIVERED', 'PICKED_UP', 'RETURNED'] as OrderStatus[]).includes(order.status) && (
                <button
                  className="btn-secondary text-xs py-1 px-2.5 flex items-center gap-1.5"
                  onClick={() => setShowInitiateReturn(true)}
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  Initiate Return
                </button>
              )}
            </div>

            {orderReturns.length === 0 ? (
              <div className="px-5 py-6 text-center">
                <p className="text-xs text-gray-400">No returns for this order.</p>
              </div>
            ) : (
              <div className="divide-y divide-gray-100">
                {orderReturns.map(ret => (
                  <div key={ret.id} className="p-4 space-y-3">
                    {/* Return summary row */}
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-xs font-mono font-semibold text-gray-700">{ret.return_number}</span>
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                            ret.status === 'REQUESTED'  ? 'bg-gray-100 text-gray-700' :
                            ret.status === 'APPROVED'   ? 'bg-blue-100 text-blue-700' :
                            ret.status === 'IN_TRANSIT' ? 'bg-purple-100 text-purple-700' :
                            ret.status === 'RECEIVED'   ? 'bg-amber-100 text-amber-700' :
                            ret.status === 'RESTOCKED'  ? 'bg-teal-100 text-teal-700' :
                            ret.status === 'COMPLETED'  ? 'bg-green-100 text-green-700' :
                            ret.status === 'REJECTED'   ? 'bg-red-100 text-red-700' :
                            'bg-gray-100 text-gray-600'
                          }`}>
                            {ret.status.replace(/_/g, ' ')}
                          </span>
                          <span className="text-xs text-gray-500">{ret.reason.replace(/_/g, ' ')}</span>
                        </div>
                        <p className="text-[10px] text-gray-400">
                          Created {ret.created_at.slice(0, 10)}
                          {ret.return_tracking_number && ` · Tracking: ${ret.return_tracking_number}`}
                          {ret.return_carrier && ` via ${ret.return_carrier}`}
                        </p>
                      </div>
                    </div>

                    {/* Items */}
                    {ret.items.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {ret.items.map(item => (
                          <span key={item.id} className="text-[10px] bg-gray-100 text-gray-600 rounded px-2 py-0.5 font-mono">
                            {item.sku} ×{item.quantity_requested}
                          </span>
                        ))}
                      </div>
                    )}

                    {/* Refund sub-section */}
                    {ret.refund ? (
                      <div className="rounded-lg bg-green-50 border border-green-100 px-3 py-2 flex items-center gap-3 flex-wrap text-xs">
                        <span className="font-mono font-semibold text-green-800">{ret.refund.refund_number}</span>
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                          ret.refund.status === 'COMPLETED'  ? 'bg-green-100 text-green-700' :
                          ret.refund.status === 'PROCESSING' ? 'bg-blue-100 text-blue-700' :
                          ret.refund.status === 'FAILED'     ? 'bg-red-100 text-red-700' :
                          'bg-gray-100 text-gray-600'
                        }`}>{ret.refund.status}</span>
                        <span className="text-gray-700 font-semibold">${ret.refund.amount} {ret.refund.currency}</span>
                        <span className="text-gray-500">{ret.refund.refund_method.replace(/_/g, ' ')}</span>
                      </div>
                    ) : user?.is_superadmin && ['RECEIVED', 'COMPLETED'].includes(ret.status) ? (
                      <button
                        className="btn-primary text-xs py-1 px-2.5 flex items-center gap-1.5"
                        onClick={() => setReturnRefundTarget(ret)}
                      >
                        Create Refund
                      </button>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right: Summary + Audit Trail */}
        <div className="space-y-4">
          {/* Order Summary */}
          <div className="card p-5">
            <h2 className="text-sm font-semibold text-gray-700 mb-3">Order Summary</h2>
            <div className="space-y-2 text-sm">
              {[
                ['Subtotal', `$${order.subtotal}`],
                ['Tax', `$${order.tax_amount}`],
                ['Shipping', `$${order.shipping_amount}`],
                ['Discount', `-$${order.discount_amount}`],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between">
                  <span className="text-gray-500">{label}</span>
                  <span>{value}</span>
                </div>
              ))}
              <div className="border-t pt-2 flex justify-between font-bold">
                <span>Total</span>
                <span>${order.total_amount} {order.currency}</span>
              </div>
            </div>
          </div>

          {/* Audit Timeline */}
          <div className="card p-5">
            <div className="flex items-center gap-2 mb-4">
              <Clock className="w-4 h-4 text-gray-400" />
              <h2 className="text-sm font-semibold text-gray-700">Audit Trail</h2>
              {sortedEvents.length > 0 && (
                <span className="text-xs text-gray-400 ml-auto">{sortedEvents.length} event{sortedEvents.length !== 1 ? 's' : ''}</span>
              )}
            </div>
            <div className="space-y-0">
              {sortedEvents.length > 0 ? (
                sortedEvents.map((ev, i) => (
                  <div key={i} className="flex gap-3">
                    <div className="flex flex-col items-center">
                      <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 mt-0.5 ${eventDotColor(ev.event_type)}`} />
                      {i < sortedEvents.length - 1 && <div className="w-px flex-1 bg-gray-200 mt-1 mb-1" />}
                    </div>
                    <div className="pb-4 min-w-0 flex-1">
                      <p className="text-xs font-semibold text-gray-800">{eventLabel(ev.event_type)}</p>
                      <p className="text-[10px] text-gray-400 mt-0.5">
                        {typeof ev.timestamp === 'string' ? ev.timestamp.slice(0, 16).replace('T', ' ') : '—'} UTC
                      </p>
                      <EventDataSummary event={ev} />
                    </div>
                  </div>
                ))
              ) : (
                <p className="text-xs text-gray-400">No events recorded yet</p>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Cancel Modal */}
      <Modal open={showCancel} onClose={() => setShowCancel(false)} title="Cancel Order" size="sm">
        <div className="space-y-4">
          <p className="text-sm text-gray-600">
            Are you sure you want to cancel <span className="font-semibold">{order.order_number}</span>?
          </p>
          <div>
            <label className="label">Reason *</label>
            <input
              className="input"
              value={cancelReason}
              onChange={e => setCancelReason(e.target.value)}
              placeholder="Customer request, out of stock, etc."
            />
          </div>
          <div className="flex justify-end gap-2">
            <button className="btn-secondary" onClick={() => setShowCancel(false)}>Back</button>
            <button
              className="btn-danger"
              disabled={!cancelReason || cancelMutation.isPending}
              onClick={() => cancelMutation.mutate()}
            >
              {cancelMutation.isPending ? 'Cancelling...' : 'Cancel Order'}
            </button>
          </div>
        </div>
      </Modal>

      {/* Initiate Return Modal */}
      <Modal
        open={showInitiateReturn}
        onClose={() => setShowInitiateReturn(false)}
        title="Initiate Return"
        size="md"
      >
        <div className="space-y-4">
          <div>
            <label className="label">Reason *</label>
            <select
              className="select"
              value={returnReason}
              onChange={e => setReturnReason(e.target.value)}
            >
              {['DEFECTIVE', 'WRONG_ITEM', 'NOT_AS_DESCRIBED', 'CHANGED_MIND', 'DUPLICATE_ORDER', 'DAMAGED_IN_TRANSIT', 'OTHER'].map(r => (
                <option key={r} value={r}>{r.replace(/_/g, ' ')}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Customer Notes (optional)</label>
            <textarea
              className="input min-h-[64px] resize-none"
              value={returnNotes}
              onChange={e => setReturnNotes(e.target.value)}
              placeholder="Customer explanation…"
            />
          </div>
          <div>
            <p className="label mb-2">Items to Return</p>
            <div className="space-y-3">
              {order.line_items.map(li => {
                const qty = returnItemQtys[li.id] ?? 0
                const restock = returnItemRestock[li.id] ?? true
                return (
                  <div key={li.id} className="flex items-center gap-3 p-3 rounded-lg bg-gray-50 border border-gray-100">
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-mono font-semibold text-gray-700">{li.sku}</p>
                      <p className="text-[10px] text-gray-500 truncate">{li.product_name}</p>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <label className="text-[10px] text-gray-500">Qty</label>
                      <input
                        type="range"
                        min={0}
                        max={li.quantity}
                        value={qty}
                        onChange={e =>
                          setReturnItemQtys(prev => ({ ...prev, [li.id]: Number(e.target.value) }))
                        }
                        className="w-20"
                      />
                      <span className="text-xs font-semibold text-gray-700 w-6 text-right">{qty}</span>
                    </div>
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      <input
                        type="checkbox"
                        id={`restock-${li.id}`}
                        checked={restock}
                        onChange={e =>
                          setReturnItemRestock(prev => ({ ...prev, [li.id]: e.target.checked }))
                        }
                      />
                      <label htmlFor={`restock-${li.id}`} className="text-[10px] text-gray-500 cursor-pointer">
                        Restock
                      </label>
                    </div>
                  </div>
                )
              })}
            </div>
            {order.line_items.every(li => (returnItemQtys[li.id] ?? 0) === 0) && (
              <p className="text-[10px] text-amber-600 mt-2">Select at least one item with quantity &gt; 0.</p>
            )}
          </div>
          {returnMutation.isError && (
            <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded px-2 py-1">
              {(() => {
                const e = returnMutation.error as { response?: { data?: { detail?: unknown } } }
                const detail = e?.response?.data?.detail
                if (!detail) return 'An error occurred'
                if (typeof detail === 'string') return detail
                if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join('; ')
                return JSON.stringify(detail)
              })()}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button className="btn-secondary" onClick={() => setShowInitiateReturn(false)}>Cancel</button>
            <button
              className="btn-primary"
              disabled={
                returnMutation.isPending ||
                order.line_items.every(li => (returnItemQtys[li.id] ?? 0) === 0)
              }
              onClick={() => returnMutation.mutate()}
            >
              {returnMutation.isPending ? 'Submitting…' : 'Submit Return'}
            </button>
          </div>
        </div>
      </Modal>

      {/* Return Refund Modal */}
      <Modal
        open={!!returnRefundTarget}
        onClose={() => setReturnRefundTarget(null)}
        title={`Create Refund — ${returnRefundTarget?.return_number ?? ''}`}
        size="sm"
      >
        <div className="space-y-4">
          <div>
            <label className="label">Refund Method</label>
            <select
              className="select"
              value={orderDetailRefundMethod}
              onChange={e => setOrderDetailRefundMethod(e.target.value)}
            >
              {['ORIGINAL_PAYMENT', 'STORE_CREDIT', 'BANK_TRANSFER', 'CHECK', 'OTHER'].map(m => (
                <option key={m} value={m}>{m.replace(/_/g, ' ')}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Amount</label>
            <input
              className="input"
              type="number"
              min="0"
              step="0.01"
              value={orderDetailRefundAmount}
              onChange={e => setOrderDetailRefundAmount(e.target.value)}
              placeholder="0.00"
            />
            <p className="text-[10px] text-gray-400 mt-0.5">Order total: ${order.total_amount}</p>
          </div>
          <div>
            <label className="label">Reason *</label>
            <input
              className="input"
              value={orderDetailRefundReason}
              onChange={e => setOrderDetailRefundReason(e.target.value)}
              placeholder="Refund reason"
            />
          </div>
          <div>
            <label className="label">Transaction ID (optional)</label>
            <input
              className="input"
              value={orderDetailRefundTxId}
              onChange={e => setOrderDetailRefundTxId(e.target.value)}
              placeholder="Payment gateway transaction ID"
            />
          </div>
          <div>
            <label className="label">Notes (optional)</label>
            <textarea
              className="input min-h-[64px] resize-none"
              value={orderDetailRefundNotes}
              onChange={e => setOrderDetailRefundNotes(e.target.value)}
              placeholder="Additional notes…"
            />
          </div>
          {returnRefundMutation.isError && (
            <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded px-2 py-1">
              {(() => {
                const e = returnRefundMutation.error as { response?: { data?: { detail?: unknown } } }
                const detail = e?.response?.data?.detail
                if (!detail) return 'An error occurred'
                if (typeof detail === 'string') return detail
                if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join('; ')
                return JSON.stringify(detail)
              })()}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button className="btn-secondary" onClick={() => setReturnRefundTarget(null)}>Cancel</button>
            <button
              className="btn-primary"
              disabled={returnRefundMutation.isPending || !orderDetailRefundReason || !orderDetailRefundAmount}
              onClick={() => returnRefundMutation.mutate()}
            >
              {returnRefundMutation.isPending ? 'Saving…' : 'Create Refund'}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
