import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Package, Search, Plus, Edit2, ChevronDown, ChevronUp,
  AlertTriangle, TrendingUp, RefreshCw, X,
} from 'lucide-react'
import {
  fetchProducts, updateProduct, fetchInventoryBySku, fetchNodes,
  createInventoryItem, adjustInventory, updateInventoryItem,
  type ProductSummary, type InventoryItem, type AdjustmentReason,
} from '../api/client'
import Modal from '../components/Modal'

// ─── Adjust sub-modal (reused across Inventory and Products) ─────────────────

function AdjustModal({
  item,
  onClose,
  onSuccess,
}: {
  item: InventoryItem
  onClose: () => void
  onSuccess: () => void
}) {
  const [delta, setDelta] = useState('')
  const [reason, setReason] = useState('')
  const [notes, setNotes] = useState('')
  const [err, setErr] = useState('')

  const mutation = useMutation({
    mutationFn: () =>
      adjustInventory(item.id, {
        quantity_delta: Number(delta),
        reason: reason as AdjustmentReason,
        notes: notes || undefined,
      }),
    onSuccess: () => { onSuccess(); onClose() },
    onError: (e: unknown) => {
      const er = e as { response?: { data?: { detail?: string | Array<{ msg: string }> } } }
      const detail = er.response?.data?.detail
      setErr(Array.isArray(detail) ? detail.map(d => d.msg).join('; ') : (detail ?? 'Adjustment failed'))
    },
  })

  return (
    <div className="space-y-4">
      <div className="bg-gray-50 rounded-lg p-3 text-sm">
        <p className="font-semibold text-gray-800">{item.sku}</p>
        <p className="text-gray-500 text-xs mt-0.5">{item.product_name}</p>
        <div className="flex gap-4 mt-2 text-xs">
          <span className="text-gray-500">On Hand: <span className="font-semibold text-gray-800">{item.quantity_on_hand}</span></span>
          <span className="text-gray-500">Available: <span className="font-semibold text-green-600">{item.quantity_available}</span></span>
        </div>
      </div>

      {err && <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg">{err}</div>}

      <div>
        <label className="label">Delta (+ to add, − to remove) *</label>
        <input
          className="input"
          type="number"
          value={delta}
          onChange={e => setDelta(e.target.value)}
          placeholder="e.g. 50 or -10"
          autoFocus
        />
        {delta && (
          <p className="text-xs text-gray-500 mt-1">
            New on-hand: <span className="font-semibold">{item.quantity_on_hand + Number(delta)}</span>
          </p>
        )}
      </div>

      <div>
        <label className="label">Reason *</label>
        <select className="select" value={reason} onChange={e => setReason(e.target.value)}>
          <option value="">Select a reason…</option>
          <option value="RECEIVED">Receiving / Purchase Order</option>
          <option value="RETURNED">Customer Return</option>
          <option value="DAMAGED">Damaged / Write-off</option>
          <option value="CYCLE_COUNT">Cycle Count</option>
          <option value="CORRECTION">Correction</option>
          <option value="SOLD">Sale (manual)</option>
        </select>
      </div>

      <div>
        <label className="label">Notes</label>
        <input
          className="input"
          value={notes}
          onChange={e => setNotes(e.target.value)}
          placeholder="Optional reference or comment"
        />
      </div>

      <div className="flex justify-end gap-2">
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button
          className="btn-primary"
          disabled={!delta || !reason || mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          <TrendingUp className="w-4 h-4" />
          {mutation.isPending ? 'Saving…' : 'Apply Adjustment'}
        </button>
      </div>
    </div>
  )
}

// ─── Main Products Page ───────────────────────────────────────────────────────

export default function Products() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [expandedSku, setExpandedSku] = useState<string | null>(null)
  const [editProduct, setEditProduct] = useState<ProductSummary | null>(null)
  const [adjustItem, setAdjustItem] = useState<InventoryItem | null>(null)
  const [nodeEditItem, setNodeEditItem] = useState<InventoryItem | null>(null)
  const [addOpen, setAddOpen] = useState(false)

  // Product-level edit form state
  const [editName, setEditName] = useState('')
  const [editCost, setEditCost] = useState('')
  const [editWeight, setEditWeight] = useState('')
  const [editReorderPt, setEditReorderPt] = useState('')
  const [editReorderQty, setEditReorderQty] = useState('')
  const [editIsActive, setEditIsActive] = useState(true)
  const [editErr, setEditErr] = useState('')

  // Node-level edit form state
  const [nodeEditReorderPt, setNodeEditReorderPt] = useState('')
  const [nodeEditReorderQty, setNodeEditReorderQty] = useState('')
  const [nodeEditOnOrder, setNodeEditOnOrder] = useState('')
  const [nodeEditIsActive, setNodeEditIsActive] = useState(true)
  const [nodeEditErr, setNodeEditErr] = useState('')

  // Add product form state
  const [addNodeId, setAddNodeId] = useState('')
  const [addSku, setAddSku] = useState('')
  const [addName, setAddName] = useState('')
  const [addQty, setAddQty] = useState('0')
  const [addCost, setAddCost] = useState('0')
  const [addWeight, setAddWeight] = useState('0')
  const [addReorderPt, setAddReorderPt] = useState('10')
  const [addErr, setAddErr] = useState('')

  const { data: products, isLoading, refetch } = useQuery({
    queryKey: ['products', debouncedSearch],
    queryFn: () => fetchProducts({ search: debouncedSearch || undefined, page_size: 100 }),
  })

  const { data: skuItems } = useQuery({
    queryKey: ['inventory-sku', expandedSku],
    queryFn: () => fetchInventoryBySku(expandedSku!),
    enabled: !!expandedSku,
  })

  const { data: nodes } = useQuery({
    queryKey: ['nodes'],
    queryFn: () => fetchNodes({ page: 1, page_size: 100 }),
  })

  const nodeMap = Object.fromEntries((nodes?.items ?? []).map(n => [n.id, n.name]))

  // Debounce search
  const handleSearch = (v: string) => {
    setSearch(v)
    clearTimeout((window as unknown as { _searchTimer?: ReturnType<typeof setTimeout> })._searchTimer)
    ;(window as unknown as { _searchTimer?: ReturnType<typeof setTimeout> })._searchTimer = setTimeout(
      () => setDebouncedSearch(v),
      300,
    )
  }

  const openEdit = (p: ProductSummary) => {
    setEditProduct(p)
    setEditName(p.product_name ?? '')
    setEditCost(String(p.unit_cost))
    setEditWeight(String(p.weight_lbs))
    setEditReorderPt(String(p.reorder_point))
    setEditReorderQty('')
    setEditIsActive(true)  // product summary doesn't carry is_active; default to no change
    setEditErr('')
  }

  const openNodeEdit = (item: InventoryItem) => {
    setNodeEditItem(item)
    setNodeEditReorderPt(String(item.reorder_point))
    setNodeEditReorderQty(String(item.reorder_quantity))
    setNodeEditOnOrder(String(item.quantity_on_order))
    setNodeEditIsActive(item.is_active)
    setNodeEditErr('')
  }

  const editMutation = useMutation({
    mutationFn: () =>
      updateProduct(editProduct!.sku, {
        product_name: editName || undefined,
        unit_cost: editCost !== '' ? Number(editCost) : undefined,
        weight_lbs: editWeight !== '' ? Number(editWeight) : undefined,
        reorder_point: editReorderPt !== '' ? Number(editReorderPt) : undefined,
        reorder_quantity: editReorderQty !== '' ? Number(editReorderQty) : undefined,
        is_active: editIsActive,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['products'] })
      qc.invalidateQueries({ queryKey: ['inventory'] })
      qc.invalidateQueries({ queryKey: ['inventory-sku', expandedSku] })
      setEditProduct(null)
    },
    onError: (e: unknown) => {
      const er = e as { response?: { data?: { detail?: string | Array<{ msg: string }> } } }
      const detail = er.response?.data?.detail
      setEditErr(Array.isArray(detail) ? detail.map(d => d.msg).join('; ') : (detail ?? 'Update failed'))
    },
  })

  const nodeEditMutation = useMutation({
    mutationFn: () =>
      updateInventoryItem(nodeEditItem!.id, {
        reorder_point: nodeEditReorderPt !== '' ? Number(nodeEditReorderPt) : undefined,
        reorder_quantity: nodeEditReorderQty !== '' ? Number(nodeEditReorderQty) : undefined,
        quantity_on_order: nodeEditOnOrder !== '' ? Number(nodeEditOnOrder) : undefined,
        is_active: nodeEditIsActive,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['products'] })
      qc.invalidateQueries({ queryKey: ['inventory-sku', expandedSku] })
      setNodeEditItem(null)
    },
    onError: (e: unknown) => {
      const er = e as { response?: { data?: { detail?: string | Array<{ msg: string }> } } }
      const detail = er.response?.data?.detail
      setNodeEditErr(Array.isArray(detail) ? detail.map(d => d.msg).join('; ') : (detail ?? 'Update failed'))
    },
  })

  const addMutation = useMutation({
    mutationFn: () =>
      createInventoryItem({
        node_id: addNodeId,
        sku: addSku.trim().toUpperCase(),
        product_name: addName || undefined,
        quantity_on_hand: Number(addQty),
        unit_cost: Number(addCost),
        weight_lbs: Number(addWeight),
        reorder_point: Number(addReorderPt),
        reorder_quantity: 100,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['products'] })
      qc.invalidateQueries({ queryKey: ['inventory'] })
      setAddOpen(false)
      setAddSku(''); setAddName(''); setAddQty('0'); setAddCost('0')
      setAddWeight('0'); setAddReorderPt('10'); setAddNodeId(''); setAddErr('')
    },
    onError: (e: unknown) => {
      const er = e as { response?: { data?: { detail?: string | Array<{ msg: string }> } } }
      const detail = er.response?.data?.detail
      setAddErr(Array.isArray(detail) ? detail.map(d => d.msg).join('; ') : (detail ?? 'Create failed'))
    },
  })

  const toggleExpand = (sku: string) => setExpandedSku(prev => prev === sku ? null : sku)

  const isLowStock = (p: ProductSummary) => p.total_available <= p.reorder_point

  return (
    <div className="p-6 space-y-5 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Products</h1>
          <p className="text-sm text-gray-500 mt-0.5">{products?.length ?? 0} unique SKUs</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => refetch()} className="btn-secondary">
            <RefreshCw className="w-4 h-4" />
          </button>
          <button onClick={() => setAddOpen(true)} className="btn-primary">
            <Plus className="w-4 h-4" /> Add Product
          </button>
        </div>
      </div>

      {/* Brand-neutral callout */}
      <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-3 text-xs text-blue-700 flex items-start gap-2">
        <span className="flex-shrink-0 mt-0.5 font-bold">i</span>
        <p>Product catalog is shared across all brands. Brand-specific order routing is configured in Sourcing Rules.</p>
      </div>

      {/* Search */}
      <div className="card p-3 flex items-center gap-3">
        <Search className="w-4 h-4 text-gray-400 flex-shrink-0" />
        <input
          className="flex-1 text-sm outline-none bg-transparent placeholder-gray-400"
          placeholder="Search by SKU or product name…"
          value={search}
          onChange={e => handleSearch(e.target.value)}
        />
        {search && (
          <button onClick={() => { setSearch(''); setDebouncedSearch('') }} className="text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Summary cards */}
      {products && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: 'Total SKUs', value: products.length, color: 'text-gray-900' },
            { label: 'Total On Hand', value: products.reduce((s, p) => s + p.total_on_hand, 0).toLocaleString(), color: 'text-gray-900' },
            { label: 'Total Available', value: products.reduce((s, p) => s + p.total_available, 0).toLocaleString(), color: 'text-green-600' },
            { label: 'Low Stock SKUs', value: products.filter(isLowStock).length, color: 'text-red-600' },
          ].map(({ label, value, color }) => (
            <div key={label} className="card p-4">
              <p className="text-xs text-gray-500 font-medium">{label}</p>
              <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Products table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['SKU', 'Product Name', 'Nodes', 'On Hand', 'Available', 'Reserved', 'Unit Cost', 'Weight', 'Status', ''].map(h => (
                  <th key={h} className="table-header">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {isLoading
                ? Array.from({ length: 6 }).map((_, i) => (
                    <tr key={i} className="animate-pulse">
                      {Array.from({ length: 10 }).map((_, j) => (
                        <td key={j} className="table-cell"><div className="h-4 bg-gray-200 rounded w-20" /></td>
                      ))}
                    </tr>
                  ))
                : products?.map(p => {
                    const low = isLowStock(p)
                    const expanded = expandedSku === p.sku
                    return (
                      <>
                        <tr
                          key={p.sku}
                          className={`transition-colors ${low ? 'bg-red-50 hover:bg-red-100' : 'hover:bg-gray-50'}`}
                        >
                          <td className="table-cell font-mono text-xs text-gray-600 font-semibold">{p.sku}</td>
                          <td className="table-cell font-medium text-gray-900">{p.product_name ?? <span className="text-gray-400 italic text-xs">—</span>}</td>
                          <td className="table-cell text-center text-gray-600">{p.nodes_count}</td>
                          <td className="table-cell font-semibold text-gray-900">{p.total_on_hand.toLocaleString()}</td>
                          <td className={`table-cell font-bold ${low ? 'text-red-600' : 'text-green-600'}`}>
                            {p.total_available.toLocaleString()}
                          </td>
                          <td className="table-cell text-blue-600">{p.total_reserved.toLocaleString()}</td>
                          <td className="table-cell text-gray-600">{p.unit_cost > 0 ? `$${p.unit_cost.toFixed(2)}` : '—'}</td>
                          <td className="table-cell text-gray-500">{p.weight_lbs > 0 ? `${p.weight_lbs} lb` : '—'}</td>
                          <td className="table-cell">
                            {low ? (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">
                                <AlertTriangle className="w-3 h-3" /> Low Stock
                              </span>
                            ) : (
                              <span className="inline-flex px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">OK</span>
                            )}
                          </td>
                          <td className="table-cell">
                            <div className="flex items-center gap-1">
                              <button
                                onClick={() => openEdit(p)}
                                className="p-1 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
                                title="Edit product attributes"
                              >
                                <Edit2 className="w-3.5 h-3.5" />
                              </button>
                              <button
                                onClick={() => toggleExpand(p.sku)}
                                className="p-1 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded transition-colors"
                                title="View nodes & adjust stock"
                              >
                                {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                              </button>
                            </div>
                          </td>
                        </tr>

                        {/* Expanded per-node inventory */}
                        {expanded && (
                          <tr key={`${p.sku}-detail`} className="bg-blue-50/40">
                            <td colSpan={10} className="px-6 py-3">
                              <p className="text-xs font-semibold text-gray-500 mb-2">Node-level inventory for {p.sku}</p>
                              {!skuItems ? (
                                <p className="text-xs text-gray-400">Loading…</p>
                              ) : (
                                <div className="overflow-x-auto">
                                  <table className="w-full text-xs">
                                    <thead>
                                      <tr className="text-left text-gray-500">
                                        <th className="pb-1 pr-4 font-medium">Node</th>
                                        <th className="pb-1 pr-4 font-medium">On Hand</th>
                                        <th className="pb-1 pr-4 font-medium">Reserved</th>
                                        <th className="pb-1 pr-4 font-medium">Available</th>
                                        <th className="pb-1 pr-4 font-medium">On Order</th>
                                        <th className="pb-1 pr-4 font-medium">Reorder Pt</th>
                                        <th className="pb-1 pr-4 font-medium">Reorder Qty</th>
                                        <th className="pb-1 pr-4 font-medium">Status</th>
                                        <th className="pb-1"></th>
                                      </tr>
                                    </thead>
                                    <tbody className="divide-y divide-blue-100">
                                      {skuItems.map(item => (
                                        <tr key={item.id} className="text-gray-700">
                                          <td className="py-1.5 pr-4 font-medium">
                                            {nodeMap[item.node_id] ?? item.node_id.slice(0, 8) + '…'}
                                          </td>
                                          <td className="py-1.5 pr-4">{item.quantity_on_hand}</td>
                                          <td className="py-1.5 pr-4 text-blue-600">{item.quantity_reserved}</td>
                                          <td className={`py-1.5 pr-4 font-semibold ${item.quantity_available <= item.reorder_point ? 'text-red-600' : 'text-green-600'}`}>
                                            {item.quantity_available}
                                          </td>
                                          <td className="py-1.5 pr-4 text-gray-500">{item.quantity_on_order}</td>
                                          <td className="py-1.5 pr-4 text-gray-500">{item.reorder_point}</td>
                                          <td className="py-1.5 pr-4 text-gray-500">{item.reorder_quantity}</td>
                                          <td className="py-1.5 pr-4">
                                            <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold ${item.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                                              {item.is_active ? 'Active' : 'Inactive'}
                                            </span>
                                          </td>
                                          <td className="py-1.5">
                                            <div className="flex gap-1">
                                              <button
                                                onClick={() => openNodeEdit(item)}
                                                className="text-xs text-gray-600 hover:text-gray-800 font-medium px-2 py-0.5 rounded hover:bg-gray-100 transition-colors"
                                              >
                                                Edit
                                              </button>
                                              <button
                                                onClick={() => setAdjustItem(item)}
                                                className="text-xs text-blue-600 hover:text-blue-800 font-medium px-2 py-0.5 rounded hover:bg-blue-100 transition-colors"
                                              >
                                                Adjust
                                              </button>
                                            </div>
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              )}
                            </td>
                          </tr>
                        )}
                      </>
                    )
                  })
              }
              {!isLoading && !products?.length && (
                <tr>
                  <td colSpan={10} className="text-center py-16 text-gray-400 text-sm">
                    <Package className="w-8 h-8 mx-auto mb-2 opacity-30" />
                    No products found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Edit Product Modal */}
      <Modal open={!!editProduct} onClose={() => setEditProduct(null)} title={`Edit Product — ${editProduct?.sku}`} size="sm">
        {editProduct && (
          <div className="space-y-4">
            {editErr && <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg">{editErr}</div>}
            <p className="text-xs text-gray-500">Changes apply to all {editProduct.nodes_count} node(s) carrying this SKU.</p>

            <div>
              <label className="label">Product Name</label>
              <input className="input" value={editName} onChange={e => setEditName(e.target.value)} placeholder="e.g. Blue Widget Large" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Unit Cost ($)</label>
                <input className="input" type="number" min="0" step="0.01" value={editCost} onChange={e => setEditCost(e.target.value)} />
              </div>
              <div>
                <label className="label">Weight (lbs)</label>
                <input className="input" type="number" min="0" step="0.01" value={editWeight} onChange={e => setEditWeight(e.target.value)} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Reorder Point</label>
                <input className="input" type="number" min="0" value={editReorderPt} onChange={e => setEditReorderPt(e.target.value)} />
              </div>
              <div>
                <label className="label">Reorder Qty</label>
                <input className="input" type="number" min="1" value={editReorderQty} onChange={e => setEditReorderQty(e.target.value)} placeholder="No change" />
              </div>
            </div>

            <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
              <div>
                <p className="text-sm font-medium text-gray-700">Active Status</p>
                <p className="text-xs text-gray-500">Deactivate to hide from sourcing across all nodes</p>
              </div>
              <button
                type="button"
                onClick={() => setEditIsActive(v => !v)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${editIsActive ? 'bg-green-500' : 'bg-gray-300'}`}
              >
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${editIsActive ? 'translate-x-6' : 'translate-x-1'}`} />
              </button>
            </div>

            <div className="flex justify-end gap-2">
              <button className="btn-secondary" onClick={() => setEditProduct(null)}>Cancel</button>
              <button
                className="btn-primary"
                disabled={editMutation.isPending}
                onClick={() => editMutation.mutate()}
              >
                {editMutation.isPending ? 'Saving…' : 'Save Changes'}
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* Node-level Edit Modal */}
      <Modal open={!!nodeEditItem} onClose={() => setNodeEditItem(null)} title="Edit Node Inventory" size="sm">
        {nodeEditItem && (
          <div className="space-y-4">
            <div className="bg-gray-50 rounded-lg p-3 text-sm">
              <p className="font-semibold text-gray-800">{nodeEditItem.sku}</p>
              <p className="text-xs text-gray-500 mt-0.5">{nodeMap[nodeEditItem.node_id] ?? nodeEditItem.node_id.slice(0, 8)}</p>
              <div className="flex gap-4 mt-2 text-xs text-gray-500">
                <span>On Hand: <span className="font-semibold text-gray-800">{nodeEditItem.quantity_on_hand}</span></span>
                <span>Reserved: <span className="font-semibold text-blue-600">{nodeEditItem.quantity_reserved}</span></span>
                <span>Available: <span className="font-semibold text-green-600">{nodeEditItem.quantity_available}</span></span>
              </div>
            </div>

            {nodeEditErr && <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg">{nodeEditErr}</div>}

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Reorder Point</label>
                <input className="input" type="number" min="0" value={nodeEditReorderPt} onChange={e => setNodeEditReorderPt(e.target.value)} />
              </div>
              <div>
                <label className="label">Reorder Qty</label>
                <input className="input" type="number" min="1" value={nodeEditReorderQty} onChange={e => setNodeEditReorderQty(e.target.value)} />
              </div>
            </div>

            <div>
              <label className="label">Quantity On Order</label>
              <input
                className="input"
                type="number"
                min="0"
                value={nodeEditOnOrder}
                onChange={e => setNodeEditOnOrder(e.target.value)}
                placeholder="Units expected from suppliers"
              />
              <p className="text-xs text-gray-400 mt-1">Units ordered from supplier but not yet received</p>
            </div>

            <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
              <div>
                <p className="text-sm font-medium text-gray-700">Active at this Node</p>
                <p className="text-xs text-gray-500">Inactive items are excluded from sourcing at this location</p>
              </div>
              <button
                type="button"
                onClick={() => setNodeEditIsActive(v => !v)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${nodeEditIsActive ? 'bg-green-500' : 'bg-gray-300'}`}
              >
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${nodeEditIsActive ? 'translate-x-6' : 'translate-x-1'}`} />
              </button>
            </div>

            <div className="flex justify-end gap-2">
              <button className="btn-secondary" onClick={() => setNodeEditItem(null)}>Cancel</button>
              <button
                className="btn-primary"
                disabled={nodeEditMutation.isPending}
                onClick={() => nodeEditMutation.mutate()}
              >
                {nodeEditMutation.isPending ? 'Saving…' : 'Save Changes'}
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* Adjust Inventory Modal */}
      <Modal
        open={!!adjustItem}
        onClose={() => setAdjustItem(null)}
        title="Adjust Inventory"
        size="sm"
      >
        {adjustItem && (
          <AdjustModal
            item={adjustItem}
            onClose={() => setAdjustItem(null)}
            onSuccess={() => {
              qc.invalidateQueries({ queryKey: ['products'] })
              qc.invalidateQueries({ queryKey: ['inventory'] })
              qc.invalidateQueries({ queryKey: ['inventory-sku', expandedSku] })
            }}
          />
        )}
      </Modal>

      {/* Add Product Modal */}
      <Modal open={addOpen} onClose={() => setAddOpen(false)} title="Add Product / Inventory" size="sm">
        <div className="space-y-4">
          {addErr && <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg">{addErr}</div>}

          <div>
            <label className="label">Fulfillment Node *</label>
            <select className="select" value={addNodeId} onChange={e => setAddNodeId(e.target.value)}>
              <option value="">Select a node…</option>
              {nodes?.items.map(n => (
                <option key={n.id} value={n.id}>{n.name} ({n.node_type})</option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">SKU *</label>
              <input className="input" value={addSku} onChange={e => setAddSku(e.target.value)} placeholder="WIDGET-BLU-L" />
            </div>
            <div>
              <label className="label">Initial Qty</label>
              <input className="input" type="number" min="0" value={addQty} onChange={e => setAddQty(e.target.value)} />
            </div>
          </div>

          <div>
            <label className="label">Product Name</label>
            <input className="input" value={addName} onChange={e => setAddName(e.target.value)} placeholder="e.g. Blue Widget Large" />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Unit Cost ($)</label>
              <input className="input" type="number" min="0" step="0.01" value={addCost} onChange={e => setAddCost(e.target.value)} />
            </div>
            <div>
              <label className="label">Weight (lbs)</label>
              <input className="input" type="number" min="0" step="0.01" value={addWeight} onChange={e => setAddWeight(e.target.value)} />
            </div>
          </div>

          <div>
            <label className="label">Reorder Point</label>
            <input className="input" type="number" min="0" value={addReorderPt} onChange={e => setAddReorderPt(e.target.value)} />
          </div>

          <div className="flex justify-end gap-2">
            <button className="btn-secondary" onClick={() => setAddOpen(false)}>Cancel</button>
            <button
              className="btn-primary"
              disabled={!addNodeId || !addSku.trim() || addMutation.isPending}
              onClick={() => addMutation.mutate()}
            >
              <Plus className="w-4 h-4" />
              {addMutation.isPending ? 'Creating…' : 'Create Product'}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
