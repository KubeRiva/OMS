import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { fetchOrderVolume, fetchDashboard, fetchOrders, fetchReturns, getBrands } from '../api/client'
import { StatusBadge } from '../components/Badge'
import { Link } from 'react-router-dom'
import { Filter, X, Calendar, Tag, Layers, ShoppingBag, RotateCcw } from 'lucide-react'

const CHANNEL_COLORS: Record<string, string> = {
  WEB: '#3b82f6', MOBILE: '#8b5cf6', POS: '#f59e0b',
  API: '#6b7280', MARKETPLACE: '#f97316', B2B: '#10b981', EDI: '#ec4899',
}

const ORDER_TYPE_COLORS: Record<string, string> = {
  RETAIL: '#3b82f6', WHOLESALE: '#f59e0b', B2B: '#10b981',
}

const FULFILLMENT_COLORS = ['#6366f1', '#3b82f6', '#10b981', '#f59e0b', '#f97316']

const CHANNELS = ['WEB', 'MOBILE', 'POS', 'API', 'MARKETPLACE', 'B2B', 'EDI', 'WHOLESALE']

const ORDER_TYPES = ['RETAIL', 'WHOLESALE', 'B2B']

const DATE_PRESETS = [
  { label: 'Today', days: 1 },
  { label: '7D',   days: 7 },
  { label: '14D',  days: 14 },
  { label: '30D',  days: 30 },
  { label: '90D',  days: 90 },
]

function toISODate(d: Date) {
  return d.toISOString().slice(0, 10)
}

