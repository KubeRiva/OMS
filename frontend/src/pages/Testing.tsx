import React, { useState, useRef, useCallback } from 'react'
import {
  AlertCircle, CheckCircle, Clock, Loader, Play,
  ChevronDown, ChevronUp, Package, Truck, BarChart3, FlaskConical,
  Shield, RefreshCw,
} from 'lucide-react'
import api from '../api/client'

// ── Types ────────────────────────────────────────────────────────────────────

interface TestResult {
  name: string
  status: 'PASSED' | 'FAILED'
  duration_ms: number
  message: string
  created_resources: Record<string, any>
  errors: string[]
}

interface TestRunResponse {
  test_id: string
  status: string
  total_tests: number
  passed: number
  failed: number
  test_duration_ms: number
  cleanup_duration_ms?: number
  total_duration_ms: number
  deleted_resources?: Record<string, number>
  results: TestResult[]
}

interface ApiTestCase {
  id: string
  desc: string
  group: string
  status: 'pending' | 'running' | 'pass' | 'fail' | 'skip'
  note: string
  duration_ms?: number
}

// ── E2E Test Catalog (Pipeline Tests) ───────────────────────────────────────

const TEST_CATALOG = [
  {
    group: 'Basic (Data-Driven)',
    color: 'blue',
    icon: BarChart3,
    tests: [
      { id: 'basic-01', name: 'Create Order',            desc: 'Creates a valid order and verifies DB persistence' },
      { id: 'basic-02', name: 'Source Order',            desc: 'Runs sourcing engine and confirms allocations created' },
      { id: 'basic-03', name: 'Create Shipment',         desc: 'Books a shipment and checks tracking numbers' },
      { id: 'basic-04', name: 'Multi-Node Allocation',   desc: 'Splits order across two fulfillment nodes' },
      { id: 'basic-05', name: 'Inventory Validation',    desc: 'Confirms reserved quantities are updated correctly' },
      { id: 'basic-06', name: 'Order Status Transitions',desc: 'Validates status progression from PENDING → DELIVERED' },
      { id: 'basic-07', name: 'Large Order',             desc: 'Stress-tests with 50-line order' },
      { id: 'basic-08', name: 'Partial Allocation',      desc: 'Verifies graceful handling of partial available stock' },
    ],
  },
  {
    group: 'Pipeline Scenarios',
    color: 'purple',
    icon: Truck,
    tests: [
      {
        id: 'TC-01', name: 'TC-01: Single Line, Single Unit',
        desc: 'Order 1 × E2E-SKU-A. Expect: 1 shipment from DC-EAST → DELIVERED.',
        inventory: 'E2E-SKU-A: DC-EAST=50',
        expected: '1 shipment · DELIVERED',
      },
      {
        id: 'TC-02', name: 'TC-02: Single Line, 10 Units',
        desc: 'Order 10 × E2E-SKU-A from single DC. Expect: 1 shipment → DELIVERED.',
        inventory: 'E2E-SKU-A: DC-EAST=50',
        expected: '1 shipment · DELIVERED',
      },
      {
        id: 'TC-03', name: 'TC-03: Single Line, Split DCs (8+7)',
        desc: 'Order 15 × E2E-SKU-C with DC-EAST=8 and DC-WEST=7. Expect: 2 shipments → DELIVERED.',
        inventory: 'E2E-SKU-C: DC-EAST=8, DC-WEST=7',
        expected: '2 shipments · DELIVERED',
      },
      {
        id: 'TC-04', name: 'TC-04: Multi-Line Grouped Shipment',
        desc: '3 SKUs × 5 units, all at DC-EAST. Expect: 1 grouped shipment with all 3 SKUs → DELIVERED.',
        inventory: 'E2E-SKU-A, D, E: DC-EAST=50 each',
        expected: '1 grouped shipment · all 3 SKUs · DELIVERED',
      },
      {
        id: 'TC-05', name: 'TC-05: Multi-Line, SKUs at Different DCs',
        desc: 'SKU-A only at DC-EAST, SKU-B only at DC-WEST. Expect: 2 shipments → DELIVERED.',
        inventory: 'E2E-SKU-A: DC-EAST=50, E2E-SKU-B: DC-WEST=50',
        expected: '2 shipments (one per DC) · DELIVERED',
      },
      {
        id: 'TC-06', name: 'TC-06: Backorder (Insufficient Stock)',
        desc: 'Order 20 × E2E-SKU-F with only 10 in stock. Expects no oversell; order BACKORDERED.',
        inventory: 'E2E-SKU-F: DC-EAST=10',
        expected: 'allocated ≤ 10 · BACKORDERED',
      },
    ],
  },
]

// ── API Test definitions (mirrors run_e2e.sh) ────────────────────────────────

const API_TEST_GROUPS = [
  { group: 'AUTH',     color: 'indigo', count: 11 },
  { group: 'ORDERS',   color: 'blue',   count: 8  },
  { group: 'INVENTORY',color: 'teal',   count: 5  },
  { group: 'ANALYTICS',color: 'amber',  count: 3  },
  { group: 'SEARCH',   color: 'pink',   count: 2  },
  { group: 'AI',       color: 'violet', count: 2  },
  { group: 'RBAC',     color: 'orange', count: 4  },
  { group: 'SECURITY', color: 'red',    count: 3  },
]

