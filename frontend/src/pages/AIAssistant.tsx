import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Sparkles, Send, User, Bot, Loader2, AlertCircle,
  Package, ShoppingCart, BarChart2, MapPin, Zap,
  CheckCircle2, Circle, Clock, TrendingUp, TrendingDown,
  ChevronRight, ExternalLink, RefreshCw,
} from 'lucide-react'
import {
  streamAIChat, fetchAIStatus,
  type AIChatMessage, type AIEvent, type AIDataKind,
} from '../api/client'

// ─── Status color helpers ──────────────────────────────────────────────────────
const STATUS_COLORS: Record<string, string> = {
  PENDING: 'bg-gray-100 text-gray-700',
  CONFIRMED: 'bg-blue-100 text-blue-700',
  SOURCING: 'bg-yellow-100 text-yellow-700',
  SOURCED: 'bg-yellow-100 text-yellow-800',
  PICKING: 'bg-orange-100 text-orange-700',
  PACKING: 'bg-orange-100 text-orange-800',
  READY_TO_SHIP: 'bg-purple-100 text-purple-700',
  SHIPPED: 'bg-indigo-100 text-indigo-700',
  OUT_FOR_DELIVERY: 'bg-blue-100 text-blue-800',
  DELIVERED: 'bg-green-100 text-green-700',
  READY_FOR_PICKUP: 'bg-teal-100 text-teal-700',
  PICKED_UP: 'bg-green-100 text-green-800',
  CANCELLED: 'bg-red-100 text-red-700',
  RETURNED: 'bg-pink-100 text-pink-700',
  REFUNDED: 'bg-pink-100 text-pink-800',
  FAILED: 'bg-red-100 text-red-800',
}

const STATUS_FLOW = [
  'PENDING', 'CONFIRMED', 'SOURCING', 'SOURCED',
  'PICKING', 'PACKING', 'READY_TO_SHIP', 'SHIPPED',
  'OUT_FOR_DELIVERY', 'DELIVERED',
]

