import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Package, AlertTriangle, RefreshCw, TrendingUp,
  ChevronDown, ChevronUp, Search, X,
} from 'lucide-react'
import {
  fetchNodes, fetchProducts, fetchInventoryBySku, adjustInventory,
  type ProductSummary, type InventoryItem, type AdjustmentReason,
} from '../api/client'
import Modal from '../components/Modal'

export default function Inventory() {
  const qc = useQueryClient()

  // Filters
  const [nodeId, setNodeId] = useState('')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [lowStockOnly, setLowStockOnly] = useState(false)

  // Row state
  const [expandedSku, setExpandedSku] = useState<string | null>(null)

  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>()

  // Adjust modal
  const [adjustItem, setAdjustItem] = useState<InventoryItem | null>(null)
  const [delta, setDelta] = useState('')
  const [reason, setReason] = useState('')
  const [notes, setNotes] = useState('')
  const [adjError, setAdjError] = useState('')

  const { data: nodes } = useQuery({
    queryKey: ['nodes'],
    queryFn: () => fetchNodes({ page: 1, page_size: 100 }),
  })

  const { data: products, isLoading, refetch } = useQuery({
    queryKey: ['products', debouncedSearch, nodeId, lowStockOnly],
    queryFn: () => fetchProducts({
      search: debouncedSearch || undefined,
      node_id: nodeId || undefined,
      low_stock_only: lowStockOnly || undefined,
      page_size: 200,
    }),
  })

  const { data: skuItems } = useQuery({
    queryKey: ['inventory-sku', expandedSku],
    queryFn: () => fetchInventoryBySku(expandedSku!),
    enabled: !!expandedSku,
  })

  const nodeMap = Object.fromEntries((nodes?.items ?? []).map(n => [n.id, n]))

  const handleSearch = (v: string) => {
    setSearch(v)
    clearTimeout(searchTimerRef.current)
    searchTimerRef.current = setTimeout(() => setDebouncedSearch(v), 300)
  }

  const openAdjust = (item: InventoryItem) => {
    setAdjustItem(item)
    setDelta('')
    setReason('')
    setNotes('')
    setAdjError('')
  }

  const adjustMutation = useMutation({
    mutationFn: () =>
      adjustInventory(adjustItem!.id, {
        quantity_delta: Number(delta),
        reason: reason as AdjustmentReason,
        notes: notes || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['products'] })
      qc.invalidateQueries({ queryKey: ['inventory-sku', expandedSku] })
      qc.invalidateQueries({ queryKey: ['inventory'] })
      setAdjustItem(null)
      setDelta('')
      setReason('')
      setNotes('')
      setAdjError('')
    },
    onError: (err: unknown) => {
      const e = err as { response?: { data?: { detail?: string | Array<{ msg: string }> } } }
      const detail = e.response?.data?.detail
      setAdjError(Array.isArray(detail) ? detail.map(d => d.msg).join('; ') : (detail ?? 'Adjustment failed'))
    },
  })

  const toggleExpand = (sku: string) =>
    setExpandedSku(prev => (prev === sku ? null : sku))

  const isLowStock = (p: ProductSummary) => p.total_available <= p.reorder_point

  const totalOnHand = products?.reduce((s, p) => s + p.total_on_hand, 0) ?? 0
  const totalAvailable = products?.reduce((s, p) => s + p.total_available, 0) ?? 0
  const lowCount = products?.filter(isLowStock).length ?? 0

  return (
    <div className="p-6 space-y-5 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Inventory</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {products?.length ?? 0} SKUs
            {nodeId ? ` at ${nodeMap[nodeId]?.name ?? 'selected node'}` : ' across all nodes'}
          </p>
        </div>
        <button onClick={() => refetch()} className="btn-secondary">
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="card p-3 flex flex-wrap items-center gap-3">
        <Package className="w-4 h-4 text-gray-400 flex-shrink-0" />
        <select
          className="select max-w-56"
          value={nodeId}
          onChange={e => setNodeId(e.target.value)}
        >
          <option value="">All Nodes</option>
          {nodes?.items.map(n => (
            <option key={n.id} value={n.id}>{n.name}</option>
          ))}
        </select>

        <div className="flex items-center gap-2 flex-1 min-w-48 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2">
          <Search className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
          <input
            className="flex-1 text-sm outline-none bg-transparent placeholder-gray-400"
            placeholder="Search SKU or name…"
            value={search}
            onChange={e => handleSearch(e.target.value)}
          />
          {search && (
            <button onClick={() => { setSearch(''); setDebouncedSearch('') }}>
              <X className="w-3.5 h-3.5 text-gray-400 hover:text-gray-600" />
            </button>
          )}
        </div>

        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none">
          <input
            type="checkbox"
            className="w-4 h-4 rounded text-red-500"
            checked={lowStockOnly}
            onChange={e => setLowStockOnly(e.target.checked)}
          />
          Low stock only
        </label>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Total SKUs', value: products?.length ?? 0, color: 'text-gray-900' },
          { label: 'Total On Hand', value: totalOnHand.toLocaleString(), color: 'text-gray-900' },
          { label: 'Available', value: totalAvailable.toLocaleString(), color: 'text-green-600' },
          { label: 'Low Stock', value: lowCount, color: 'text-red-600' },
        ].map(({ label, value, color }) => (
          <div key={label} className="card p-4">
            <p className="text-xs text-gray-500 font-medium">{label}</p>
            <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Inventory Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['SKU', 'Product', 'Locations', 'On Hand', 'Available', 'Reserved', 'Reorder Pt', 'Status', ''].map(h => (
                  <th key={h} className="table-header">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {isLoading
                ? Array.from({ length: 8 }).map((_, i) => (
                    <tr key={i} className="animate-pulse">
                      {Array.from({ length: 9 }).map((_, j) => (
                        <td key={j} className="table-cell">
                          <div className="h-4 bg-gray-200 rounded w-20" />
                        </td>
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
                          className={`transition-colors cursor-pointer ${low ? 'bg-red-50 hover:bg-red-100' : 'hover:bg-gray-50'}`}
                          onClick={() => toggleExpand(p.sku)}
                        >
                          <td className="table-cell font-mono text-xs text-gray-600 font-semibold">{p.sku}</td>
                          <td className="table-cell font-medium text-gray-900">
                            {p.product_name ?? <span className="text-gray-400 italic text-xs">—</span>}
                          </td>
                          <td className="table-cell text-center text-gray-500 text-sm">{p.nodes_count}</td>
                          <td className="table-cell font-semibold text-gray-900">{p.total_on_hand.toLocaleString()}</td>
                          <td className={`table-cell font-bold ${low ? 'text-red-600' : 'text-green-600'}`}>
                            {p.total_available.toLocaleString()}
                          </td>
                          <td className="table-cell text-blue-600">{p.total_reserved.toLocaleString()}</td>
                          <td className="table-cell text-gray-500">{p.reorder_point}</td>
                          <td className="table-cell">
                            {low ? (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">
                                <AlertTriangle className="w-3 h-3" /> Low
                              </span>
                            ) : (
                              <span className="inline-flex px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">OK</span>
                            )}
                          </td>
                          <td className="table-cell" onClick={e => e.stopPropagation()}>
                            <button
                              onClick={() => toggleExpand(p.sku)}
                              className="p-1 text-gray-400 hover:text-gray-700 rounded"
                            >
                              {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                            </button>
                          </td>
                        </tr>

                        {/* Per-node inventory breakdown */}
                        {expanded && (
                          <tr key={`${p.sku}-nodes`} className="bg-blue-50/50">
                            <td colSpan={9} className="px-8 py-3">
                              <p className="text-xs font-semibold text-gray-500 mb-2 uppercase tracking-wide">
                                Inventory by Location
                              </p>
                              {!skuItems ? (
                                <p className="text-xs text-gray-400 animate-pulse">Loading…</p>
                              ) : (
                                <table className="w-full text-xs">
                                  <thead>
                                    <tr className="text-left text-gray-400 uppercase tracking-wide">
                                      <th className="pb-1.5 pr-6 font-medium">Location</th>
                                      <th className="pb-1.5 pr-6 font-medium">Type</th>
                                      <th className="pb-1.5 pr-6 font-medium">On Hand</th>
                                      <th className="pb-1.5 pr-6 font-medium">Reserved</th>
                                      <th className="pb-1.5 pr-6 font-medium">Available</th>
                                      <th className="pb-1.5 pr-6 font-medium">On Order</th>
                                      <th className="pb-1.5 pr-6 font-medium">Reorder Pt</th>
                                      <th className="pb-1.5"></th>
                                    </tr>
                                  </thead>
                                  <tbody className="divide-y divide-blue-100">
                                    {skuItems.map(item => {
                                      const node = nodeMap[item.node_id]
                                      const itemLow = item.quantity_available <= item.reorder_point
                                      return (
                                        <tr key={item.id} className="text-gray-700">
                                          <td className="py-2 pr-6 font-medium text-gray-800">
                                            {node?.name ?? item.node_id.slice(0, 8) + '…'}
                                          </td>
                                          <td className="py-2 pr-6 text-gray-500 capitalize">
                                            {node?.node_type?.toLowerCase() ?? '—'}
                                          </td>
                                          <td className="py-2 pr-6 font-semibold text-gray-800">{item.quantity_on_hand}</td>
                                          <td className="py-2 pr-6 text-blue-600">{item.quantity_reserved}</td>
                                          <td className={`py-2 pr-6 font-bold ${itemLow ? 'text-red-600' : 'text-green-600'}`}>
                                            {item.quantity_available}
                                            {itemLow && <AlertTriangle className="inline w-3 h-3 ml-1 text-red-500" />}
                                          </td>
                                          <td className="py-2 pr-6 text-gray-500">{item.quantity_on_order}</td>
                                          <td className="py-2 pr-6 text-gray-500">{item.reorder_point}</td>
                                          <td className="py-2">
                                            <button
                                              onClick={() => openAdjust(item)}
                                              className="text-xs text-blue-600 hover:text-blue-800 font-medium px-2.5 py-1 rounded-lg hover:bg-blue-100 transition-colors"
                                            >
                                              Adjust
                                            </button>
                                          </td>
                                        </tr>
                                      )
                                    })}
                                  </tbody>
                                </table>
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
                  <td colSpan={9} className="text-center py-16 text-gray-400 text-sm">
                    <Package className="w-8 h-8 mx-auto mb-2 opacity-30" />
                    No inventory records found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Adjust Modal */}
      <Modal
        open={!!adjustItem}
        onClose={() => setAdjustItem(null)}
        title="Adjust Inventory"
        size="sm"
      >
        {adjustItem && (
          <div className="space-y-4">
            <div className="bg-gray-50 rounded-lg p-3 text-sm">
              <p className="font-semibold text-gray-800">{adjustItem.sku}</p>
              <p className="text-gray-500 text-xs mt-0.5">{adjustItem.product_name}</p>
              <p className="text-xs text-gray-400 mt-0.5">
                at {nodeMap[adjustItem.node_id]?.name ?? adjustItem.node_id.slice(0, 8)}
              </p>
              <div className="flex gap-4 mt-2 text-xs">
                <span className="text-gray-500">On Hand: <span className="font-semibold text-gray-800">{adjustItem.quantity_on_hand}</span></span>
                <span className="text-gray-500">Available: <span className="font-semibold text-green-600">{adjustItem.quantity_available}</span></span>
              </div>
            </div>

            {adjError && (
              <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg">{adjError}</div>
            )}

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
                  New on-hand: <span className="font-semibold">
                    {adjustItem.quantity_on_hand + Number(delta)}
                  </span>
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
              <button className="btn-secondary" onClick={() => setAdjustItem(null)}>Cancel</button>
              <button
                className="btn-primary"
                disabled={!delta || !reason || adjustMutation.isPending}
                onClick={() => adjustMutation.mutate()}
              >
                <TrendingUp className="w-4 h-4" />
                {adjustMutation.isPending ? 'Saving…' : 'Apply Adjustment'}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
