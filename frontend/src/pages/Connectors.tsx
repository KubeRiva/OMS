import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plug, Plus, RefreshCw, Trash2, Edit2, CheckCircle, XCircle,
  AlertCircle, ChevronRight, Copy, Check, Zap, ExternalLink,
  ShoppingBag, Package, Truck, Globe, ToggleLeft, ToggleRight,
  Clock, ArrowDownCircle, ArrowUpCircle, Activity,
} from 'lucide-react'
import api from '../api/client'
import Modal from '../components/Modal'

// ─── Types ────────────────────────────────────────────────────────────────────

type ConnectorType =
  | 'SHOPIFY' | 'WOOCOMMERCE' | 'AMAZON_SP' | 'MAGENTO'
  | 'BIGCOMMERCE' | 'FEDEX' | 'UPS' | 'DHL' | 'CUSTOM'

type ConnectorDirection = 'INBOUND' | 'OUTBOUND' | 'BIDIRECTIONAL'
type ConnectorStatus = 'ACTIVE' | 'INACTIVE' | 'ERROR'

interface Connector {
  id: string
  name: string
  connector_type: ConnectorType
  direction: ConnectorDirection
  status: ConnectorStatus
  config: Record<string, string>
  orders_received: number
  orders_synced: number
  last_error: string | null
  last_error_at: string | null
  last_synced_at: string | null
  created_at: string
  updated_at: string
  webhook_url: string | null
}

interface ConnectorEvent {
  id: string
  connector_id: string
  order_id: string | null
  external_order_id: string | null
  event_type: string
  direction: string
  status: string
  error_message: string | null
  created_at: string
}

interface TestResult {
  success: boolean
  message: string
  details: Record<string, string> | null
}

// ─── Platform Metadata ───────────────────────────────────────────────────────

interface PlatformMeta {
  label: string
  category: string
  color: string
  icon: React.ReactNode
  fields: FieldDef[]
  defaultDirection: ConnectorDirection
  implemented: boolean
}

interface FieldDef {
  key: string
  label: string
  placeholder: string
  type?: 'text' | 'password' | 'select'
  options?: { value: string; label: string }[]
  help?: string
}

