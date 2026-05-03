import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Webhook, Plus, RefreshCw, Trash2, Power, Shield,
  Copy, Eye, EyeOff, TestTube2, Edit2, ChevronDown, ChevronUp,
  CheckCircle, XCircle, Clock, RotateCcw, AlertTriangle,
} from 'lucide-react'
import Modal from '../components/Modal'
import { StatusBadge } from '../components/Badge'
import {
  fetchWebhookEndpoints, createWebhookEndpoint, updateWebhookEndpoint,
  deleteWebhookEndpoint, testWebhookEndpoint,
  fetchWebhookEvents, retryWebhookEvent, fetchWebhookEventTypes,
  type WebhookEndpoint, type WebhookEvent,
} from '../api/client'

// ─── Fallback constants (used until API responds) ─────────────────────────────

const FALLBACK_EVENT_TYPES = [
  'order.created', 'order.confirmed', 'order.sourced', 'order.sourcing_failed',
  'order.picking', 'order.packing', 'order.ready_to_ship',
  'order.shipped', 'order.out_for_delivery', 'order.delivered',
  'order.cancelled', 'order.returned', 'order.test',
]

const FALLBACK_EVENT_GROUPS = [
  { label: 'Lifecycle', events: ['order.created', 'order.confirmed'] },
  { label: 'Fulfillment', events: ['order.sourced', 'order.sourcing_failed', 'order.picking', 'order.packing', 'order.ready_to_ship'] },
  { label: 'Shipping', events: ['order.shipped', 'order.out_for_delivery', 'order.delivered'] },
  { label: 'Post-order', events: ['order.cancelled', 'order.returned'] },
]

