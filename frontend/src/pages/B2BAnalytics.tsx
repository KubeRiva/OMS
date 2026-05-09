import { useQuery } from '@tanstack/react-query'
import { BarChart2 } from 'lucide-react'
import { fetchInvoices, fetchCustomerAccounts, fetchOrders, type Invoice, type InvoiceStatus } from '../api/client'

const STATUS_COLORS: Record<InvoiceStatus, string> = {
  DRAFT: 'bg-gray-400',
  SENT: 'bg-blue-500',
  PAID: 'bg-green-500',
  OVERDUE: 'bg-red-500',
  VOID: 'bg-gray-300',
}

const ALL_STATUSES: InvoiceStatus[] = ['DRAFT', 'SENT', 'PAID', 'OVERDUE', 'VOID']

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(amount)
}

interface AccountRow {
  id: string
  company_name: string
  paid: number
  outstanding: number
  overdue: number
  credit_used: number
  credit_limit: number
}

function deriveAccountRows(invoices: Invoice[], accountMap: Map<string, { credit_used: number; credit_limit: number }>): AccountRow[] {
  const byAccount = new Map<string, { company_name: string; paid: number; outstanding: number; overdue: number }>()

  for (const inv of invoices) {
    const existing = byAccount.get(inv.customer_account_id) ?? {
      company_name: inv.customer_account_name ?? inv.customer_account_id,
      paid: 0,
      outstanding: 0,
      overdue: 0,
    }
    if (inv.status === 'PAID') existing.paid += inv.total_amount
    if (inv.status === 'SENT') existing.outstanding += inv.total_amount
    if (inv.status === 'OVERDUE') { existing.outstanding += inv.total_amount; existing.overdue += inv.total_amount }
    byAccount.set(inv.customer_account_id, existing)
  }

  return Array.from(byAccount.entries()).map(([id, row]) => {
    const credit = accountMap.get(id) ?? { credit_used: 0, credit_limit: 0 }
    return { id, ...row, ...credit }
  }).sort((a, b) => b.paid - a.paid)
}