const PLATFORMS: Record<ConnectorType, PlatformMeta> = {
  SHOPIFY: {
    label: 'Shopify',
    category: 'E-commerce',
    color: 'bg-green-500',
    icon: <ShoppingBag className="w-5 h-5 text-white" />,
    defaultDirection: 'BIDIRECTIONAL',
    implemented: true,
    fields: [
      { key: 'shop_url', label: 'Store URL', placeholder: 'my-store.myshopify.com', help: 'Your Shopify store domain (without https://)' },
      { key: 'access_token', label: 'Access Token', placeholder: 'shpat_xxxxxxxxxxxxxxxx', type: 'password', help: 'Admin API access token from Shopify Partners or Custom App' },
      { key: 'webhook_secret', label: 'Webhook Secret', placeholder: 'Generate or paste your secret', type: 'password', help: 'Used to verify incoming webhook authenticity' },
      { key: 'api_version', label: 'API Version', placeholder: '2024-01', help: 'Shopify Admin API version (default: 2024-01)' },
    ],
  },
  WOOCOMMERCE: {
    label: 'WooCommerce',
    category: 'E-commerce',
    color: 'bg-purple-600',
    icon: <ShoppingBag className="w-5 h-5 text-white" />,
    defaultDirection: 'BIDIRECTIONAL',
    implemented: false,
    fields: [
      { key: 'site_url', label: 'Site URL', placeholder: 'https://mystore.com' },
      { key: 'consumer_key', label: 'Consumer Key', placeholder: 'ck_xxxxxxxx' },
      { key: 'consumer_secret', label: 'Consumer Secret', placeholder: 'cs_xxxxxxxx', type: 'password' },
      { key: 'webhook_secret', label: 'Webhook Secret', placeholder: 'Your webhook secret', type: 'password' },
    ],
  },
  AMAZON_SP: {
    label: 'Amazon SP-API',
    category: 'E-commerce',
    color: 'bg-orange-500',
    icon: <Package className="w-5 h-5 text-white" />,
    defaultDirection: 'BIDIRECTIONAL',
    implemented: true,
    fields: [
      { key: 'marketplace_id', label: 'Marketplace ID', placeholder: 'ATVPDKIKX0DER', help: 'Amazon Marketplace ID (e.g. ATVPDKIKX0DER for US)' },
      { key: 'seller_id', label: 'Seller ID', placeholder: 'A1B2C3D4E5F6G7', help: 'Your Amazon Seller/Merchant ID' },
      { key: 'client_id', label: 'SP-API Client ID', placeholder: 'amzn1.application-oa2-client.xxx', help: 'OAuth2 client ID from your SP-API app in Seller Central' },
      { key: 'client_secret', label: 'SP-API Client Secret', placeholder: 'xxxxxxxx', type: 'password', help: 'OAuth2 client secret from your SP-API app' },
      { key: 'refresh_token', label: 'LWA Refresh Token', placeholder: 'Atzr|...', type: 'password', help: 'Login With Amazon (LWA) refresh token authorizing this app for your seller account' },
      { key: 'region', label: 'Region', placeholder: 'na', help: 'SP-API region: na (North America), eu (Europe), fe (Far East)' },
    ],
  },
  MAGENTO: {
    label: 'Magento 2',
    category: 'E-commerce',
    color: 'bg-red-600',
    icon: <ShoppingBag className="w-5 h-5 text-white" />,
    defaultDirection: 'BIDIRECTIONAL',
    implemented: false,
    fields: [
      { key: 'site_url', label: 'Site URL', placeholder: 'https://mystore.com' },
      { key: 'access_token', label: 'Access Token', placeholder: 'xxxxxxxx', type: 'password' },
      { key: 'webhook_secret', label: 'Webhook Secret', placeholder: 'Your webhook secret', type: 'password' },
    ],
  },
  BIGCOMMERCE: {
    label: 'BigCommerce',
    category: 'E-commerce',
    color: 'bg-blue-500',
    icon: <ShoppingBag className="w-5 h-5 text-white" />,
    defaultDirection: 'BIDIRECTIONAL',
    implemented: false,
    fields: [
      { key: 'store_hash', label: 'Store Hash', placeholder: 'abc123xyz' },
      { key: 'client_id', label: 'Client ID', placeholder: 'xxxxxxxx' },
      { key: 'access_token', label: 'Access Token', placeholder: 'xxxxxxxx', type: 'password' },
      { key: 'webhook_secret', label: 'Webhook Secret', placeholder: 'Your webhook secret', type: 'password' },
    ],
  },
  FEDEX: {
    label: 'FedEx',
    category: 'Carrier',
    color: 'bg-purple-700',
    icon: <Truck className="w-5 h-5 text-white" />,
    defaultDirection: 'OUTBOUND',
    implemented: false,
    fields: [
      { key: 'account_number', label: 'Account Number', placeholder: 'xxxxxxxx' },
      { key: 'api_key', label: 'API Key', placeholder: 'xxxxxxxx', type: 'password' },
      { key: 'secret_key', label: 'Secret Key', placeholder: 'xxxxxxxx', type: 'password' },
      {
        key: 'environment', label: 'Environment', placeholder: '', type: 'select',
        options: [{ value: 'sandbox', label: 'Sandbox' }, { value: 'production', label: 'Production' }],
      },
    ],
  },
  UPS: {
    label: 'UPS',
    category: 'Carrier',
    color: 'bg-yellow-600',
    icon: <Truck className="w-5 h-5 text-white" />,
    defaultDirection: 'OUTBOUND',
    implemented: false,
    fields: [
      { key: 'client_id', label: 'Client ID', placeholder: 'xxxxxxxx' },
      { key: 'client_secret', label: 'Client Secret', placeholder: 'xxxxxxxx', type: 'password' },
      { key: 'account_number', label: 'Account Number', placeholder: 'xxxxxxxx' },
    ],
  },
  DHL: {
    label: 'DHL',
    category: 'Carrier',
    color: 'bg-yellow-500',
    icon: <Truck className="w-5 h-5 text-white" />,
    defaultDirection: 'OUTBOUND',
    implemented: false,
    fields: [
      { key: 'api_key', label: 'API Key', placeholder: 'xxxxxxxx', type: 'password' },
      { key: 'account_number', label: 'Account Number', placeholder: 'xxxxxxxx' },
    ],
  },
  CUSTOM: {
    label: 'Custom',
    category: 'Generic',
    color: 'bg-gray-600',
    icon: <Globe className="w-5 h-5 text-white" />,
    defaultDirection: 'INBOUND',
    implemented: false,
    fields: [
      { key: 'webhook_secret', label: 'Webhook Secret', placeholder: 'Your HMAC secret', type: 'password' },
    ],
  },
}

