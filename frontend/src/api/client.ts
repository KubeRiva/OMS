import axios from 'axios'

// In Docker: nginx proxies /api/ → FastAPI. In dev: vite proxies /api/ → localhost:8000
const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
  timeout: 30_000,
  // Send the httpOnly auth cookie automatically on every request.
  // The server sets this cookie on login (HttpOnly; SameSite=Strict).
  withCredentials: true,
})

const ENV_STORAGE_KEY = 'oms_environment_id'

// Inject active environment header on every request.
// Auth is handled by the httpOnly cookie (withCredentials: true above).
api.interceptors.request.use(config => {
  const envId = localStorage.getItem(ENV_STORAGE_KEY)
  if (envId) config.headers['X-OMS-Environment'] = envId
  return config
})

// On 401, clear token and redirect to login
api.interceptors.response.use(
  r => r,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('oms_auth_user')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  },
)

// ─── Types ────────────────────────────────────────────────────────────────────

export type OrderStatus =
  | 'PENDING' | 'CONFIRMED' | 'SOURCING' | 'SOURCED'
  | 'PICKING' | 'PACKING' | 'READY_TO_SHIP' | 'SHIPPED'
  | 'PARTIALLY_SHIPPED' | 'OUT_FOR_DELIVERY' | 'PARTIALLY_DELIVERED'
  | 'DELIVERED' | 'READY_FOR_PICKUP' | 'PICKED_UP'
  | 'BACKORDERED' | 'CANCELLED' | 'RETURNED' | 'REFUNDED' | 'FAILED'

export type OrderChannel = 'WEB' | 'MOBILE' | 'POS' | 'API' | 'MARKETPLACE'
export type FulfillmentType =
  | 'SHIP_TO_HOME' | 'STORE_PICKUP' | 'SHIP_FROM_STORE'
  | 'CURBSIDE_PICKUP' | 'SAME_DAY_DELIVERY'

export type AdjustmentReason =
  | 'RECEIVED' | 'SOLD' | 'RETURNED' | 'DAMAGED' | 'CYCLE_COUNT'
  | 'TRANSFER_IN' | 'TRANSFER_OUT' | 'CORRECTION'

export interface OrderItem {
  id: string
  sku: string
  product_name: string
  quantity: number
  quantity_fulfilled: number
  quantity_pending: number
  quantity_allocated: number
  quantity_backordered: number
  quantity_shipped: number
  quantity_delivered: number
  status: string
  unit_price: string
  total_price: string
}

export interface Allocation {
  id: string
  node_id: string
  node_code?: string
  node_name?: string
  sku: string
  quantity_allocated: number
  status: string
  allocated_at: string
  shipped_at?: string
  sourcing_score?: number
}

export interface ShipmentLineItem {
  allocation_id?: string
  sku: string
  quantity: number
  node_id?: string
}

export interface Shipment {
  id: string
  allocation_id?: string
  tracking_number?: string
  carrier?: string
  service_level?: string
  status: string
  label_url?: string
  shipped_at?: string
  estimated_delivery_at?: string
  actual_delivery_at?: string
  shipping_cost?: string
  line_items: ShipmentLineItem[]
}

export interface Order {
  id: string
  order_number: string
  channel: OrderChannel
  fulfillment_type: FulfillmentType
  status: OrderStatus
  payment_status: string
  customer_email: string
  customer_name?: string
  customer_phone?: string
  subtotal: string
  tax_amount: string
  shipping_amount: string
  discount_amount: string
  total_amount: string
  currency: string
  shipping_address1?: string
  shipping_city?: string
  shipping_state?: string
  shipping_country?: string
  created_at: string
  updated_at: string
  confirmed_at?: string
  delivered_at?: string
  cancelled_at?: string
  tags: string[]
  notes?: string
  line_items: OrderItem[]
  fulfillment_allocations: Allocation[]
  shipments: Shipment[]
}