function fmt(val: number, prefix = '') {
  if (val >= 1_000_000) return `${prefix}${(val / 1_000_000).toFixed(1)}M`
  if (val >= 1_000) return `${prefix}${(val / 1_000).toFixed(1)}K`
  return `${prefix}${val.toLocaleString()}`
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

// ─── Rich Data Renderers ───────────────────────────────────────────────────────

interface OrderData {
  id: string
  order_number: string
  status: string
  channel: string
  fulfillment_type: string
  customer_email: string
  customer_name?: string
  total_amount: number
  currency: string
  created_at: string
  delivered_at?: string
  line_items?: Array<{ sku: string; product_name: string; quantity: number; unit_price: number }>
  shipments?: Array<{ tracking_number?: string; carrier?: string; status: string; shipped_at?: string }>
}

function OrderStatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[status] ?? 'bg-gray-100 text-gray-700'}`}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

function OrderTimeline({ order }: { order: OrderData }) {
  const statusIdx = STATUS_FLOW.indexOf(order.status)
  return (
    <div className="flex items-center gap-0 mt-2 overflow-x-auto">
      {STATUS_FLOW.slice(0, 6).map((s, i) => {
        const done = statusIdx >= i
        const active = STATUS_FLOW[statusIdx] === s
        return (
          <div key={s} className="flex items-center">
            <div className={`flex flex-col items-center ${active ? 'opacity-100' : done ? 'opacity-100' : 'opacity-30'}`}>
              <div className={`w-5 h-5 rounded-full flex items-center justify-center border-2 ${
                active ? 'border-blue-500 bg-blue-500' :
                done ? 'border-green-500 bg-green-500' : 'border-gray-300 bg-white'
              }`}>
                {done && !active && <CheckCircle2 className="w-3 h-3 text-white" />}
                {active && <Circle className="w-3 h-3 text-white fill-white" />}
              </div>
              <span className="text-[9px] mt-0.5 text-gray-500 whitespace-nowrap">{s.replace(/_/g, ' ')}</span>
            </div>
            {i < 5 && (
              <div className={`w-6 h-0.5 mb-3 ${done && statusIdx > i ? 'bg-green-400' : 'bg-gray-200'}`} />
            )}
          </div>
        )
      })}
      {statusIdx > 5 && (
        <div className="ml-2 flex-shrink-0">
          <OrderStatusBadge status={order.status} />
        </div>
      )}
    </div>
  )
}

function OrderCard({ order, onNavigate }: { order: OrderData; onNavigate: (id: string) => void }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden bg-white">
      <div
        className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-gray-50"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="flex items-center gap-2 min-w-0">
          <ShoppingCart className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
          <span className="font-mono text-xs font-semibold text-blue-600">{order.order_number}</span>
          <OrderStatusBadge status={order.status} />
          <span className="text-xs text-gray-500 truncate">{order.customer_name || order.customer_email}</span>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-xs font-semibold text-gray-800">
            {order.currency} {order.total_amount.toFixed(2)}
          </span>
          <span className="text-[10px] text-gray-400">{fmtDate(order.created_at)}</span>
          <button
            onClick={e => { e.stopPropagation(); onNavigate(order.id) }}
            className="text-gray-400 hover:text-blue-500 transition-colors"
            title="Open order"
          >
            <ExternalLink className="w-3.5 h-3.5" />
          </button>
          <ChevronRight className={`w-3.5 h-3.5 text-gray-400 transition-transform ${expanded ? 'rotate-90' : ''}`} />
        </div>
      </div>
      {expanded && (
        <div className="px-3 pb-3 border-t border-gray-100 bg-gray-50">
          <OrderTimeline order={order} />
          <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
            <div>
              <span className="text-gray-400">Channel: </span>
              <span className="font-medium">{order.channel}</span>
            </div>
            <div>
              <span className="text-gray-400">Fulfillment: </span>
              <span className="font-medium">{order.fulfillment_type?.replace(/_/g, ' ')}</span>
            </div>
          </div>
          {order.line_items && order.line_items.length > 0 && (
            <div className="mt-2">
              <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Items</p>
              <div className="space-y-0.5">
                {order.line_items.map((item, i) => (
                  <div key={i} className="flex justify-between text-xs">
                    <span className="text-gray-600">{item.product_name} <span className="text-gray-400">×{item.quantity}</span></span>
                    <span className="font-medium">${(item.unit_price * item.quantity).toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {order.shipments && order.shipments.length > 0 && (
            <div className="mt-2">
              <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Shipments</p>
              {order.shipments.map((s, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className="text-gray-400">{s.carrier}</span>
                  <span className="font-mono text-gray-600">{s.tracking_number}</span>
                  <OrderStatusBadge status={s.status} />
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function OrdersData({ data, onNavigate }: { data: { orders: OrderData[]; count: number }; onNavigate: (id: string) => void }) {
  return (
    <div className="mt-2 space-y-1.5">
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide">
        {data.count} order{data.count !== 1 ? 's' : ''} found
      </p>
      {data.orders.map(o => (
        <OrderCard key={o.id} order={o} onNavigate={onNavigate} />
      ))}
    </div>
  )
}

interface InventoryRow {
  sku: string
  product_name?: string
  node_name: string
  node_type: string
  quantity_on_hand: number
  quantity_reserved: number
  quantity_available: number
  reorder_point: number
  is_low_stock: boolean
  unit_cost: number
}

function InventoryData({ data }: { data: { inventory: InventoryRow[]; count: number } }) {
  return (
    <div className="mt-2">
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
        {data.count} SKU{data.count !== 1 ? 's' : ''}
      </p>
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-2 py-1.5 font-semibold text-gray-600">SKU</th>
              <th className="text-left px-2 py-1.5 font-semibold text-gray-600">Node</th>
              <th className="text-right px-2 py-1.5 font-semibold text-gray-600">On Hand</th>
              <th className="text-right px-2 py-1.5 font-semibold text-gray-600">Reserved</th>
              <th className="text-right px-2 py-1.5 font-semibold text-gray-600">Available</th>
              <th className="text-right px-2 py-1.5 font-semibold text-gray-600">Reorder Pt</th>
              <th className="text-left px-2 py-1.5 font-semibold text-gray-600">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data.inventory.map((item, i) => (
              <tr key={i} className={item.is_low_stock ? 'bg-red-50' : 'bg-white hover:bg-gray-50'}>
                <td className="px-2 py-1.5 font-mono font-semibold text-gray-800">{item.sku}</td>
                <td className="px-2 py-1.5 text-gray-600">{item.node_name}</td>
                <td className="px-2 py-1.5 text-right text-gray-800">{item.quantity_on_hand}</td>
                <td className="px-2 py-1.5 text-right text-yellow-700">{item.quantity_reserved}</td>
                <td className={`px-2 py-1.5 text-right font-semibold ${item.is_low_stock ? 'text-red-700' : 'text-green-700'}`}>
                  {item.quantity_available}
                </td>
                <td className="px-2 py-1.5 text-right text-gray-500">{item.reorder_point}</td>
                <td className="px-2 py-1.5">
                  {item.is_low_stock ? (
                    <span className="inline-flex items-center gap-0.5 text-red-600 font-medium">
                      <TrendingDown className="w-3 h-3" /> Low Stock
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-0.5 text-green-600">
                      <TrendingUp className="w-3 h-3" /> OK
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

interface AnalyticsData {
  period_days: number
  total_orders: number
  total_revenue: number
  avg_order_value: number
  orders_by_status: Record<string, number>
  orders_by_channel: Record<string, number>
  low_stock_alerts: number
  active_nodes: number
}

function AnalyticsData({ data }: { data: AnalyticsData }) {
  return (
    <div className="mt-2 space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          { label: 'Total Orders', value: fmt(data.total_orders), icon: ShoppingCart, color: 'text-blue-600' },
          { label: 'Revenue', value: fmt(data.total_revenue, '$'), icon: TrendingUp, color: 'text-green-600' },
          { label: 'Avg Order', value: fmt(data.avg_order_value, '$'), icon: BarChart2, color: 'text-purple-600' },
          { label: 'Low Stock', value: String(data.low_stock_alerts), icon: Package, color: data.low_stock_alerts > 0 ? 'text-red-600' : 'text-gray-600' },
        ].map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="bg-white border border-gray-200 rounded-lg p-2.5">
            <div className="flex items-center gap-1.5 mb-1">
              <Icon className={`w-3.5 h-3.5 ${color}`} />
              <span className="text-[10px] text-gray-500">{label}</span>
            </div>
            <p className={`text-base font-bold ${color}`}>{value}</p>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="bg-white border border-gray-200 rounded-lg p-2.5">
          <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">By Status</p>
          <div className="space-y-1">
            {Object.entries(data.orders_by_status).map(([s, c]) => (
              <div key={s} className="flex items-center justify-between">
                <OrderStatusBadge status={s} />
                <span className="text-xs font-semibold">{c}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-2.5">
          <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">By Channel</p>
          <div className="space-y-1">
            {Object.entries(data.orders_by_channel).map(([ch, c]) => (
              <div key={ch} className="flex items-center justify-between text-xs">
                <span className="text-gray-600">{ch}</span>
                <span className="font-semibold">{c}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

interface NodeData {
  id: string
  code: string
  name: string
  node_type: string
  status: string
  city?: string
  state?: string
  daily_order_capacity: number
  current_daily_orders: number
  capacity_utilization: number
}

function NodesData({ data }: { data: { nodes: NodeData[]; count: number } }) {
  return (
    <div className="mt-2 space-y-1.5">
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide">{data.count} nodes</p>
      {data.nodes.map(n => {
        const pct = n.capacity_utilization
        const bar = Math.min(pct, 100)
        const barColor = pct > 90 ? 'bg-red-500' : pct > 70 ? 'bg-yellow-500' : 'bg-green-500'
        return (
          <div key={n.id} className="bg-white border border-gray-200 rounded-lg p-2.5">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1.5">
                <MapPin className="w-3.5 h-3.5 text-gray-400" />
                <span className="text-sm font-semibold text-gray-800">{n.name}</span>
                <span className="text-[10px] bg-gray-100 text-gray-600 rounded px-1">{n.node_type}</span>
              </div>
              <span className="text-xs text-gray-500">{n.city}, {n.state}</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${barColor}`} style={{ width: `${bar}%` }} />
              </div>
              <span className="text-xs text-gray-600 flex-shrink-0">{n.current_daily_orders}/{n.daily_order_capacity} ({pct.toFixed(0)}%)</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