// ─── API helpers ──────────────────────────────────────────────────────────────

const connectorsApi = {
  list: (): Promise<Connector[]> =>
    api.get<Connector[]>('/connectors/').then(r => r.data),
  create: (data: { name: string; connector_type: ConnectorType; direction: ConnectorDirection; config: Record<string, string> }): Promise<Connector> =>
    api.post<Connector>('/connectors/', data).then(r => r.data),
  update: (id: string, data: Partial<{ name: string; direction: ConnectorDirection; status: ConnectorStatus; config: Record<string, string> }>): Promise<Connector> =>
    api.patch<Connector>(`/connectors/${id}`, data).then(r => r.data),
  delete: (id: string) => api.delete(`/connectors/${id}`),
  toggle: (id: string): Promise<{ id: string; status: ConnectorStatus }> =>
    api.post<{ id: string; status: ConnectorStatus }>(`/connectors/${id}/toggle`).then(r => r.data),
  test: (id: string): Promise<TestResult> =>
    api.post<TestResult>(`/connectors/${id}/test`).then(r => r.data),
  events: (id: string, offset = 0): Promise<ConnectorEvent[]> =>
    api.get<ConnectorEvent[]>(`/connectors/${id}/events`, { params: { limit: 50, offset } }).then(r => r.data),
  generateSecret: (): Promise<{ secret: string }> =>
    api.post<{ secret: string }>('/connectors/generate-secret').then(r => r.data),
}

// ─── Utility Components ───────────────────────────────────────────────────────

function StatusBadge({ status }: { status: ConnectorStatus }) {
  const map: Record<ConnectorStatus, { color: string; dot: string; label: string }> = {
    ACTIVE: { color: 'bg-green-50 text-green-700 border-green-200', dot: 'bg-green-500', label: 'Active' },
    INACTIVE: { color: 'bg-gray-50 text-gray-500 border-gray-200', dot: 'bg-gray-400', label: 'Inactive' },
    ERROR: { color: 'bg-red-50 text-red-700 border-red-200', dot: 'bg-red-500', label: 'Error' },
  }
  const s = map[status]
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[10px] font-semibold ${s.color}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  )
}

