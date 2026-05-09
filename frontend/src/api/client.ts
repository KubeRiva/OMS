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

export type OrderChannel = 'WEB' | 'MOBILE' | 'POS' | 'API' | 'MARKETPLACE' | 'B2B' | 'EDI' | 'WHOLESALE'
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
  // B2B fields
  order_type: 'RETAIL' | 'B2B' | 'WHOLESALE'
  customer_account_id?: string
  po_number?: string
  payment_terms: string
  approval_status: 'NOT_REQUIRED' | 'PENDING' | 'APPROVED' | 'REJECTED'
  payment_due_date?: string
  approved_by_id?: string
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
  address_line1?: string
  address_line2?: string
  city?: string
  state?: string
  postal_code?: string
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
  created_at?: string
  updated_at?: string
}

export type Node = FulfillmentNode

export interface NodeCreatePayload {
  code: string
  name: string
  node_type: string
  status?: string
  address_line1?: string
  address_line2?: string
  city?: string
  state?: string
  postal_code?: string
  country?: string
  latitude: number
  longitude: number
  can_ship?: boolean
  can_pickup?: boolean
  can_curbside?: boolean
  can_same_day?: boolean
  daily_order_capacity?: number
  avg_processing_hours?: number
  shipping_cost_multiplier?: number
}

export interface NodeUpdatePayload {
  name?: string
  status?: string
  can_ship?: boolean
  can_pickup?: boolean
  can_curbside?: boolean
  can_same_day?: boolean
  daily_order_capacity?: number
  avg_processing_hours?: number
  shipping_cost_multiplier?: number
}

export interface SourcingCondition {
  field: string
  operator: string
  value: unknown
}

export interface SourcingTarget {
  type: 'DISTRIBUTION_GROUP' | 'NODE'
  id: string
  priority: number
}

export interface SourcingRule {
  id: string
  name: string
  description?: string
  priority: number
  is_active: boolean
  strategy: string
  conditions: SourcingCondition[]
  sourcing_targets: SourcingTarget[]
  allowed_node_types: string[]
  excluded_node_ids: string[]
  required_capabilities: string[]
  max_split_nodes: number
  max_distance_km?: number
  cost_weight: number
  distance_weight: number
  brand_id?: string
  created_at: string
}

export interface SourcingRulePayload {
  name: string
  description?: string
  priority: number
  is_active: boolean
  strategy: string
  conditions: SourcingCondition[]
  sourcing_targets?: SourcingTarget[]
  allowed_node_types: string[]
  excluded_node_ids: string[]
  required_capabilities: string[]
  max_split_nodes: number
  max_distance_km?: number
  cost_weight: number
  distance_weight: number
}

// ─── Distribution Groups ──────────────────────────────────────────────────────

export interface DGMember {
  id: string
  group_id: string
  node_id: string
  priority: number
  node_name?: string
  node_code?: string
  node_type?: string
}

export interface DistributionGroup {
  id: string
  name: string
  description?: string
  is_active: boolean
  brand_id?: string
  created_at: string
  updated_at: string
  members: DGMember[]
}

export interface DistributionGroupPayload {
  name: string
  description?: string
  is_active?: boolean
  brand_id?: string
  members?: Array<{ node_id: string; priority: number }>
}

export const fetchDistributionGroups = (params?: { is_active?: boolean; brand_id?: string; page?: number; page_size?: number }) =>
  api.get<{ items: DistributionGroup[]; total: number }>('/distribution-groups/', { params }).then(r => r.data)

export const createDistributionGroup = (data: DistributionGroupPayload) =>
  api.post<DistributionGroup>('/distribution-groups/', data).then(r => r.data)

export const updateDistributionGroup = (id: string, data: Partial<DistributionGroupPayload>) =>
  api.patch<DistributionGroup>(`/distribution-groups/${id}`, data).then(r => r.data)

export const deleteDistributionGroup = (id: string) =>
  api.delete(`/distribution-groups/${id}`)