export interface OrderListResponse {
  items: Order[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface InventoryItem {
  id: string
  node_id: string
  sku: string
  product_name?: string
  quantity_on_hand: number
  quantity_reserved: number
  quantity_available: number
  quantity_on_order: number
  reorder_point: number
  reorder_quantity: number
  unit_cost: number
  is_active: boolean
  updated_at: string
}

// Matches NodeResponse from backend
export interface FulfillmentNode {
  id: string
  code: string
  name: string
  node_type: string
  status: string           // 'ACTIVE' | 'INACTIVE' | 'MAINTENANCE' | 'CLOSED'
  city?: string
  state?: string
  country: string
  latitude: number
  longitude: number
  can_ship: boolean
  can_pickup: boolean
  can_curbside: boolean
  can_same_day: boolean
  daily_order_capacity: number
  current_daily_orders: number
  avg_processing_hours: number
  shipping_cost_multiplier: number
}

export type Node = FulfillmentNode

export interface SourcingCondition {
  field: string
  operator: string
  value: unknown
}

export interface SourcingRule {
  id: string
  name: string
  description?: string
  priority: number
  is_active: boolean
  strategy: string
  conditions: SourcingCondition[]
  allowed_node_types: string[]
  excluded_node_ids: string[]
  required_capabilities: string[]
  max_split_nodes: number
  max_distance_km?: number
  cost_weight: number
  distance_weight: number
  created_at: string
}

export interface SourcingRulePayload {
  name: string
  description?: string
  priority: number
  is_active: boolean
  strategy: string
  conditions: SourcingCondition[]
  allowed_node_types: string[]
  excluded_node_ids: string[]
  required_capabilities: string[]
  max_split_nodes: number
  max_distance_km?: number
  cost_weight: number
  distance_weight: number
}

export interface SearchHit {
  id: string
  score?: number
  source: Record<string, unknown>
}

export interface OrderSearchResponse {
  hits: SearchHit[]
  total: number
  page: number
  page_size: number
  total_pages: number
  query_time_ms: number
}

export interface DashboardSummary {
  period_start: string
  period_end: string
  total_orders: number
  total_revenue: number
  avg_order_value: number
  orders_by_status: Record<string, number>
  orders_by_channel: Array<{ channel: string; count: number; total_revenue: number; percentage: number }>
  orders_by_fulfillment_type: Array<{ fulfillment_type: string; count: number; percentage: number }>
  top_nodes: Array<{ node_id: string; node_name: string; node_code: string; total_allocations: number; capacity_utilization: number }>
  inventory_alerts: Array<{ sku: string; node: string; available: number; reorder_point: number }>
}

// ─── API Functions ────────────────────────────────────────────────────────────

// Orders
export const fetchOrders = (params: Record<string, string | number>) =>
  api.get<OrderListResponse>('/orders/', { params }).then(r => r.data)

export const fetchOrder = (id: string) =>
  api.get<Order>(`/orders/${id}`).then(r => r.data)

export const createOrder = (data: unknown) =>
  api.post<Order>('/orders/', data).then(r => r.data)

export const updateOrderStatus = (id: string, status: string, notes?: string) =>
  api.patch<Order>(`/orders/${id}/status`, { status, notes }).then(r => r.data)

export const cancelOrder = (id: string, reason: string) =>
  api.post<Order>(`/orders/${id}/cancel`, { reason, notify_customer: true }).then(r => r.data)

export const fetchOrderEvents = (id: string) =>
  api.get<Array<{ event_type: string; timestamp: string; data: Record<string, unknown> }>>(`/orders/${id}/events`).then(r => r.data)

export const triggerOrderWorker = (id: string, action: 'source' | 'pick' | 'pack' | 'ship') =>
  api.post<{ action: string; order_id: string; queued: boolean }>(`/orders/${id}/trigger-worker`, { action }).then(r => r.data)

// Inventory — returns flat array (not paginated)
export const fetchInventory = (params?: Record<string, string | number | boolean | undefined>) =>
  api.get<InventoryItem[]>('/inventory/', { params }).then(r => r.data)

export const fetchInventoryBySku = (sku: string) =>
  api.get<InventoryItem[]>(`/inventory/sku/${sku}`).then(r => r.data)

export const createInventoryItem = (data: {
  node_id: string; sku: string; product_name?: string;
  quantity_on_hand?: number; unit_cost?: number; weight_lbs?: number;
  reorder_point?: number; reorder_quantity?: number;
}) =>
  api.post<InventoryItem>('/inventory/', data).then(r => r.data)

export const updateInventoryItem = (
  id: string,
  data: {
    product_name?: string; reorder_point?: number; reorder_quantity?: number;
    unit_cost?: number; weight_lbs?: number; is_active?: boolean; quantity_on_order?: number;
  },
) =>
  api.patch<InventoryItem>(`/inventory/${id}`, data).then(r => r.data)

export const adjustInventory = (
  id: string,
  data: { quantity_delta: number; reason: AdjustmentReason; notes?: string },
) =>
  api.post(`/inventory/${id}/adjust`, { ...data, created_by: 'ops_ui' }).then(r => r.data)

export const checkAvailability = (items: Array<{ sku: string; quantity: number }>) =>
  api.post('/inventory/check-availability', { items }).then(r => r.data)

// Products — grouped by SKU
export interface ProductSummary {
  sku: string
  product_name: string | null
  total_on_hand: number
  total_available: number
  total_reserved: number
  nodes_count: number
  unit_cost: number
  weight_lbs: number
  reorder_point: number
  updated_at: string | null
}

export const fetchProducts = (params?: {
  search?: string; node_id?: string; low_stock_only?: boolean; page_size?: number
}) =>
  api.get<ProductSummary[]>('/inventory/products', { params }).then(r => r.data)

export const updateProduct = (sku: string, data: {
  product_name?: string; unit_cost?: number; weight_lbs?: number;
  reorder_point?: number; reorder_quantity?: number; is_active?: boolean;
}) =>
  api.patch<{ updated: number; sku: string }>(`/inventory/products/${sku}`, data).then(r => r.data)

// Nodes
export const fetchNodes = (params?: Record<string, string | number>) =>
  api.get<{ items: FulfillmentNode[]; total: number }>('/nodes/', { params }).then(r => r.data)

export const fetchNodeCapacity = (id: string) =>
  api.get<unknown>(`/nodes/${id}/capacity`).then(r => r.data)

// Sourcing Rules
export interface SourcingMetadata {
  strategies: string[]
  node_types: string[]
  operators: string[]
  capabilities: string[]
}

export const fetchSourcingMetadata = () =>
  api.get<SourcingMetadata>('/sourcing-rules/metadata').then(r => r.data)

export const fetchSourcingRules = (params?: Record<string, string | number>) =>
  api.get<{ items: SourcingRule[]; total: number }>('/sourcing-rules/', { params }).then(r => r.data)

export const createSourcingRule = (payload: SourcingRulePayload) =>
  api.post<SourcingRule>('/sourcing-rules/', payload).then(r => r.data)

export const updateSourcingRule = (id: string, payload: Partial<SourcingRulePayload>) =>
  api.patch<SourcingRule>(`/sourcing-rules/${id}`, payload).then(r => r.data)

export const toggleSourcingRule = (id: string) =>
  api.post<SourcingRule>(`/sourcing-rules/${id}/toggle`).then(r => r.data)

export const deleteSourcingRule = (id: string) =>
  api.delete<void>(`/sourcing-rules/${id}`)

// Analytics
export const fetchDashboard = (fromDate?: string, toDate?: string) => {
  const params: Record<string, string> = {}
  if (fromDate) params.from_date = fromDate
  if (toDate) params.to_date = toDate
  return api.get<DashboardSummary>('/analytics/dashboard', { params }).then(r => r.data)
}

export const fetchOrderVolume = (days = 30) =>
  api.get<Array<{ date: string; count: number; total_revenue: number }>>('/analytics/orders/volume', { params: { days } }).then(r => r.data)

export const fetchInventorySummary = () =>
  api.get<{ total_skus: number; total_on_hand: number; total_available: number; total_reserved: number; low_stock_count: number }>('/analytics/inventory/summary').then(r => r.data)

// Search
export const searchOrders = (query: string, page = 1) =>
  api.post<OrderSearchResponse>('/search/orders', { query, page, page_size: 20 }).then(r => r.data)

export const searchProducts = (query: string) =>
  api.post('/search/products', { query, page: 1, page_size: 20 }).then(r => r.data)

// ─── Lifecycles ───────────────────────────────────────────────────────────────

export interface LifecycleStep {
  id: string
  status: string
  label: string
  description: string
  step_order: number
  allowed_next_statuses: string[]
  action_type?: string | null
  sla_hours?: number | null
}

export interface Lifecycle {
  id: string
  name: string
  description: string
  fulfillment_types: string[]
  channels: string[]
  is_active: boolean
  is_default: boolean
  steps: LifecycleStep[]
  created_at: string
  updated_at: string
}

export interface LifecycleStepPayload {
  status: string
  label: string
  description?: string
  step_order: number
  allowed_next_statuses?: string[]
  action_type?: string | null
  sla_hours?: number | null
}

export interface LifecyclePayload {
  name: string
  description?: string
  fulfillment_types?: string[]
  channels?: string[]
  is_active?: boolean
  is_default?: boolean
  steps?: LifecycleStepPayload[]
}

export const fetchLifecycles = (params?: { fulfillment_type?: string; active_only?: boolean }) =>
  api.get<Lifecycle[]>('/lifecycles/', { params }).then(r => r.data)

export const resolveLifecycle = (fulfillment_type: string, channel?: string) =>
  api.get<{ lifecycle: Lifecycle | null; matched_on: string | null }>(
    '/lifecycles/resolve', { params: { fulfillment_type, channel } }
  ).then(r => r.data)

export const createLifecycle = (data: LifecyclePayload) =>
  api.post<Lifecycle>('/lifecycles/', data).then(r => r.data)

export const updateLifecycle = (id: string, data: LifecyclePayload) =>
  api.patch<Lifecycle>(`/lifecycles/${id}`, data).then(r => r.data)

export const deleteLifecycle = (id: string) =>
  api.delete<void>(`/lifecycles/${id}`)

// ─── Auth & Admin ─────────────────────────────────────────────────────────────

export interface TokenResponse {
  access_token: string
  token_type: string
  user: AuthUser
}

export interface AuthUser {
  id: string
  email: string
  full_name: string | null
  is_superadmin: boolean
  permissions: string[]
}

export interface AdminUser {
  id: string
  email: string
  full_name: string | null
  is_active: boolean
  is_superadmin: boolean
  platform_role: string
  group_id: string | null
  group_name: string | null
  permissions: string[]
  created_at: string
}

export interface AdminGroup {
  id: string
  name: string
  description: string | null
  permissions: string[]
  user_count: number
}

export const loginUser = (email: string, password: string) =>
  api.post<TokenResponse>('/auth/login', { email, password }).then((r: { data: TokenResponse }) => r.data)

export const fetchMe = () =>
  api.get<AuthUser>('/auth/me').then((r: { data: AuthUser }) => r.data)

// Admin — Users
export const fetchAdminUsers = () =>
  api.get<AdminUser[]>('/admin/users').then((r: { data: AdminUser[] }) => r.data)

export const createAdminUser = (data: {
  email: string
  full_name?: string
  password: string
  group_id?: string
  is_superadmin?: boolean
}) => api.post<AdminUser>('/admin/users', data).then((r: { data: AdminUser }) => r.data)

export const updateAdminUser = (id: string, data: {
  full_name?: string
  group_id?: string
  is_active?: boolean
  is_superadmin?: boolean
  password?: string
}) => api.patch<AdminUser>(`/admin/users/${id}`, data).then((r: { data: AdminUser }) => r.data)

export const deleteAdminUser = (id: string) =>
  api.delete(`/admin/users/${id}`)

// Admin — Groups
export const fetchAdminGroups = () =>
  api.get<AdminGroup[]>('/admin/groups').then((r: { data: AdminGroup[] }) => r.data)

export const createAdminGroup = (data: {
  name: string
  description?: string
  permissions: string[]
}) => api.post<AdminGroup>('/admin/groups', data).then((r: { data: AdminGroup }) => r.data)

export const updateAdminGroup = (id: string, data: {
  name?: string
  description?: string | null
  permissions?: string[]
}) => api.patch<AdminGroup>(`/admin/groups/${id}`, data).then((r: { data: AdminGroup }) => r.data)

export const deleteAdminGroup = (id: string) =>
  api.delete(`/admin/groups/${id}`)

// ─── AI Assistant ──────────────────────────────────────────────────────────────

export type AIEventType = 'tool_call' | 'text_delta' | 'data' | 'error'
export type AIDataKind = 'orders' | 'order_detail' | 'inventory' | 'analytics' | 'nodes' | 'sourcing' | 'top_items' | 'aggregate'

export interface AIEvent {
  type: AIEventType
  // tool_call
  tool?: string
  input?: Record<string, unknown>
  // text_delta
  text?: string
  // data
  kind?: AIDataKind
  data?: unknown
  // error
  message?: string
}

export interface AIChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export async function* streamAIChat(messages: AIChatMessage[]): AsyncGenerator<AIEvent> {
  // Auth is handled by the httpOnly cookie sent via credentials: 'include'.
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }

  const response = await fetch('/api/ai/chat', {
    method: 'POST',
    headers,
    credentials: 'include',
    body: JSON.stringify({ messages }),
  })
  if (!response.ok || !response.body) {
    yield { type: 'error', message: `HTTP ${response.status}` }
    return
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const raw = line.slice(6).trim()
        if (raw === '[DONE]') return
        try {
          yield JSON.parse(raw) as AIEvent
        } catch {
          // skip malformed
        }
      }
    }
  }
}