export default function Analytics() {
  const today = toISODate(new Date())

  // Filter state
  const [preset, setPreset]         = useState<number>(30)
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo]     = useState('')
  const [isCustom, setIsCustom]     = useState(false)
  const [channel, setChannel]       = useState('')
  const [brandId, setBrandId]       = useState('')
  const [orderType, setOrderType]   = useState('')

  // Derive effective date range
  const effectiveFrom = isCustom ? customFrom : toISODate(new Date(Date.now() - preset * 86400000))
  const effectiveTo   = isCustom ? customTo   : today
  const effectiveDays = isCustom ? undefined  : preset

  const hasActiveFilters = channel !== '' || brandId !== '' || orderType !== '' || isCustom

  function clearFilters() {
    setChannel('')
    setBrandId('')
    setOrderType('')
    setIsCustom(false)
    setCustomFrom('')
    setCustomTo('')
    setPreset(30)
  }

  function applyCustom() {
    if (customFrom && customTo && customFrom <= customTo) {
      setIsCustom(true)
    }
  }

  const { data: brands } = useQuery({
    queryKey: ['brands', 'active'],
    queryFn: () => getBrands({ is_active: true }),
  })

  const queryKey = [effectiveFrom, effectiveTo, effectiveDays, channel, brandId, orderType]

  const { data: volume, isLoading: volumeLoading } = useQuery({
    queryKey: ['orderVolume', ...queryKey],
    queryFn: () => fetchOrderVolume(
      effectiveDays ?? 30,
      brandId || undefined,
      channel || undefined,
      isCustom ? effectiveFrom : undefined,
      isCustom ? effectiveTo : undefined,
      orderType || undefined,
    ),
  })

  const { data: dash } = useQuery({
    queryKey: ['dashboard', ...queryKey],
    queryFn: () => fetchDashboard(effectiveFrom, effectiveTo, brandId || undefined, channel || undefined, orderType || undefined),
  })

  const { data: recentOrders } = useQuery({
    queryKey: ['orders', { page: 1, page_size: 100, brand_id: brandId }],
    queryFn: () => fetchOrders({ page: 1, page_size: 100, ...(brandId ? { brand_id: brandId } : {}) }),
  })

  const { data: returnsData } = useQuery({
    queryKey: ['returns-analytics', effectiveFrom, effectiveTo, brandId],
    queryFn: () => fetchReturns({ from_date: effectiveFrom, to_date: effectiveTo, limit: 500 }),
  })

  const avgValueData = volume?.map(v => ({
    date: v.date,
    avg_value: v.count > 0 ? +(v.total_revenue / v.count).toFixed(2) : 0,
  }))

  const totalOrders  = volume?.reduce((s, v) => s + v.count, 0) ?? 0
  const totalRevenue = volume?.reduce((s, v) => s + v.total_revenue, 0) ?? 0
  const avgOrderValue = totalOrders > 0 ? (totalRevenue / totalOrders).toFixed(2) : '0.00'

  const returnItems = returnsData?.items ?? []
  const totalReturns = returnsData?.total ?? 0
  const totalRefundAmount = returnItems.reduce((s, r) => s + (r.refund ? parseFloat(r.refund.amount) : 0), 0)
  const returnRate = totalOrders > 0 ? ((totalReturns / totalOrders) * 100).toFixed(1) : '0.0'

  const selectedBrand = brands?.find(b => b.id === brandId)
  const periodLabel   = isCustom
    ? `${effectiveFrom} — ${effectiveTo}`
    : DATE_PRESETS.find(p => p.days === preset)?.label ?? `${preset}D`

  const orderTypeBreakdown = dash?.orders_by_order_type ?? []
  const showOrderTypeChart = orderTypeBreakdown.length > 0 && orderTypeBreakdown.some(t => t.order_type !== 'RETAIL')

  return (
    <div className="p-6 space-y-6 max-w-7xl">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Analytics</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {periodLabel}
            {selectedBrand && <span className="ml-2 font-medium text-gray-700">· {selectedBrand.name}</span>}
            {channel && <span className="ml-2 font-medium text-gray-700">· {channel}</span>}
            {orderType && <span className="ml-2 font-medium text-gray-700">· {orderType}</span>}
          </p>
        </div>
        {hasActiveFilters && (
          <button
            onClick={clearFilters}
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-800 border border-gray-200 rounded-lg px-2.5 py-1.5 bg-white hover:bg-gray-50 transition-colors"
          >
            <X className="w-3.5 h-3.5" />
            Clear filters
          </button>
        )}
      </div>

      {/* Filter Bar */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          {/* Date presets */}
          <div className="flex items-center gap-1.5">
            <Calendar className="w-4 h-4 text-gray-400 flex-shrink-0" />
            <div className="flex items-center gap-1">
              {DATE_PRESETS.map(p => (
                <button
                  key={p.days}
                  onClick={() => { setPreset(p.days); setIsCustom(false) }}
                  className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                    !isCustom && preset === p.days
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Divider */}
          <div className="h-6 w-px bg-gray-200 hidden sm:block" />

          {/* Custom date range */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500 font-medium flex-shrink-0">Custom:</span>
            <input
              type="date"
              value={customFrom}
              max={customTo || today}
              onChange={e => { setCustomFrom(e.target.value); setIsCustom(false) }}
              className="input text-xs py-1 px-2 w-[130px]"
            />
            <span className="text-xs text-gray-400">to</span>
            <input
              type="date"
              value={customTo}
              min={customFrom}
              max={today}
              onChange={e => { setCustomTo(e.target.value); setIsCustom(false) }}
              className="input text-xs py-1 px-2 w-[130px]"
            />
            <button
              onClick={applyCustom}
              disabled={!customFrom || !customTo || customFrom > customTo}
              className="px-3 py-1.5 text-xs rounded-lg font-medium bg-blue-50 text-blue-700 hover:bg-blue-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Apply
            </button>
          </div>
        </div>

        {/* Second row: channel + brand + order type filters */}
        <div className="flex flex-wrap items-center gap-3 pt-0.5 border-t border-gray-100">
          {/* Channel */}
          <div className="flex items-center gap-1.5">
            <Layers className="w-4 h-4 text-gray-400" />
            <select
              value={channel}
              onChange={e => setChannel(e.target.value)}
              className="select text-xs py-1.5 pr-8 min-w-[140px]"
            >
              <option value="">All Channels</option>
              {CHANNELS.map(c => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>

          {/* Order Type */}
          <div className="flex items-center gap-1.5">
            <ShoppingBag className="w-4 h-4 text-gray-400" />
            <select
              value={orderType}
              onChange={e => setOrderType(e.target.value)}
              className="select text-xs py-1.5 pr-8 min-w-[140px]"
            >
              <option value="">All Types</option>
              {ORDER_TYPES.map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>

          {/* Brand (only shown when brands exist) */}
          {brands && brands.length > 0 && (
            <div className="flex items-center gap-1.5">
              <Tag className="w-4 h-4 text-gray-400" />
              <select
                value={brandId}
                onChange={e => setBrandId(e.target.value)}
                className="select text-xs py-1.5 pr-8 min-w-[150px]"
              >
                <option value="">All Brands</option>
                {brands.map(b => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </select>
            </div>
          )}

          {/* Active filter pills */}
          {hasActiveFilters && (
            <div className="flex items-center gap-1.5 ml-auto">
              <Filter className="w-3.5 h-3.5 text-blue-500" />
              <span className="text-xs text-blue-600 font-medium">
                {[
                  isCustom && 'Custom range',
                  channel && channel,
                  orderType && orderType,
                  selectedBrand && selectedBrand.name,
                ].filter(Boolean).join(' · ')}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* KPI Row — Orders / Revenue / AOV */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: `Orders (${periodLabel})`, value: totalOrders.toLocaleString(), color: 'text-blue-600' },
          {
            label: `Revenue (${periodLabel})`,
            value: totalRevenue >= 1000 ? `$${(totalRevenue / 1000).toFixed(1)}k` : `$${totalRevenue.toFixed(2)}`,
            color: 'text-green-600',
          },
          { label: 'Avg Order Value', value: `$${avgOrderValue}`, color: 'text-purple-600' },
        ].map(({ label, value, color }) => (
          <div key={label} className="card p-5">
            <p className="text-xs text-gray-500 font-medium">{label}</p>
            <p className={`text-3xl font-bold mt-1 ${color}`}>
              {volumeLoading ? <span className="animate-pulse">—</span> : value}
            </p>
          </div>
        ))}
      </div>

      {/* Returns KPI Row */}
      <div className="grid grid-cols-3 gap-4">
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-1">
            <RotateCcw className="w-4 h-4 text-orange-500" />
            <p className="text-xs text-gray-500 font-medium">Returns ({periodLabel})</p>
          </div>
          <p className="text-3xl font-bold text-orange-600">{totalReturns.toLocaleString()}</p>
        </div>
        <div className="card p-5">
          <p className="text-xs text-gray-500 font-medium mb-1">Refunds Issued</p>
          <p className="text-3xl font-bold text-red-600">
            {totalRefundAmount >= 1000
              ? `$${(totalRefundAmount / 1000).toFixed(1)}k`
              : `$${totalRefundAmount.toFixed(2)}`}
          </p>
        </div>
        <div className="card p-5">
          <p className="text-xs text-gray-500 font-medium mb-1">Return Rate</p>
          <p className={`text-3xl font-bold ${parseFloat(returnRate) > 10 ? 'text-red-600' : parseFloat(returnRate) > 5 ? 'text-amber-600' : 'text-green-600'}`}>
            {returnRate}%
          </p>
        </div>
      </div>

      {/* Volume + Revenue Line Chart */}
      <div className="card p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">
          Orders &amp; Revenue — {periodLabel}
          {selectedBrand && <span className="ml-2 text-xs font-normal text-gray-400">· {selectedBrand.name}</span>}
          {channel && <span className="ml-2 text-xs font-normal text-gray-400">· {channel}</span>}
          {orderType && <span className="ml-2 text-xs font-normal text-gray-400">· {orderType}</span>}
        </h2>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={volume ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: '#9ca3af' }}
              tickFormatter={v => v.slice(5)}
            />
            <YAxis yAxisId="orders" tick={{ fontSize: 10, fill: '#9ca3af' }} />
            <YAxis
              yAxisId="revenue"
              orientation="right"
              tick={{ fontSize: 10, fill: '#9ca3af' }}
              tickFormatter={v => `$${v}`}
            />
            <Tooltip
              contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
              formatter={(v: number, name: string) => [
                name === 'Revenue' ? `$${v.toFixed(2)}` : v,
                name,
              ]}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line yAxisId="orders"  type="monotone" dataKey="count"         name="Orders"  stroke="#3b82f6" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
            <Line yAxisId="revenue" type="monotone" dataKey="total_revenue" name="Revenue" stroke="#10b981" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Avg Order Value Trend */}
      <div className="card p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Average Order Value Trend</h2>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={avgValueData ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#9ca3af' }} tickFormatter={v => v.slice(5)} />
            <YAxis tick={{ fontSize: 10, fill: '#9ca3af' }} tickFormatter={v => `$${v}`} />
            <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} formatter={(v: number) => [`$${v.toFixed(2)}`, 'Avg Value']} />
            <Line type="monotone" dataKey="avg_value" name="Avg Value" stroke="#8b5cf6" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Bottom Row: Channel + Order Type (or Fulfillment) */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* Channel Breakdown */}
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Orders by Channel</h2>
          {dash?.orders_by_channel?.length ? (
            <div className="flex items-center gap-6">
              <ResponsiveContainer width={180} height={180}>
                <PieChart>
                  <Pie data={dash.orders_by_channel} dataKey="count" nameKey="channel" cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={2}>
                    {dash.orders_by_channel.map(entry => (
                      <Cell key={entry.channel} fill={CHANNEL_COLORS[entry.channel] ?? '#6b7280'} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8 }} />
                </PieChart>
              </ResponsiveContainer>
              <div className="flex-1 space-y-2">
                {dash.orders_by_channel.map(c => (
                  <div key={c.channel} className="flex items-center justify-between text-sm">
                    <div className="flex items-center gap-2">
                      <span className="w-3 h-3 rounded-sm flex-shrink-0" style={{ background: CHANNEL_COLORS[c.channel] ?? '#6b7280' }} />
                      <span className="text-gray-600">{c.channel}</span>
                    </div>
                    <span className="font-semibold text-gray-900">
                      {c.count} <span className="text-gray-400 font-normal text-xs">({c.percentage.toFixed(0)}%)</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-40 text-gray-400 text-sm">No data</div>
          )}
        </div>

        {/* Order Type breakdown (B2B vs Retail) — shown when mixed types exist, else Fulfillment Type */}
        {showOrderTypeChart ? (
          <div className="card p-5">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">B2B vs Retail Split</h2>
            <div className="flex items-center gap-6">
              <ResponsiveContainer width={180} height={180}>
                <PieChart>
                  <Pie data={orderTypeBreakdown} dataKey="count" nameKey="order_type" cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={2}>
                    {orderTypeBreakdown.map(entry => (
                      <Cell key={entry.order_type} fill={ORDER_TYPE_COLORS[entry.order_type] ?? '#6b7280'} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8 }} />
                </PieChart>
              </ResponsiveContainer>
              <div className="flex-1 space-y-3">
                {orderTypeBreakdown.map(t => (
                  <div key={t.order_type}>
                    <div className="flex items-center justify-between text-sm mb-1">
                      <div className="flex items-center gap-2">
                        <span className="w-3 h-3 rounded-sm flex-shrink-0" style={{ background: ORDER_TYPE_COLORS[t.order_type] ?? '#6b7280' }} />
                        <span className="text-gray-600">{t.order_type}</span>
                      </div>
                      <span className="font-semibold text-gray-900">
                        {t.count} <span className="text-gray-400 font-normal text-xs">({t.percentage.toFixed(0)}%)</span>
                      </span>
                    </div>
                    <p className="text-xs text-gray-400 ml-5">
                      ${t.total_revenue >= 1000 ? `${(t.total_revenue / 1000).toFixed(1)}k` : t.total_revenue.toFixed(0)} revenue
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="card p-5">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">Orders by Fulfillment Type</h2>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={dash?.orders_by_fulfillment_type ?? []} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
                <XAxis type="number" tick={{ fontSize: 10, fill: '#9ca3af' }} />
                <YAxis type="category" dataKey="fulfillment_type" tick={{ fontSize: 9, fill: '#6b7280' }} width={105} tickFormatter={v => v.replace(/_/g, ' ')} />
                <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8 }} formatter={(v: number) => [v, 'Orders']} />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {(dash?.orders_by_fulfillment_type ?? []).map((_, i) => (
                    <Cell key={i} fill={FULFILLMENT_COLORS[i % FULFILLMENT_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Fulfillment Type (shown when order type chart took its spot) */}
      {showOrderTypeChart && (
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Orders by Fulfillment Type</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={dash?.orders_by_fulfillment_type ?? []} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis type="number" tick={{ fontSize: 10, fill: '#9ca3af' }} />
              <YAxis type="category" dataKey="fulfillment_type" tick={{ fontSize: 9, fill: '#6b7280' }} width={105} tickFormatter={v => v.replace(/_/g, ' ')} />
              <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8 }} formatter={(v: number) => [v, 'Orders']} />
              <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                {(dash?.orders_by_fulfillment_type ?? []).map((_, i) => (
                  <Cell key={i} fill={FULFILLMENT_COLORS[i % FULFILLMENT_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Status Breakdown */}
      <div className="card p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Orders by Status</h2>
        {dash?.orders_by_status ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {Object.entries(dash.orders_by_status).map(([status, count]) => (
              <div key={status} className="bg-gray-50 rounded-xl p-3 text-center">
                <div className="flex justify-center mb-2"><StatusBadge value={status} /></div>
                <p className="text-2xl font-bold text-gray-900">{count as number}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-gray-400 text-sm">No data</p>
        )}
      </div>

      {/* Top Orders Table */}
      {recentOrders && recentOrders.items.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700">
              Recent High-Value Orders
              {selectedBrand && <span className="ml-2 text-xs font-normal text-gray-400">· {selectedBrand.name}</span>}
            </h2>
            <Link to={brandId ? `/orders?brand_id=${brandId}` : '/orders'} className="text-xs text-blue-600 hover:text-blue-800">
              View all →
            </Link>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  {['Order', 'Customer', 'Channel', 'Type', 'Status', 'Total', 'Date'].map(h => (
                    <th key={h} className="table-header">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {[...recentOrders.items]
                  .sort((a, b) => Number(b.total_amount) - Number(a.total_amount))
                  .slice(0, 10)
                  .map(order => (
                    <tr key={order.id} className="hover:bg-gray-50 transition-colors">
                      <td className="table-cell">
                        <Link to={`/orders/${order.id}`} className="text-blue-600 hover:text-blue-800 font-mono text-sm">
                          {order.order_number}
                        </Link>
                      </td>
                      <td className="table-cell text-gray-900">{order.customer_name || order.customer_email}</td>
                      <td className="table-cell"><StatusBadge value={order.channel} /></td>
                      <td className="table-cell">
                        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                          order.order_type === 'WHOLESALE' ? 'bg-amber-100 text-amber-700' :
                          order.order_type === 'B2B'       ? 'bg-emerald-100 text-emerald-700' :
                          'bg-blue-50 text-blue-600'
                        }`}>
                          {order.order_type ?? 'RETAIL'}
                        </span>
                      </td>
                      <td className="table-cell"><StatusBadge value={order.status} /></td>
                      <td className="table-cell font-bold text-gray-900">${order.total_amount}</td>
                      <td className="table-cell text-gray-500 text-xs">{order.created_at.slice(0, 10)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