export const addDGMember = (groupId: string, data: { node_id: string; priority: number }) =>
  api.post<DistributionGroup>(`/distribution-groups/${groupId}/members`, data).then(r => r.data)

export const updateDGMemberPriority = (groupId: string, nodeId: string, priority: number) =>
  api.patch<DistributionGroup>(`/distribution-groups/${groupId}/members/${nodeId}`, { node_id: nodeId, priority }).then(r => r.data)

export const removeDGMember = (groupId: string, nodeId: string) =>
  api.delete<DistributionGroup>(`/distribution-groups/${groupId}/members/${nodeId}`).then(r => r.data)

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
  orders_by_order_type: Array<{ order_type: string; count: number; percentage: number; total_revenue: number }>
  top_nodes: Array<{ node_id: string; node_name: string; node_code: string; total_allocations: number; capacity_utilization: number }>
  inventory_alerts: Array<{ sku: string; node: string; available: number; reorder_point: number }>
}

// ─── API Functions ────────────────────────────────────────────────────────────

// Orders
export const fetchOrders = (params: Record<string, string | number | undefined>) =>
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

export const approveOrder = (id: string) =>
  api.post<Order>(`/orders/${id}/approve`).then(r => r.data)

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

export const createNode = (data: NodeCreatePayload) =>
  api.post<FulfillmentNode>('/nodes/', data).then(r => r.data)

export const updateNode = (id: string, data: NodeUpdatePayload) =>
  api.patch<FulfillmentNode>(`/nodes/${id}`, data).then(r => r.data)

export const deactivateNode = (id: string) =>
  api.delete(`/nodes/${id}`)

// Sourcing Rules
export interface SourcingConditionField {
  field: string
  label: string
  group: string
  values: string[]
}

export interface SourcingMetadata {
  strategies: string[]
  node_types: string[]
  operators: string[]
  capabilities: string[]
  condition_fields: SourcingConditionField[]
}

export const fetchSourcingMetadata = () =>
  api.get<SourcingMetadata>('/sourcing-rules/metadata').then(r => r.data)

export const fetchSourcingRules = (params?: Record<string, string | number | undefined>) =>
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
export const fetchDashboard = (fromDate?: string, toDate?: string, brandId?: string, channel?: string, orderType?: string) => {
  const params: Record<string, string> = {}
  if (fromDate) params.from_date = fromDate
  if (toDate) params.to_date = toDate
  if (brandId) params.brand_id = brandId
  if (channel) params.channel = channel
  if (orderType) params.order_type = orderType
  return api.get<DashboardSummary>('/analytics/dashboard', { params }).then(r => r.data)
}

export const fetchOrderVolume = (
  days = 30,
  brandId?: string,
  channel?: string,
  fromDate?: string,
  toDate?: string,
  orderType?: string,
) => {
  const params: Record<string, string | number> = {}
  if (fromDate && toDate) {
    params.from_date = fromDate
    params.to_date = toDate
  } else {
    params.days = days
  }
  if (brandId) params.brand_id = brandId
  if (channel) params.channel = channel
  if (orderType) params.order_type = orderType
  return api.get<Array<{ date: string; count: number; total_revenue: number }>>('/analytics/orders/volume', { params }).then(r => r.data)
}

export const fetchInventorySummary = () =>
  api.get<{ total_skus: number; total_on_hand: number; total_available: number; total_reserved: number; low_stock_count: number }>('/analytics/inventory/summary').then(r => r.data)

// Search
export const searchOrders = (query: string, page = 1, brand_id?: string) =>
  api.post<OrderSearchResponse>('/search/orders', { query, page, page_size: 20, ...(brand_id ? { brand_id } : {}) }).then(r => r.data)

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

export type PipelineType = 'ORDER' | 'RETURN'

export interface CustomStatusDef {
  key: string
  label: string
  description?: string
  color?: string
}

