import { useState } from 'react'
import type { ElementType } from 'react'
import { useQuery } from '@tanstack/react-query'
import { MapPin, RefreshCw, Warehouse, Store, Moon } from 'lucide-react'
import { fetchNodes, type FulfillmentNode } from '../api/client'
import { StatusBadge } from '../components/Badge'

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

function NodeCard({ node }: { node: FulfillmentNode }) {
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
    </div>
  )
}

export default function Nodes() {
  const [typeFilter, setTypeFilter] = useState('')

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['nodes'],
    queryFn: () => fetchNodes({ page: 1, page_size: 100 }),
  })

  const nodes = data?.items ?? []
  const filtered = typeFilter ? nodes.filter(n => n.node_type === typeFilter) : nodes

  const types = [...new Set(nodes.map(n => n.node_type))]

  // Summary counts
  const active = nodes.filter(n => n.status === 'ACTIVE').length
  const avgLoad = nodes.length > 0
    ? nodes.reduce((s, n) => s + (n.daily_order_capacity > 0 ? n.current_daily_orders / n.daily_order_capacity : 0), 0) / nodes.length * 100
    : 0

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
        <button onClick={() => refetch()} className="btn-secondary">
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
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
            <NodeCard key={node.id} node={node} />
          ))}
        </div>
      )}
    </div>
  )
}