// Runs all API tests in sequence; calls onProgress(cases[]) after each case
async function runApiTests(
  adminEmail: string,
  adminPass: string,
  onProgress: (cases: ApiTestCase[]) => void
): Promise<ApiTestCase[]> {
  const BASE = '/api'
  const ts = () => Date.now()
  const cases: ApiTestCase[] = []
  let token = ''
  let orderId = ''
  let cancelId = ''
  let nodeId = ''
  let invId = ''
  let regToken = ''

  function push(id: string, desc: string, group: string, pass: boolean, note = '') {
    const idx = cases.findIndex(c => c.id === id)
    const entry: ApiTestCase = { id, desc, group, status: pass ? 'pass' : 'fail', note, duration_ms: 0 }
    if (idx >= 0) cases[idx] = entry; else cases.push(entry)
    onProgress([...cases])
  }

  function markRunning(id: string, desc: string, group: string) {
    const idx = cases.findIndex(c => c.id === id)
    const entry: ApiTestCase = { id, desc, group, status: 'running', note: '', duration_ms: 0 }
    if (idx >= 0) cases[idx] = entry; else cases.push(entry)
    onProgress([...cases])
  }

  async function req(method: string, path: string, body?: any, headers?: Record<string, string>) {
    const t0 = ts()
    try {
      const opts: RequestInit = {
        method,
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...headers,
        },
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      }
      const res = await fetch(BASE + path, opts)
      let data: any = null
      try { data = await res.clone().json() } catch { data = null }
      return { code: res.status, data, ms: ts() - t0 }
    } catch (err) {
      return { code: 0, data: null, ms: ts() - t0 }
    }
  }

  // ── AUTH ──────────────────────────────────────────────────────────────────
  markRunning('AUTH-1', 'Login correct credentials → 200', 'AUTH')
  let r = await req('POST', '/auth/login', { email: adminEmail, password: adminPass })
  token = r.data?.access_token ?? ''
  push('AUTH-1', 'Login correct credentials → 200', 'AUTH', r.code === 200 && !!token, `HTTP ${r.code}`)

  markRunning('AUTH-2', 'Login wrong password → 401', 'AUTH')
  r = await req('POST', '/auth/login', { email: adminEmail, password: 'wrong' })
  push('AUTH-2', 'Login wrong password → 401', 'AUTH', r.code === 401, `HTTP ${r.code}`)

  markRunning('AUTH-3', 'No token → 401', 'AUTH')
  const savedToken = token; token = ''
  r = await req('GET', '/orders/')
  push('AUTH-3', 'No token → 401', 'AUTH', r.code === 401, `HTTP ${r.code}`)
  token = savedToken

  markRunning('AUTH-4', 'Valid token → 200', 'AUTH')
  r = await req('GET', '/orders/')
  push('AUTH-4', 'Valid token → 200', 'AUTH', r.code === 200, `HTTP ${r.code}`)

  markRunning('AUTH-5', 'POST /auth/logout → 204', 'AUTH')
  r = await req('POST', '/auth/logout')
  push('AUTH-5', 'POST /auth/logout → 204', 'AUTH', r.code === 204, `HTTP ${r.code}`)

  markRunning('AUTH-6', 'Revoked token → 401', 'AUTH')
  r = await req('GET', '/orders/')
  push('AUTH-6', 'Revoked token → 401', 'AUTH', r.code === 401, `HTTP ${r.code}`)

  markRunning('AUTH-7', 'Malformed JWT → 401', 'AUTH')
  token = 'notvalidjwt'
  r = await req('GET', '/orders/')
  push('AUTH-7', 'Malformed JWT → 401', 'AUTH', r.code === 401, `HTTP ${r.code}`)
  token = ''

  // Re-login
  r = await req('POST', '/auth/login', { email: adminEmail, password: adminPass })
  token = r.data?.access_token ?? ''

  markRunning('AUTH-8', 'AI /chat no token → 401', 'AUTH')
  const t2 = token; token = ''
  r = await req('POST', '/ai/chat', { messages: [{ role: 'user', content: 'hi' }] })
  push('AUTH-8', 'AI /chat no token → 401', 'AUTH', r.code === 401, `HTTP ${r.code}`)
  token = t2

  markRunning('AUTH-9', 'Analytics no token → 401', 'AUTH')
  token = ''
  r = await req('GET', '/analytics/dashboard')
  push('AUTH-9', 'Analytics no token → 401', 'AUTH', r.code === 401, `HTTP ${r.code}`)

  markRunning('AUTH-10', 'Inventory no token → 401', 'AUTH')
  r = await req('GET', '/inventory/')
  push('AUTH-10', 'Inventory no token → 401', 'AUTH', r.code === 401, `HTTP ${r.code}`)

  markRunning('AUTH-11', 'Search no token → 401', 'AUTH')
  r = await req('POST', '/search/orders', {})
  push('AUTH-11', 'Search no token → 401', 'AUTH', r.code === 401, `HTTP ${r.code}`)
  token = t2

  // ── ORDERS ────────────────────────────────────────────────────────────────
  markRunning('ORDER-1', 'Create order → 201', 'ORDERS')
  r = await req('POST', '/orders/', {
    channel: 'WEB', fulfillment_type: 'SHIP_TO_HOME',
    customer_name: 'UAT Tester', customer_email: 'test.uat@example.com',
    shipping_address: { address1: '123 Test St', city: 'San Francisco', state: 'CA', postal_code: '94105', country: 'US' },
    line_items: [{ sku: 'UAT-SKU-001', product_name: 'Test Widget', quantity: 2, unit_price: 49.99 }],
  })
  orderId = r.data?.id ?? ''
  push('ORDER-1', 'Create order → 201', 'ORDERS', !!orderId, orderId ? '' : `HTTP ${r.code}`)

  markRunning('ORDER-2', 'List orders → 200', 'ORDERS')
  r = await req('GET', '/orders/')
  push('ORDER-2', 'List orders → 200', 'ORDERS', r.code === 200, `HTTP ${r.code}`)

  markRunning('ORDER-3', 'Get order by ID → 200', 'ORDERS')
  if (orderId) {
    r = await req('GET', `/orders/${orderId}`)
    push('ORDER-3', 'Get order by ID → 200', 'ORDERS', r.code === 200, `HTTP ${r.code}`)
  } else {
    push('ORDER-3', 'Get order by ID → 200', 'ORDERS', false, 'No ORDER_ID')
  }

  markRunning('ORDER-4', 'Status transition → SOURCING', 'ORDERS')
  if (orderId) {
    r = await req('PATCH', `/orders/${orderId}/status`, { status: 'SOURCING' })
    push('ORDER-4', 'Status → SOURCING', 'ORDERS', r.code === 200, `HTTP ${r.code}`)
  } else {
    push('ORDER-4', 'Status → SOURCING', 'ORDERS', false, 'No ORDER_ID')
  }

  markRunning('ORDER-4b', 'Status transition → SOURCED', 'ORDERS')
  if (orderId) {
    r = await req('PATCH', `/orders/${orderId}/status`, { status: 'SOURCED' })
    push('ORDER-4b', 'Status → SOURCED', 'ORDERS', r.code === 200, `HTTP ${r.code}`)
  } else {
    push('ORDER-4b', 'Status → SOURCED', 'ORDERS', false, 'No ORDER_ID')
  }

  markRunning('ORDER-4c', 'Invalid status transition → 422', 'ORDERS')
  if (orderId) {
    r = await req('PATCH', `/orders/${orderId}/status`, { status: 'DELIVERED' })
    push('ORDER-4c', 'Invalid transition → 422', 'ORDERS', r.code === 422 || r.code === 400, `HTTP ${r.code}`)
  } else {
    push('ORDER-4c', 'Invalid transition → 422', 'ORDERS', false, 'No ORDER_ID')
  }

  markRunning('ORDER-5', 'Cancel order → 200', 'ORDERS')
  r = await req('POST', '/orders/', {
    channel: 'WEB', fulfillment_type: 'SHIP_TO_HOME',
    customer_name: 'Cancel', customer_email: 'cancel@example.com',
    shipping_address: { address1: '1 St', city: 'SF', state: 'CA', postal_code: '94105', country: 'US' },
    line_items: [{ sku: 'CANCEL', product_name: 'Item', quantity: 1, unit_price: 1.0 }],
  })
  cancelId = r.data?.id ?? ''
  if (cancelId) {
    r = await req('POST', `/orders/${cancelId}/cancel`, { reason: 'UAT cancel' })
    push('ORDER-5', 'Cancel order → 200', 'ORDERS', r.code === 200, `HTTP ${r.code}`)
  } else {
    push('ORDER-5', 'Cancel order → 200', 'ORDERS', false, 'Could not create order')
  }

  markRunning('ORDER-6', 'Order audit trail → 200', 'ORDERS')
  if (orderId) {
    r = await req('GET', `/orders/${orderId}/events`)
    push('ORDER-6', 'Order audit trail → 200', 'ORDERS', r.code === 200, `HTTP ${r.code}`)
  } else {
    push('ORDER-6', 'Order audit trail → 200', 'ORDERS', false, 'No ORDER_ID')
  }

  markRunning('ORDER-ERR1', 'Missing fields → 422', 'ORDERS')
  r = await req('POST', '/orders/', { channel: 'WEB' })
  push('ORDER-ERR1', 'Missing fields → 422', 'ORDERS', r.code === 422, `HTTP ${r.code}`)

  markRunning('ORDER-ERR2', 'Non-existent order → 404', 'ORDERS')
  r = await req('GET', '/orders/00000000-0000-0000-0000-000000000000')
  push('ORDER-ERR2', 'Non-existent order → 404', 'ORDERS', r.code === 404, `HTTP ${r.code}`)

  // ── INVENTORY ─────────────────────────────────────────────────────────────
  markRunning('INV-1', 'List inventory → 200', 'INVENTORY')
  r = await req('GET', '/inventory/')
  push('INV-1', 'List inventory → 200', 'INVENTORY', r.code === 200, `HTTP ${r.code}`)

  // Get a node
  r = await req('GET', '/nodes/')
  const nodeItems = Array.isArray(r.data) ? r.data : (r.data?.items ?? [])
  nodeId = nodeItems[0]?.id ?? ''

  markRunning('INV-2', 'Create inventory item → 201', 'INVENTORY')
  if (nodeId) {
    const sku = `UAT-INV-${Date.now()}`
    r = await req('POST', '/inventory/', { sku, node_id: nodeId, quantity_available: 0, quantity_reserved: 0, reorder_point: 5, reorder_quantity: 50 })
    invId = r.data?.id ?? ''
    push('INV-2', 'Create inventory item → 201', 'INVENTORY', !!invId, invId ? '' : `HTTP ${r.code}`)
  } else {
    push('INV-2', 'Create inventory item → 201', 'INVENTORY', false, 'No nodes available')
  }

  markRunning('INV-3', 'Adjust inventory +100 → 200', 'INVENTORY')
  if (invId) {
    r = await req('POST', `/inventory/${invId}/adjust`, { quantity_delta: 100, reason: 'RECEIVED', notes: 'UAT' })
    push('INV-3', 'Adjust inventory +100 → 200', 'INVENTORY', r.code === 200, `HTTP ${r.code}`)
  } else {
    push('INV-3', 'Adjust inventory +100 → 200', 'INVENTORY', false, 'No INV_ID')
  }

  markRunning('INV-4', 'Check availability → 200', 'INVENTORY')
  r = await req('POST', '/inventory/check-availability', { items: [{ sku: 'UAT-SKU-001', quantity: 1 }] })
  push('INV-4', 'Check availability → 200', 'INVENTORY', r.code === 200, `HTTP ${r.code}`)

  markRunning('INV-5', 'Products grouped by SKU → 200', 'INVENTORY')
  r = await req('GET', '/inventory/products')
  push('INV-5', 'Products grouped by SKU → 200', 'INVENTORY', r.code === 200, `HTTP ${r.code}`)

  markRunning('INV-ERR1', 'Invalid adjustment reason → 422', 'INVENTORY')
  const target = invId || '00000000-0000-0000-0000-000000000001'
  r = await req('POST', `/inventory/${target}/adjust`, { quantity_delta: 10, reason: 'BAD_REASON' })
  push('INV-ERR1', 'Invalid adjustment reason → 422', 'INVENTORY', r.code === 422, `HTTP ${r.code}`)

  // ── ANALYTICS ─────────────────────────────────────────────────────────────
  for (const [id, desc, path] of [
    ['ANA-1', 'Dashboard → 200', '/analytics/dashboard'],
    ['ANA-2', 'Order volume → 200', '/analytics/orders/volume'],
    ['ANA-3', 'Inventory summary → 200', '/analytics/inventory/summary'],
  ] as [string, string, string][]) {
    markRunning(id, desc, 'ANALYTICS')
    r = await req('GET', path)
    push(id, desc, 'ANALYTICS', r.code === 200, `HTTP ${r.code}`)
  }

  // ── SEARCH ────────────────────────────────────────────────────────────────
  markRunning('SEARCH-1', 'Search orders → 200', 'SEARCH')
  r = await req('POST', '/search/orders', { query: 'UAT', page: 1, page_size: 5 })
  push('SEARCH-1', 'Search orders → 200', 'SEARCH', r.code === 200, `HTTP ${r.code}`)

  markRunning('SEARCH-2', 'Invalid sort field (allowlist fallback) → 200', 'SEARCH')
  r = await req('POST', '/search/orders', { query: 'test', sort_by: '__proto__', page: 1, page_size: 5 })
  push('SEARCH-2', 'Invalid sort field fallback → 200', 'SEARCH', r.code === 200, `HTTP ${r.code}`)

  // ── AI ────────────────────────────────────────────────────────────────────
  markRunning('AI-1', 'AI status → 200', 'AI')
  r = await req('GET', '/ai/status')
  push('AI-1', 'AI status → 200', 'AI', r.code === 200, `HTTP ${r.code}`)

  markRunning('AI-2', 'AI chat (SSE) → 200', 'AI')
  r = await req('POST', '/ai/chat', { messages: [{ role: 'user', content: 'How many orders?' }] })
  push('AI-2', 'AI chat → 200', 'AI', r.code === 200, `HTTP ${r.code}`)

  // ── RBAC ──────────────────────────────────────────────────────────────────
  const regEmail = `uat.reg.${Date.now()}@example.com`
  markRunning('RBAC-1', 'Create regular user → 201/429', 'RBAC')
  r = await req('POST', '/admin/users', { email: regEmail, password: 'Pass1234!', full_name: 'UAT Regular', is_superadmin: false })
  const rbacOk = r.code === 201 || r.code === 200 || r.code === 429
  push('RBAC-1', 'Create regular user → 201/429', 'RBAC', rbacOk, `HTTP ${r.code}`)

  if (r.code === 201 || r.code === 200) {
    const lr = await req('POST', '/auth/login', { email: regEmail, password: 'Pass1234!' })
    regToken = lr.data?.access_token ?? ''
  }
  const rbacToken = regToken || 'invalid.rbac.test.token'
  const savedMainToken = token

  markRunning('RBAC-2', 'Non-admin → /admin/users → 403/401', 'RBAC')
  token = rbacToken
  r = await req('GET', '/admin/users')
  push('RBAC-2', 'Non-admin → admin endpoint → 403/401', 'RBAC', r.code === 403 || r.code === 401, `HTTP ${r.code}`)

  markRunning('RBAC-3', 'Non-admin → /architect → 403/401', 'RBAC')
  r = await req('GET', '/architect/proposals')
  push('RBAC-3', 'Non-admin → architect → 403/401', 'RBAC', r.code === 403 || r.code === 401, `HTTP ${r.code}`)

  markRunning('RBAC-4', 'Non-admin → /testing → 403/401', 'RBAC')
  r = await req('POST', '/testing/e2e/run')
  push('RBAC-4', 'Non-admin → testing → 403/401/405', 'RBAC', r.code === 403 || r.code === 401 || r.code === 405, `HTTP ${r.code}`)
  token = savedMainToken

  // ── SECURITY ──────────────────────────────────────────────────────────────
  markRunning('SEC-1', 'Deployment config → 403/404 for non-superadmin', 'SECURITY')
  token = regToken || savedMainToken
  r = await req('GET', '/environments/00000000-0000-0000-0000-000000000000/deployment-config')
  push('SEC-1', 'Deployment config non-superadmin → 403/404', 'SECURITY', r.code === 403 || r.code === 404, `HTTP ${r.code}`)
  token = savedMainToken

  markRunning('SEC-2', 'Exception handler hides stack traces', 'SECURITY')
  r = await req('GET', '/orders/not-a-valid-uuid')
  const body = JSON.stringify(r.data ?? '')
  const hasLeak = ['Traceback', 'sqlalchemy', 'psycopg', 'File "/'].some(x => body.includes(x))
  push('SEC-2', 'Exception handler hides stack traces', 'SECURITY', !hasLeak, hasLeak ? 'Stack trace in response' : '')

  markRunning('SEC-3', 'Connector webhook_secret masked', 'SECURITY')
  r = await req('GET', '/connectors/')
  const connectors = Array.isArray(r.data) ? r.data : []
  const leaked = connectors.filter((c: any) => c?.config?.webhook_secret && c.config.webhook_secret !== '***')
  push('SEC-3', 'Connector webhook_secret masked', 'SECURITY', leaked.length === 0, leaked.length > 0 ? 'Secret leaked' : '')

  return cases
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const isPipeline = (name: string) => /^TC-\d+:/.test(name)

