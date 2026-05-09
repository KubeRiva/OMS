import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { RotateCcw, ExternalLink } from 'lucide-react'
import {
  fetchReturns, updateReturnStatus, createReturnRefund,
  type OrderReturn, type ReturnListResponse,
} from '../api/client'
import { useAuth } from '../context/AuthContext'
import Modal from '../components/Modal'

// ─── Enums ────────────────────────────────────────────────────────────────────

const RETURN_STATUSES = [
  'REQUESTED', 'APPROVED', 'REJECTED', 'IN_TRANSIT', 'RECEIVED', 'RESTOCKED', 'COMPLETED',
] as const

const REFUND_METHODS = [
  'ORIGINAL_PAYMENT', 'STORE_CREDIT', 'BANK_TRANSFER', 'CHECK', 'OTHER',
] as const

// ─── Status badge ─────────────────────────────────────────────────────────────

function ReturnStatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    REQUESTED:  'bg-gray-100 text-gray-700',
    APPROVED:   'bg-blue-100 text-blue-700',
    IN_TRANSIT: 'bg-purple-100 text-purple-700',
    RECEIVED:   'bg-amber-100 text-amber-700',
    RESTOCKED:  'bg-teal-100 text-teal-700',
    COMPLETED:  'bg-green-100 text-green-700',
    REJECTED:   'bg-red-100 text-red-700',
  }
  const cls = colorMap[status] ?? 'bg-gray-100 text-gray-600'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold ${cls}`}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

// ─── Error helper ─────────────────────────────────────────────────────────────

function extractError(err: unknown): string {
  const e = err as { response?: { data?: { detail?: unknown } } }
  const detail = e?.response?.data?.detail
  if (!detail) return 'An error occurred'
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join('; ')
  return JSON.stringify(detail)
}

// ─── Update Status Modal ──────────────────────────────────────────────────────

function UpdateStatusModal({
  open, onClose, ret,
}: { open: boolean; onClose: () => void; ret: OrderReturn }) {
  const qc = useQueryClient()
  const [status, setStatus] = useState(ret.status)
  const [carrier, setCarrier] = useState(ret.return_carrier ?? '')
  const [tracking, setTracking] = useState(ret.return_tracking_number ?? '')
  const [staffNotes, setStaffNotes] = useState(ret.staff_notes ?? '')

  const mutation = useMutation({
    mutationFn: () => updateReturnStatus(ret.id, {
      status,
      staff_notes: staffNotes || undefined,
      return_tracking_number: tracking || undefined,
      return_carrier: carrier || undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['returns'] })
      onClose()
    },
  })

  return (
    <Modal open={open} onClose={onClose} title={`Update Status — ${ret.return_number}`} size="sm">
      <div className="space-y-4">
        <div>
          <label className="label">Status</label>
          <select className="select" value={status} onChange={e => setStatus(e.target.value)}>
            {RETURN_STATUSES.map(s => (
              <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Return Carrier</label>
          <input
            className="input"
            value={carrier}
            onChange={e => setCarrier(e.target.value)}
            placeholder="UPS, FedEx, USPS…"
          />
        </div>
        <div>
          <label className="label">Tracking Number</label>
          <input
            className="input"
            value={tracking}
            onChange={e => setTracking(e.target.value)}
            placeholder="Tracking number"
          />
        </div>
        <div>
          <label className="label">Staff Notes</label>
          <textarea
            className="input min-h-[72px] resize-none"
            value={staffNotes}
            onChange={e => setStaffNotes(e.target.value)}
            placeholder="Internal notes…"
          />
        </div>
        {mutation.isError && (
          <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded px-2 py-1">
            {extractError(mutation.error)}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button
            className="btn-primary"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ─── Create Refund Modal ──────────────────────────────────────────────────────

function CreateRefundModal({
  open, onClose, ret,
}: { open: boolean; onClose: () => void; ret: OrderReturn }) {
  const qc = useQueryClient()
  const [method, setMethod] = useState<string>('ORIGINAL_PAYMENT')
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const [txId, setTxId] = useState('')
  const [notes, setNotes] = useState('')

  const mutation = useMutation({
    mutationFn: () => createReturnRefund(ret.id, {
      refund_method: method,
      amount,
      reason,
      transaction_id: txId || undefined,
      notes: notes || undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['returns'] })
      onClose()
    },
  })

  return (
    <Modal open={open} onClose={onClose} title={`Create Refund — ${ret.return_number}`} size="sm">
      <div className="space-y-4">
        <div>
          <label className="label">Refund Method</label>
          <select className="select" value={method} onChange={e => setMethod(e.target.value)}>
            {REFUND_METHODS.map(m => (
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
            value={amount}
            onChange={e => setAmount(e.target.value)}
            placeholder="0.00"
          />
        </div>
        <div>
          <label className="label">Reason *</label>
          <input
            className="input"
            value={reason}
            onChange={e => setReason(e.target.value)}
            placeholder="Refund reason"
          />
        </div>
        <div>
          <label className="label">Transaction ID (optional)</label>
          <input
            className="input"
            value={txId}
            onChange={e => setTxId(e.target.value)}
            placeholder="Payment gateway transaction ID"
          />
        </div>
        <div>
          <label className="label">Notes (optional)</label>
          <textarea
            className="input min-h-[64px] resize-none"
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="Additional notes…"
          />
        </div>
        {mutation.isError && (
          <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded px-2 py-1">
            {extractError(mutation.error)}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button
            className="btn-primary"
            disabled={mutation.isPending || !reason || !amount}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? 'Saving…' : 'Create Refund'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

const PAGE_SIZE = 20

export default function Returns() {
  const { user } = useAuth()
  const nav = useNavigate()

  const [statusFilter, setStatusFilter] = useState('')
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [orderIdSearch, setOrderIdSearch] = useState('')
  const [page, setPage] = useState(0)

  const [statusModal, setStatusModal] = useState<OrderReturn | null>(null)
  const [refundModal, setRefundModal] = useState<OrderReturn | null>(null)

  const params = {
    status: statusFilter || undefined,
    order_id: orderIdSearch || undefined,
    from_date: fromDate || undefined,
    to_date: toDate || undefined,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  }

  const { data, isLoading, isError } = useQuery<ReturnListResponse>({
    queryKey: ['returns', params],
    queryFn: () => fetchReturns(params),
  })

  const returns = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.ceil(total / PAGE_SIZE)

  const canRefund = (ret: OrderReturn) =>
    user?.is_superadmin &&
    ['RECEIVED', 'COMPLETED'].includes(ret.status) &&
    !ret.refund

  return (
    <div className="p-6 space-y-5 max-w-6xl">
      {/* Header */}
      <div className="flex items-center gap-3">
        <RotateCcw className="w-6 h-6 text-gray-500" />
        <div>
          <h1 className="text-xl font-bold text-gray-900">Returns</h1>
          <p className="text-xs text-gray-500 mt-0.5">RMA & refund management</p>
        </div>
      </div>

      {/* Filters */}
      <div className="card p-4">
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="label">Status</label>
            <select
              className="select"
              value={statusFilter}
              onChange={e => { setStatusFilter(e.target.value); setPage(0) }}
            >
              <option value="">All Statuses</option>
              {RETURN_STATUSES.map(s => (
                <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">From Date</label>
            <input
              type="date"
              className="input"
              value={fromDate}
              onChange={e => { setFromDate(e.target.value); setPage(0) }}
            />
          </div>
          <div>
            <label className="label">To Date</label>
            <input
              type="date"
              className="input"
              value={toDate}
              onChange={e => { setToDate(e.target.value); setPage(0) }}
            />
          </div>
          <div>
            <label className="label">Search by Order ID</label>
            <input
              className="input"
              value={orderIdSearch}
              onChange={e => { setOrderIdSearch(e.target.value); setPage(0) }}
              placeholder="Order ID…"
            />
          </div>
          <div className="ml-auto flex items-end pb-0.5">
            <span className="text-xs text-gray-500">
              {isLoading ? 'Loading…' : `${total} return${total !== 1 ? 's' : ''}`}
            </span>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="card overflow-hidden p-0">
        {isError ? (
          <div className="p-6 text-sm text-red-600">Failed to load returns. Check API connectivity.</div>
        ) : isLoading ? (
          <div className="p-6 text-sm text-gray-400">Loading…</div>
        ) : returns.length === 0 ? (
          <div className="p-10 text-center">
            <RotateCcw className="w-8 h-8 text-gray-300 mx-auto mb-3" />
            <p className="text-sm text-gray-500">No returns found</p>
            <p className="text-xs text-gray-400 mt-1">Adjust your filters or initiate a return from an order.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  {['RMA #', 'Order', 'Status', 'Reason', 'Items', 'Tracking', 'Created', 'Actions'].map(h => (
                    <th key={h} className="table-header">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {returns.map(ret => (
                  <tr key={ret.id} className="hover:bg-gray-50 transition-colors">
                    <td className="table-cell font-mono text-xs font-semibold text-gray-700">
                      {ret.return_number}
                    </td>
                    <td className="table-cell">
                      <button
                        className="text-blue-600 hover:underline text-xs font-mono"
                        onClick={() => nav(`/orders/${ret.order_id}`)}
                      >
                        {ret.order_id.slice(0, 8)}…
                      </button>
                    </td>
                    <td className="table-cell">
                      <ReturnStatusBadge status={ret.status} />
                    </td>
                    <td className="table-cell text-xs text-gray-600">
                      {ret.reason.replace(/_/g, ' ')}
                    </td>
                    <td className="table-cell text-xs text-gray-500">
                      {ret.items.length} item{ret.items.length !== 1 ? 's' : ''}
                    </td>
                    <td className="table-cell">
                      {ret.return_tracking_number ? (
                        <div>
                          <p className="text-xs font-mono text-gray-700">{ret.return_tracking_number}</p>
                          {ret.return_carrier && (
                            <p className="text-[10px] text-gray-400">{ret.return_carrier}</p>
                          )}
                        </div>
                      ) : (
                        <span className="text-xs text-gray-400">—</span>
                      )}
                    </td>
                    <td className="table-cell text-xs text-gray-500">
                      {ret.created_at.slice(0, 10)}
                    </td>
                    <td className="table-cell">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {/* Update Status */}
                        {user?.is_superadmin ? (
                          <button
                            className="btn-secondary text-xs py-1 px-2"
                            onClick={() => setStatusModal(ret)}
                          >
                            Update Status
                          </button>
                        ) : (
                          <button
                            className="btn-secondary text-xs py-1 px-2 opacity-50 cursor-not-allowed"
                            disabled
                            title="Superadmin only"
                          >
                            Update Status
                          </button>
                        )}

                        {/* Create Refund */}
                        {canRefund(ret) ? (
                          <button
                            className="btn-primary text-xs py-1 px-2"
                            onClick={() => setRefundModal(ret)}
                          >
                            Create Refund
                          </button>
                        ) : !ret.refund && ['RECEIVED', 'COMPLETED'].includes(ret.status) && !user?.is_superadmin ? (
                          <button
                            className="btn-primary text-xs py-1 px-2 opacity-50 cursor-not-allowed"
                            disabled
                            title="Superadmin only"
                          >
                            Create Refund
                          </button>
                        ) : null}

                        {/* View Order */}
                        <button
                          className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800 transition-colors"
                          onClick={() => nav(`/orders/${ret.order_id}`)}
                          title="View order"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-gray-500">
          <span>
            Page {page + 1} of {totalPages} · {total} total
          </span>
          <div className="flex gap-2">
            <button
              className="btn-secondary py-1 px-3"
              disabled={page === 0}
              onClick={() => setPage(p => p - 1)}
            >
              Previous
            </button>
            <button
              className="btn-secondary py-1 px-3"
              disabled={page >= totalPages - 1}
              onClick={() => setPage(p => p + 1)}
            >
              Next
            </button>
          </div>
        </div>
      )}

      {/* Modals */}
      {statusModal && (
        <UpdateStatusModal
          open
          onClose={() => setStatusModal(null)}
          ret={statusModal}
        />
      )}
      {refundModal && (
        <CreateRefundModal
          open
          onClose={() => setRefundModal(null)}
          ret={refundModal}
        />
      )}
    </div>
  )
}