export const fetchAIStatus = () =>
  api.get<{ status: string; model: string }>('/ai/status').then(r => r.data)

// ─── Webhooks ─────────────────────────────────────────────────────────────────

export interface WebhookEndpoint {
  id: string
  name: string
  url: string
  is_active: boolean
  event_types: string[]
  headers: Record<string, string>
  retry_count: number
  created_at: string
  updated_at: string
}

export interface WebhookEvent {
  id: string
  endpoint_id: string
  order_id?: string
  event_type: string
  status: string
  attempt_count: number
  next_retry_at?: string
  last_response_code?: number
  last_response_body?: string
  delivered_at?: string
  created_at: string
}

export interface WebhookEventTypesResponse {
  event_types: string[]
  groups: Array<{ label: string; events: string[] }>
}

export const fetchWebhookEventTypes = () =>
  api.get<WebhookEventTypesResponse>('/webhooks/event-types').then(r => r.data)

export const fetchWebhookEndpoints = () =>
  api.get<WebhookEndpoint[]>('/webhooks/endpoints').then(r => r.data)

export const createWebhookEndpoint = (data: {
  name: string; url: string; secret: string; is_active: boolean
  event_types: string[]; headers: Record<string, string>
}) => api.post<WebhookEndpoint>('/webhooks/endpoints', data).then(r => r.data)

