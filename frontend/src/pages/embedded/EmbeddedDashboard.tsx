import { useQuery } from '@tanstack/react-query'
import { ShoppingCart, Clock, Truck, AlertTriangle } from 'lucide-react'
import { fetchDashboard, fetchOrders, fetchInventorySummary } from '../../api/client'

interface KpiCardProps {
  title: string
  value: string | number
  subtitle?: string
  icon: React.ElementType
  iconColor: string
  iconBg: string
  loading?: boolean
}

function KpiCard({ title, value, subtitle, icon: Icon, iconColor, iconBg, loading }: KpiCardProps) {
  if (loading) {
    return (
      <div className="card p-5 animate-pulse">
        <div className="h-3 bg-gray-200 rounded w-2/3 mb-3" />
        <div className="h-7 bg-gray-200 rounded w-1/2" />
      </div>
    )
  }
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">{title}</p>
          <p className="mt-1.5 text-2xl font-bold text-gray-900">{value}</p>
          {subtitle && <p className="mt-0.5 text-xs text-gray-500">{subtitle}</p>}
        </div>
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${iconBg}`}>
          <Icon className={`w-5 h-5 ${iconColor}`} />
        </div>
      </div>
    </div>
  )
}

export default function EmbeddedDashboard() {
  const { data: dash, isLoading: dashLoading } = useQuery({
    queryKey: ['embedded', 'dashboard'],
    queryFn: () => fetchDashboard(),
    refetchInterval: 30_000,
  })

  const { data: pendingOrders, isLoading: pendingLoading } = useQuery({
    queryKey: ['embedded', 'orders', 'pending'],
    queryFn: () => fetchOrders({ status: 'PENDING', page: 1, page_size: 1 }),
    refetchInterval: 30_000,
  })

  const { data: inTransitOrders, isLoading: transitLoading } = useQuery({
    queryKey: ['embedded', 'orders', 'shipped'],
    queryFn: () => fetchOrders({ status: 'SHIPPED', page: 1, page_size: 1 }),
    refetchInterval: 30_000,
  })

  const { data: invSummary } = useQuery({
    queryKey: ['embedded', 'inventorySummary'],
    queryFn: fetchInventorySummary,
    refetchInterval: 60_000,
  })

  const omsUrl = window.location.origin

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-gray-900">KubeRiva Overview</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          {dash
            ? `${dash.period_start.slice(0, 10)} — ${dash.period_end.slice(0, 10)}`
            : 'Last 30 days'}
        </p>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-4">
        <KpiCard
          title="Total Orders"
          value={dash?.total_orders ?? '—'}
          subtitle="Last 30 days"
          icon={ShoppingCart}
          iconColor="text-blue-600"
          iconBg="bg-blue-50"
          loading={dashLoading}
        />
        <KpiCard
          title="Pending Orders"
          value={pendingOrders?.total ?? '—'}
          subtitle="Awaiting processing"
          icon={Clock}
          iconColor="text-amber-600"
          iconBg="bg-amber-50"
          loading={pendingLoading}
        />
        <KpiCard
          title="In Transit"
          value={inTransitOrders?.total ?? '—'}
          subtitle="Shipped, not delivered"
          icon={Truck}
          iconColor="text-green-600"
          iconBg="bg-green-50"
          loading={transitLoading}
        />
        <KpiCard
          title="Low Stock Alerts"
          value={invSummary?.low_stock_count ?? '—'}
          subtitle={invSummary ? `${invSummary.total_skus} total SKUs` : undefined}
          icon={AlertTriangle}
          iconColor="text-red-600"
          iconBg="bg-red-50"
        />
      </div>

      {/* Link to full OMS */}
      <div className="card p-4">
        <p className="text-sm text-gray-600">
          For the complete Order Management System including inventory management,
          sourcing rules, analytics, and AI assistant, visit the full KubeRiva.
        </p>
        <a
          href={omsUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="btn-primary mt-3 inline-flex items-center gap-1.5 text-sm"
        >
          Open KubeRiva
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </a>
      </div>
    </div>
  )
}
