import { useState, useRef, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Search as SearchIcon, ArrowRight, Clock, Package } from 'lucide-react'
import { searchOrders, type SearchHit } from '../api/client'
import { StatusBadge } from '../components/Badge'

function Highlight({ text, query }: { text: string; query: string }) {
  if (!query || !text) return <>{text}</>
  const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
  const parts = text.split(regex)
  return (
    <>
      {parts.map((part, i) =>
        regex.test(part)
          ? <mark key={i} className="bg-yellow-200 text-yellow-900 rounded px-0.5">{part}</mark>
          : part
      )}
    </>
  )
}

function ResultCard({ hit, query }: { hit: SearchHit; query: string }) {
  const src = hit.source
  const orderId = String(src.id ?? hit.id)
  const orderNumber = String(src.order_number ?? '')
  const status = String(src.status ?? '')
  const channel = String(src.channel ?? '')
  const customerName = String(src.customer_name ?? '')
  const customerEmail = String(src.customer_email ?? '')
  const totalAmount = String(src.total_amount ?? '')
  const createdAt = String(src.created_at ?? '')
  const lineItems = Array.isArray(src.line_items) ? src.line_items as Array<{ sku: string; quantity: number }> : []

  return (
    <Link
      to={`/orders/${orderId}`}
      className="card p-4 flex items-start justify-between gap-4 hover:shadow-md transition-all group"
    >
      <div className="flex items-start gap-3 min-w-0">
        <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center flex-shrink-0 group-hover:bg-blue-100 transition-colors">
          <Package className="w-4 h-4 text-blue-600" />
        </div>
        <div className="min-w-0 space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono font-semibold text-sm text-blue-600">
              <Highlight text={orderNumber} query={query} />
            </span>
            {status && <StatusBadge value={status} />}
            {channel && <StatusBadge value={channel} />}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-gray-500">
            <span>
              <Highlight text={customerName} query={query} />
              {customerName && ' · '}
              <Highlight text={customerEmail} query={query} />
            </span>
          </div>
          {lineItems.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {lineItems.slice(0, 3).map((item, i) => (
                <span key={i} className="px-2 py-0.5 bg-gray-100 rounded text-xs text-gray-600 font-mono">
                  <Highlight text={item.sku} query={query} /> ×{item.quantity}
                </span>
              ))}
              {lineItems.length > 3 && (
                <span className="text-xs text-gray-400">+{lineItems.length - 3} more</span>
              )}
            </div>
          )}
        </div>
      </div>
      <div className="flex flex-col items-end gap-1 flex-shrink-0">
        {totalAmount && <span className="font-bold text-gray-900 text-sm">${totalAmount}</span>}
        {createdAt && (
          <span className="text-xs text-gray-400 flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {createdAt.slice(0, 10)}
          </span>
        )}
        <ArrowRight className="w-4 h-4 text-gray-300 group-hover:text-blue-500 transition-colors mt-1" />
      </div>
    </Link>
  )
}

export default function Search() {
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['search', query],
    queryFn: () => searchOrders(query),
    enabled: query.trim().length >= 2,
    staleTime: 10_000,
  })

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (input.trim().length >= 2) setQuery(input.trim())
  }

  const handleClear = () => {
    setInput('')
    setQuery('')
    inputRef.current?.focus()
  }

  const hits = data?.hits ?? []
  const hasQuery = query.trim().length >= 2
  const showEmpty = hasQuery && !isLoading && !isFetching && hits.length === 0

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-gray-900">Search</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Search orders by order number, customer email, name, or SKU
        </p>
      </div>

      {/* Search Box */}
      <form onSubmit={handleSubmit} className="relative">
        <div className="relative">
          <SearchIcon className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            ref={inputRef}
            className="w-full pl-10 pr-28 py-3 rounded-xl border border-gray-200 bg-white shadow-sm text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition"
            placeholder="Search orders, customers, SKUs…"
            value={input}
            onChange={e => setInput(e.target.value)}
            autoFocus
          />
          <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1.5">
            {input && (
              <button
                type="button"
                onClick={handleClear}
                className="text-xs text-gray-400 hover:text-gray-600 px-2 py-1"
              >
                Clear
              </button>
            )}
            <button
              type="submit"
              disabled={input.trim().length < 2}
              className="btn-primary py-1.5 text-xs"
            >
              Search
            </button>
          </div>
        </div>
        {input.trim().length === 1 && (
          <p className="text-xs text-gray-400 mt-1.5 ml-1">Type at least 2 characters</p>
        )}
      </form>

      {/* Results */}
      {(isLoading || isFetching) && hasQuery && (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="card p-4 animate-pulse flex gap-3">
              <div className="w-9 h-9 bg-gray-200 rounded-lg flex-shrink-0" />
              <div className="flex-1 space-y-2">
                <div className="h-4 bg-gray-200 rounded w-48" />
                <div className="h-3 bg-gray-200 rounded w-64" />
                <div className="h-5 bg-gray-200 rounded w-32" />
              </div>
            </div>
          ))}
        </div>
      )}

      {!isLoading && !isFetching && hits.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs text-gray-500">
            {data?.total ?? hits.length} result{hits.length !== 1 ? 's' : ''} for{' '}
            <span className="font-semibold text-gray-700">"{query}"</span>
          </p>
          {hits.map(hit => (
            <ResultCard key={hit.id} hit={hit} query={query} />
          ))}
        </div>
      )}

      {showEmpty && (
        <div className="text-center py-16 space-y-3">
          <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto">
            <SearchIcon className="w-7 h-7 text-gray-400" />
          </div>
          <p className="text-gray-500 font-medium">No results for "{query}"</p>
          <p className="text-sm text-gray-400">Try a different order number, email, or SKU</p>
        </div>
      )}

      {!hasQuery && (
        <div className="text-center py-16 space-y-3">
          <div className="w-16 h-16 bg-blue-50 rounded-full flex items-center justify-center mx-auto">
            <SearchIcon className="w-7 h-7 text-blue-400" />
          </div>
          <p className="text-gray-500 font-medium">Start searching</p>
          <div className="text-xs text-gray-400 space-y-1">
            <p>Try: <span className="font-mono bg-gray-100 px-1.5 py-0.5 rounded">ORD-</span> for order numbers</p>
            <p>Try: <span className="font-mono bg-gray-100 px-1.5 py-0.5 rounded">SKU-WIDGET</span> for products</p>
            <p>Try: <span className="font-mono bg-gray-100 px-1.5 py-0.5 rounded">@example.com</span> for customers</p>
          </div>
        </div>
      )}
    </div>
  )
}
