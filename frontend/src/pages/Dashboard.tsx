import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import {
  ShoppingCart, DollarSign, TrendingUp, AlertTriangle,
  ArrowRight, Sparkles, Tag, Layers, X,
} from 'lucide-react'
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts'
import { fetchDashboard, fetchOrderVolume, fetchInventorySummary, fetchOrders, getBrands } from '../api/client'
import StatCard from '../components/StatCard'
import { StatusBadge } from '../components/Badge'

const CHANNEL_COLORS: Record<string, string> = {
  WEB: '#3b82f6', MOBILE: '#8b5cf6', POS: '#f59e0b',
  API: '#6b7280', MARKETPLACE: '#f97316', B2B: '#10b981',
}

const CHANNELS = ['WEB', 'MOBILE', 'POS', 'API', 'MARKETPLACE', 'B2B', 'EDI', 'WHOLESALE']

const DATE_PRESETS = [
  { label: '7D',  days: 7 },
  { label: '30D', days: 30 },
  { label: '90D', days: 90 },
]

const AI_QUICK = [
  'Give me an analytics summary for the last 30 days',
  'Which SKUs are low on stock?',
  'Show me all pending orders',
]

function toISODate(d: Date) { return d.toISOString().slice(0, 10) }

export default function Dashboard() {
  const navigate = useNavigate()
  const today = toISODate(new Date())

  const [days, setDays]     = useState(30)
  const [channel, setChannel] = useState('')
  const [brandId, setBrandId] = useState('')

  const fromDate = toISODate(new Date(Date.now() - days * 86400000))
  const hasFilters = channel !== '' || brandId !== ''

  const { data: brands } = useQuery({
    queryKey: ['brands', 'active'],
    queryFn: () => getBrands({ is_active: true }),
  })

  const { data: dash, isLoading: dashLoading } = useQuery({
    queryKey: ['dashboard', fromDate, today, brandId, channel],
    queryFn: () => fetchDashboard(fromDate, today, brandId || undefined, channel || undefined),
  })
  const { data: volume } = useQuery({
    queryKey: ['orderVolume', days, brandId, channel],
    queryFn: () => fetchOrderVolume(days, brandId || undefined, channel || undefined),
  })
  const { data: invSummary } = useQuery({
    queryKey: ['inventorySummary'],
    queryFn: fetchInventorySummary,
  })
  const { data: recentOrders } = useQuery({
    queryKey: ['orders', { page: 1, page_size: 8, brand_id: brandId }],
    queryFn: () => fetchOrders({ page: 1, page_size: 8, ...(brandId ? { brand_id: brandId } : {}) }),
  })

  const fmt = (n: number) =>
    n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${n.toFixed(2)}`

  const selectedBrand = brands?.find(b => b.id === brandId)

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {fromDate} — {today}
            {selectedBrand && <span className="ml-2 font-medium text-gray-700">· {selectedBrand.name}</span>}
            {channel && <span className="ml-2 font-medium text-gray-700">· {channel}</span>}
          </p>
        </div>
        {hasFilters && (
          <button
            onClick={() => { setChannel(''); setBrandId('') }}
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-800 border border-gray-200 rounded-lg px-2.5 py-1.5 bg-white hover:bg-gray-50 transition-colors"
          >
            <X className="w-3.5 h-3.5" /> Clear filters
          </button>
        )}
      </div>

      {/* Filter Bar */}
      <div className="flex flex-wrap items-center gap-3 bg-white border border-gray-200 rounded-xl px-4 py-3">
        {/* Date presets */}
        <div className="flex items-center gap-1">
          {DATE_PRESETS.map(p => (
            <button
              key={p.days}
              onClick={() => setDays(p.days)}
              className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                days === p.days ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>

        <div className="h-5 w-px bg-gray-200" />

        {/* Channel */}
        <div className="flex items-center gap-1.5">
          <Layers className="w-4 h-4 text-gray-400" />
          <select
            value={channel}
            onChange={e => setChannel(e.target.value)}
            className="select text-xs py-1.5 pr-8 min-w-[140px]"
          >
            <option value="">All Channels</option>
            {CHANNELS.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>

        {/* Brand */}
        {brands && brands.length > 0 && (
          <div className="flex items-center gap-1.5">
            <Tag className="w-4 h-4 text-gray-400" />
            <select
              value={brandId}
              onChange={e => setBrandId(e.target.value)}
              className="select text-xs py-1.5 pr-8 min-w-[150px]"
            >
              <option value="">All Brands</option>
              {brands.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </div>
        )}
      </div>

      {/* AI Quick-access banner */}
      <div className="flex items-center gap-4 bg-gradient-to-r from-blue-600 to-purple-600 rounded-xl p-4 text-white">
        <div className="w-9 h-9 rounded-lg bg-white/20 flex items-center justify-center flex-shrink-0">
          <Sparkles className="w-5 h-5" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold">Ask AI about your operations</p>
          <div className="flex flex-wrap gap-2 mt-1.5">
            {AI_QUICK.map(q => (
              <button
                key={q}
                onClick={() => navigate('/ai')}
                className="text-[11px] bg-white/20 hover:bg-white/30 rounded-full px-2.5 py-1 transition-colors truncate max-w-xs"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
        <button
          onClick={() => navigate('/ai')}
          className="flex-shrink-0 text-xs bg-white text-blue-700 font-semibold rounded-lg px-3 py-2 hover:bg-blue-50 transition-colors"
        >
          Open AI →
        </button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Total Orders"
          value={dash?.total_orders ?? '—'}
          icon={ShoppingCart}
          iconColor="text-blue-600"
          loading={dashLoading}
        />
        <StatCard
          title="Revenue"
          value={dash ? fmt(dash.total_revenue) : '—'}
          icon={DollarSign}
          iconColor="text-green-600"
          loading={dashLoading}
        />
        <StatCard
          title="Avg Order Value"
          value={dash ? `$${dash.avg_order_value.toFixed(2)}` : '—'}
          icon={TrendingUp}
          iconColor="text-purple-600"
          loading={dashLoading}
        />
        <StatCard
          title="Low Stock Alerts"
          value={invSummary?.low_stock_count ?? '—'}
          subtitle={`${invSummary?.total_skus ?? 0} total SKUs`}
          icon={AlertTriangle}
          iconColor="text-amber-600"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Order Volume Line Chart */}
        <div className="card p-5 xl:col-span-2">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">
            Order Volume — Last 30 Days
            {selectedBrand && <span className="ml-2 text-xs font-normal text-gray-400">· {selectedBrand.name}</span>}
          </h2>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={volume ?? []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: '#9ca3af' }}
                tickFormatter={v => v.slice(5)}
              />
              <YAxis tick={{ fontSize: 10, fill: '#9ca3af' }} />
              <Tooltip
                contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
                formatter={(v: number, name: string) => [
                  name === 'total_revenue' ? `$${v.toFixed(2)}` : v,
                  name === 'total_revenue' ? 'Revenue' : 'Orders',
                ]}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line type="monotone" dataKey="count" name="Orders" stroke="#3b82f6" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="total_revenue" name="Revenue" stroke="#10b981" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Channel Pie */}
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Orders by Channel</h2>
          {dash?.orders_by_channel?.length ? (
            <>
              <ResponsiveContainer width="100%" height={160}>
                <PieChart>
                  <Pie
                    data={dash.orders_by_channel}
                    dataKey="count"
                    nameKey="channel"
                    cx="50%"
                    cy="50%"
                    innerRadius={45}
                    outerRadius={70}
                    paddingAngle={2}
                  >
                    {dash.orders_by_channel.map(entry => (
                      <Cell key={entry.channel} fill={CHANNEL_COLORS[entry.channel] ?? '#6b7280'} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8 }} />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-1.5 mt-2">
                {dash.orders_by_channel.map(c => (
                  <div key={c.channel} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                        style={{ background: CHANNEL_COLORS[c.channel] ?? '#6b7280' }} />
                      <span className="text-gray-600">{c.channel}</span>
                    </div>
                    <span className="font-medium text-gray-900">{c.count} ({c.percentage.toFixed(0)}%)</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="flex items-center justify-center h-40 text-gray-400 text-sm">No data yet</div>
          )}
        </div>
      </div>

      {/* Bottom Row */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Orders by Status */}
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Orders by Status</h2>
          {dash?.orders_by_status ? (
            <div className="space-y-2">
              {Object.entries(dash.orders_by_status).map(([status, count]) => (
                <div key={status} className="flex items-center justify-between">
                  <StatusBadge value={status} />
                  <span className="text-sm font-semibold text-gray-900">{count}</span>
                </div>
              ))}
            </div>
          ) : <div className="h-20 flex items-center justify-center text-gray-400 text-sm">No data</div>}
        </div>

        {/* Fulfillment Type Bar */}
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Fulfillment Types</h2>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={dash?.orders_by_fulfillment_type ?? []} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis type="number" tick={{ fontSize: 10, fill: '#9ca3af' }} />
              <YAxis
                type="category"
                dataKey="fulfillment_type"
                tick={{ fontSize: 9, fill: '#6b7280' }}
                width={90}
                tickFormatter={v => v.replace(/_/g, ' ')}
              />
              <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8 }} />
              <Bar dataKey="count" fill="#6366f1" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Inventory Summary */}
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Inventory Health</h2>
          {invSummary ? (
            <div className="space-y-3">
              {[
                { label: 'Total SKUs', value: invSummary.total_skus, color: 'text-gray-900' },
                { label: 'Units On Hand', value: invSummary.total_on_hand.toLocaleString(), color: 'text-gray-900' },
                { label: 'Available', value: invSummary.total_available.toLocaleString(), color: 'text-green-600' },
                { label: 'Reserved', value: invSummary.total_reserved.toLocaleString(), color: 'text-blue-600' },
                { label: 'Low Stock', value: invSummary.low_stock_count, color: 'text-amber-600' },
              ].map(({ label, value, color }) => (
                <div key={label} className="flex justify-between items-center">
                  <span className="text-xs text-gray-500">{label}</span>
                  <span className={`text-sm font-semibold ${color}`}>{value}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="space-y-3 animate-pulse">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex justify-between">
                  <div className="h-3 bg-gray-200 rounded w-24" />
                  <div className="h-3 bg-gray-200 rounded w-12" />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Recent Orders */}
      <div className="card">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700">
            Recent Orders
            {selectedBrand && <span className="ml-2 text-xs font-normal text-gray-400">· {selectedBrand.name}</span>}
          </h2>
          <Link
            to={brandId ? `/orders?brand_id=${brandId}` : '/orders'}
            className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1"
          >
            View all <ArrowRight className="w-3 h-3" />
          </Link>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50">
              <tr>
                {['Order', 'Customer', 'Channel', 'Status', 'Total', 'Created'].map(h => (
                  <th key={h} className="table-header">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {recentOrders?.items.map(order => (
                <tr key={order.id} className="hover:bg-gray-50 transition-colors">
                  <td className="table-cell">
                    <Link to={`/orders/${order.id}`} className="font-medium text-blue-600 hover:text-blue-800">
                      {order.order_number}
                    </Link>
                  </td>
                  <td className="table-cell text-gray-900">{order.customer_name || order.customer_email}</td>
                  <td className="table-cell"><StatusBadge value={order.channel} /></td>
                  <td className="table-cell"><StatusBadge value={order.status} /></td>
                  <td className="table-cell font-medium">${order.total_amount}</td>
                  <td className="table-cell text-gray-500">{order.created_at.slice(0, 10)}</td>
                </tr>
              ))}
              {!recentOrders?.items.length && (
                <tr>
                  <td colSpan={6} className="table-cell text-center text-gray-400 py-8">No orders yet</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