function generateSecret(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
  return Array.from({ length: 32 }, () => chars[Math.floor(Math.random() * chars.length)]).join('')
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface EndpointForm {
  name: string
  url: string
  secret: string
  is_active: boolean
  event_types: string[]
}

const DEFAULT_FORM: EndpointForm = {
  name: '',
  url: '',
  secret: '',
  is_active: true,
  event_types: [],
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function EventTypesPill({ types, totalEventTypes }: { types: string[]; totalEventTypes: number }) {
  const [expanded, setExpanded] = useState(false)
  if (types.length >= totalEventTypes) {
    return <span className="text-xs text-gray-500">All events ({types.length})</span>
  }
  return (
    <div>
      <button
        onClick={() => setExpanded(e => !e)}
        className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700"
      >
        {types.length} events
        {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
      </button>
      {expanded && (
        <div className="mt-1 flex flex-wrap gap-1 max-w-xs">
          {types.map(t => (
            <span key={t} className="px-1.5 py-0.5 bg-blue-50 text-blue-700 text-[10px] rounded font-mono">
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function DeliveryStatusIcon({ status }: { status: string }) {
  if (status === 'DELIVERED') return <CheckCircle className="w-4 h-4 text-green-500" />
  if (status === 'FAILED' || status === 'ABANDONED') return <XCircle className="w-4 h-4 text-red-500" />
  if (status === 'RETRYING') return <RotateCcw className="w-4 h-4 text-yellow-500" />
  return <Clock className="w-4 h-4 text-gray-400" />
}

// ─── Create/Edit Modal ────────────────────────────────────────────────────────

function EndpointModal({
  open, onClose, editing, allEventTypes, eventGroups,
}: {
  open: boolean; onClose: () => void; editing: WebhookEndpoint | null
  allEventTypes: string[]
  eventGroups: Array<{ label: string; events: string[] }>
}) {
  const qc = useQueryClient()
  const isEdit = editing !== null
  const [form, setForm] = useState<EndpointForm>(() =>
    editing
      ? { name: editing.name, url: editing.url, secret: '', is_active: editing.is_active, event_types: [...editing.event_types] }
      : { ...DEFAULT_FORM, secret: generateSecret(), event_types: [] }
  )

  // When creating a new endpoint, pre-select all events once the list is available
  const prevAllRef = useRef<string[]>([])
  useEffect(() => {
    if (!isEdit && allEventTypes.length > 0 && prevAllRef.current.length === 0) {
      setForm(f => ({ ...f, event_types: [...allEventTypes] }))
      prevAllRef.current = allEventTypes
    }
  }, [allEventTypes, isEdit])
  const [showSecret, setShowSecret] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState('')

  const createMut = useMutation({
    mutationFn: createWebhookEndpoint,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['webhooks', 'endpoints'] }); onClose() },
    onError: (e: unknown) => setError((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? 'Failed to create endpoint'),
  })
  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof updateWebhookEndpoint>[1] }) =>
      updateWebhookEndpoint(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['webhooks', 'endpoints'] }); onClose() },
    onError: (e: unknown) => setError((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? 'Failed to update endpoint'),
  })

  const loading = createMut.isPending || updateMut.isPending

  function toggleEvent(evt: string) {
    setForm(f => ({
      ...f,
      event_types: f.event_types.includes(evt)
        ? f.event_types.filter(e => e !== evt)
        : [...f.event_types, evt],
    }))
  }

  function toggleGroup(events: string[]) {
    const allSelected = events.every(e => form.event_types.includes(e))
    setForm(f => ({
      ...f,
      event_types: allSelected
        ? f.event_types.filter(e => !events.includes(e))
        : [...new Set([...f.event_types, ...events])],
    }))
  }

  function copySecret() {
    navigator.clipboard.writeText(form.secret)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!form.name.trim()) return setError('Name is required')
    if (!form.url.trim() || !form.url.startsWith('http')) return setError('A valid URL is required')
    if (!isEdit && form.secret.length < 16) return setError('Secret must be at least 16 characters')
    if (form.event_types.length === 0) return setError('Select at least one event type')

    if (isEdit) {
      const data: Parameters<typeof updateWebhookEndpoint>[1] = {
        name: form.name, url: form.url, is_active: form.is_active, event_types: form.event_types,
      }
      updateMut.mutate({ id: editing!.id, data })
    } else {
      createMut.mutate({ name: form.name, url: form.url, secret: form.secret, is_active: form.is_active, event_types: form.event_types, headers: {} })
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={isEdit ? 'Edit Webhook Endpoint' : 'Create Webhook Endpoint'}>
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Name */}
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Name</label>
          <input
            className="input w-full"
            placeholder="My Integration Endpoint"
            value={form.name}
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
          />
        </div>

        {/* URL */}
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Endpoint URL</label>
          <input
            className="input w-full font-mono text-sm"
            placeholder="https://your-server.com/webhooks/oms"
            value={form.url}
            onChange={e => setForm(f => ({ ...f, url: e.target.value }))}
          />
        </div>

        {/* Secret — create only */}
        {!isEdit && (
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">
              Signing Secret
              <span className="ml-1 text-gray-400 font-normal">(HMAC-SHA256 — save this now)</span>
            </label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <input
                  className="input w-full font-mono text-sm pr-8"
                  type={showSecret ? 'text' : 'password'}
                  value={form.secret}
                  onChange={e => setForm(f => ({ ...f, secret: e.target.value }))}
                />
                <button
                  type="button"
                  onClick={() => setShowSecret(s => !s)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                >
                  {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              <button type="button" onClick={() => setForm(f => ({ ...f, secret: generateSecret() }))}
                className="btn-secondary text-xs px-2 whitespace-nowrap">
                Generate
              </button>
              <button type="button" onClick={copySecret}
                className="btn-secondary text-xs px-2">
                {copied ? <CheckCircle className="w-4 h-4 text-green-500" /> : <Copy className="w-4 h-4" />}
              </button>
            </div>
          </div>
        )}

        {/* Active toggle */}
        <div className="flex items-center justify-between">
          <label className="text-xs font-medium text-gray-700">Active</label>
          <button
            type="button"
            onClick={() => setForm(f => ({ ...f, is_active: !f.is_active }))}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${form.is_active ? 'bg-blue-600' : 'bg-gray-300'}`}
          >
            <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${form.is_active ? 'translate-x-5' : 'translate-x-0.5'}`} />
          </button>
        </div>

        {/* Event Types */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs font-medium text-gray-700">Event Types</label>
            <div className="flex gap-2">
              <button type="button" onClick={() => setForm(f => ({ ...f, event_types: [...allEventTypes] }))}
                className="text-[10px] text-blue-600 hover:underline">All</button>
              <button type="button" onClick={() => setForm(f => ({ ...f, event_types: [] }))}
                className="text-[10px] text-gray-400 hover:underline">None</button>
            </div>
          </div>
          <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 overflow-hidden">
            {eventGroups.map(group => {
              const allGroupSelected = group.events.every(e => form.event_types.includes(e))
              const someGroupSelected = group.events.some(e => form.event_types.includes(e))
              return (
                <div key={group.label} className="p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">{group.label}</span>
                    <button type="button" onClick={() => toggleGroup(group.events)}
                      className="text-[10px] text-blue-600 hover:underline">
                      {allGroupSelected ? 'Deselect all' : someGroupSelected ? 'Select all' : 'Select all'}
                    </button>
                  </div>
                  <div className="grid grid-cols-2 gap-1.5">
                    {group.events.map(evt => (
                      <label key={evt} className="flex items-center gap-2 cursor-pointer group">
                        <input
                          type="checkbox"
                          checked={form.event_types.includes(evt)}
                          onChange={() => toggleEvent(evt)}
                          className="w-3.5 h-3.5 rounded border-gray-300 text-blue-600 cursor-pointer"
                        />
                        <span className="font-mono text-[11px] text-gray-700 group-hover:text-blue-600">{evt}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
          <p className="text-[10px] text-gray-400 mt-1">{form.event_types.length} of {allEventTypes.length} events selected</p>
        </div>

        {error && (
          <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        <div className="flex gap-2 pt-1">
          <button type="button" onClick={onClose} className="btn-secondary flex-1">Cancel</button>
          <button type="submit" disabled={loading} className="btn-primary flex-1">
            {loading ? 'Saving…' : isEdit ? 'Save Changes' : 'Create Endpoint'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Webhooks() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<'endpoints' | 'events'>('endpoints')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<WebhookEndpoint | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<WebhookEndpoint | null>(null)
  const [testState, setTestState] = useState<Record<string, 'loading' | 'ok' | 'err'>>({})
  const [statusFilter, setStatusFilter] = useState('')
  const [endpointFilter, setEndpointFilter] = useState('')

  // ── Queries ──────────────────────────────────────────────────────────────

  const { data: eventTypesData } = useQuery({
    queryKey: ['webhooks', 'event-types'],
    queryFn: fetchWebhookEventTypes,
    staleTime: Infinity,
  })
  const ALL_EVENT_TYPES = eventTypesData?.event_types ?? FALLBACK_EVENT_TYPES
  const EVENT_GROUPS = eventTypesData?.groups ?? FALLBACK_EVENT_GROUPS

  const { data: endpoints = [], isLoading: loadingEndpoints, refetch: refetchEndpoints } = useQuery({
    queryKey: ['webhooks', 'endpoints'],
    queryFn: fetchWebhookEndpoints,
  })

  const { data: events = [], isLoading: loadingEvents, refetch: refetchEvents } = useQuery({
    queryKey: ['webhooks', 'events', endpointFilter, statusFilter],
    queryFn: () => fetchWebhookEvents({
      endpoint_id: endpointFilter || undefined,
      status: statusFilter || undefined,
      page_size: 100,
    }),
    enabled: tab === 'events',
  })

  // ── Mutations ─────────────────────────────────────────────────────────────

  const toggleMut = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      updateWebhookEndpoint(id, { is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['webhooks', 'endpoints'] }),
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteWebhookEndpoint(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['webhooks', 'endpoints'] })
      setDeleteTarget(null)
    },
  })

  const retryMut = useMutation({
    mutationFn: retryWebhookEvent,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['webhooks', 'events'] }),
  })

  // ── Test ─────────────────────────────────────────────────────────────────

  async function handleTest(id: string) {
    setTestState(s => ({ ...s, [id]: 'loading' }))
    try {
      await testWebhookEndpoint(id)
      setTestState(s => ({ ...s, [id]: 'ok' }))
      setTimeout(() => setTestState(s => { const n = { ...s }; delete n[id]; return n }), 3000)
    } catch {
      setTestState(s => ({ ...s, [id]: 'err' }))
      setTimeout(() => setTestState(s => { const n = { ...s }; delete n[id]; return n }), 4000)
    }
  }

  // ── Stats ─────────────────────────────────────────────────────────────────

  const active = endpoints.filter(e => e.is_active).length
  const totalEvents = events.length
  const delivered = events.filter(e => e.status === 'DELIVERED').length
  const failed = events.filter(e => e.status === 'FAILED' || e.status === 'ABANDONED').length

  return (
    <div className="p-6 space-y-5 max-w-6xl">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-gray-900">Webhooks</h1>
            <span className="flex items-center gap-1 px-2 py-0.5 bg-purple-100 text-purple-700 rounded-full text-[10px] font-semibold uppercase tracking-wider">
              <Shield className="w-3 h-3" /> Admin
            </span>
          </div>
          <p className="text-sm text-gray-500 mt-0.5">
            Configure HTTP endpoints to receive real-time order lifecycle events
          </p>
        </div>
        {tab === 'endpoints' && (
          <button onClick={() => { setEditing(null); setModalOpen(true) }} className="btn-primary">
            <Plus className="w-4 h-4" /> New Endpoint
          </button>
        )}
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Total Endpoints', value: endpoints.length, color: 'text-gray-900' },
          { label: 'Active', value: active, color: 'text-green-600' },
          { label: 'Inactive', value: endpoints.length - active, color: 'text-gray-500' },
          {
            label: tab === 'events' ? 'Success Rate' : 'Event Types',
            value: tab === 'events'
              ? (totalEvents > 0 ? `${Math.round((delivered / totalEvents) * 100)}%` : '—')
              : ALL_EVENT_TYPES.length,
            color: 'text-blue-600',
          },
        ].map(({ label, value, color }) => (
          <div key={label} className="card p-4">
            <p className="text-xs text-gray-500 font-medium">{label}</p>
            <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 p-1 rounded-lg w-fit">
        {([['endpoints', 'Endpoints'], ['events', 'Delivery Log']] as const).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-1.5 text-sm font-medium rounded-md transition-colors ${
              tab === key ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── Endpoints Tab ─────────────────────────────────────────────────── */}
      {tab === 'endpoints' && (
        <div className="card overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
            <p className="text-sm font-medium text-gray-700">{endpoints.length} endpoint{endpoints.length !== 1 ? 's' : ''}</p>
            <button onClick={() => refetchEndpoints()} className="btn-secondary text-xs py-1">
              <RefreshCw className="w-3.5 h-3.5" /> Refresh
            </button>
          </div>
          {loadingEndpoints ? (
            <div className="divide-y divide-gray-100">
              {[1, 2, 3].map(i => (
                <div key={i} className="p-4 animate-pulse flex gap-3">
                  <div className="w-8 h-8 bg-gray-100 rounded-lg" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 bg-gray-100 rounded w-48" />
                    <div className="h-3 bg-gray-100 rounded w-72" />
                  </div>
                </div>
              ))}
            </div>
          ) : endpoints.length === 0 ? (
            <div className="py-16 text-center">
              <div className="w-12 h-12 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-3">
                <Webhook className="w-6 h-6 text-gray-400" />
              </div>
              <p className="text-sm font-medium text-gray-700">No webhook endpoints configured</p>
              <p className="text-xs text-gray-400 mt-1">Create one to start receiving order events</p>
              <button onClick={() => { setEditing(null); setModalOpen(true) }} className="btn-primary mt-4">
                <Plus className="w-4 h-4" /> Create Endpoint
              </button>
            </div>
          ) : (
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  {['Name & URL', 'Events', 'Status', 'Created', 'Actions'].map(h => (
                    <th key={h} className="table-header">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {endpoints.map(ep => {
                  const ts = testState[ep.id]
                  return (
                    <tr key={ep.id} className="hover:bg-gray-50 transition-colors">
                      {/* Name & URL */}
                      <td className="table-cell">
                        <div className="flex items-center gap-3">
                          <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${ep.is_active ? 'bg-blue-100' : 'bg-gray-100'}`}>
                            <Webhook className={`w-4 h-4 ${ep.is_active ? 'text-blue-600' : 'text-gray-400'}`} />
                          </div>
                          <div>
                            <p className="font-medium text-sm text-gray-900">{ep.name}</p>
                            <p className="font-mono text-xs text-gray-400 truncate max-w-[280px]">{ep.url}</p>
                          </div>
                        </div>
                      </td>
                      {/* Events */}
                      <td className="table-cell">
                        <EventTypesPill types={ep.event_types} totalEventTypes={ALL_EVENT_TYPES.length} />
                      </td>
                      {/* Status */}
                      <td className="table-cell">
                        <div className="flex items-center gap-2">
                          <StatusBadge value={ep.is_active ? 'ACTIVE' : 'INACTIVE'} />
                        </div>
                      </td>
                      {/* Created */}
                      <td className="table-cell text-xs text-gray-500">
                        {ep.created_at.slice(0, 10)}
                      </td>
                      {/* Actions */}
                      <td className="table-cell">
                        <div className="flex items-center gap-1">
                          {/* Test */}
                          <button
                            onClick={() => handleTest(ep.id)}
                            disabled={ts === 'loading'}
                            title="Send test event"
                            className={`p-1.5 rounded-lg text-xs transition-colors ${
                              ts === 'ok' ? 'text-green-600 bg-green-50' :
                              ts === 'err' ? 'text-red-600 bg-red-50' :
                              'text-gray-500 hover:text-blue-600 hover:bg-blue-50'
                            }`}
                          >
                            {ts === 'ok' ? <CheckCircle className="w-4 h-4" /> :
                             ts === 'err' ? <XCircle className="w-4 h-4" /> :
                             <TestTube2 className={`w-4 h-4 ${ts === 'loading' ? 'animate-spin' : ''}`} />}
                          </button>
                          {/* Edit */}
                          <button
                            onClick={() => { setEditing(ep); setModalOpen(true) }}
                            title="Edit"
                            className="p-1.5 rounded-lg text-gray-500 hover:text-blue-600 hover:bg-blue-50 transition-colors"
                          >
                            <Edit2 className="w-4 h-4" />
                          </button>
                          {/* Toggle active */}
                          <button
                            onClick={() => toggleMut.mutate({ id: ep.id, is_active: !ep.is_active })}
                            title={ep.is_active ? 'Deactivate' : 'Activate'}
                            className={`p-1.5 rounded-lg transition-colors ${
                              ep.is_active
                                ? 'text-green-600 hover:bg-red-50 hover:text-red-600'
                                : 'text-gray-400 hover:bg-green-50 hover:text-green-600'
                            }`}
                          >
                            <Power className="w-4 h-4" />
                          </button>
                          {/* Delete */}
                          <button
                            onClick={() => setDeleteTarget(ep)}
                            title="Delete"
                            className="p-1.5 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Delivery Log Tab ───────────────────────────────────────────────── */}
      {tab === 'events' && (
        <div className="space-y-3">
          {/* Filters */}
          <div className="flex items-center gap-3 flex-wrap">
            <select
              value={endpointFilter}
              onChange={e => setEndpointFilter(e.target.value)}
              className="input text-sm py-1.5 w-56"
            >
              <option value="">All Endpoints</option>
              {endpoints.map(ep => (
                <option key={ep.id} value={ep.id}>{ep.name}</option>
              ))}
            </select>
            <div className="flex gap-1">
              {['', 'DELIVERED', 'FAILED', 'PENDING', 'ABANDONED'].map(s => (
                <button
                  key={s}
                  onClick={() => setStatusFilter(s)}
                  className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                    statusFilter === s
                      ? 'bg-gray-900 text-white'
                      : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  {s || 'All'}
                </button>
              ))}
            </div>
            <button onClick={() => refetchEvents()} className="btn-secondary text-xs py-1 ml-auto">
              <RefreshCw className="w-3.5 h-3.5" /> Refresh
            </button>
          </div>

          {/* Summary bar */}
          {events.length > 0 && (
            <div className="flex gap-4 px-4 py-2 bg-gray-50 rounded-lg text-xs text-gray-600">
              <span className="flex items-center gap-1"><CheckCircle className="w-3.5 h-3.5 text-green-500" />{delivered} delivered</span>
              <span className="flex items-center gap-1"><XCircle className="w-3.5 h-3.5 text-red-500" />{failed} failed</span>
              <span className="flex items-center gap-1"><Clock className="w-3.5 h-3.5 text-gray-400" />{events.filter(e => e.status === 'PENDING').length} pending</span>
            </div>
          )}

          <div className="card overflow-hidden">
            {loadingEvents ? (
              <div className="p-8 text-center text-sm text-gray-400 animate-pulse">Loading delivery log…</div>
            ) : events.length === 0 ? (
              <div className="py-16 text-center">
                <div className="w-12 h-12 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-3">
                  <Clock className="w-6 h-6 text-gray-400" />
                </div>
                <p className="text-sm font-medium text-gray-700">No delivery events yet</p>
                <p className="text-xs text-gray-400 mt-1">Events appear here when orders trigger webhook deliveries</p>
              </div>
            ) : (
              <table className="w-full">
                <thead className="bg-gray-50">
                  <tr>
                    {['Time', 'Event', 'Endpoint', 'Order', 'Status', 'HTTP', 'Attempts', ''].map(h => (
                      <th key={h} className="table-header">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {events.map(ev => {
                    const ep = endpoints.find(e => e.id === ev.endpoint_id)
                    const canRetry = ev.status === 'FAILED' || ev.status === 'ABANDONED'
                    return (
                      <tr key={ev.id} className="hover:bg-gray-50 transition-colors">
                        <td className="table-cell text-xs text-gray-400 whitespace-nowrap">
                          {ev.created_at.slice(0, 19).replace('T', ' ')}
                        </td>
                        <td className="table-cell">
                          <span className="font-mono text-xs bg-gray-100 px-1.5 py-0.5 rounded text-gray-700">
                            {ev.event_type}
                          </span>
                        </td>
                        <td className="table-cell text-xs text-gray-600 max-w-[160px] truncate">
                          {ep?.name ?? <span className="text-gray-400 font-mono">{ev.endpoint_id.slice(0, 8)}…</span>}
                        </td>
                        <td className="table-cell">
                          {ev.order_id
                            ? <span className="font-mono text-xs text-blue-600">{ev.order_id.slice(0, 8)}…</span>
                            : <span className="text-gray-300">—</span>
                          }
                        </td>
                        <td className="table-cell">
                          <div className="flex items-center gap-1.5">
                            <DeliveryStatusIcon status={ev.status} />
                            <StatusBadge value={ev.status} />
                          </div>
                        </td>
                        <td className="table-cell text-xs">
                          {ev.last_response_code
                            ? <span className={ev.last_response_code >= 200 && ev.last_response_code < 300 ? 'text-green-600' : 'text-red-600'}>
                                {ev.last_response_code}
                              </span>
                            : <span className="text-gray-300">—</span>
                          }
                        </td>
                        <td className="table-cell text-xs text-gray-500 text-center">
                          {ev.attempt_count}
                        </td>
                        <td className="table-cell">
                          {canRetry && (
                            <button
                              onClick={() => retryMut.mutate(ev.id)}
                              disabled={retryMut.isPending}
                              className="flex items-center gap-1 px-2 py-1 text-xs bg-amber-50 text-amber-700 border border-amber-200 rounded-lg hover:bg-amber-100 transition-colors"
                            >
                              <RotateCcw className="w-3 h-3" /> Retry
                            </button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* ── Create/Edit Modal ─────────────────────────────────────────────── */}
      {modalOpen && (
        <EndpointModal
          open={modalOpen}
          onClose={() => { setModalOpen(false); setEditing(null) }}
          editing={editing}
          allEventTypes={ALL_EVENT_TYPES}
          eventGroups={EVENT_GROUPS}
        />
      )}

      {/* ── Delete Confirm Modal ──────────────────────────────────────────── */}
      {deleteTarget && (
        <Modal open onClose={() => setDeleteTarget(null)} title="Delete Webhook Endpoint">
          <div className="space-y-4">
            <div className="flex items-start gap-3 p-4 bg-red-50 border border-red-200 rounded-lg">
              <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-red-800">Delete "{deleteTarget.name}"?</p>
                <p className="text-xs text-red-600 mt-1">
                  This will permanently delete the endpoint and all its delivery history. This action cannot be undone.
                </p>
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={() => setDeleteTarget(null)} className="btn-secondary flex-1">Cancel</button>
              <button
                onClick={() => deleteMut.mutate(deleteTarget.id)}
                disabled={deleteMut.isPending}
                className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
              >
                {deleteMut.isPending ? 'Deleting…' : 'Delete Endpoint'}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