export const updateWebhookEndpoint = (id: string, data: {
  name?: string; url?: string; is_active?: boolean
  event_types?: string[]; headers?: Record<string, string>
}) => api.patch<WebhookEndpoint>(`/webhooks/endpoints/${id}`, data).then(r => r.data)

export const deleteWebhookEndpoint = (id: string) =>
  api.delete(`/webhooks/endpoints/${id}`)

export const testWebhookEndpoint = (id: string) =>
  api.post<{ message: string; endpoint_id: string }>(`/webhooks/endpoints/${id}/test`).then(r => r.data)

export const fetchWebhookEvents = (params?: { endpoint_id?: string; status?: string; page?: number; page_size?: number }) =>
  api.get<WebhookEvent[]>('/webhooks/events', { params }).then(r => r.data)

export const retryWebhookEvent = (id: string) =>
  api.post<{ message: string; event_id: string }>(`/webhooks/events/${id}/retry`).then(r => r.data)

// ─── Monitoring ───────────────────────────────────────────────────────────────

export interface ErrorEvent {
  _id: string
  fingerprint: string
  timestamp: string
  level: string                        // 'ERROR' | 'WARNING' | 'CRITICAL'
  source_service: string
  error_type: string
  error_message: string
  stack_frames: Array<{
    filename: string
    lineno: number
    name: string
    line: string
  }>
  request_context?: {
    method?: string
    path?: string
    status_code?: number
    correlation_id?: string
    user_id?: string
  }
  task_context?: {
    task?: string
    queue?: string
    retry?: number
  }
  order_context?: {
    order_id?: string
  }
  tags: string[]
  extra: Record<string, unknown>
}

