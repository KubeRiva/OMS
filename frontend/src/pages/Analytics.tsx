import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { fetchOrderVolume, fetchDashboard, fetchOrders } from '../api/client'
import { StatusBadge } from '../components/Badge'
import { Link } from 'react-router-dom'

const CHANNEL_COLORS: Record<string, string> = {
  WEB: '#3b82f6', MOBILE: '#8b5cf6', POS: '#f59e0b',
  API: '#6b7280', MARKETPLACE: '#f97316',
}

const FULFILLMENT_COLORS = [
  '#6366f1', '#3b82f6', '#10b981', '#f59e0b', '#f97316',
]

export default function Analytics() {
  const [days, setDays] = useState(30)

  const { data: volume } = useQuery({
    queryKey: ['orderVolume', days],
    queryFn: () => fetchOrderVolume(days),
  })

  const { data: dash } = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => fetchDashboard(),
  })

  const { data: recentOrders } = useQuery({
    queryKey: ['orders', { page: 1, page_size: 100 }],
    queryFn: () => fetchOrders({ page: 1, page_size: 100 }),
  })

  // Compute avg order value trend from volume data
  const avgValueData = volume?.map(v => ({
    date: v.date,
    avg_value: v.count > 0 ? +(v.total_revenue / v.count).toFixed(2) : 0,
  }))

  const totalOrders = volume?.reduce((s, v) => s + v.count, 0) ?? 0
  const totalRevenue = volume?.reduce((s, v) => s + v.total_revenue, 0) ?? 0
  const avgOrderValue = totalOrders > 0 ? (totalRevenue / totalOrders).toFixed(2) : '0.00'

  return (
    <div className="p-6 space-y-6 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Analytics</h1>
          <p className="text-sm text-gray-500 mt-0.5">Order and revenue insights</p>
        </div>
        <div className="flex items-center gap-2">
          {[7, 14, 30, 60].map(d => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                days === d
                  ? 'bg-blue-600 text-white'
                  : 'bg-white text-gray-600 border border-gray-200 hover:bg-gray-50'
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: `Orders (${days}d)`, value: totalOrders.toLocaleString(), color: 'text-blue-600' },
          {
            label: `Revenue (${days}d)`,
            value: totalRevenue >= 1000 ? `$${(totalRevenue / 1000).toFixed(1)}k` : `$${totalRevenue.toFixed(2)}`,
            color: 'text-green-600',
          },
          { label: 'Avg Order Value', value: `$${avgOrderValue}`, color: 'text-purple-600' },
        ].map(({ label, value, color }) => (
          <div key={label} className="card p-5">
            <p className="text-xs text-gray-500 font-medium">{label}</p>
            <p className={`text-3xl font-bold mt-1 ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Volume + Revenue Line Chart */}
      <div className="card p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">
          Orders & Revenue — Last {days} Days
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
            <Line
              yAxisId="orders"
              type="monotone"
              dataKey="count"
              name="Orders"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
            <Line
              yAxisId="revenue"
              type="monotone"
              dataKey="total_revenue"
              name="Revenue"
              stroke="#10b981"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Avg Order Value Trend */}
      <div className="card p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Average Order Value Trend</h2>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={avgValueData ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: '#9ca3af' }}
              tickFormatter={v => v.slice(5)}
            />
            <YAxis
              tick={{ fontSize: 10, fill: '#9ca3af' }}
              tickFormatter={v => `$${v}`}
            />
            <Tooltip
              contentStyle={{ fontSize: 12, borderRadius: 8 }}
              formatter={(v: number) => [`$${v.toFixed(2)}`, 'Avg Value']}
            />
            <Line
              type="monotone"
              dataKey="avg_value"
              name="Avg Value"
              stroke="#8b5cf6"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Bottom Row: Channel + Fulfillment */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* Channel Breakdown */}
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Orders by Channel</h2>
          {dash?.orders_by_channel?.length ? (
            <div className="flex items-center gap-6">
              <ResponsiveContainer width={180} height={180}>
                <PieChart>
                  <Pie
                    data={dash.orders_by_channel}
                    dataKey="count"
                    nameKey="channel"
                    cx="50%"
                    cy="50%"
                    innerRadius={50}
                    outerRadius={80}
                    paddingAngle={2}
                  >
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
                      <span
                        className="w-3 h-3 rounded-sm flex-shrink-0"
                        style={{ background: CHANNEL_COLORS[c.channel] ?? '#6b7280' }}
                      />
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

        {/* Fulfillment Type Bar */}
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Orders by Fulfillment Type</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={dash?.orders_by_fulfillment_type ?? []} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis type="number" tick={{ fontSize: 10, fill: '#9ca3af' }} />
              <YAxis
                type="category"
                dataKey="fulfillment_type"
                tick={{ fontSize: 9, fill: '#6b7280' }}
                width={105}
                tickFormatter={v => v.replace(/_/g, ' ')}
              />
              <Tooltip
                contentStyle={{ fontSize: 11, borderRadius: 8 }}
                formatter={(v: number) => [v, 'Orders']}
              />
              <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                {(dash?.orders_by_fulfillment_type ?? []).map((_, i) => (
                  <Cell key={i} fill={FULFILLMENT_COLORS[i % FULFILLMENT_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Status Breakdown */}
      <div className="card p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Orders by Status</h2>
        {dash?.orders_by_status ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {Object.entries(dash.orders_by_status).map(([status, count]) => (
              <div key={status} className="bg-gray-50 rounded-xl p-3 text-center">
                <div className="flex justify-center mb-2">
                  <StatusBadge value={status} />
                </div>
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
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-700">Recent High-Value Orders</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  {['Order', 'Customer', 'Channel', 'Status', 'Total', 'Date'].map(h => (
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
