import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FileText, Search, ChevronDown, ChevronUp } from 'lucide-react'
import {
  fetchInvoices, updateInvoiceStatus,
  type Invoice, type InvoiceStatus,
} from '../api/client'

const STATUS_COLORS: Record<InvoiceStatus, string> = {
  DRAFT: 'bg-gray-100 text-gray-600',
  SENT: 'bg-blue-100 text-blue-700',
  PAID: 'bg-green-100 text-green-700',
  OVERDUE: 'bg-red-100 text-red-700',
  VOID: 'bg-gray-100 text-gray-500',
}

const STATUS_OPTIONS: Array<InvoiceStatus | ''> = ['', 'DRAFT', 'SENT', 'PAID', 'OVERDUE', 'VOID']

function formatCurrency(amount: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(amount)
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
}

function getErrMsg(e: unknown): string {
  const err = e as { response?: { data?: { detail?: unknown } } }
  const detail = err.response?.data?.detail
  if (Array.isArray(detail)) return detail.map((d: { msg: string }) => d.msg).join(', ')
  if (typeof detail === 'string') return detail
  return 'An error occurred'
}

export default function Invoices() {
  const qc = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<InvoiceStatus | ''>('')
  const [accountSearch, setAccountSearch] = useState('')
  const [page, setPage] = useState(1)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [actionError, setActionError] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['invoices', statusFilter, accountSearch, page],
    queryFn: () => fetchInvoices({
      status: statusFilter || undefined,
      page,
      page_size: 20,
    }),
    placeholderData: prev => prev,
  })

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      updateInvoiceStatus(id, status),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['invoices'] }); setActionError('') },
    onError: (e: unknown) => setActionError(getErrMsg(e)),
  })

  const visibleItems = accountSearch.trim()
    ? (data?.items ?? []).filter(inv =>
        inv.customer_account_name?.toLowerCase().includes(accountSearch.toLowerCase())
      )
    : (data?.items ?? [])

  function toggleExpand(id: string) {
    setExpandedId(prev => (prev === id ? null : id))
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <FileText className="w-6 h-6 text-blue-600" />
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Invoices</h1>
            <p className="text-sm text-gray-500">B2B invoice management</p>
          </div>
        </div>
      </div>

      {/* Filter bar */}
      <div className="card flex flex-wrap gap-3 items-center">
        <select
          className="select"
          value={statusFilter}
          onChange={e => { setStatusFilter(e.target.value as InvoiceStatus | ''); setPage(1) }}
        >
          {STATUS_OPTIONS.map(s => (
            <option key={s} value={s}>{s === '' ? 'All statuses' : s}</option>
          ))}
        </select>

        <div className="flex-1 min-w-48 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            className="input pl-9 w-full"
            placeholder="Filter by customer account..."
            value={accountSearch}
            onChange={e => setAccountSearch(e.target.value)}
          />
        </div>

        {data && (
          <span className="text-sm text-gray-500 ml-auto">{data.total} invoices</span>
        )}
      </div>

      {actionError && (
        <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">{actionError}</div>
      )}

      {/* Table */}
      <div className="card overflow-hidden p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100">
              {['Invoice #', 'Customer Account', 'Order #', 'Status', 'Amount', 'Issued', 'Due', 'Actions'].map(h => (
                <th key={h} className="table-header">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {isLoading ? (
              <tr><td colSpan={8} className="text-center py-12 text-gray-400">Loading...</td></tr>
            ) : !visibleItems.length ? (
              <tr><td colSpan={8} className="text-center py-12 text-gray-400">No invoices found</td></tr>
            ) : visibleItems.map(inv => (
              <>
                <tr
                  key={inv.id}
                  className="hover:bg-gray-50 cursor-pointer"
                  onClick={() => toggleExpand(inv.id)}
                >
                  <td className="table-cell">
                    <div className="flex items-center gap-2">
                      {expandedId === inv.id
                        ? <ChevronUp className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                        : <ChevronDown className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                      }
                      <span className="font-mono font-medium text-gray-900">{inv.invoice_number}</span>
                    </div>
                  </td>
                  <td className="table-cell text-gray-700">
                    {inv.customer_account_name || inv.customer_account_id}
                  </td>
                  <td className="table-cell text-gray-500 font-mono text-xs">
                    {inv.order_number || '—'}
                  </td>
                  <td className="table-cell">
                    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[inv.status]}`}>
                      {inv.status}
                    </span>
                  </td>
                  <td className="table-cell font-medium text-gray-900">
                    {formatCurrency(inv.total_amount, inv.currency)}
                  </td>
                  <td className="table-cell text-gray-500">{formatDate(inv.issued_date)}</td>
                  <td className="table-cell text-gray-500">{formatDate(inv.due_date)}</td>
                  <td className="table-cell" onClick={e => e.stopPropagation()}>
                    <div className="flex items-center gap-1.5">
                      {inv.status === 'DRAFT' && (
                        <button
                          className="btn-secondary text-xs py-1 px-2"
                          disabled={statusMutation.isPending}
                          onClick={() => statusMutation.mutate({ id: inv.id, status: 'SENT' })}
                        >
                          Mark Sent
                        </button>
                      )}
                      {(inv.status === 'SENT' || inv.status === 'OVERDUE') && (
                        <button
                          className="btn-primary text-xs py-1 px-2"
                          disabled={statusMutation.isPending}
                          onClick={() => statusMutation.mutate({ id: inv.id, status: 'PAID' })}
                        >
                          Mark Paid
                        </button>
                      )}
                    </div>
                  </td>
                </tr>

                {expandedId === inv.id && (
                  <tr key={`${inv.id}-detail`} className="bg-gray-50">
                    <td colSpan={8} className="px-6 py-4">
                      <div className="grid grid-cols-4 gap-6 text-sm">
                        <div>
                          <div className="text-xs font-semibold text-gray-400 uppercase mb-2">Amounts</div>
                          <div className="space-y-1 text-gray-600">
                            <div className="flex justify-between">
                              <span>Subtotal</span>
                              <span className="font-medium">{formatCurrency(inv.subtotal, inv.currency)}</span>
                            </div>
                            <div className="flex justify-between">
                              <span>Tax</span>
                              <span className="font-medium">{formatCurrency(inv.tax_amount, inv.currency)}</span>
                            </div>
                            <div className="flex justify-between border-t pt-1 mt-1">
                              <span className="font-semibold">Total</span>
                              <span className="font-semibold">{formatCurrency(inv.total_amount, inv.currency)}</span>
                            </div>
                          </div>
                        </div>

                        <div>
                          <div className="text-xs font-semibold text-gray-400 uppercase mb-2">Payment</div>
                          <div className="space-y-1 text-gray-600">
                            <div className="flex justify-between">
                              <span>Terms</span>
                              <span className="font-medium">{inv.payment_terms.replace('_', ' ')}</span>
                            </div>
                            {inv.paid_date && (
                              <div className="flex justify-between">
                                <span>Paid</span>
                                <span className="font-medium text-green-700">{formatDate(inv.paid_date)}</span>
                              </div>
                            )}
                          </div>
                        </div>

                        <div>
                          <div className="text-xs font-semibold text-gray-400 uppercase mb-2">Dates</div>
                          <div className="space-y-1 text-gray-600">
                            <div className="flex justify-between">
                              <span>Created</span>
                              <span className="font-medium">{formatDate(inv.created_at)}</span>
                            </div>
                            <div className="flex justify-between">
                              <span>Issued</span>
                              <span className="font-medium">{formatDate(inv.issued_date)}</span>
                            </div>
                            <div className="flex justify-between">
                              <span>Due</span>
                              <span className="font-medium">{formatDate(inv.due_date)}</span>
                            </div>
                          </div>
                        </div>

                        {inv.notes && (
                          <div>
                            <div className="text-xs font-semibold text-gray-400 uppercase mb-2">Notes</div>
                            <p className="text-gray-600 text-xs italic">{inv.notes}</p>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {data && data.total_pages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-500">
          <span>Page {data.page} of {data.total_pages}</span>
          <div className="flex gap-2">
            <button className="btn-secondary" disabled={page === 1} onClick={() => setPage(p => p - 1)}>
              Previous
            </button>
            <button className="btn-secondary" disabled={page >= data.total_pages} onClick={() => setPage(p => p + 1)}>
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