export interface ErrorIssue {
  fingerprint: string
  error_type: string
  source_service: string
  level: string
  status: string                       // 'open' | 'resolved' | 'muted'
  first_seen: string
  last_seen: string
  count: number
  last_message: string
  last_stack_frames: Array<{
    filename: string
    lineno: number
    name: string
    line: string
  }>
  muted_until?: string
}

export interface MonitoringSummary {
  errors_last_1h: number
  errors_last_24h: number
  warnings_last_24h: number
  open_issues: number
  top_error_source: string | null
}

export interface MetricsRateBucket {
  bucket: string
  count: number
  level: string
}

export interface MetricsTopEntry {
  fingerprint: string
  error_type: string
  source_service: string
  count: number
  last_seen: string
}

export interface MetricsSourceEntry {
  source_service: string
  count: number
}

export const fetchMonitoringSummary = () =>
  api.get<MonitoringSummary>('/monitoring/summary').then(r => r.data)

export const fetchMonitoringEvents = (params?: Record<string, string | number>) =>
  api.get<{ items: ErrorEvent[]; total: number; page: number; page_size: number; total_pages: number }>(
    '/monitoring/events', { params }
  ).then(r => r.data)

export const fetchMonitoringEvent = (id: string) =>
  api.get<ErrorEvent>(`/monitoring/events/${id}`).then(r => r.data)