export interface Lifecycle {
  id: string
  name: string
  description: string
  fulfillment_types: string[]
  channels: string[]
  is_active: boolean
  is_default: boolean
  pipeline_type: PipelineType
  order_type?: string | null
  brand_id?: string | null
  custom_statuses: CustomStatusDef[]
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
  pipeline_type?: PipelineType
  order_type?: string | null
  brand_id?: string | null
  custom_statuses?: CustomStatusDef[]
  steps?: LifecycleStepPayload[]
}

export const fetchLifecycles = (params?: {
  fulfillment_type?: string
  active_only?: boolean
  pipeline_type?: PipelineType
  order_type?: string
  brand_id?: string
}) => api.get<Lifecycle[]>('/lifecycles/', { params }).then(r => r.data)

export const resolveLifecycle = (fulfillment_type: string, channel?: string, pipeline_type?: PipelineType, order_type?: string, brand_id?: string) =>
  api.get<{ lifecycle: Lifecycle | null; matched_on: string | null }>(
    '/lifecycles/resolve', { params: { fulfillment_type, channel, pipeline_type, order_type, brand_id } }
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

// ─── Customer Accounts (B2B) ──────────────────────────────────────────────────

export type AccountType = 'PROSPECT' | 'ACTIVE' | 'INACTIVE' | 'ON_HOLD'
export type PricingTier = 'STANDARD' | 'BRONZE' | 'SILVER' | 'GOLD' | 'PLATINUM'

export interface CustomerAccount {
  id: string
  account_number: string
  company_name: string
  brand_id?: string
  trading_name?: string
  industry?: string
  website?: string
  account_type: AccountType
  pricing_tier: PricingTier
  payment_terms: string
  contact_name?: string
  contact_email?: string
  contact_phone?: string
  credit_limit: string
  credit_used: string
  available_credit: number
  tax_exempt: boolean
  tax_exempt_id?: string
  billing_name?: string
  billing_address1?: string
  billing_address2?: string
  billing_city?: string
  billing_state?: string
  billing_postal_code?: string
  billing_country?: string
  account_manager_id?: string
  parent_account_id?: string
  approval_threshold?: string
  is_active: boolean
  notes?: string
  metadata_: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface CustomerAccountListResponse {
  items: CustomerAccount[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface CustomerAccountCreate {
  company_name: string
  brand_id?: string
  trading_name?: string
  industry?: string
  website?: string
  account_type?: AccountType
  contact_name?: string
  contact_email?: string
  contact_phone?: string
  credit_limit?: string
  payment_terms?: string
  pricing_tier?: PricingTier
  tax_exempt?: boolean
  billing_name?: string
  billing_address1?: string
  billing_address2?: string
  billing_city?: string
  billing_state?: string
  billing_postal_code?: string
  billing_country?: string
  approval_threshold?: string
  notes?: string
}

export const fetchCustomerAccounts = (params?: {
  search?: string
  account_type?: AccountType
  is_active?: boolean
  brand_id?: string
  page?: number
  page_size?: number
}) => api.get<CustomerAccountListResponse>('/customers/', { params }).then(r => r.data)

export const createCustomerAccount = (data: CustomerAccountCreate) =>
  api.post<CustomerAccount>('/customers/', data).then(r => r.data)

export const updateCustomerAccount = (id: string, data: Partial<CustomerAccountCreate> & { is_active?: boolean }) =>
  api.patch<CustomerAccount>(`/customers/${id}`, data).then(r => r.data)

export const adjustCustomerCredit = (id: string, amount: number, reason: string) =>
  api.post<CustomerAccount>(`/customers/${id}/credit-adjustment`, { amount: String(amount), reason }).then(r => r.data)

export const deactivateCustomerAccount = (id: string) =>
  api.delete(`/customers/${id}`)

// ─── Invoices (B2B) ───────────────────────────────────────────────────────────

export type InvoiceStatus = 'DRAFT' | 'SENT' | 'PAID' | 'OVERDUE' | 'VOID'

export interface Invoice {
  id: string
  invoice_number: string
  customer_account_id: string
  customer_account_name?: string
  order_id?: string
  order_number?: string
  status: InvoiceStatus
  subtotal: number
  tax_amount: number
  total_amount: number
  currency: string
  issued_date: string
  due_date: string
  paid_date?: string
  payment_terms: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface InvoiceListResponse {
  items: Invoice[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export const fetchInvoices = (params?: {
  status?: string
  customer_account_id?: string
  page?: number
  page_size?: number
}) => api.get<InvoiceListResponse>('/invoices/', { params }).then(r => r.data)

export const updateInvoiceStatus = (invoiceId: string, status: string, notes?: string) =>
  api.patch<Invoice>(`/invoices/${invoiceId}/status`, { status, ...(notes ? { notes } : {}) }).then(r => r.data)

// ── Brands ────────────────────────────────────────────────────────────────────

export type BrandTenantMode = 'B2C_ONLY' | 'B2B_ONLY' | 'HYBRID'

export interface Brand {
  id: string
  slug: string
  name: string
  tenant_mode: BrandTenantMode
  description: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  order_count: number
  rule_count: number
  account_count: number
}

export interface BrandCreate {
  slug: string
  name: string
  tenant_mode: BrandTenantMode
  description?: string
}

export interface BrandUpdate {
  name?: string
  tenant_mode?: BrandTenantMode
  description?: string
  is_active?: boolean
}

export interface BrandConfig {
  id: string
  brand_id: string
  default_currency: string
  default_locale: string
  sla_ship_hours: number
  sla_deliver_days: number
  return_window_days: number
  logo_url?: string
  support_email?: string
  support_phone?: string
  default_fulfillment_type?: string
  auto_approve_orders: boolean
  ai_sourcing_enabled: boolean
  created_at: string
  updated_at: string
}

export interface BrandNode {
  id: string
  brand_id: string
  node_id: string
  node_name?: string
  node_code?: string
  priority: number
  is_active: boolean
  max_daily_orders?: number
  created_at: string
}

export interface BrandCloneRequest {
  name: string
  slug: string
  tenant_mode: string
  clone_config: boolean
  clone_nodes: boolean
  clone_sourcing_rules: boolean
}

export const getBrands = (params?: { is_active?: boolean; tenant_mode?: string }) =>
  api.get<Brand[]>('/brands/', { params }).then(r => r.data)

export const createBrand = (data: BrandCreate) =>
  api.post<Brand>('/brands/', data).then(r => r.data)

export const updateBrand = (id: string, data: BrandUpdate) =>
  api.patch<Brand>(`/brands/${id}`, data).then(r => r.data)

export const deleteBrand = (id: string) =>
  api.delete(`/brands/${id}`)

export const toggleBrand = (id: string) =>
  api.post<Brand>(`/brands/${id}/toggle`).then(r => r.data)

export const getBrandConfig = (id: string) =>
  api.get<BrandConfig>(`/brands/${id}/config`).then(r => r.data)

export const upsertBrandConfig = (id: string, data: Partial<BrandConfig>) =>
  api.put<BrandConfig>(`/brands/${id}/config`, data).then(r => r.data)

export const getBrandNodes = (id: string) =>
  api.get<BrandNode[]>(`/brands/${id}/nodes`).then(r => r.data)

export const assignBrandNode = (
  id: string,
  data: { node_id: string; priority: number; is_active: boolean; max_daily_orders?: number },
) => api.post<BrandNode>(`/brands/${id}/nodes`, data).then(r => r.data)

export const removeBrandNode = (brandId: string, nodeId: string) =>
  api.delete(`/brands/${brandId}/nodes/${nodeId}`)

export const cloneBrand = (id: string, data: BrandCloneRequest) =>
  api.post<Brand>(`/brands/${id}/clone`, data).then(r => r.data)

// ─── B2C Customer Profiles ───────────────────────────────────────────────────

export interface CustomerProfileAddress {
  id: string
  customer_id: string
  label?: string
  is_default: boolean
  first_name?: string
  last_name?: string
  address1: string
  address2?: string
  city: string
  state: string
  postal_code: string
  country: string
  phone?: string
  created_at: string
}

export interface CustomerProfile {
  id: string
  email: string
  first_name?: string
  last_name?: string
  phone?: string
  brand_id?: string
  tags: string[]
  email_opt_in: boolean
  sms_opt_in: boolean
  preferred_language?: string
  notes?: string
  is_active: boolean
  total_orders: number
  total_spent: string
  last_order_at?: string
  created_at: string
  updated_at: string
  addresses: CustomerProfileAddress[]
}

export interface CustomerProfileListResponse {
  items: CustomerProfile[]
  total: number
}

export async function fetchCustomerProfiles(params: {
  brand_id?: string; email?: string; is_active?: boolean; tags?: string[];
  skip?: number; limit?: number
}): Promise<CustomerProfileListResponse> {
  const p: Record<string, unknown> = { ...params }
  if (params.tags?.length) p.tags = params.tags
  const r = await api.get('/customers/profiles/', { params: p })
  return r.data
}

export async function createCustomerProfile(data: {
  email: string; first_name?: string; last_name?: string; phone?: string;
  brand_id?: string; tags?: string[]; email_opt_in?: boolean; sms_opt_in?: boolean;
  preferred_language?: string; notes?: string
}): Promise<CustomerProfile> {
  const r = await api.post('/customers/profiles/', data)
  return r.data
}

export async function updateCustomerProfile(id: string, data: {
  first_name?: string; last_name?: string; phone?: string; tags?: string[];
  email_opt_in?: boolean; sms_opt_in?: boolean; preferred_language?: string;
  notes?: string; is_active?: boolean
}): Promise<CustomerProfile> {
  const r = await api.patch(`/customers/profiles/${id}`, data)
  return r.data
}

export async function deleteCustomerProfile(id: string): Promise<void> {
  await api.delete(`/customers/profiles/${id}`)
}

export async function syncCustomerProfileStats(id: string): Promise<CustomerProfile> {
  const r = await api.post(`/customers/profiles/${id}/sync-stats`)
  return r.data
}

export async function fetchCustomerProfileOrders(id: string, params?: { skip?: number; limit?: number }): Promise<Order[]> {
  const r = await api.get(`/customers/profiles/${id}/orders`, { params })
  return r.data
}

export async function addCustomerProfileAddress(customerId: string, data: {
  label?: string; is_default?: boolean; first_name?: string; last_name?: string;
  address1: string; address2?: string; city: string; state: string;
  postal_code: string; country?: string; phone?: string
}): Promise<CustomerProfileAddress> {
  const r = await api.post(`/customers/profiles/${customerId}/addresses`, data)
  return r.data
}

export async function deleteCustomerProfileAddress(customerId: string, addressId: string): Promise<void> {
  await api.delete(`/customers/profiles/${customerId}/addresses/${addressId}`)
}

// ─── Returns / RMA ───────────────────────────────────────────────────────────

export interface ReturnItem {
  id: string
  return_id: string
  order_item_id?: string
  sku: string
  description: string
  quantity_requested: string
  quantity_received?: string
  condition?: string
  restock: boolean
  created_at: string
}

export interface ReturnRefund {
  id: string
  refund_number: string
  order_id: string
  return_id?: string
  status: string
  refund_method: string
  amount: string
  currency: string
  transaction_id?: string
  reason: string
  notes?: string
  processed_at?: string
  created_at: string
  updated_at: string
}

export interface OrderReturn {
  id: string
  return_number: string
  order_id: string
  status: string
  reason: string
  customer_notes?: string
  staff_notes?: string
  return_tracking_number?: string
  return_carrier?: string
  received_at?: string
  restocked_at?: string
  created_at: string
  updated_at: string
  items: ReturnItem[]
  refund?: ReturnRefund
}

export interface ReturnListResponse {
  items: OrderReturn[]
  total: number
}

export async function fetchReturns(params?: {
  status?: string; order_id?: string; from_date?: string; to_date?: string;
  skip?: number; limit?: number
}): Promise<ReturnListResponse> {
  const r = await api.get('/returns/', { params })
  return r.data
}

export async function fetchOrderReturns(orderId: string): Promise<ReturnListResponse> {
  const r = await api.get('/returns/', { params: { order_id: orderId, limit: 50 } })
  return r.data
}

export async function createReturn(data: {
  order_id: string; reason: string; customer_notes?: string;
  items: { sku: string; description: string; quantity_requested: number; order_item_id?: string; restock?: boolean }[]
}): Promise<OrderReturn> {
  const r = await api.post('/returns/', data)
  return r.data
}

export async function updateReturnStatus(returnId: string, data: {
  status: string; staff_notes?: string; return_tracking_number?: string; return_carrier?: string
}): Promise<OrderReturn> {
  const r = await api.patch(`/returns/${returnId}/status`, data)
  return r.data
}

export async function createReturnRefund(returnId: string, data: {
  refund_method: string; amount: string; currency?: string; reason: string;
  transaction_id?: string; notes?: string
}): Promise<ReturnRefund> {
  const r = await api.post(`/returns/${returnId}/refund`, data)
  return r.data
}

// ─── Custom Field Definitions ─────────────────────────────────────────────────

export interface CustomFieldDefinition {
  id: string
  entity_type: 'ORDER' | 'INVENTORY_ITEM' | 'NODE'
  field_key: string
  label: string
  data_type: 'text' | 'number' | 'boolean' | 'date'
  is_required: boolean
  default_value: string | null
  created_at: string
}

export interface CustomFieldDefinitionPayload {
  entity_type: 'ORDER' | 'INVENTORY_ITEM' | 'NODE'
  field_key: string
  label: string
  data_type: 'text' | 'number' | 'boolean' | 'date'
  is_required: boolean
  default_value?: string | null
}

export const fetchCustomFieldDefinitions = (entity_type?: string) =>
  api.get<CustomFieldDefinition[]>('/architect/custom-attributes', { params: entity_type ? { entity_type } : undefined }).then(r => r.data)

export const createCustomFieldDefinition = (payload: CustomFieldDefinitionPayload) =>
  api.post<CustomFieldDefinition>('/architect/custom-attributes', payload).then(r => r.data)

export const deleteCustomFieldDefinition = (id: string) =>
  api.delete(`/architect/custom-attributes/${id}`)

// ─── API Keys ─────────────────────────────────────────────────────────────────

export interface ApiKey {
  id: string
  name: string
  prefix: string
  scopes: string[]
  last_used_at: string | null
  is_active: boolean
  expires_at: string | null
  created_at: string
}

export interface ApiKeyCreatePayload {
  name: string
  scopes: string[]
  expires_at?: string
}

export interface ApiKeyCreatedResponse extends ApiKey {
  key: string
}

export const fetchApiKeys = () =>
  api.get<ApiKey[]>('/api-keys').then(r => r.data)

export const createApiKey = (payload: ApiKeyCreatePayload) =>
  api.post<ApiKeyCreatedResponse>('/api-keys', payload).then(r => r.data)

export const revokeApiKey = (id: string) =>
  api.delete(`/api-keys/${id}`)

// ─── Brand User Access ────────────────────────────────────────────────────────

export interface UserBrandRole {
  id: string
  user_id: string
  brand_id: string
  environment_id: string
  role: 'VIEWER' | 'OPERATOR' | 'ADMIN'
  created_at: string
}

export interface BrandAccessPayload {
  user_id: string
  brand_id: string
  role: 'VIEWER' | 'OPERATOR' | 'ADMIN'
}

export const fetchBrandAccess = () =>
  api.get<UserBrandRole[]>('/brand-access').then(r => r.data)

export const createBrandAccess = (payload: BrandAccessPayload) =>
  api.post<UserBrandRole>('/brand-access', payload).then(r => r.data)

export const deleteBrandAccess = (id: string) =>
  api.delete(`/brand-access/${id}`)

export default api
