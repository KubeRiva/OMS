import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Plus, RefreshCw, Filter, ChevronLeft, ChevronRight, Eye, Trash2, Search, X } from 'lucide-react'
import { fetchOrders, createOrder, fetchProducts, fetchNodes, type OrderStatus, type OrderChannel, type FulfillmentType, type ProductSummary } from '../api/client'
import { StatusBadge } from '../components/Badge'
import Modal from '../components/Modal'

const STATUSES: OrderStatus[] = [
  'PENDING','CONFIRMED','SOURCED','PICKING','PACKING',
  'READY_TO_SHIP','SHIPPED','DELIVERED','CANCELLED'
]
const CHANNELS: OrderChannel[] = ['WEB','MOBILE','POS','API','MARKETPLACE']
const FULFILLMENT_TYPES: FulfillmentType[] = [
  'SHIP_TO_HOME','STORE_PICKUP','SHIP_FROM_STORE','CURBSIDE_PICKUP','SAME_DAY_DELIVERY'
]

interface LineItemForm {
  sku: string
  product_name: string
  quantity: number
  unit_price: number
}

// ─── Product search combobox for line items ───────────────────────────────────
function SkuSearchInput({
  value,
  onSelect,
}: {
  value: LineItemForm
  onSelect: (p: ProductSummary) => void
}) {
  const [query, setQuery] = useState(value.sku || '')
  const [open, setOpen] = useState(false)
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout>>()

  // Sync query when external value changes (e.g. on clear)
  useEffect(() => { setQuery(value.sku || '') }, [value.sku])

  const handleInput = (v: string) => {
    setQuery(v)
    setOpen(true)
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setDebouncedQuery(v), 300)
  }

  const { data: results } = useQuery({
    queryKey: ['product-search', debouncedQuery],
    queryFn: () => fetchProducts({ search: debouncedQuery || undefined, page_size: 20 }),
    enabled: open && debouncedQuery.length >= 1,
  })

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const select = (p: ProductSummary) => {
    setQuery(p.sku)
    setOpen(false)
    onSelect(p)
  }

  return (
    <div ref={containerRef} className="relative">
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
        <input
          className="input pl-8"
          value={query}
          onChange={e => handleInput(e.target.value)}
          onFocus={() => { setOpen(true); setDebouncedQuery(query) }}
          placeholder="Search SKU or product name…"
          autoComplete="off"
        />
      </div>
      {open && (
        <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-52 overflow-y-auto">
          {!debouncedQuery && (
            <p className="px-3 py-2 text-xs text-gray-400">Type to search products…</p>
          )}
          {debouncedQuery && (!results || results.length === 0) && (
            <p className="px-3 py-2 text-xs text-gray-400">No products found for "{debouncedQuery}"</p>
          )}
          {results?.map(p => (
            <button
              key={p.sku}
              type="button"
              onMouseDown={() => select(p)}
              className="w-full text-left px-3 py-2 hover:bg-blue-50 transition-colors border-b border-gray-50 last:border-0"
            >
              <p className="text-xs font-semibold text-gray-800">{p.sku}</p>
              <p className="text-xs text-gray-500">{p.product_name ?? '—'} · ${p.unit_cost.toFixed(2)} · {p.total_available} available</p>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

interface NewOrderForm {
  channel: OrderChannel
  fulfillment_type: FulfillmentType
  customer_email: string
  customer_name: string
  pickup_node_id: string
  address1: string
  city: string
  state: string
  postal_code: string
  country: string
  latitude: string
  longitude: string
  line_items: LineItemForm[]
}

const emptyLineItem = (): LineItemForm => ({ sku: '', product_name: '', quantity: 1, unit_price: 0 })

const defaultForm: NewOrderForm = {
  channel: 'WEB',
  fulfillment_type: 'SHIP_TO_HOME',
  customer_email: '',
  customer_name: '',
  pickup_node_id: '',
  address1: '',
  city: '',
  state: '',
  postal_code: '',
  country: 'US',
  latitude: '',
  longitude: '',
  line_items: [emptyLineItem()],
}

export default function Orders() {
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const [channel, setChannel] = useState('')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>()
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState<NewOrderForm>(defaultForm)
  const [error, setError] = useState('')

  const handleSearch = (v: string) => {
    setSearch(v)
    clearTimeout(searchTimerRef.current)
    searchTimerRef.current = setTimeout(() => { setDebouncedSearch(v); setPage(1) }, 300)
  }

  const params: Record<string, string | number> = { page, page_size: 20 }
  if (status) params.status = status
  if (channel) params.channel = channel
  if (debouncedSearch) params.search = debouncedSearch

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['orders', params],
    queryFn: () => fetchOrders(params),
  })

  const isPickupType = form.fulfillment_type === 'STORE_PICKUP' || form.fulfillment_type === 'CURBSIDE_PICKUP'
  const { data: nodesData } = useQuery({
    queryKey: ['nodes', 'pickup'],
    queryFn: () => fetchNodes({ page_size: 200 }),
    enabled: showCreate && isPickupType,
  })

  const createMutation = useMutation({
    mutationFn: createOrder,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['orders'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setShowCreate(false)
      setForm(defaultForm)
      setError('')
    },
    onError: (err: unknown) => {
      const e = err as { response?: { data?: { detail?: string } } }
      setError(e.response?.data?.detail ?? 'Failed to create order')
    },
  })

  const handleCreate = () => {
    if (!form.customer_email) { setError('Customer email is required'); return }
    if (form.line_items.length === 0) { setError('At least one line item is required'); return }
    for (const item of form.line_items) {
      if (!item.sku || !item.product_name) { setError('All line items must have SKU and product name'); return }
      if (item.quantity < 1) { setError('Quantity must be at least 1'); return }
    }

    if (isPickupType && !form.pickup_node_id) {
      setError('Please select a pickup store for this fulfillment type')
      return
    }

    const payload: Record<string, unknown> = {
      channel: form.channel,
      fulfillment_type: form.fulfillment_type,
      customer_email: form.customer_email,
      customer_name: form.customer_name,
      ...(form.pickup_node_id ? { pickup_node_id: form.pickup_node_id } : {}),
      line_items: form.line_items.map(item => ({
        sku: item.sku,
        product_name: item.product_name,
        quantity: Number(item.quantity),
        unit_price: Number(item.unit_price),
      })),
    }
    if (form.address1 && form.city) {
      payload.shipping_address = {
        address1: form.address1,
        city: form.city,
        state: form.state,
        postal_code: form.postal_code,
        country: form.country,
        latitude: form.latitude ? parseFloat(form.latitude) : undefined,
        longitude: form.longitude ? parseFloat(form.longitude) : undefined,
      }
    }
    createMutation.mutate(payload)
  }

  // Handlers for top-level form fields
  const set = (k: keyof Omit<NewOrderForm, 'line_items'>) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setForm(f => ({ ...f, [k]: e.target.value }))

  // Handlers for line item fields
  const setItem = (idx: number, k: keyof LineItemForm) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
      const val = (k === 'quantity' || k === 'unit_price') ? Number(e.target.value) : e.target.value
      setForm(f => ({
        ...f,
        line_items: f.line_items.map((item, i) => i === idx ? { ...item, [k]: val } : item),
      }))
    }

  // When user picks a product from the search dropdown — fills SKU, name, and price
  const selectProduct = (idx: number, p: ProductSummary) => {
    setForm(f => ({
      ...f,
      line_items: f.line_items.map((item, i) =>
        i === idx
          ? { ...item, sku: p.sku, product_name: p.product_name ?? '', unit_price: p.unit_cost }
          : item
      ),
    }))
  }

  const addItem = () => setForm(f => ({ ...f, line_items: [...f.line_items, emptyLineItem()] }))

  const removeItem = (idx: number) =>
    setForm(f => ({ ...f, line_items: f.line_items.filter((_, i) => i !== idx) }))

  const totalAmount = form.line_items.reduce((sum, item) => sum + item.unit_price * item.quantity, 0)

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Orders</h1>
          <p className="text-sm text-gray-500 mt-0.5">{data?.total ?? 0} total orders</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => refetch()} className="btn-secondary">
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
          <button onClick={() => setShowCreate(true)} className="btn-primary">
            <Plus className="w-4 h-4" /> New Order
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="card p-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
          <input
            className="input pl-9 pr-8"
            value={search}
            onChange={e => handleSearch(e.target.value)}
            placeholder="Search order #, customer name or email…"
          />
          {search && (
            <button
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              onClick={() => { handleSearch(''); setDebouncedSearch('') }}
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
        <Filter className="w-4 h-4 text-gray-400 flex-shrink-0" />
        <select className="select max-w-40" value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}>
          <option value="">All Statuses</option>
          {STATUSES.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
        </select>
        <select className="select max-w-36" value={channel} onChange={e => { setChannel(e.target.value); setPage(1) }}>
          <option value="">All Channels</option>
          {CHANNELS.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        {(status || channel || search) && (
          <button className="text-xs text-blue-600 hover:text-blue-800" onClick={() => { setStatus(''); setChannel(''); handleSearch(''); setDebouncedSearch(''); setPage(1) }}>
            Clear all
          </button>
        )}
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['Order #', 'Customer', 'Channel', 'Fulfillment', 'Status', 'Total', 'Created', ''].map(h => (
                  <th key={h} className="table-header">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {isLoading
                ? Array.from({ length: 8 }).map((_, i) => (
                    <tr key={i} className="animate-pulse">
                      {Array.from({ length: 8 }).map((_, j) => (
                        <td key={j} className="table-cell">
                          <div className="h-4 bg-gray-200 rounded w-24" />
                        </td>
                      ))}
                    </tr>
                  ))
                : data?.items.map(order => (
                    <tr key={order.id} className="hover:bg-gray-50 transition-colors">
                      <td className="table-cell">
                        <Link to={`/orders/${order.id}`} className="font-mono text-xs font-semibold text-blue-600 hover:text-blue-800">
                          {order.order_number}
                        </Link>
                      </td>
                      <td className="table-cell">
                        <div className="font-medium text-gray-900">{order.customer_name || '—'}</div>
                        <div className="text-xs text-gray-400">{order.customer_email}</div>
                      </td>
                      <td className="table-cell"><StatusBadge value={order.channel} /></td>
                      <td className="table-cell">
                        <span className="text-xs text-gray-600">{order.fulfillment_type.replace(/_/g, ' ')}</span>
                      </td>
                      <td className="table-cell"><StatusBadge value={order.status} /></td>
                      <td className="table-cell font-semibold text-gray-900">${order.total_amount}</td>
                      <td className="table-cell text-gray-500 text-xs">{order.created_at.slice(0, 16).replace('T', ' ')}</td>
                      <td className="table-cell">
                        <Link to={`/orders/${order.id}`} className="p-1.5 rounded-lg hover:bg-gray-100 inline-flex text-gray-400 hover:text-gray-600">
                          <Eye className="w-4 h-4" />
                        </Link>
                      </td>
                    </tr>
                  ))
              }
              {!isLoading && !data?.items.length && (
                <tr>
                  <td colSpan={8} className="text-center py-12 text-gray-400 text-sm">
                    No orders found. Create your first order!
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {data && data.total_pages > 1 && (
          <div className="px-5 py-3 border-t border-gray-100 flex items-center justify-between">
            <span className="text-xs text-gray-500">
              Page {data.page} of {data.total_pages} ({data.total} orders)
            </span>
            <div className="flex items-center gap-2">
              <button
                className="btn-secondary px-2 py-1.5 text-xs"
                disabled={page === 1}
                onClick={() => setPage(p => p - 1)}
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <button
                className="btn-secondary px-2 py-1.5 text-xs"
                disabled={page === data.total_pages}
                onClick={() => setPage(p => p + 1)}
              >
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Create Order Modal */}
      <Modal open={showCreate} onClose={() => { setShowCreate(false); setError(''); setForm(defaultForm) }} title="Create New Order" size="lg">
        <div className="space-y-4">
          {error && <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg">{error}</div>}

          {/* Order meta */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Channel *</label>
              <select className="select" value={form.channel} onChange={set('channel')}>
                {CHANNELS.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Fulfillment Type *</label>
              <select
                className="select"
                value={form.fulfillment_type}
                onChange={e => setForm(f => ({
                  ...f,
                  fulfillment_type: e.target.value as FulfillmentType,
                  pickup_node_id: '',  // reset store selection on type change
                }))}
              >
                {FULFILLMENT_TYPES.map(f => <option key={f} value={f}>{f.replace(/_/g, ' ')}</option>)}
              </select>
            </div>
          </div>

          {/* Pickup Store — shown only for STORE_PICKUP / CURBSIDE_PICKUP */}
          {isPickupType && (
            <div>
              <label className="label">
                Pickup Store *
                <span className="text-gray-400 font-normal ml-1">
                  (only stores with {form.fulfillment_type === 'CURBSIDE_PICKUP' ? 'curbside' : 'pickup'} capability)
                </span>
              </label>
              <select
                className="select"
                value={form.pickup_node_id}
                onChange={e => setForm(f => ({ ...f, pickup_node_id: e.target.value }))}
              >
                <option value="">— Select a store —</option>
                {(nodesData?.items ?? [])
                  .filter(n => form.fulfillment_type === 'CURBSIDE_PICKUP' ? n.can_curbside : n.can_pickup)
                  .map(n => (
                    <option key={n.id} value={n.id}>
                      {n.name} ({n.code}) — {n.city}, {n.state}
                    </option>
                  ))}
              </select>
            </div>
          )}

          {/* Customer */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Customer Email *</label>
              <input className="input" type="email" value={form.customer_email} onChange={set('customer_email')} placeholder="customer@example.com" />
            </div>
            <div>
              <label className="label">Customer Name</label>
              <input className="input" value={form.customer_name} onChange={set('customer_name')} placeholder="Full name" />
            </div>
          </div>

          {/* Line Items */}
          <div className="border-t pt-3">
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Line Items ({form.line_items.length})
              </p>
              <button
                type="button"
                className="btn-secondary text-xs py-1 px-2"
                onClick={addItem}
              >
                <Plus className="w-3.5 h-3.5" /> Add Item
              </button>
            </div>

            <div className="space-y-3">
              {form.line_items.map((item, idx) => (
                <div key={idx} className="p-3 bg-gray-50 rounded-lg border border-gray-100">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-gray-500">Item {idx + 1}</span>
                    {form.line_items.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeItem(idx)}
                        className="text-red-400 hover:text-red-600 transition-colors p-0.5 rounded"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                  <div className="space-y-2">
                    <div>
                      <label className="label">Product *</label>
                      <SkuSearchInput
                        value={item}
                        onSelect={p => selectProduct(idx, p)}
                      />
                      {item.sku && (
                        <p className="text-xs text-gray-400 mt-1">
                          Selected: <span className="font-mono font-semibold text-gray-600">{item.sku}</span>
                          {' · '}
                          <button
                            type="button"
                            className="text-red-400 hover:text-red-600"
                            onClick={() => setForm(f => ({
                              ...f,
                              line_items: f.line_items.map((li, i) => i === idx ? emptyLineItem() : li),
                            }))}
                          >
                            Clear
                          </button>
                        </p>
                      )}
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="label">Product Name *</label>
                        <input
                          className="input"
                          value={item.product_name}
                          onChange={setItem(idx, 'product_name')}
                          placeholder="Auto-filled from product"
                        />
                      </div>
                      <div>
                        <label className="label">Unit Price ($) *</label>
                        <input className="input" type="number" step="0.01" min={0} value={item.unit_price || ''} onChange={setItem(idx, 'unit_price')} placeholder="0.00" />
                      </div>
                      <div>
                        <label className="label">Quantity *</label>
                        <input className="input" type="number" min={1} value={item.quantity} onChange={setItem(idx, 'quantity')} />
                      </div>
                      <div className="flex items-end">
                        <div className="text-xs text-gray-500 pb-2">
                          Subtotal: <span className="font-semibold text-gray-700">${(item.unit_price * item.quantity).toFixed(2)}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {form.line_items.length > 0 && (
              <div className="mt-2 flex justify-end">
                <div className="text-xs text-gray-500 bg-gray-100 rounded px-3 py-1.5">
                  Order Total: <span className="font-bold text-gray-800">${totalAmount.toFixed(2)}</span>
                  <span className="text-gray-400 ml-1">({form.line_items.length} item{form.line_items.length !== 1 ? 's' : ''})</span>
                </div>
              </div>
            )}
          </div>

          {/* Shipping Address */}
          <div className="border-t pt-3">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Shipping Address</p>
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="label">Address</label>
                <input className="input" value={form.address1} onChange={set('address1')} placeholder="123 Main St" />
              </div>
              <div>
                <label className="label">City</label>
                <input className="input" value={form.city} onChange={set('city')} placeholder="New York" />
              </div>
              <div>
                <label className="label">State</label>
                <input className="input" value={form.state} onChange={set('state')} placeholder="NY" />
              </div>
              <div>
                <label className="label">ZIP Code</label>
                <input className="input" value={form.postal_code} onChange={set('postal_code')} placeholder="10001" />
              </div>
              <div>
                <label className="label">Country</label>
                <input className="input" value={form.country} onChange={set('country')} placeholder="US" />
              </div>
              <div>
                <label className="label">Latitude (optional)</label>
                <input className="input" type="number" step="any" value={form.latitude} onChange={set('latitude')} placeholder="40.7484" />
              </div>
              <div>
                <label className="label">Longitude (optional)</label>
                <input className="input" type="number" step="any" value={form.longitude} onChange={set('longitude')} placeholder="-73.9967" />
              </div>
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t">
            <button className="btn-secondary" onClick={() => { setShowCreate(false); setForm(defaultForm) }}>Cancel</button>
            <button
              className="btn-primary"
              onClick={handleCreate}
              disabled={createMutation.isPending}
            >
              {createMutation.isPending ? 'Creating...' : `Create Order (${form.line_items.length} item${form.line_items.length !== 1 ? 's' : ''})`}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