export default function B2BAnalytics() {
  const { data: invoiceData, isLoading: invoicesLoading } = useQuery({
    queryKey: ['b2b-analytics', 'invoices'],
    queryFn: () => fetchInvoices({ page_size: 500 }),
  })

  const { data: customersData, isLoading: customersLoading } = useQuery({
    queryKey: ['b2b-analytics', 'customers'],
    queryFn: () => fetchCustomerAccounts({ page_size: 500, is_active: true }),
  })

  const { data: ordersData, isLoading: ordersLoading } = useQuery({
    queryKey: ['b2b-analytics', 'orders'],
    queryFn: () => fetchOrders({ order_type: 'B2B', page_size: 100 }),
  })

  const isLoading = invoicesLoading || customersLoading || ordersLoading

  const invoices: Invoice[] = invoiceData?.items ?? []

  // KPI derivations
  const totalRevenue = invoices.filter(i => i.status === 'PAID').reduce((s, i) => s + i.total_amount, 0)
  const outstandingBalance = invoices.filter(i => i.status === 'SENT' || i.status === 'OVERDUE').reduce((s, i) => s + i.total_amount, 0)
  const overdueAmount = invoices.filter(i => i.status === 'OVERDUE').reduce((s, i) => s + i.total_amount, 0)
  const activeAccounts = (customersData?.items ?? []).filter(a => parseFloat(a.credit_limit) > 0).length

  // Credit map for account rows
  const accountMap = new Map<string, { credit_used: number; credit_limit: number }>(
    (customersData?.items ?? []).map(a => [
      a.id,
      { credit_used: parseFloat(a.credit_used) || 0, credit_limit: parseFloat(a.credit_limit) || 0 },
    ])
  )
  const accountRows = deriveAccountRows(invoices, accountMap)

  // Status breakdown
  const statusCounts = ALL_STATUSES.map(status => ({
    status,
    count: invoices.filter(i => i.status === status).length,
  }))
  const totalInvoices = invoices.length || 1

  // Approval funnel
  const orders = ordersData?.items ?? []
  const approvalCounts: Record<string, number> = {
    NOT_REQUIRED: 0,
    PENDING: 0,
    APPROVED: 0,
    REJECTED: 0,
  }
  for (const o of orders) {
    if (o.approval_status in approvalCounts) {
      approvalCounts[o.approval_status]++
    }
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center gap-3">
        <BarChart2 className="w-6 h-6 text-blue-600" />
        <div>
          <h1 className="text-xl font-semibold text-gray-900">B2B Analytics</h1>
          <p className="text-sm text-gray-500">Revenue, invoices, and approval pipeline</p>
        </div>
      </div>

      {isLoading && (
        <div className="text-center py-16 text-gray-400">Loading analytics...</div>
      )}

      {!isLoading && (
        <>
          {/* Section 1 — KPI Cards */}
          <div className="grid grid-cols-4 gap-4">
            <div className="card">
              <div className="text-xs font-semibold text-gray-400 uppercase mb-1">Total B2B Revenue</div>
              <div className="text-2xl font-bold text-gray-900">{formatCurrency(totalRevenue)}</div>
              <div className="text-xs text-gray-400 mt-1">From paid invoices</div>
            </div>
            <div className="card">
              <div className="text-xs font-semibold text-gray-400 uppercase mb-1">Outstanding Balance</div>
              <div className="text-2xl font-bold text-blue-700">{formatCurrency(outstandingBalance)}</div>
              <div className="text-xs text-gray-400 mt-1">Sent + overdue</div>
            </div>
            <div className="card">
              <div className="text-xs font-semibold text-gray-400 uppercase mb-1">Overdue Amount</div>
              <div className={`text-2xl font-bold ${overdueAmount > 0 ? 'text-red-600' : 'text-gray-900'}`}>
                {formatCurrency(overdueAmount)}
              </div>
              <div className="text-xs text-gray-400 mt-1">Past due date</div>
            </div>
            <div className="card">
              <div className="text-xs font-semibold text-gray-400 uppercase mb-1">Active Accounts</div>
              <div className="text-2xl font-bold text-gray-900">{activeAccounts}</div>
              <div className="text-xs text-gray-400 mt-1">With credit limit</div>
            </div>
          </div>

          {/* Section 2 — Revenue by Account */}
          <div className="card p-0">
            <div className="px-6 py-4 border-b border-gray-100">
              <h2 className="text-base font-semibold text-gray-900">Revenue by Account</h2>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100">
                  {['Company', 'Paid Revenue', 'Outstanding', 'Overdue', 'Credit Used / Limit'].map(h => (
                    <th key={h} className="table-header">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {accountRows.length === 0 ? (
                  <tr><td colSpan={5} className="text-center py-8 text-gray-400">No data</td></tr>
                ) : accountRows.map(row => {
                  const creditPct = row.credit_limit > 0
                    ? Math.min(100, Math.round((row.credit_used / row.credit_limit) * 100))
                    : 0
                  return (
                    <tr key={row.id} className="hover:bg-gray-50">
                      <td className="table-cell font-medium text-gray-900">{row.company_name}</td>
                      <td className="table-cell text-green-700 font-medium">{formatCurrency(row.paid)}</td>
                      <td className="table-cell text-blue-700">{formatCurrency(row.outstanding)}</td>
                      <td className="table-cell">
                        {row.overdue > 0
                          ? <span className="text-red-600 font-medium">{formatCurrency(row.overdue)}</span>
                          : <span className="text-gray-400">—</span>
                        }
                      </td>
                      <td className="table-cell">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 bg-gray-200 rounded-full h-1.5 max-w-24">
                            <div
                              className={`h-1.5 rounded-full ${creditPct > 80 ? 'bg-red-500' : 'bg-blue-500'}`}
                              style={{ width: `${creditPct}%` }}
                            />
                          </div>
                          <span className="text-xs text-gray-500 whitespace-nowrap">
                            {formatCurrency(row.credit_used)} / {formatCurrency(row.credit_limit)}
                          </span>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Section 3 — Invoice Status Breakdown */}
          <div className="card">
            <h2 className="text-base font-semibold text-gray-900 mb-5">Invoice Status Breakdown</h2>
            <div className="space-y-3">
              {statusCounts.map(({ status, count }) => {
                const pct = Math.round((count / totalInvoices) * 100)
                return (
                  <div key={status} className="flex items-center gap-3">
                    <div className="w-20 text-sm font-medium text-gray-600 shrink-0">{status}</div>
                    <div className="flex-1 bg-gray-100 rounded-full h-5 overflow-hidden">
                      <div
                        className={`h-5 rounded-full ${STATUS_COLORS[status]} transition-all`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <div className="w-24 text-right text-sm text-gray-600 shrink-0">
                      {count} <span className="text-gray-400">({pct}%)</span>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Section 4 — Approval Funnel */}
          <div>
            <h2 className="text-base font-semibold text-gray-900 mb-4">B2B Order Approval Funnel</h2>
            <div className="grid grid-cols-4 gap-4">
              {[
                { key: 'NOT_REQUIRED', label: 'No Approval Needed', color: 'text-gray-700', bg: 'bg-gray-50' },
                { key: 'PENDING', label: 'Pending Approval', color: 'text-amber-700', bg: 'bg-amber-50' },
                { key: 'APPROVED', label: 'Approved', color: 'text-green-700', bg: 'bg-green-50' },
                { key: 'REJECTED', label: 'Rejected', color: 'text-red-700', bg: 'bg-red-50' },
              ].map(({ key, label, color, bg }) => (
                <div key={key} className={`card ${bg} border border-gray-100`}>
                  <div className="text-xs font-semibold text-gray-400 uppercase mb-1">{label}</div>
                  <div className={`text-3xl font-bold ${color}`}>{approvalCounts[key] ?? 0}</div>
                  <div className="text-xs text-gray-400 mt-1">orders</div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