function DirectionBadge({ direction }: { direction: ConnectorDirection }) {
  const map: Record<ConnectorDirection, { label: string; color: string }> = {
    INBOUND: { label: 'Inbound', color: 'text-blue-600 bg-blue-50' },
    OUTBOUND: { label: 'Outbound', color: 'text-purple-600 bg-purple-50' },
    BIDIRECTIONAL: { label: 'Bidirectional', color: 'text-green-600 bg-green-50' },
  }
  const d = map[direction]
  return (
    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${d.color}`}>{d.label}</span>
  )
}

function PlatformIcon({ type, size = 'sm' }: { type: ConnectorType; size?: 'sm' | 'md' }) {
  const p = PLATFORMS[type]
  const sz = size === 'md' ? 'w-10 h-10' : 'w-7 h-7'
  return (
    <div className={`${sz} ${p.color} rounded-lg flex items-center justify-center flex-shrink-0`}>
      {p.icon}
    </div>
  )
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button onClick={copy} className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors" title="Copy">
      {copied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
    </button>
  )
}

function timeAgo(dateStr: string | null) {
  if (!dateStr) return null
  const diff = (Date.now() - new Date(dateStr).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

// ─── Connector Card ───────────────────────────────────────────────────────────

function ConnectorCard({
  connector,
  onEdit,
  onShowEvents,
}: {
  connector: Connector
  onEdit: (c: Connector) => void
  onShowEvents: (c: Connector) => void
}) {
  const qc = useQueryClient()
  const platform = PLATFORMS[connector.connector_type]

  const toggleMut = useMutation({
    mutationFn: () => connectorsApi.toggle(connector.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connectors'] }),
  })

  const deleteMut = useMutation({
    mutationFn: () => connectorsApi.delete(connector.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connectors'] }),
  })

  const testMut = useMutation({
    mutationFn: () => connectorsApi.test(connector.id),
  })

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [testResult, setTestResult] = useState<TestResult | null>(null)

  const handleTest = async () => {
    setTestResult(null)
    const result = await testMut.mutateAsync()
    setTestResult(result)
    setTimeout(() => setTestResult(null), 6000)
  }

  return (
    <div className={`bg-white rounded-xl border ${connector.status === 'ERROR' ? 'border-red-200' : 'border-gray-200'} shadow-sm hover:shadow-md transition-shadow`}>
      <div className="p-4">
        {/* Header */}
        <div className="flex items-start gap-3">
          <PlatformIcon type={connector.connector_type} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <p className="text-sm font-semibold text-gray-900 truncate">{connector.name}</p>
              <StatusBadge status={connector.status} />
              <DirectionBadge direction={connector.direction} />
            </div>
            <p className="text-[11px] text-gray-400 mt-0.5">
              {platform.label} · {platform.category}
              {!platform.implemented && (
                <span className="ml-1.5 text-[9px] bg-yellow-100 text-yellow-700 px-1 py-0.5 rounded font-medium uppercase tracking-wide">
                  Coming soon
                </span>
              )}
            </p>
          </div>
        </div>

        {/* Error message */}
        {connector.status === 'ERROR' && connector.last_error && (
          <div className="mt-2.5 flex items-start gap-2 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
            <AlertCircle className="w-3.5 h-3.5 text-red-500 flex-shrink-0 mt-0.5" />
            <p className="text-[11px] text-red-700 line-clamp-2">{connector.last_error}</p>
          </div>
        )}

        {/* Stats */}
        <div className="mt-3 grid grid-cols-2 gap-2">
          <div className="bg-gray-50 rounded-lg px-3 py-2">
            <div className="flex items-center gap-1.5">
              <ArrowDownCircle className="w-3 h-3 text-blue-500" />
              <p className="text-[10px] text-gray-500 font-medium">Orders received</p>
            </div>
            <p className="text-sm font-bold text-gray-800 mt-0.5">{connector.orders_received.toLocaleString()}</p>
          </div>
          <div className="bg-gray-50 rounded-lg px-3 py-2">
            <div className="flex items-center gap-1.5">
              <ArrowUpCircle className="w-3 h-3 text-purple-500" />
              <p className="text-[10px] text-gray-500 font-medium">Fulfillments synced</p>
            </div>
            <p className="text-sm font-bold text-gray-800 mt-0.5">{connector.orders_synced.toLocaleString()}</p>
          </div>
        </div>

        {/* Last sync */}
        {connector.last_synced_at && (
          <p className="mt-2 text-[10px] text-gray-400 flex items-center gap-1">
            <Clock className="w-3 h-3" />
            Last sync {timeAgo(connector.last_synced_at)}
          </p>
        )}

        {/* Webhook URL (inbound only, not for Amazon which uses polling) */}
        {connector.webhook_url && connector.direction !== 'OUTBOUND' && connector.connector_type !== 'AMAZON_SP' && (
          <div className="mt-2.5">
            <p className="text-[10px] font-medium text-gray-500 mb-1">Webhook URL</p>
            <div className="flex items-center gap-1 bg-gray-50 rounded-lg px-2 py-1.5 border border-gray-200">
              <code className="text-[10px] text-gray-600 flex-1 truncate font-mono">{connector.webhook_url}</code>
              <CopyButton value={connector.webhook_url} />
            </div>
          </div>
        )}
        {/* Amazon polling note */}
        {connector.connector_type === 'AMAZON_SP' && (
          <div className="mt-2.5 flex items-center gap-1.5 text-[10px] text-orange-600">
            <Clock className="w-3 h-3 flex-shrink-0" />
            <span>Polls Amazon every 15 min for new orders</span>
          </div>
        )}

        {/* Test result */}
        {testResult && (
          <div className={`mt-2.5 flex items-start gap-2 rounded-lg px-3 py-2 border ${testResult.success ? 'bg-green-50 border-green-100' : 'bg-red-50 border-red-100'}`}>
            {testResult.success
              ? <CheckCircle className="w-3.5 h-3.5 text-green-500 flex-shrink-0 mt-0.5" />
              : <XCircle className="w-3.5 h-3.5 text-red-500 flex-shrink-0 mt-0.5" />
            }
            <div>
              <p className={`text-[11px] font-medium ${testResult.success ? 'text-green-700' : 'text-red-700'}`}>{testResult.message}</p>
              {testResult.details && (
                <div className="mt-1 space-y-0.5">
                  {Object.entries(testResult.details).map(([k, v]) => v && (
                    <p key={k} className="text-[10px] text-gray-500">{k.replace(/_/g, ' ')}: <span className="font-medium text-gray-700">{v}</span></p>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="px-4 py-3 border-t border-gray-100 flex items-center gap-2 flex-wrap">
        <button
          onClick={handleTest}
          disabled={testMut.isPending}
          className="btn-secondary text-xs px-2 py-1 flex items-center gap-1"
        >
          {testMut.isPending ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
          Test
        </button>
        <button
          onClick={() => onEdit(connector)}
          className="btn-secondary text-xs px-2 py-1 flex items-center gap-1"
        >
          <Edit2 className="w-3 h-3" />
          Edit
        </button>
        <button
          onClick={() => onShowEvents(connector)}
          className="btn-secondary text-xs px-2 py-1 flex items-center gap-1"
        >
          <Activity className="w-3 h-3" />
          Events
        </button>
        <button
          onClick={() => toggleMut.mutate()}
          disabled={toggleMut.isPending}
          className="btn-secondary text-xs px-2 py-1 flex items-center gap-1 ml-auto"
        >
          {connector.status === 'ACTIVE'
            ? <><ToggleRight className="w-3.5 h-3.5 text-green-500" /> Disable</>
            : <><ToggleLeft className="w-3.5 h-3.5 text-gray-400" /> Enable</>
          }
        </button>
        {showDeleteConfirm ? (
          <>
            <span className="text-[10px] text-red-600">Confirm delete?</span>
            <button
              onClick={() => { deleteMut.mutate(); setShowDeleteConfirm(false) }}
              className="text-[11px] font-medium text-red-600 hover:text-red-800"
            >Yes</button>
            <button
              onClick={() => setShowDeleteConfirm(false)}
              className="text-[11px] text-gray-400 hover:text-gray-600"
            >No</button>
          </>
        ) : (
          <button
            onClick={() => setShowDeleteConfirm(true)}
            className="p-1 rounded hover:bg-red-50 text-gray-300 hover:text-red-500 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </div>
  )
}

// ─── Add/Edit Modal ───────────────────────────────────────────────────────────

type ModalMode = 'add-step1' | 'add-step2' | 'edit'

function ConnectorModal({
  open,
  onClose,
  editing,
}: {
  open: boolean
  onClose: () => void
  editing: Connector | null
}) {
  const qc = useQueryClient()
  const [step, setStep] = useState<1 | 2>(editing ? 2 : 1)
  const [selectedType, setSelectedType] = useState<ConnectorType | null>(editing?.connector_type ?? null)
  const [name, setName] = useState(editing?.name ?? '')
  const [direction, setDirection] = useState<ConnectorDirection>(editing?.direction ?? 'BIDIRECTIONAL')
  const [config, setConfig] = useState<Record<string, string>>(
    editing ? Object.fromEntries(
      Object.entries(editing.config).map(([k, v]) => [k, v === '***' ? '' : v])
    ) : {}
  )
  const [generating, setGenerating] = useState(false)

  const createMut = useMutation({
    mutationFn: connectorsApi.create,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['connectors'] }); onClose() },
  })
  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof connectorsApi.update>[1] }) =>
      connectorsApi.update(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['connectors'] }); onClose() },
  })

  const platform = selectedType ? PLATFORMS[selectedType] : null

  const handleGenerateSecret = async (fieldKey: string) => {
    setGenerating(true)
    try {
      const { secret } = await connectorsApi.generateSecret()
      setConfig(c => ({ ...c, [fieldKey]: secret }))
    } finally {
      setGenerating(false)
    }
  }

  const handleSubmit = () => {
    if (!selectedType || !name) return
    if (editing) {
      updateMut.mutate({ id: editing.id, data: { name, direction, config } })
    } else {
      createMut.mutate({ name, connector_type: selectedType, direction, config })
    }
  }

  const isPending = createMut.isPending || updateMut.isPending
  const error = createMut.error || updateMut.error

  const groups = Array.from(new Set(Object.values(PLATFORMS).map(p => p.category)))

  return (
    <Modal open={open} onClose={onClose} title={editing ? `Edit ${editing.name}` : 'Add Connector'} size="lg">
      {/* Step 1: Platform selection */}
      {!editing && step === 1 && (
        <div>
          <p className="text-xs text-gray-500 mb-4">Choose the platform to integrate with.</p>
          {groups.map(group => (
            <div key={group} className="mb-4">
              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2">{group}</p>
              <div className="grid grid-cols-3 gap-2">
                {Object.entries(PLATFORMS)
                  .filter(([, p]) => p.category === group)
                  .map(([type, p]) => (
                    <button
                      key={type}
                      onClick={() => {
                        setSelectedType(type as ConnectorType)
                        setDirection(p.defaultDirection)
                        setConfig({})
                        setStep(2)
                      }}
                      className={`flex flex-col items-center gap-2 p-3 rounded-xl border-2 transition-all ${
                        selectedType === type
                          ? 'border-blue-500 bg-blue-50'
                          : 'border-gray-200 hover:border-gray-300 bg-white'
                      } ${!p.implemented ? 'opacity-60' : ''}`}
                    >
                      <div className={`w-8 h-8 ${p.color} rounded-lg flex items-center justify-center`}>
                        {p.icon}
                      </div>
                      <span className="text-xs font-medium text-gray-700">{p.label}</span>
                      {!p.implemented && (
                        <span className="text-[9px] bg-gray-100 text-gray-400 px-1.5 py-0.5 rounded font-medium">
                          Soon
                        </span>
                      )}
                    </button>
                  ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Step 2: Configuration */}
      {(editing || step === 2) && selectedType && platform && (
        <div>
          {!editing && (
            <button
              onClick={() => setStep(1)}
              className="flex items-center gap-1 text-[11px] text-blue-600 hover:text-blue-800 mb-4"
            >
              ← Back to platform selection
            </button>
          )}

          <div className="flex items-center gap-2.5 mb-5 pb-4 border-b border-gray-100">
            <PlatformIcon type={selectedType} size="md" />
            <div>
              <p className="text-sm font-semibold text-gray-800">{platform.label}</p>
              <p className="text-[11px] text-gray-400">{platform.category}</p>
            </div>
          </div>

          <div className="space-y-3">
            <div>
              <label className="label">Connector Name</label>
              <input
                className="input"
                placeholder={`e.g. My ${platform.label} Store`}
                value={name}
                onChange={e => setName(e.target.value)}
              />
            </div>

            <div>
              <label className="label">Direction</label>
              <select className="select" value={direction} onChange={e => setDirection(e.target.value as ConnectorDirection)}>
                <option value="BIDIRECTIONAL">Bidirectional (receive orders + send fulfillments)</option>
                <option value="INBOUND">Inbound only (receive orders)</option>
                <option value="OUTBOUND">Outbound only (send fulfillments)</option>
              </select>
            </div>

            <div className="border-t border-gray-100 pt-3">
              <p className="text-xs font-semibold text-gray-600 mb-3">Platform Configuration</p>
              {platform.fields.map(field => (
                <div key={field.key} className="mb-3">
                  <label className="label">{field.label}</label>
                  {field.type === 'select' ? (
                    <select
                      className="select"
                      value={config[field.key] ?? ''}
                      onChange={e => setConfig(c => ({ ...c, [field.key]: e.target.value }))}
                    >
                      <option value="">Select...</option>
                      {field.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                  ) : (
                    <div className="flex gap-2">
                      <input
                        className="input flex-1"
                        type={field.type === 'password' ? 'password' : 'text'}
                        placeholder={field.placeholder}
                        value={config[field.key] ?? ''}
                        onChange={e => setConfig(c => ({ ...c, [field.key]: e.target.value }))}
                      />
                      {field.key === 'webhook_secret' && (
                        <button
                          type="button"
                          onClick={() => handleGenerateSecret(field.key)}
                          disabled={generating}
                          className="btn-secondary text-xs px-2.5 whitespace-nowrap"
                        >
                          {generating ? <RefreshCw className="w-3 h-3 animate-spin" /> : 'Generate'}
                        </button>
                      )}
                    </div>
                  )}
                  {field.help && <p className="text-[10px] text-gray-400 mt-0.5">{field.help}</p>}
                </div>
              ))}
            </div>

            {/* Webhook URL hint for inbound connectors */}
            {direction !== 'OUTBOUND' && editing?.webhook_url && (
              <div className="bg-blue-50 border border-blue-100 rounded-lg p-3">
                <p className="text-[10px] font-semibold text-blue-700 mb-1.5">
                  Configure this webhook URL in {platform.label}:
                </p>
                <div className="flex items-center gap-1 bg-white rounded border border-blue-200 px-2 py-1.5">
                  <code className="text-[10px] text-blue-800 flex-1 truncate font-mono">{editing.webhook_url}</code>
                  <CopyButton value={editing.webhook_url} />
                </div>
                {editing.connector_type === 'SHOPIFY' ? (
                  <div className="mt-1.5">
                    <p className="text-[10px] text-blue-700 font-medium mb-1">Register this URL in Shopify for each topic:</p>
                    <div className="flex flex-wrap gap-1">
                      {['orders/create', 'orders/paid', 'products/create', 'products/update'].map(t => (
                        <span key={t} className="text-[9px] font-mono bg-blue-100 text-blue-800 px-1.5 py-0.5 rounded">{t}</span>
                      ))}
                    </div>
                    <p className="text-[10px] text-blue-500 mt-1">All topics share this one URL and the same signing secret.</p>
                  </div>
                ) : editing.connector_type === 'AMAZON_SP' ? (
                  <p className="text-[10px] text-orange-600 mt-1.5">
                    Amazon uses <strong>polling</strong>, not webhooks. KubeRiva polls Amazon every 15 minutes for new orders automatically — no webhook registration required.
                  </p>
                ) : (
                  <p className="text-[10px] text-blue-600 mt-1.5">
                    Subscribe to: <code className="font-mono">orders/create</code> and <code className="font-mono">orders/paid</code>
                  </p>
                )}
              </div>
            )}
          </div>

          {error && (
            <div className="mt-3 flex items-center gap-2 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
              <XCircle className="w-3.5 h-3.5 text-red-500 flex-shrink-0" />
              <p className="text-[11px] text-red-700">
                {(error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Something went wrong'}
              </p>
            </div>
          )}

          <div className="mt-5 flex gap-2 justify-end">
            <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
            <button
              onClick={handleSubmit}
              disabled={!name || isPending}
              className="btn-primary text-sm flex items-center gap-1.5"
            >
              {isPending && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
              {editing ? 'Save Changes' : 'Create Connector'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}

// ─── Events Log Modal ─────────────────────────────────────────────────────────

function EventsModal({ connector, open, onClose }: { connector: Connector | null; open: boolean; onClose: () => void }) {
  const { data: events, isLoading } = useQuery({
    queryKey: ['connector-events', connector?.id],
    queryFn: () => connector ? connectorsApi.events(connector.id) : Promise.resolve([]),
    enabled: open && !!connector,
  })

  return (
    <Modal open={open} onClose={onClose} title={`Events — ${connector?.name ?? ''}`} size="xl">
      {isLoading && <p className="text-sm text-gray-400 text-center py-8">Loading events...</p>}
      {!isLoading && (!events || events.length === 0) && (
        <div className="text-center py-12">
          <Activity className="w-8 h-8 text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-400">No events recorded yet.</p>
        </div>
      )}
      {events && events.length > 0 && (
        <div className="space-y-1.5">
          {events.map(ev => (
            <div key={ev.id} className={`flex items-start gap-3 px-3 py-2.5 rounded-lg border ${ev.status === 'success' ? 'bg-green-50/50 border-green-100' : 'bg-red-50/50 border-red-100'}`}>
              <div className="flex-shrink-0 mt-0.5">
                {ev.status === 'success'
                  ? <CheckCircle className="w-4 h-4 text-green-500" />
                  : <XCircle className="w-4 h-4 text-red-500" />
                }
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-semibold text-gray-700">{ev.event_type}</span>
                  <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded uppercase ${ev.direction === 'inbound' ? 'bg-blue-100 text-blue-600' : 'bg-purple-100 text-purple-600'}`}>
                    {ev.direction}
                  </span>
                  {ev.external_order_id && (
                    <span className="text-[10px] text-gray-400 font-mono">ext:{ev.external_order_id}</span>
                  )}
                </div>
                {ev.error_message && (
                  <p className="text-[11px] text-red-600 mt-0.5 line-clamp-2">{ev.error_message}</p>
                )}
                <p className="text-[10px] text-gray-400 mt-0.5">{new Date(ev.created_at).toLocaleString()}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function Connectors() {
  const { data: connectors, isLoading, refetch } = useQuery({
    queryKey: ['connectors'],
    queryFn: connectorsApi.list,
    refetchInterval: 15_000,
  })

  const [showModal, setShowModal] = useState(false)
  const [editingConnector, setEditingConnector] = useState<Connector | null>(null)
  const [eventsConnector, setEventsConnector] = useState<Connector | null>(null)
  const [showEventsModal, setShowEventsModal] = useState(false)

  const handleEdit = useCallback((c: Connector) => {
    setEditingConnector(c)
    setShowModal(true)
  }, [])

  const handleShowEvents = useCallback((c: Connector) => {
    setEventsConnector(c)
    setShowEventsModal(true)
  }, [])

  const handleCloseModal = useCallback(() => {
    setShowModal(false)
    setEditingConnector(null)
  }, [])

  const activeCount = connectors?.filter(c => c.status === 'ACTIVE').length ?? 0
  const errorCount = connectors?.filter(c => c.status === 'ERROR').length ?? 0

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Connectors</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Integrate with e-commerce platforms, carriers, and other systems
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => refetch()} className="btn-secondary p-2" title="Refresh">
            <RefreshCw className="w-4 h-4" />
          </button>
          <button onClick={() => { setEditingConnector(null); setShowModal(true) }} className="btn-primary flex items-center gap-1.5 text-sm">
            <Plus className="w-4 h-4" />
            Add Connector
          </button>
        </div>
      </div>

      {/* Summary stats */}
      {connectors && connectors.length > 0 && (
        <div className="flex gap-3 mb-6">
          <div className="bg-white border border-gray-200 rounded-lg px-4 py-2.5 flex items-center gap-2.5">
            <Plug className="w-4 h-4 text-gray-400" />
            <div>
              <p className="text-[10px] text-gray-400 font-medium">Total</p>
              <p className="text-lg font-bold text-gray-900 leading-none">{connectors.length}</p>
            </div>
          </div>
          <div className="bg-white border border-green-200 rounded-lg px-4 py-2.5 flex items-center gap-2.5">
            <CheckCircle className="w-4 h-4 text-green-500" />
            <div>
              <p className="text-[10px] text-gray-400 font-medium">Active</p>
              <p className="text-lg font-bold text-green-700 leading-none">{activeCount}</p>
            </div>
          </div>
          {errorCount > 0 && (
            <div className="bg-white border border-red-200 rounded-lg px-4 py-2.5 flex items-center gap-2.5">
              <AlertCircle className="w-4 h-4 text-red-500" />
              <div>
                <p className="text-[10px] text-gray-400 font-medium">Errors</p>
                <p className="text-lg font-bold text-red-700 leading-none">{errorCount}</p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="text-center py-20">
          <RefreshCw className="w-6 h-6 text-gray-300 mx-auto animate-spin mb-2" />
          <p className="text-sm text-gray-400">Loading connectors...</p>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && (!connectors || connectors.length === 0) && (
        <div className="text-center py-20 bg-white rounded-2xl border border-dashed border-gray-200">
          <Plug className="w-10 h-10 text-gray-200 mx-auto mb-3" />
          <p className="text-sm font-medium text-gray-500">No connectors configured</p>
          <p className="text-xs text-gray-400 mt-1 mb-4">Connect KubeRiva to Shopify, carriers, and other platforms</p>
          <button
            onClick={() => { setEditingConnector(null); setShowModal(true) }}
            className="btn-primary text-sm inline-flex items-center gap-1.5"
          >
            <Plus className="w-4 h-4" />
            Add your first connector
          </button>
        </div>
      )}

      {/* Connector grid */}
      {connectors && connectors.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {connectors.map(c => (
            <ConnectorCard
              key={c.id}
              connector={c}
              onEdit={handleEdit}
              onShowEvents={handleShowEvents}
            />
          ))}
        </div>
      )}

      {/* Integration roadmap */}
      <div className="mt-8 bg-gray-50 border border-gray-200 rounded-xl p-4">
        <p className="text-xs font-semibold text-gray-600 mb-3 flex items-center gap-1.5">
          <ChevronRight className="w-3.5 h-3.5" />
          Connector Roadmap
        </p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {Object.entries(PLATFORMS).map(([type, p]) => (
            <div key={type} className="flex items-center gap-2 bg-white rounded-lg px-2.5 py-2 border border-gray-100">
              <div className={`w-5 h-5 ${p.color} rounded flex items-center justify-center flex-shrink-0`}>
                <div className="scale-75">{p.icon}</div>
              </div>
              <div className="min-w-0">
                <p className="text-[11px] font-medium text-gray-700 truncate">{p.label}</p>
                <p className="text-[9px] text-gray-400">{p.category}</p>
              </div>
              {p.implemented
                ? <CheckCircle className="w-3 h-3 text-green-400 ml-auto flex-shrink-0" />
                : <ExternalLink className="w-3 h-3 text-gray-300 ml-auto flex-shrink-0" />
              }
            </div>
          ))}
        </div>
      </div>

      {/* Modals */}
      <ConnectorModal
        key={editingConnector?.id ?? 'new'}
        open={showModal}
        onClose={handleCloseModal}
        editing={editingConnector}
      />
      <EventsModal
        connector={eventsConnector}
        open={showEventsModal}
        onClose={() => { setShowEventsModal(false); setEventsConnector(null) }}
      />
    </div>
  )
}