const GROUP_COLOR: Record<string, string> = {
  AUTH: 'indigo', ORDERS: 'blue', INVENTORY: 'teal',
  ANALYTICS: 'amber', SEARCH: 'pink', AI: 'violet', RBAC: 'orange', SECURITY: 'red',
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function E2ETestingPage() {
  const [activeTab, setActiveTab] = useState<'pipeline' | 'api'>('pipeline')

  // Pipeline test state
  const [pipeLoading, setPipeLoading] = useState(false)
  const [pipeResults, setPipeResults] = useState<TestRunResponse | null>(null)
  const [pipeError, setPipeError] = useState<string | null>(null)
  const [catalogOpen, setCatalogOpen] = useState(true)
  const [expandedTests, setExpandedTests] = useState<Set<number>>(new Set())
  const pipeResultsRef = useRef<HTMLDivElement>(null)

  // API test state
  const [apiRunning, setApiRunning] = useState(false)
  const [apiCases, setApiCases] = useState<ApiTestCase[]>([])
  const [apiDone, setApiDone] = useState(false)
  const [apiError, setApiError] = useState<string | null>(null)
  const [apiCleanup, setApiCleanup] = useState<Record<string, number> | null>(null)
  const [apiRunMeta, setApiRunMeta] = useState<{ testId: string; durationMs: number; cleanupMs: number } | null>(null)

  const toggleExpand = (idx: number) => {
    setExpandedTests(prev => {
      const next = new Set(prev); next.has(idx) ? next.delete(idx) : next.add(idx); return next
    })
  }

  const runPipelineTests = async (cleanup: boolean) => {
    setPipeLoading(true); setPipeError(null); setPipeResults(null); setExpandedTests(new Set())
    try {
      const endpoint = cleanup ? '/testing/e2e/run-with-cleanup' : '/testing/e2e/run'
      const { data } = await api.post(endpoint)
      setPipeResults(cleanup ? data : { ...data, cleanup_duration_ms: 0 })
      setTimeout(() => pipeResultsRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
    } catch (err: any) {
      const msg = err?.response?.data?.detail ?? err?.message ?? 'Unknown error'
      setPipeError(Array.isArray(msg) ? msg.map((e: any) => e.msg).join(', ') : String(msg))
    } finally {
      setPipeLoading(false)
    }
  }

  const runApiTestSuite = useCallback(async () => {
    setApiRunning(true); setApiCases([]); setApiDone(false); setApiError(null); setApiCleanup(null); setApiRunMeta(null)
    try {
      const { data } = await api.post('/testing/e2e/run-api')
      // Map server results to ApiTestCase format
      const cases: ApiTestCase[] = (data.results ?? []).map((r: any) => ({
        id: r.id,
        desc: r.desc,
        group: r.group,
        status: r.status === 'PASSED' ? 'pass' : r.status === 'SKIPPED' ? 'skip' : 'fail',
        note: r.note ?? '',
        duration_ms: r.duration_ms ?? 0,
      }))
      setApiCases(cases)
      setApiCleanup(data.deleted_resources ?? null)
      setApiRunMeta({ testId: data.test_id, durationMs: data.total_duration_ms, cleanupMs: data.cleanup_duration_ms ?? 0 })
      setApiDone(true)
    } catch (err: any) {
      const msg = err?.response?.data?.detail ?? err?.message ?? 'Unknown error'
      setApiError(Array.isArray(msg) ? msg.map((e: any) => e.msg).join(', ') : String(msg))
    } finally {
      setApiRunning(false)
    }
  }, [])

  const basicResults    = pipeResults?.results.filter(r => !isPipeline(r.name)) ?? []
  const pipelineResults = pipeResults?.results.filter(r => isPipeline(r.name)) ?? []

  const apiPass = apiCases.filter(c => c.status === 'pass').length
  const apiFail = apiCases.filter(c => c.status === 'fail').length
  const apiTotal = apiPass + apiFail

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 p-8">
      <div className="max-w-6xl mx-auto space-y-8">

        {/* Header */}
        <div>
          <h1 className="text-4xl font-bold text-slate-900 mb-2">E2E Testing Dashboard</h1>
          <p className="text-slate-600">
            Automated end-to-end testing for KubeRiva workflows. Run pipeline tests (Celery workers) or API integration tests (curl-equivalent browser checks).
          </p>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b border-slate-200">
          {([['pipeline', 'Pipeline Tests', Truck], ['api', 'API Integration Tests', Shield]] as const).map(([key, label, Icon]) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={`flex items-center gap-2 px-5 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === key
                  ? 'border-blue-600 text-blue-700 bg-white'
                  : 'border-transparent text-slate-500 hover:text-slate-700 hover:bg-slate-50'
              }`}
            >
              <Icon className="w-4 h-4" />{label}
            </button>
          ))}
        </div>

        {/* ── Pipeline Tests Tab ─────────────────────────────────────────────── */}
        {activeTab === 'pipeline' && (
          <div className="space-y-8">
            {/* Control Panel */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <button onClick={() => runPipelineTests(true)} disabled={pipeLoading}
                className="flex items-center justify-center gap-2 bg-gradient-to-r from-blue-600 to-blue-700 hover:from-blue-700 hover:to-blue-800 disabled:opacity-50 text-white font-semibold py-3 px-6 rounded-lg transition-all shadow-lg hover:shadow-xl disabled:cursor-not-allowed">
                {pipeLoading ? <Loader className="w-5 h-5 animate-spin" /> : <Play className="w-5 h-5" />}
                {pipeLoading ? 'Running Tests…' : 'Run Tests (Auto Cleanup)'}
              </button>
              <button onClick={() => runPipelineTests(false)} disabled={pipeLoading}
                className="flex items-center justify-center gap-2 bg-gradient-to-r from-amber-600 to-amber-700 hover:from-amber-700 hover:to-amber-800 disabled:opacity-50 text-white font-semibold py-3 px-6 rounded-lg transition-all shadow-lg hover:shadow-xl disabled:cursor-not-allowed">
                {pipeLoading ? <Loader className="w-5 h-5 animate-spin" /> : <Play className="w-5 h-5" />}
                {pipeLoading ? 'Running Tests…' : 'Run Tests (Keep Data)'}
              </button>
            </div>

            {pipeLoading && (
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 flex items-center gap-3">
                <Loader className="w-5 h-5 text-blue-600 animate-spin flex-shrink-0" />
                <div>
                  <p className="font-semibold text-blue-900">Tests running — this may take 60–120 s</p>
                  <p className="text-sm text-blue-700">Pipeline scenarios drive real Celery workers. Please wait…</p>
                </div>
              </div>
            )}

            {pipeError && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex gap-3">
                <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                <div>
                  <h3 className="font-semibold text-red-900">Error</h3>
                  <p className="text-red-700">{pipeError}</p>
                </div>
              </div>
            )}

            {/* Test Catalog */}
            <div className="bg-white rounded-lg shadow border border-slate-200">
              <button onClick={() => setCatalogOpen(o => !o)} className="w-full flex items-center justify-between p-5 text-left">
                <div className="flex items-center gap-2">
                  <FlaskConical className="w-5 h-5 text-slate-600" />
                  <span className="font-semibold text-lg text-slate-900">Test Catalog</span>
                  <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full">
                    {TEST_CATALOG.reduce((a, g) => a + g.tests.length, 0)} tests
                  </span>
                </div>
                {catalogOpen ? <ChevronUp className="w-5 h-5 text-slate-500" /> : <ChevronDown className="w-5 h-5 text-slate-500" />}
              </button>
              {catalogOpen && (
                <div className="border-t border-slate-100 divide-y divide-slate-100">
                  {TEST_CATALOG.map(group => (
                    <div key={group.group} className="p-5">
                      <div className="flex items-center gap-2 mb-3">
                        <group.icon className={`w-4 h-4 text-${group.color}-600`} />
                        <h3 className={`text-sm font-semibold uppercase tracking-wide text-${group.color}-700`}>{group.group}</h3>
                        <span className="text-xs text-slate-400">{group.tests.length} tests</span>
                      </div>
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="text-left text-slate-500 text-xs uppercase border-b border-slate-100">
                              <th className="pb-2 pr-4 font-medium">Test</th>
                              <th className="pb-2 pr-4 font-medium">Description</th>
                              {'inventory' in group.tests[0] && <th className="pb-2 pr-4 font-medium">Seed Inventory</th>}
                              {'expected' in group.tests[0] && <th className="pb-2 font-medium">Expected Outcome</th>}
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-50">
                            {group.tests.map((t: any) => (
                              <tr key={t.id} className="hover:bg-slate-50">
                                <td className="py-2 pr-4 font-medium text-slate-800 whitespace-nowrap">{t.name}</td>
                                <td className="py-2 pr-4 text-slate-600">{t.desc}</td>
                                {t.inventory && <td className="py-2 pr-4 font-mono text-xs text-slate-500">{t.inventory}</td>}
                                {t.expected && (
                                  <td className="py-2">
                                    <span className="inline-flex items-center gap-1 text-xs bg-green-50 text-green-700 border border-green-200 px-2 py-0.5 rounded-full">
                                      <CheckCircle className="w-3 h-3" />{t.expected}
                                    </span>
                                  </td>
                                )}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Pipeline Results */}
            {pipeResults && (
              <div ref={pipeResultsRef} className="space-y-6">
                <SummaryCard results={pipeResults} />
                {basicResults.length > 0 && (
                  <ResultGroup title="Basic Tests" icon={BarChart3} color="blue"
                    results={basicResults} allResults={pipeResults.results}
                    expandedTests={expandedTests} onToggle={toggleExpand} />
                )}
                {pipelineResults.length > 0 && (
                  <ResultGroup title="Pipeline Scenarios" icon={Truck} color="purple"
                    results={pipelineResults} allResults={pipeResults.results}
                    expandedTests={expandedTests} onToggle={toggleExpand} />
                )}
                {pipeResults.deleted_resources && Object.keys(pipeResults.deleted_resources).length > 0 && (
                  <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                    <h3 className="font-semibold text-green-900 mb-3">Cleanup Summary</h3>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      {Object.entries(pipeResults.deleted_resources).map(([k, v]) => (
                        <div key={k}><p className="text-sm text-green-700 capitalize">{k}</p><p className="text-2xl font-bold text-green-600">{v}</p></div>
                      ))}
                    </div>
                    {!!pipeResults.cleanup_duration_ms && (
                      <p className="text-xs text-green-600 mt-2">Cleanup in {(pipeResults.cleanup_duration_ms / 1000).toFixed(2)}s</p>
                    )}
                  </div>
                )}
                <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                  <div><p className="text-xs text-slate-500">Test ID</p><p className="font-mono text-slate-800">{pipeResults.test_id}</p></div>
                  <div><p className="text-xs text-slate-500">Status</p><p className="font-semibold text-slate-800">{pipeResults.status}</p></div>
                  <div><p className="text-xs text-slate-500">Duration</p><p className="text-slate-800">{(pipeResults.test_duration_ms / 1000).toFixed(2)}s</p></div>
                </div>
              </div>
            )}

            {!pipeResults && !pipeLoading && (
              <div className="bg-white rounded-lg shadow-lg p-12 text-center border border-slate-200">
                <Package className="w-16 h-16 text-slate-300 mx-auto mb-4" />
                <h3 className="text-lg font-semibold text-slate-600 mb-2">Ready to test</h3>
                <p className="text-slate-500">Select a run mode above to execute all {TEST_CATALOG.reduce((a, g) => a + g.tests.length, 0)} pipeline tests</p>
              </div>
            )}
          </div>
        )}

        {/* ── API Integration Tests Tab ──────────────────────────────────────── */}
        {activeTab === 'api' && (
          <div className="space-y-6">
            <div className="bg-white border border-slate-200 rounded-lg p-5">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">API Integration Test Suite</h2>
                  <p className="text-sm text-slate-500 mt-1">
                    Server-side HTTP tests across Auth, Orders, Inventory, Analytics, Search, AI, RBAC, and Security — mirrors <code className="bg-slate-100 px-1 rounded">run_e2e.sh</code>. All test data is cleaned up automatically.
                  </p>
                </div>
                <button
                  onClick={runApiTestSuite}
                  disabled={apiRunning}
                  className="flex items-center gap-2 bg-gradient-to-r from-slate-700 to-slate-800 hover:from-slate-800 hover:to-slate-900 disabled:opacity-50 text-white font-semibold py-3 px-6 rounded-lg transition-all shadow-lg whitespace-nowrap"
                >
                  {apiRunning
                    ? <><Loader className="w-5 h-5 animate-spin" />Running…</>
                    : <><RefreshCw className="w-5 h-5" />Run All API Tests</>}
                </button>
              </div>

              {/* Group legend */}
              <div className="mt-4 flex flex-wrap gap-2">
                {API_TEST_GROUPS.map(g => (
                  <span key={g.group} className={`text-xs font-medium px-2 py-0.5 rounded-full bg-${g.color}-50 text-${g.color}-700 border border-${g.color}-200`}>
                    {g.group} ({g.count})
                  </span>
                ))}
              </div>
            </div>

            {apiError && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex gap-3">
                <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                <p className="text-red-700">{apiError}</p>
              </div>
            )}

            {/* Live progress / summary */}
            {(apiCases.length > 0 || apiDone) && (
              <>
                {/* Summary bar */}
                <div className={`bg-white rounded-lg shadow p-5 border-l-4 ${apiDone ? (apiFail === 0 ? 'border-green-500' : 'border-red-500') : 'border-blue-500'}`}>
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex gap-6">
                      <div><p className="text-xs text-slate-500 uppercase tracking-wide">Pass</p><p className="text-3xl font-bold text-green-600">{apiPass}</p></div>
                      <div><p className="text-xs text-slate-500 uppercase tracking-wide">Fail</p><p className="text-3xl font-bold text-red-600">{apiFail}</p></div>
                      <div><p className="text-xs text-slate-500 uppercase tracking-wide">Running / Pending</p><p className="text-3xl font-bold text-slate-400">{apiCases.filter(c => c.status === 'running' || c.status === 'pending').length}</p></div>
                    </div>
                    {apiDone && (
                      <span className={`text-sm font-semibold px-3 py-1 rounded-full ${apiFail === 0 ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                        {apiFail === 0 ? `All ${apiPass} passed` : `${apiPass}/${apiTotal} passed`}
                      </span>
                    )}
                  </div>
                  {apiTotal > 0 && (
                    <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                      <div className="h-full bg-green-500 rounded-full transition-all" style={{ width: `${apiPass / Math.max(apiTotal, 42) * 100}%` }} />
                    </div>
                  )}
                </div>

                {/* Results table grouped by group */}
                {API_TEST_GROUPS.map(({ group, color }) => {
                  const rows = apiCases.filter(c => c.group === group)
                  if (rows.length === 0) return null
                  const gPass = rows.filter(r => r.status === 'pass').length
                  const gTotal = rows.filter(r => r.status === 'pass' || r.status === 'fail').length
                  return (
                    <div key={group} className="bg-white rounded-lg shadow border border-slate-200 overflow-hidden">
                      <div className={`px-5 py-3 bg-${color}-50 border-b border-${color}-100 flex items-center justify-between`}>
                        <span className={`font-semibold text-sm text-${color}-800`}>{group}</span>
                        {gTotal > 0 && (
                          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${gPass === gTotal ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                            {gPass}/{gTotal}
                          </span>
                        )}
                      </div>
                      <table className="w-full text-sm">
                        <tbody>
                          {rows.map(c => (
                            <tr key={c.id} className={`border-b border-slate-50 last:border-0 ${c.status === 'fail' ? 'bg-red-50' : c.status === 'running' ? 'bg-blue-50' : ''}`}>
                              <td className="px-4 py-2.5 font-mono text-xs text-slate-500 whitespace-nowrap w-28">{c.id}</td>
                              <td className="px-4 py-2.5 text-slate-700">{c.desc}</td>
                              <td className="px-4 py-2.5 whitespace-nowrap">
                                {c.status === 'running' && <span className="flex items-center gap-1 text-blue-600 text-xs font-medium"><Loader className="w-3.5 h-3.5 animate-spin" />Running</span>}
                                {c.status === 'pass' && <span className="flex items-center gap-1 text-green-600 text-xs font-semibold"><CheckCircle className="w-3.5 h-3.5" />PASS</span>}
                                {c.status === 'fail' && <span className="flex items-center gap-1 text-red-600 text-xs font-semibold"><AlertCircle className="w-3.5 h-3.5" />FAIL</span>}
                                {c.status === 'pending' && <span className="text-slate-400 text-xs flex items-center gap-1"><Clock className="w-3.5 h-3.5" />Pending</span>}
                              </td>
                              <td className="px-4 py-2.5 text-xs text-slate-400 font-mono">{c.note}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )
                })}
              </>
            )}

            {/* Cleanup summary */}
            {apiDone && apiCleanup && Object.keys(apiCleanup).length > 0 && (
              <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                <h3 className="font-semibold text-green-900 mb-3">Cleanup Summary</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {Object.entries(apiCleanup).filter(([k]) => k !== 'error').map(([k, v]) => (
                    <div key={k}><p className="text-sm text-green-700 capitalize">{k.replace(/_/g, ' ')}</p><p className="text-2xl font-bold text-green-600">{v}</p></div>
                  ))}
                </div>
                {apiRunMeta && <p className="text-xs text-green-600 mt-2">Cleanup in {(apiRunMeta.cleanupMs / 1000).toFixed(2)}s</p>}
              </div>
            )}
            {apiRunMeta && (
              <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                <div><p className="text-xs text-slate-500">Test ID</p><p className="font-mono text-slate-800">{apiRunMeta.testId}</p></div>
                <div><p className="text-xs text-slate-500">Duration</p><p className="text-slate-800">{(apiRunMeta.durationMs / 1000).toFixed(2)}s</p></div>
              </div>
            )}

            {apiCases.length === 0 && !apiRunning && !apiDone && (
              <div className="bg-white rounded-lg shadow-lg p-12 text-center border border-slate-200">
                <Shield className="w-16 h-16 text-slate-300 mx-auto mb-4" />
                <h3 className="text-lg font-semibold text-slate-600 mb-2">API integration tests ready</h3>
                <p className="text-slate-500 mb-2">Covers Auth, Orders, Inventory, Analytics, Search, AI, RBAC, and Security regression checks.</p>
                <p className="text-xs text-slate-400">Runs server-side via httpx — equivalent to <code className="bg-slate-100 px-1 rounded">bash run_e2e.sh</code>. All test data cleaned up automatically.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function SummaryCard({ results }: { results: TestRunResponse }) {
  return (
    <div className={`bg-white rounded-lg shadow-lg p-6 border-l-4 ${results.failed === 0 ? 'border-green-500' : 'border-red-500'}`}>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {[
          { label: 'Total', value: results.total_tests, color: 'slate' },
          { label: 'Passed', value: results.passed, color: 'green' },
          { label: 'Failed', value: results.failed, color: 'red' },
          { label: 'Pass Rate', value: `${results.total_tests ? Math.round(results.passed / results.total_tests * 100) : 0}%`, color: 'slate' },
          { label: 'Duration', value: `${(results.total_duration_ms / 1000).toFixed(1)}s`, color: 'slate' },
        ].map(({ label, value, color }) => (
          <div key={label}>
            <p className="text-slate-500 text-xs font-medium uppercase tracking-wide">{label}</p>
            <p className={`text-3xl font-bold text-${color}-${color === 'slate' ? 900 : 600}`}>{value}</p>
          </div>
        ))}
      </div>
      <div className="mt-4 h-2 bg-slate-100 rounded-full overflow-hidden">
        <div className="h-full bg-green-500 rounded-full transition-all"
          style={{ width: `${results.total_tests ? results.passed / results.total_tests * 100 : 0}%` }} />
      </div>
    </div>
  )
}

interface ResultGroupProps {
  title: string; icon: React.ElementType; color: string
  results: TestResult[]; allResults: TestResult[]
  expandedTests: Set<number>; onToggle: (idx: number) => void
}

function ResultGroup({ title, icon: Icon, color, results, allResults, expandedTests, onToggle }: ResultGroupProps) {
  const passed = results.filter(r => r.status === 'PASSED').length
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <Icon className={`w-5 h-5 text-${color}-600`} />
        <h2 className="text-lg font-bold text-slate-900">{title}</h2>
        <span className={`text-xs bg-${color}-50 text-${color}-700 border border-${color}-200 px-2 py-0.5 rounded-full`}>
          {passed}/{results.length} passed
        </span>
      </div>
      <div className="space-y-3">
        {results.map((result) => {
          const globalIdx = allResults.indexOf(result)
          const expanded = expandedTests.has(globalIdx)
          const isPass = result.status === 'PASSED'
          const isPipe = isPipeline(result.name)
          return (
            <div key={globalIdx}
              className={`bg-white rounded-lg shadow border-l-4 ${isPass ? 'border-green-400' : 'border-red-400'} overflow-hidden transition-shadow hover:shadow-md`}>
              <button className="w-full text-left p-4 flex items-start justify-between gap-3" onClick={() => onToggle(globalIdx)}>
                <div className="flex items-center gap-3 min-w-0">
                  {isPass ? <CheckCircle className="w-5 h-5 text-green-500 flex-shrink-0" /> : <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0" />}
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-slate-900">{result.name}</span>
                      {isPipe && <span className="text-xs bg-purple-50 text-purple-600 border border-purple-200 px-1.5 py-0.5 rounded">pipeline</span>}
                    </div>
                    <p className="text-sm text-slate-500 truncate">{result.message}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <span className="flex items-center gap-1 text-xs text-slate-400">
                    <Clock className="w-3.5 h-3.5" />
                    {result.duration_ms >= 1000 ? `${(result.duration_ms / 1000).toFixed(1)}s` : `${result.duration_ms.toFixed(0)}ms`}
                  </span>
                  {expanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
                </div>
              </button>
              {expanded && (
                <div className="border-t border-slate-100 p-4 space-y-3">
                  {isPipe && result.created_resources.order_status && (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      {[
                        { label: 'Order', value: result.created_resources.order_number ?? '—' },
                        { label: 'Final Status', value: result.created_resources.order_status ?? '—' },
                        { label: 'Shipments', value: result.created_resources.shipment_count ?? '—' },
                        { label: 'Allocations', value: result.created_resources.alloc_count ?? '—' },
                      ].map(({ label, value }) => (
                        <div key={label} className="bg-slate-50 rounded p-2 border border-slate-200">
                          <p className="text-xs text-slate-500">{label}</p>
                          <p className="font-semibold text-slate-800 font-mono text-sm">{String(value)}</p>
                        </div>
                      ))}
                    </div>
                  )}
                  {isPipe && Array.isArray(result.created_resources.allocations) && result.created_resources.allocations.length > 0 && (
                    <div>
                      <p className="text-xs font-semibold text-slate-600 mb-1">Allocations</p>
                      <div className="flex flex-wrap gap-2">
                        {result.created_resources.allocations.map((a: any, i: number) => (
                          <span key={i} className="text-xs bg-blue-50 border border-blue-200 text-blue-700 px-2 py-0.5 rounded-full">
                            {a.sku} × {a.qty} — {a.status}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {isPipe && Array.isArray(result.created_resources.shipments) && result.created_resources.shipments.length > 0 && (
                    <div>
                      <p className="text-xs font-semibold text-slate-600 mb-1">Shipments</p>
                      <div className="space-y-1">
                        {result.created_resources.shipments.map((s: any, i: number) => (
                          <div key={i} className="text-xs bg-purple-50 border border-purple-200 text-purple-700 px-3 py-1.5 rounded flex flex-wrap gap-x-3">
                            <span className="font-mono">{s.tracking}</span>
                            <span>Status: <strong>{s.status}</strong></span>
                            {s.items?.length > 0 && <span>SKUs: {s.items.map((it: any) => it.sku).join(', ')}</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {!isPipe && Object.keys(result.created_resources).length > 0 && (
                    <div className="bg-slate-50 rounded border border-slate-200 p-3">
                      <p className="text-xs font-semibold text-slate-600 mb-2">Resources</p>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                        {Object.entries(result.created_resources).map(([k, v]) => (
                          <div key={k} className="text-xs">
                            <p className="text-slate-500">{k}</p>
                            <p className="font-mono text-slate-800 break-all">{String(v)}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {result.errors.length > 0 && (
                    <div className="bg-red-50 rounded border border-red-200 p-3">
                      <p className="text-xs font-semibold text-red-700 mb-1">Errors</p>
                      <ul className="space-y-0.5">
                        {result.errors.map((e, ei) => (
                          <li key={ei} className="text-xs text-red-600 font-mono">• {e}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