interface SourcingRuleData {
  id: string
  name: string
  priority: number
  is_active: boolean
  strategy: string
  conditions: Array<{ field: string; operator: string; value: unknown }>
  cost_weight: number
  distance_weight: number
}

function SourcingData({ data }: { data: { rules: SourcingRuleData[]; count: number } }) {
  return (
    <div className="mt-2 space-y-1.5">
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide">{data.count} rules</p>
      {data.rules.map(r => (
        <div key={r.id} className="bg-white border border-gray-200 rounded-lg p-2.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] bg-gray-100 text-gray-500 rounded px-1 font-mono">#{r.priority}</span>
              <span className="text-sm font-semibold text-gray-800">{r.name}</span>
            </div>
            <span className={`text-[10px] rounded-full px-2 py-0.5 font-medium ${r.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
              {r.is_active ? 'Active' : 'Disabled'}
            </span>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs text-blue-600 bg-blue-50 rounded px-1.5 py-0.5">{r.strategy.replace(/_/g, ' ')}</span>
            <span className="text-[10px] text-gray-400">Cost: {(r.cost_weight * 100).toFixed(0)}% | Dist: {(r.distance_weight * 100).toFixed(0)}%</span>
          </div>
          {r.conditions.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {r.conditions.map((c, i) => (
                <span key={i} className="text-[10px] bg-gray-50 border border-gray-200 rounded px-1.5 py-0.5 text-gray-600">
                  {c.field} {c.operator} {String(c.value)}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

interface AggregateRow {
  label: string
  sublabel: string | null
  primary_value: number
  primary_label: string
  secondary_value: number
  secondary_label: string
  count: number
}

interface AggregatePayload {
  group_by: string
  metric: string
  sort_order: string
  period_days: number
  rows: AggregateRow[]
  count: number
}

function AggregateData({ data }: { data: AggregatePayload }) {
  const maxPrimary = Math.max(...data.rows.map(r => r.primary_value), 1)
  const isPrimRevenue = data.rows[0]?.primary_label === 'revenue'
  const fmt = (v: number, label: string) =>
    label === 'revenue' ? `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : v.toLocaleString()

  const groupLabel: Record<string, string> = {
    sku: 'By Product', product: 'By Product', customer: 'By Customer',
    channel: 'By Channel', status: 'By Status', node: 'By Node',
    day: 'Daily Trend', week: 'Weekly Trend', month: 'Monthly Trend',
  }

  return (
    <div className="mt-2">
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
        {groupLabel[data.group_by] ?? data.group_by}
        {data.period_days > 0 ? ` · last ${data.period_days} days` : ' · all time'}
        {' · '}{data.count} result{data.count !== 1 ? 's' : ''}
      </p>
      <div className="space-y-1.5">
        {data.rows.map((row, i) => (
          <div key={i} className="bg-white border border-gray-200 rounded-lg px-3 py-2">
            <div className="flex items-center justify-between mb-1">
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold text-gray-800 truncate">{row.label}</p>
                {row.sublabel && <p className="text-[10px] text-gray-400 truncate">{row.sublabel}</p>}
              </div>
              <div className="text-right flex-shrink-0 ml-3">
                <p className="text-xs font-bold text-gray-800">{fmt(row.primary_value, row.primary_label)} <span className="text-[10px] font-normal text-gray-400">{row.primary_label}</span></p>
                <p className="text-[10px] text-gray-500">{fmt(row.secondary_value, row.secondary_label)} {row.secondary_label}</p>
              </div>
            </div>
            <div className="h-1 bg-gray-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${isPrimRevenue ? 'bg-green-400' : 'bg-blue-400'}`}
                style={{ width: `${(row.primary_value / maxPrimary) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

interface TopItem {
  sku: string
  product_name: string
  total_quantity: number
  total_revenue: number
  order_count: number
}

interface TopItemsPayload {
  items: TopItem[]
  count: number
  period_days: number
  rank_by: string
}

function TopItemsData({ data }: { data: TopItemsPayload }) {
  const max = data.items[0]?.total_quantity ?? 1
  const maxRev = data.items[0]?.total_revenue ?? 1
  return (
    <div className="mt-2">
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
        Top {data.count} items · {data.period_days > 0 ? `last ${data.period_days} days` : 'all time'} · ranked by {data.rank_by === 'revenue' ? 'revenue' : 'units sold'}
      </p>
      <div className="space-y-1.5">
        {data.items.map((item, i) => {
          const barPct = data.rank_by === 'revenue'
            ? (item.total_revenue / maxRev) * 100
            : (item.total_quantity / max) * 100
          return (
            <div key={item.sku} className="bg-white border border-gray-200 rounded-lg px-3 py-2">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-[10px] w-5 h-5 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center font-bold flex-shrink-0">
                    {i + 1}
                  </span>
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-gray-800 truncate">{item.product_name}</p>
                    <p className="text-[10px] text-gray-400 font-mono">{item.sku}</p>
                  </div>
                </div>
                <div className="text-right flex-shrink-0 ml-3">
                  <p className="text-xs font-bold text-gray-800">{item.total_quantity.toLocaleString()} <span className="font-normal text-gray-400">units</span></p>
                  <p className="text-[10px] text-green-600 font-semibold">${item.total_revenue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
                </div>
              </div>
              <div className="h-1 bg-gray-100 rounded-full overflow-hidden">
                <div className="h-full bg-blue-400 rounded-full" style={{ width: `${barPct}%` }} />
              </div>
              <p className="text-[10px] text-gray-400 mt-0.5">{item.order_count} order{item.order_count !== 1 ? 's' : ''}</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Message Renderer ──────────────────────────────────────────────────────────

interface RichData {
  kind: AIDataKind
  data: unknown
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  richData: RichData[]
  toolCalls: string[]
  streaming: boolean
}

function MessageBubble({ msg, onNavigate }: { msg: Message; onNavigate: (id: string) => void }) {
  if (msg.role === 'user') {
    return (
      <div className="flex justify-end mb-3">
        <div className="flex items-start gap-2 max-w-[85%]">
          <div className="bg-blue-600 text-white rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm">
            {msg.content}
          </div>
          <div className="w-7 h-7 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0 mt-0.5">
            <User className="w-4 h-4 text-gray-600" />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start mb-3">
      <div className="flex items-start gap-2 max-w-[92%]">
        <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center flex-shrink-0 mt-0.5">
          <Sparkles className="w-3.5 h-3.5 text-white" />
        </div>
        <div className="flex-1 min-w-0">
          {/* Tool call indicators */}
          {msg.toolCalls.length > 0 && (
            <div className="flex flex-wrap gap-1 mb-2">
              {msg.toolCalls.map((t, i) => (
                <span key={i} className="inline-flex items-center gap-1 text-[10px] bg-purple-50 border border-purple-100 text-purple-600 rounded-full px-2 py-0.5">
                  <Zap className="w-2.5 h-2.5" />
                  {t.replace(/_/g, ' ')}
                </span>
              ))}
            </div>
          )}

          {/* Text content */}
          {(msg.content || msg.streaming) && (
            <div className="bg-white border border-gray-200 rounded-2xl rounded-tl-sm px-4 py-2.5 shadow-sm">
              <div className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">
                {msg.content}
                {msg.streaming && (
                  <span className="inline-block w-1.5 h-4 bg-blue-500 animate-pulse ml-0.5 align-middle" />
                )}
              </div>
            </div>
          )}

          {/* Rich data panels */}
          {msg.richData.map((rd, i) => (
            <div key={i} className="mt-2">
              {rd.kind === 'orders' && (
                <OrdersData
                  data={rd.data as { orders: OrderData[]; count: number }}
                  onNavigate={onNavigate}
                />
              )}
              {rd.kind === 'order_detail' && (
                <OrdersData
                  data={{ orders: [(rd.data as { order: OrderData }).order], count: 1 }}
                  onNavigate={onNavigate}
                />
              )}
              {rd.kind === 'inventory' && (
                <InventoryData data={rd.data as { inventory: InventoryRow[]; count: number }} />
              )}
              {rd.kind === 'analytics' && (
                <AnalyticsData data={rd.data as AnalyticsData} />
              )}
              {rd.kind === 'nodes' && (
                <NodesData data={rd.data as { nodes: NodeData[]; count: number }} />
              )}
              {rd.kind === 'sourcing' && (
                <SourcingData data={rd.data as { rules: SourcingRuleData[]; count: number }} />
              )}
              {rd.kind === 'top_items' && (
                <TopItemsData data={rd.data as TopItemsPayload} />
              )}
              {rd.kind === 'aggregate' && (
                <AggregateData data={rd.data as AggregatePayload} />
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ─── Suggested Prompts ─────────────────────────────────────────────────────────

const SUGGESTIONS = [
  { icon: ShoppingCart, text: 'Show me all pending orders', color: 'text-blue-600 bg-blue-50 border-blue-100' },
  { icon: Package, text: 'Which SKUs are low on stock?', color: 'text-red-600 bg-red-50 border-red-100' },
  { icon: BarChart2, text: 'Give me an analytics summary for the last 30 days', color: 'text-purple-600 bg-purple-50 border-purple-100' },
  { icon: MapPin, text: 'Show all active fulfillment nodes and their capacity', color: 'text-green-600 bg-green-50 border-green-100' },
  { icon: Zap, text: 'What sourcing rules are currently active?', color: 'text-yellow-600 bg-yellow-50 border-yellow-100' },
  { icon: TrendingUp, text: 'Which orders were delivered today?', color: 'text-teal-600 bg-teal-50 border-teal-100' },
]

// ─── Main Component ────────────────────────────────────────────────────────────

export default function AIAssistant() {
  const navigate = useNavigate()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<boolean>(false)

  const { data: aiStatus } = useQuery({
    queryKey: ['ai-status'],
    queryFn: fetchAIStatus,
  })

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleNavigate = useCallback((orderId: string) => {
    navigate(`/orders/${orderId}`)
  }, [navigate])

  const generateId = () =>
    typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2) + Date.now().toString(36)

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || isStreaming) return
    const userMsg: Message = {
      id: generateId(),
      role: 'user',
      content: text.trim(),
      richData: [],
      toolCalls: [],
      streaming: false,
    }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setIsStreaming(true)
    abortRef.current = false

    // Build conversation history for API
    const history: AIChatMessage[] = [...messages, userMsg].map(m => ({
      role: m.role,
      content: m.content,
    }))

    const assistantId = generateId()
    const assistantMsg: Message = {
      id: assistantId,
      role: 'assistant',
      content: '',
      richData: [],
      toolCalls: [],
      streaming: true,
    }
    setMessages(prev => [...prev, assistantMsg])

    try {
      const stream = streamAIChat(history)
      for await (const event of stream) {
        if (abortRef.current) break
        setMessages(prev => prev.map(m => {
          if (m.id !== assistantId) return m
          if (event.type === 'text_delta' && event.text) {
            return { ...m, content: m.content + event.text }
          }
          if (event.type === 'tool_call' && event.tool) {
            return { ...m, toolCalls: [...m.toolCalls, event.tool] }
          }
          if (event.type === 'data' && event.kind) {
            return { ...m, richData: [...m.richData, { kind: event.kind, data: event.data }] }
          }
          if (event.type === 'error') {
            return { ...m, content: `Error: ${event.message}`, streaming: false }
          }
          return m
        }))
      }
    } catch (err) {
      setMessages(prev => prev.map(m => {
        if (m.id !== assistantId) return m
        // Only show error if we got no content and no rich data at all
        const hasData = m.richData.length > 0 || m.content.length > 0
        return {
          ...m,
          content: hasData ? m.content : 'Connection error. Please try again.',
          streaming: false,
        }
      }))
    } finally {
      setMessages(prev => prev.map(m =>
        m.id === assistantId ? { ...m, streaming: false } : m
      ))
      setIsStreaming(false)
    }
  }, [messages, isStreaming])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  const handleClear = () => {
    setMessages([])
    abortRef.current = true
    setIsStreaming(false)
    setTimeout(() => { abortRef.current = false }, 100)
  }

  const empty = messages.length === 0

  return (
    <div className="flex flex-col h-full bg-gray-50">
      {/* Header */}
      <div className="flex-shrink-0 bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-gray-900">AI Assistant</h1>
              <p className="text-xs text-gray-500">Ask anything about your orders, inventory, or operations</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {aiStatus && (
              <div className={`flex items-center gap-1.5 text-xs rounded-full px-3 py-1.5 border ${
                aiStatus.status === 'ok'
                  ? 'bg-green-50 text-green-700 border-green-200'
                  : 'bg-red-50 text-red-700 border-red-200'
              }`}>
                <span className={`w-1.5 h-1.5 rounded-full ${aiStatus.status === 'ok' ? 'bg-green-500' : 'bg-red-500'}`} />
                {aiStatus.status === 'ok' ? 'Connected' : 'API key not set'}
              </div>
            )}
            {messages.length > 0 && (
              <button
                onClick={handleClear}
                className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 border border-gray-200 rounded-full px-3 py-1.5 hover:bg-gray-50 transition-colors"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Clear
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {empty ? (
          <div className="flex flex-col items-center justify-center h-full max-w-2xl mx-auto">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center mb-4 shadow-lg">
              <Sparkles className="w-8 h-8 text-white" />
            </div>
            <h2 className="text-xl font-bold text-gray-800 mb-2">KubeRiva Intelligence</h2>
            <p className="text-sm text-gray-500 text-center mb-8 max-w-md">
              Ask me about orders, inventory levels, sourcing rules, node capacity, analytics — I have live access to your KubeRiva data.
            </p>
            {aiStatus && aiStatus.status !== 'ok' && (
              <div className="w-full mb-6 flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
                <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="font-semibold">API Key Required</p>
                  <p className="text-xs mt-1">
                    Set <code className="bg-amber-100 px-1 rounded">ANTHROPIC_API_KEY</code> in your environment and restart the backend container.
                    The backend is at <code className="bg-amber-100 px-1 rounded">localhost:8000</code>.
                  </p>
                </div>
              </div>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full">
              {SUGGESTIONS.map(({ icon: Icon, text, color }) => (
                <button
                  key={text}
                  onClick={() => sendMessage(text)}
                  disabled={isStreaming}
                  className={`flex items-center gap-2.5 text-left px-4 py-3 rounded-xl border text-sm font-medium transition-all hover:shadow-sm disabled:opacity-50 ${color}`}
                >
                  <Icon className="w-4 h-4 flex-shrink-0" />
                  {text}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto">
            {messages.map(msg => (
              <MessageBubble key={msg.id} msg={msg} onNavigate={handleNavigate} />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="flex-shrink-0 bg-white border-t border-gray-200 px-6 py-4">
        <div className="max-w-3xl mx-auto">
          {/* Quick suggestions when in conversation */}
          {!empty && (
            <div className="flex gap-2 mb-3 overflow-x-auto pb-1">
              {SUGGESTIONS.slice(0, 4).map(({ text }) => (
                <button
                  key={text}
                  onClick={() => sendMessage(text)}
                  disabled={isStreaming}
                  className="flex-shrink-0 text-xs text-gray-600 border border-gray-200 rounded-full px-3 py-1.5 hover:bg-gray-50 hover:border-gray-300 transition-colors disabled:opacity-50"
                >
                  {text}
                </button>
              ))}
            </div>
          )}
          <div className="flex items-end gap-3">
            <div className="flex-1 relative">
              <textarea
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about orders, inventory, sourcing rules, analytics..."
                rows={1}
                disabled={isStreaming}
                className="w-full resize-none border border-gray-300 rounded-xl px-4 py-3 pr-12 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50 disabled:bg-gray-50"
                style={{ minHeight: '48px', maxHeight: '160px' }}
                onInput={e => {
                  const el = e.currentTarget
                  el.style.height = 'auto'
                  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
                }}
              />
            </div>
            <button
              onClick={() => sendMessage(input)}
              disabled={!input.trim() || isStreaming}
              className="w-11 h-11 rounded-xl bg-blue-600 text-white flex items-center justify-center hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex-shrink-0"
            >
              {isStreaming ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </button>
          </div>
          <p className="text-[10px] text-gray-400 mt-2 text-center">
            Powered by KubeAI · Live KubeRiva data · Press Enter to send, Shift+Enter for new line
          </p>
        </div>
      </div>
    </div>
  )
}