export const fetchMonitoringIssues = (params?: Record<string, string | number>) =>
  api.get<{ items: ErrorIssue[]; total: number; page: number; page_size: number; total_pages: number }>(
    '/monitoring/issues', { params }
  ).then(r => r.data)

export const fetchMonitoringIssue = (fingerprint: string) =>
  api.get<ErrorIssue>(`/monitoring/issues/${fingerprint}`).then(r => r.data)

export const patchMonitoringIssue = (fingerprint: string, data: { status: string; mute_hours?: number }) =>
  api.patch<ErrorIssue>(`/monitoring/issues/${fingerprint}`, data).then(r => r.data)

export const fetchMonitoringRate = (params?: { hours?: number; bucket_minutes?: number; level?: string }) =>
  api.get<MetricsRateBucket[]>('/monitoring/metrics/rate', { params }).then(r => r.data)

export const fetchMonitoringTop = (params?: { hours?: number; limit?: number }) =>
  api.get<MetricsTopEntry[]>('/monitoring/metrics/top', { params }).then(r => r.data)

export const fetchMonitoringSources = (params?: { hours?: number }) =>
  api.get<MetricsSourceEntry[]>('/monitoring/metrics/sources', { params }).then(r => r.data)

// ─── Shopify Billing ──────────────────────────────────────────────────────────

export interface ShopifyBillingPlan {
  name: string
  display_name: string
  price: number
  currency: string
  interval: string
  trial_days: number
  features: string[]
}

export interface ShopifySubscribeResponse {
  confirmation_url: string
}

export const fetchShopifyBillingPlans = () =>
  api.get<ShopifyBillingPlan[]>('/shopify/billing/plans').then(r => r.data)

export const subscribeShopifyPlan = (shop: string, plan: string) =>
  api
    .post<ShopifySubscribeResponse>('/shopify/billing/subscribe', { shop, plan })
    .then(r => r.data)

export const confirmShopifyBilling = (params: {
  shop?: string
  plan?: string
  charge_id?: string
}) => api.get('/shopify/billing/confirm', { params }).then(r => r.data)

export default api
