import { useState, useMemo, useRef, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, AlertCircle, Info, Bug, ChevronDown, ChevronUp,
  CheckCircle, BellOff, RefreshCw, Filter, Clock, Layers,
  BarChart2, List, Activity, ExternalLink, XCircle,
  Server, Database, Zap, GitMerge, TrendingUp, Box,
  Terminal, GitBranch, Bot, Send, Copy, Search, Tag,
  ArrowRight, RotateCcw,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts'
import api, { getBrands, type Brand } from '../api/client'

// ─── Types ────────────────────────────────────────────────────────────────────

interface ErrorEvent {
  event_id: string
  fingerprint: string
  timestamp: string
  level: string
  source_service: string
  error_type: string
  error_message: string
  stack_trace: string
  stack_frames: Array<{ filename: string; lineno: number; function: string; context_line: string }>
  request_context: Record<string, unknown>
  task_context: Record<string, unknown>
  order_context: Record<string, unknown>
  environment: string
  tags: string[]
}

interface ErrorIssue {
  fingerprint: string
  status: string
  error_type: string
  error_message: string
  source_service: string
  level: string
  occurrence_count: number
  first_seen_at: string
  last_seen_at: string
  resolution_note?: string
}

interface Summary {
  open_issues: number
  errors_last_1h: number
  errors_last_24h: number
  warnings_last_24h: number
  top_error_source: string | null
}

interface SparkPoint { t: string; count: number }

interface OpsHealth {
  services: Array<{ name: string; label: string; status: string; active_tasks: number }>
  queues: Record<string, number>
  errors_last_1h: number
  errors_by_service: Record<string, number>
  failed_celery_tasks: number
  recent_errors: Array<{
    timestamp: string; level: string; source_service: string
    error_type: string; message: string; fingerprint: string
    order_context?: { order_id?: string }
  }>
  sparkline: SparkPoint[]
  checked_at: string
}

interface LogLine {
  ts: string
  level: string
  msg: string
  container: string
  order_id?: string
  fingerprint?: string
  exc?: string
  raw?: string
}

interface TraceEvent {
  ts: string
  kind: 'audit' | 'error'
  event_type: string
  status?: string
  worker: string
  message?: string
  stack_trace?: string
  data: Record<string, unknown>
  ok: boolean
}

interface TraceData {
  order_id: string
  timeline: TraceEvent[]
  last_status: string | null
  last_error: TraceEvent | null
  audit_count: number
  error_count: number
}

// ─── API helpers ──────────────────────────────────────────────────────────────

const TIME_PRESETS = [
  { label: 'Last 1h',  hours: 1 },
  { label: 'Last 4h',  hours: 4 },
  { label: 'Last 24h', hours: 24 },
  { label: 'Last 7d',  hours: 168 },
  { label: 'Last 30d', hours: 720 },
]

const SOURCES = [
  'api', 'sourcing_worker', 'fulfillment_worker',
  'carrier_worker', 'webhook_worker', 'connector_worker', 'database',
]

const LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

const DOCKER_SERVICES = ['api', 'celery_worker', 'celery_beat', 'flower', 'frontend']

function fromTs(hours: number) {
  return new Date(Date.now() - hours * 3_600_000).toISOString()
}

function buildEventsParams(filters: Filters, page: number) {
  const p: Record<string, string | number> = { page, page_size: 50 }
  p.from_ts = fromTs(filters.hours)
  if (filters.level)   p.level = filters.level
  if (filters.source)  p.source_service = filters.source
  if (filters.errType) p.error_type = filters.errType
  if (filters.orderId) p.order_id = filters.orderId
  if (filters.brandId) p.brand_id = filters.brandId
  return p
}

function buildIssuesParams(filters: Filters, page: number, sortBy: string) {
  const p: Record<string, string | number> = { page, page_size: 50, sort_by: sortBy }
  if (filters.issueStatus) p.status = filters.issueStatus
  if (filters.level)       p.level = filters.level
  if (filters.source)      p.source_service = filters.source
  if (filters.brandId)     p.brand_id = filters.brandId
  p.from_ts = fromTs(filters.hours)
  return p
}

// ─── Shared badge components ──────────────────────────────────────────────────

function LevelBadge({ level }: { level: string }) {
  const cfg: Record<string, { cls: string; icon: React.ReactNode }> = {
    CRITICAL: { cls: 'bg-red-600 text-white',          icon: <XCircle className="w-3 h-3" /> },
    ERROR:    { cls: 'bg-red-100 text-red-700',        icon: <AlertCircle className="w-3 h-3" /> },
    WARNING:  { cls: 'bg-amber-100 text-amber-800',    icon: <AlertTriangle className="w-3 h-3" /> },
    INFO:     { cls: 'bg-blue-100 text-blue-700',      icon: <Info className="w-3 h-3" /> },
    DEBUG:    { cls: 'bg-gray-100 text-gray-600',      icon: <Bug className="w-3 h-3" /> },
  }
  const { cls, icon } = cfg[level?.toUpperCase()] ?? cfg.DEBUG
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${cls}`}>
      {icon}{level}
    </span>
  )
}

function SourceBadge({ source }: { source: string }) {
  const colors: Record<string, string> = {
    api:                 'bg-blue-100 text-blue-700',
    sourcing_worker:     'bg-emerald-100 text-emerald-700',
    fulfillment_worker:  'bg-violet-100 text-violet-700',
    carrier_worker:      'bg-sky-100 text-sky-700',
    webhook_worker:      'bg-orange-100 text-orange-700',
    connector_worker:    'bg-rose-100 text-rose-700',
    database:            'bg-gray-100 text-gray-700',
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${colors[source] ?? 'bg-gray-100 text-gray-600'}`}>
      {source.replace('_worker', '')}
    </span>
  )
}

function relTime(ts: string) {
  const diff = Date.now() - new Date(ts).getTime()
  if (diff < 60_000)    return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

function fmtTs(ts: string) {
  if (!ts) return '—'
  const d = new Date(ts.endsWith('Z') ? ts : ts + 'Z')
  return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

// ─── Filters ──────────────────────────────────────────────────────────────────

interface Filters {
  hours: number
  level: string
  source: string
  errType: string
  orderId: string
  issueStatus: string
  brandId: string
}

type TabId = 'issues' | 'events' | 'metrics' | 'performance' | 'live_logs' | 'trace' | 'analyzer'

const FILTER_TABS: TabId[] = ['issues', 'events', 'metrics', 'performance']

function FilterBar({ filters, onChange, tab, brands }: {
  filters: Filters
  onChange: (f: Partial<Filters>) => void
  tab: TabId
  brands: Brand[]
}) {
  const sel = 'select text-xs border-0 bg-gray-100 rounded px-2 py-1.5 focus:ring-1 focus:ring-blue-500 outline-none'
  return (
    <div className="flex flex-wrap gap-2 items-center px-4 py-3 bg-white border-b border-gray-200">
      <Filter className="w-4 h-4 text-gray-400 flex-shrink-0" />
      <select className={sel} value={filters.hours} onChange={e => onChange({ hours: +e.target.value })}>
        {TIME_PRESETS.map(p => <option key={p.hours} value={p.hours}>{p.label}</option>)}
      </select>
      {tab !== 'performance' && (
        <select className={sel} value={filters.level} onChange={e => onChange({ level: e.target.value })}>
          <option value="">All Levels</option>
          {LEVELS.map(l => <option key={l} value={l}>{l}</option>)}
        </select>
      )}
      {tab !== 'performance' && (
        <select className={sel} value={filters.source} onChange={e => onChange({ source: e.target.value })}>
          <option value="">All Sources</option>
          {SOURCES.map(s => <option key={s} value={s}>{s.replace('_worker', '')}</option>)}
        </select>
      )}
      {tab === 'issues' && (
        <select className={sel} value={filters.issueStatus} onChange={e => onChange({ issueStatus: e.target.value })}>
          <option value="">All Issues</option>
          <option value="open">Open</option>
          <option value="resolved">Resolved</option>
          <option value="muted">Muted</option>
        </select>
      )}
      {tab !== 'metrics' && tab !== 'performance' && (
        <input
          className="text-xs border-0 bg-gray-100 rounded px-2 py-1.5 focus:ring-1 focus:ring-blue-500 outline-none w-36"
          placeholder="Error type…"
          value={filters.errType}
          onChange={e => onChange({ errType: e.target.value })}
        />
      )}
      {tab === 'events' && (
        <input
          className="text-xs border-0 bg-gray-100 rounded px-2 py-1.5 focus:ring-1 focus:ring-blue-500 outline-none w-48"
          placeholder="Order ID…"
          value={filters.orderId}
          onChange={e => onChange({ orderId: e.target.value })}
        />
      )}
      {brands.length > 0 && (
        <span className="inline-flex items-center gap-1">
          <Tag className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
          <select className={sel} value={filters.brandId} onChange={e => onChange({ brandId: e.target.value })}>
            <option value="">All Brands</option>
            {brands.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </span>
      )}
      <button
        onClick={() => onChange({ level: '', source: '', errType: '', orderId: '', issueStatus: 'open', hours: 24, brandId: '' })}
        className="text-xs text-gray-500 hover:text-gray-800 underline"
      >
        Clear
      </button>
    </div>
  )
}

// ─── Issues tab ───────────────────────────────────────────────────────────────

function IssueRow({ issue, onAction }: { issue: ErrorIssue; onAction: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const qc = useQueryClient()

  const updateIssue = useMutation({
    mutationFn: ({ status, mute_hours, resolution_note }: { status: string; mute_hours?: number; resolution_note?: string }) =>
      api.patch(`/monitoring/issues/${issue.fingerprint}`, { status, mute_hours, resolution_note }).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['monitoring-issues'] }); onAction() },
  })

  const { data: detail } = useQuery({
    queryKey: ['issue-detail', issue.fingerprint],
    queryFn: () => api.get(`/monitoring/issues/${issue.fingerprint}`).then(r => r.data),
    enabled: expanded,
  })

  const statusCls = issue.status === 'resolved' ? 'bg-green-100 text-green-700'
    : issue.status === 'muted' ? 'bg-gray-100 text-gray-500'
    : 'bg-red-50 text-red-700'

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <div
        className="flex items-start gap-3 px-4 py-3 bg-white hover:bg-gray-50 cursor-pointer"
        onClick={() => setExpanded(x => !x)}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <LevelBadge level={issue.level} />
            <SourceBadge source={issue.source_service} />
            <span className="text-xs font-mono text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded">{issue.error_type}</span>
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusCls}`}>{issue.status}</span>
          </div>
          <p className="text-sm text-gray-800 font-medium truncate">{issue.error_message}</p>
          <div className="flex items-center gap-3 mt-1 text-xs text-gray-400">
            <span className="flex items-center gap-1"><AlertCircle className="w-3 h-3" />{issue.occurrence_count} occurrences</span>
            <span className="flex items-center gap-1"><Clock className="w-3 h-3" />Last: {relTime(issue.last_seen_at)}</span>
            <span>First: {relTime(issue.first_seen_at)}</span>
          </div>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          {issue.status === 'open' && (
            <>
              <button
                onClick={e => { e.stopPropagation(); updateIssue.mutate({ status: 'resolved' }) }}
                className="text-xs px-2 py-1 rounded bg-green-100 text-green-700 hover:bg-green-200 font-medium"
              >Resolve</button>
              <button
                onClick={e => { e.stopPropagation(); updateIssue.mutate({ status: 'muted', mute_hours: 24 }) }}
                className="text-xs px-2 py-1 rounded bg-gray-100 text-gray-600 hover:bg-gray-200 font-medium"
              >Mute 24h</button>
            </>
          )}
          {issue.status !== 'open' && (
            <button
              onClick={e => { e.stopPropagation(); updateIssue.mutate({ status: 'open' }) }}
              className="text-xs px-2 py-1 rounded bg-blue-100 text-blue-700 hover:bg-blue-200 font-medium"
            >Reopen</button>
          )}
          {expanded ? <ChevronUp className="w-4 h-4 text-gray-400 ml-1" /> : <ChevronDown className="w-4 h-4 text-gray-400 ml-1" />}
        </div>
      </div>

      {expanded && detail && (
        <div className="border-t border-gray-200 bg-gray-50 px-4 py-4 space-y-4">
          {detail.recent_events?.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Recent Occurrences</p>
              <div className="space-y-1">
                {detail.recent_events.slice(0, 5).map((ev: ErrorEvent) => (
                  <div key={ev.event_id} className="flex items-center gap-3 text-xs text-gray-600">
                    <span className="text-gray-400 font-mono">{new Date(ev.timestamp).toLocaleString()}</span>
                    {(ev.order_context?.order_id as string | undefined) && (
                      <Link
                        to={`/orders/${ev.order_context.order_id as string}`}
                        className="text-blue-600 hover:underline flex items-center gap-1"
                        onClick={e => e.stopPropagation()}
                      >
                        <ExternalLink className="w-3 h-3" />
                        {String(ev.order_context.order_id).slice(0, 8)}…
                      </Link>
                    )}
                    {(ev.task_context?.task as string | undefined) && <span className="text-gray-400">{String(ev.task_context.task)}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
          {detail.recent_events?.[0]?.stack_trace && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Stack Trace</p>
              <pre className="text-xs bg-gray-900 text-gray-100 p-3 rounded overflow-x-auto max-h-48 leading-relaxed">
                {detail.recent_events[0].stack_trace}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function IssuesTab({ filters }: { filters: Filters }) {
  const [page, setPage] = useState(1)
  const [sortBy, setSortBy] = useState('last_seen')
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const qc = useQueryClient()

  const params = useMemo(() => buildIssuesParams(filters, page, sortBy), [filters, page, sortBy])
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['monitoring-issues', params],
    queryFn: () => api.get('/monitoring/issues', { params }).then(r => r.data),
    refetchInterval: 30_000,
  })

  const bulkResolve = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post('/monitoring/issues/bulk-resolve', body).then(r => r.data),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['monitoring-issues'] })
      qc.invalidateQueries({ queryKey: ['monitoring-summary'] })
      setSuccessMsg(`Resolved ${result.resolved_count} issue(s).`)
      setTimeout(() => setSuccessMsg(null), 4000)
    },
  })

  const issues: ErrorIssue[] = data?.items ?? []
  const total: number = data?.total ?? 0
  const openCount = issues.filter(i => i.status === 'open').length

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">{total} issues</p>
        <div className="flex items-center gap-2">
          <select className="text-xs border border-gray-200 rounded px-2 py-1.5 bg-white" value={sortBy} onChange={e => setSortBy(e.target.value)}>
            <option value="last_seen">Most Recent</option>
            <option value="count">Highest Count</option>
            <option value="first_seen">First Seen</option>
          </select>
          {openCount > 0 && (
            <button
              onClick={() => {
                if (!confirm(`Resolve all ${openCount} open issue(s) on this page?`)) return
                const body: Record<string, unknown> = {}
                if (filters.source) body.source_service = filters.source
                if (filters.level) body.level = filters.level
                bulkResolve.mutate(body)
              }}
              disabled={bulkResolve.isPending}
              className="text-xs px-2 py-1 rounded bg-green-100 text-green-700 hover:bg-green-200 font-medium flex items-center gap-1"
            >
              <CheckCircle className="w-3 h-3" />Resolve All ({openCount})
            </button>
          )}
          <button onClick={() => refetch()} className="btn-secondary text-xs py-1 px-2 flex items-center gap-1">
            <RefreshCw className="w-3 h-3" />Refresh
          </button>
        </div>
      </div>

      {successMsg && (
        <div className="bg-green-50 text-green-700 border border-green-200 rounded-lg p-3 text-sm">
          {successMsg}
        </div>
      )}

      {isLoading && <p className="text-sm text-gray-400 text-center py-8">Loading issues…</p>}
      {!isLoading && issues.length === 0 && (
        <div className="text-center py-16">
          <CheckCircle className="w-10 h-10 text-green-400 mx-auto mb-3" />
          <p className="text-gray-500 text-sm font-medium">No issues found</p>
          <p className="text-gray-400 text-xs mt-1">Errors captured by KubeRiva will appear here</p>
        </div>
      )}

      {issues.map(issue => (
        <IssueRow key={issue.fingerprint} issue={issue} onAction={() => qc.invalidateQueries({ queryKey: ['monitoring-issues'] })} />
      ))}

      {total > 50 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button disabled={page === 1} onClick={() => setPage(p => p - 1)} className="btn-secondary text-xs py-1 px-3">Prev</button>
          <span className="text-xs text-gray-500">Page {page}</span>
          <button disabled={issues.length < 50} onClick={() => setPage(p => p + 1)} className="btn-secondary text-xs py-1 px-3">Next</button>
        </div>
      )}
    </div>
  )
}

// ─── Events tab ───────────────────────────────────────────────────────────────

function EventRow({ ev, onTrace }: { ev: ErrorEvent; onTrace?: (id: string) => void }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <div
        className="flex items-start gap-3 px-4 py-2.5 bg-white hover:bg-gray-50 cursor-pointer"
        onClick={() => setExpanded(x => !x)}
      >
        <span className="text-xs text-gray-400 font-mono w-36 flex-shrink-0 pt-0.5">
          {new Date(ev.timestamp).toLocaleTimeString()}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <LevelBadge level={ev.level} />
            <SourceBadge source={ev.source_service} />
            <span className="text-xs font-mono text-gray-600">{ev.error_type}</span>
            {(ev.order_context?.order_id as string | undefined) && (
              <>
                <Link
                  to={`/orders/${ev.order_context.order_id as string}`}
                  className="text-xs text-blue-600 hover:underline flex items-center gap-1"
                  onClick={e => e.stopPropagation()}
                >
                  <ExternalLink className="w-3 h-3" />Order
                </Link>
                {onTrace && (
                  <button
                    className="text-xs text-purple-600 hover:underline"
                    onClick={e => { e.stopPropagation(); onTrace(ev.order_context.order_id as string) }}
                  >
                    Trace →
                  </button>
                )}
              </>
            )}
          </div>
          <p className="text-xs text-gray-700 truncate mt-0.5">{ev.error_message}</p>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-gray-300 flex-shrink-0" /> : <ChevronDown className="w-4 h-4 text-gray-300 flex-shrink-0" />}
      </div>

      {expanded && (
        <div className="border-t border-gray-200 bg-gray-50 px-4 py-4 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {Object.keys(ev.request_context || {}).length > 0 && (
              <div className="bg-white rounded border border-gray-200 p-3">
                <p className="text-xs font-semibold text-gray-400 mb-2 uppercase tracking-wider">Request</p>
                {Object.entries(ev.request_context).map(([k, v]) => (
                  <div key={k} className="text-xs flex justify-between gap-2">
                    <span className="text-gray-400">{k}</span>
                    <span className="text-gray-700 font-mono truncate">{String(v)}</span>
                  </div>
                ))}
              </div>
            )}
            {Object.keys(ev.task_context || {}).length > 0 && (
              <div className="bg-white rounded border border-gray-200 p-3">
                <p className="text-xs font-semibold text-gray-400 mb-2 uppercase tracking-wider">Task</p>
                {Object.entries(ev.task_context).map(([k, v]) => (
                  <div key={k} className="text-xs flex justify-between gap-2">
                    <span className="text-gray-400">{k}</span>
                    <span className="text-gray-700 font-mono truncate">{String(v)}</span>
                  </div>
                ))}
              </div>
            )}
            {Object.keys(ev.order_context || {}).length > 0 && (
              <div className="bg-white rounded border border-gray-200 p-3">
                <p className="text-xs font-semibold text-gray-400 mb-2 uppercase tracking-wider">Order</p>
                {Object.entries(ev.order_context).map(([k, v]) => (
                  <div key={k} className="text-xs flex justify-between gap-2">
                    <span className="text-gray-400">{k}</span>
                    {k === 'order_id' ? (
                      <Link to={`/orders/${v}`} className="text-blue-600 hover:underline font-mono text-xs">{String(v).slice(0, 8)}…</Link>
                    ) : (
                      <span className="text-gray-700 font-mono truncate">{String(v)}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
          {ev.stack_trace && (
            <div>
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Stack Trace</p>
              <pre className="text-xs bg-gray-900 text-gray-100 p-3 rounded overflow-x-auto max-h-56 leading-relaxed">
                {ev.stack_trace}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function EventsTab({ filters, onTrace }: { filters: Filters; onTrace: (id: string) => void }) {
  const [page, setPage] = useState(1)
  const params = useMemo(() => buildEventsParams(filters, page), [filters, page])
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['monitoring-events', params],
    queryFn: () => api.get('/monitoring/events', { params }).then(r => r.data),
    refetchInterval: 15_000,
  })

  const events: ErrorEvent[] = data?.items ?? []
  const total: number = data?.total ?? 0

  return (
    <div className="p-4 space-y-2">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm text-gray-500">{total} events</p>
        <button onClick={() => refetch()} className="btn-secondary text-xs py-1 px-2 flex items-center gap-1">
          <RefreshCw className="w-3 h-3" />Refresh
        </button>
      </div>
      {isLoading && <p className="text-sm text-gray-400 text-center py-8">Loading events…</p>}
      {!isLoading && events.length === 0 && (
        <div className="text-center py-16">
          <Activity className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500 text-sm font-medium">No events in this time range</p>
        </div>
      )}
      {events.map(ev => <EventRow key={ev.event_id} ev={ev} onTrace={onTrace} />)}
      {total > 50 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button disabled={page === 1} onClick={() => setPage(p => p - 1)} className="btn-secondary text-xs py-1 px-3">Prev</button>
          <span className="text-xs text-gray-500">Page {page} · {total} total</span>
          <button disabled={events.length < 50} onClick={() => setPage(p => p + 1)} className="btn-secondary text-xs py-1 px-3">Next</button>
        </div>
      )}
    </div>
  )
}

// ─── Metrics tab ──────────────────────────────────────────────────────────────

const SOURCE_COLORS: Record<string, string> = {
  api:                'bg-blue-500',
  sourcing_worker:    'bg-emerald-500',
  fulfillment_worker: 'bg-violet-500',
  carrier_worker:     'bg-sky-500',
  webhook_worker:     'bg-orange-500',
  connector_worker:   'bg-rose-500',
  database:           'bg-gray-500',
}

function MetricsTab({ filters }: { filters: Filters }) {
  const ts = fromTs(filters.hours)

  const { data: rate } = useQuery({
    queryKey: ['monitoring-rate', ts, filters.source],
    queryFn: () => api.get('/monitoring/metrics/rate', {
      params: { from_ts: ts, source_service: filters.source || undefined, bucket_hours: filters.hours <= 4 ? 1 : filters.hours <= 48 ? 4 : 24 },
    }).then(r => r.data),
    refetchInterval: 60_000,
  })

  const { data: top } = useQuery({
    queryKey: ['monitoring-top', ts],
    queryFn: () => api.get('/monitoring/metrics/top', { params: { from_ts: ts, limit: 10 } }).then(r => r.data),
    refetchInterval: 60_000,
  })

  const { data: sources } = useQuery({
    queryKey: ['monitoring-sources', ts],
    queryFn: () => api.get('/monitoring/metrics/sources', { params: { from_ts: ts } }).then(r => r.data),
    refetchInterval: 60_000,
  })

  const rateData: Array<{ bucket: string; count: number }> = rate ?? []
  const topData: Array<{ fingerprint: string; error_type: string; source_service: string; count: number; last_seen: string; error_message: string }> = top ?? []
  const sourcesData: Array<{ source_service: string; count: number; percentage: number }> = sources ?? []
  const maxCount = useMemo(() => Math.max(...rateData.map(r => r.count), 1), [rateData])

  return (
    <div className="p-4 space-y-6">
      <div className="card">
        <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
          <BarChart2 className="w-4 h-4" />Error Rate Over Time
        </h3>
        {rateData.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-8">No data in this period</p>
        ) : (
          <div className="flex items-end gap-1 h-24">
            {rateData.map((bucket, i) => (
              <div key={i} className="flex-1 flex flex-col items-center gap-1 group relative">
                <div
                  className="w-full bg-red-400 rounded-t hover:bg-red-500 transition-colors"
                  style={{ height: `${(bucket.count / maxCount) * 80}px`, minHeight: bucket.count ? '4px' : '0' }}
                />
                <div className="absolute bottom-full mb-1 hidden group-hover:block bg-gray-800 text-white text-xs rounded px-1.5 py-0.5 whitespace-nowrap z-10">
                  {new Date(bucket.bucket).toLocaleString()}<br />{bucket.count} errors
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="card">
          <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
            <List className="w-4 h-4" />Top Errors
          </h3>
          {topData.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-4">No errors in this period</p>
          ) : (
            <div className="space-y-2">
              {topData.map((item, i) => (
                <div key={item.fingerprint} className="flex items-start gap-3">
                  <span className="text-xs font-bold text-gray-300 w-5 flex-shrink-0 pt-0.5">#{i + 1}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-xs font-mono text-gray-600 bg-gray-100 px-1 rounded">{item.error_type}</span>
                      <SourceBadge source={item.source_service} />
                    </div>
                    <p className="text-xs text-gray-500 truncate">{item.error_message}</p>
                  </div>
                  <span className="text-sm font-bold text-red-600 flex-shrink-0">{item.count}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
            <Layers className="w-4 h-4" />By Source
          </h3>
          {sourcesData.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-4">No data in this period</p>
          ) : (
            <div className="space-y-2">
              {sourcesData.map(row => (
                <div key={row.source_service} className="flex items-center gap-2">
                  <span className="text-xs text-gray-600 w-32 flex-shrink-0">{row.source_service.replace('_worker', '')}</span>
                  <div className="flex-1 bg-gray-100 rounded-full h-2">
                    <div
                      className={`h-2 rounded-full ${SOURCE_COLORS[row.source_service] ?? 'bg-gray-400'}`}
                      style={{ width: `${row.percentage}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-500 w-12 text-right">{row.count} ({row.percentage}%)</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Performance tab ──────────────────────────────────────────────────────────

function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  if (seconds < 3600) { const m = Math.floor(seconds / 60); const s = Math.round(seconds % 60); return `${m}m ${s}s` }
  const h = Math.floor(seconds / 3600); const m = Math.round((seconds % 3600) / 60); return `${h}h ${m}m`
}

function fmtBytes(mb: number): string {
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(1)} MB`
}

function StatusDot({ status }: { status: string }) {
  const ok = status === 'ok' || status === 'green'
  const warn = status === 'yellow'
  return <span className={`inline-block w-2 h-2 rounded-full ${ok ? 'bg-green-500' : warn ? 'bg-amber-400' : 'bg-red-500'} flex-shrink-0`} />
}

const QUEUE_COLORS: Record<string, string> = {
  sourcing: '#10b981', fulfillment: '#8b5cf6', carrier: '#0ea5e9',
  notifications: '#f59e0b', webhooks: '#f97316', connectors: '#ef4444',
}

function PerformanceTab({ filters, onRequeue }: { filters: Filters; onRequeue: () => void }) {
  const { data: sys, isLoading: sysLoading, refetch: refetchSys } = useQuery({
    queryKey: ['perf-system'],
    queryFn: () => api.get('/performance/system').then(r => r.data),
    refetchInterval: 30_000,
  })

  const { data: opsHealth } = useQuery({
    queryKey: ['ops-health'],
    queryFn: () => api.get<OpsHealth>('/ops/health').then(r => r.data),
    refetchInterval: 15_000,
  })

  const { data: pipe, isLoading: pipeLoading } = useQuery({
    queryKey: ['perf-pipeline', filters.hours, filters.brandId],
    queryFn: () => api.get('/performance/pipeline', { params: { hours: filters.hours, ...(filters.brandId ? { brand_id: filters.brandId } : {}) } }).then(r => r.data),
    refetchInterval: 60_000,
  })

  const { data: throughput } = useQuery({
    queryKey: ['perf-throughput', filters.hours, filters.brandId],
    queryFn: () => api.get('/performance/throughput', { params: { hours: filters.hours, ...(filters.brandId ? { brand_id: filters.brandId } : {}) } }).then(r => r.data),
    refetchInterval: 60_000,
  })

  const fromTs30d = new Date(Date.now() - 30 * 86_400_000).toISOString().slice(0, 10)
  const { data: returnsHealth } = useQuery({
    queryKey: ['perf-returns', filters.brandId],
    queryFn: () => api.get('/returns/', { params: { from_date: fromTs30d, limit: 1, ...(filters.brandId ? { brand_id: filters.brandId } : {}) } }).then(r => r.data as { total: number; items: Array<{ status: string }> }),
    refetchInterval: 120_000,
  })

  const redis = sys?.redis ?? {}
  const pg = sys?.postgres ?? {}
  const mongo = sys?.mongodb ?? {}
  const es = sys?.elasticsearch ?? {}
  const queueDepths: Record<string, number> = sys?.queue_depths ?? {}
  const funnel = pipe?.funnel ?? {}
  const rates = pipe?.rates ?? {}
  const durations = pipe?.avg_durations_seconds ?? {}

  const throughputData: Array<{ hour: string; created: number; shipped: number; delivered: number }> = throughput ?? []
  const chartData = throughputData.map(d => ({
    ...d,
    label: new Date(d.hour).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
  }))
  const maxQueueDepth = Math.max(...Object.values(queueDepths), 1)

  return (
    <div className="p-4 space-y-6">

      {/* Worker health from Flower */}
      {opsHealth && opsHealth.services.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
              <Zap className="w-4 h-4" />Worker Status
            </h3>
            <button
              onClick={onRequeue}
              className="btn-secondary text-xs flex items-center gap-1"
            >
              <RotateCcw className="w-3 h-3" />Re-queue Stuck Orders
            </button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {opsHealth.services.map(svc => (
              <div key={svc.name} className="bg-white border border-gray-200 rounded-xl p-3 flex items-center gap-3">
                <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${svc.status === 'live' ? 'bg-green-500' : 'bg-red-400'}`} />
                <div>
                  <p className="text-xs font-semibold text-gray-700">{svc.label}</p>
                  <p className="text-xs text-gray-400">{svc.active_tasks} active</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Infrastructure health */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
            <Server className="w-4 h-4" />Infrastructure Health
          </h3>
          <button onClick={() => refetchSys()} className="btn-secondary text-xs py-1 px-2 flex items-center gap-1">
            <RefreshCw className="w-3 h-3" />Refresh
          </button>
        </div>
        {sysLoading ? (
          <p className="text-sm text-gray-400 text-center py-6">Loading system metrics…</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {/* Redis */}
            <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
              <div className="flex items-center gap-2">
                <StatusDot status={redis.status ?? 'error'} />
                <span className="text-sm font-semibold text-gray-700">Redis</span>
                {redis.version && <span className="text-xs text-gray-400">v{redis.version}</span>}
              </div>
              {redis.status === 'ok' ? (
                <dl className="space-y-1">
                  <div className="flex justify-between text-xs"><dt className="text-gray-400">Memory</dt><dd className="font-medium text-gray-700">{fmtBytes(redis.used_memory_mb ?? 0)}</dd></div>
                  <div className="flex justify-between text-xs"><dt className="text-gray-400">Hit rate</dt><dd className="font-medium text-gray-700">{redis.hit_rate_pct}%</dd></div>
                  <div className="flex justify-between text-xs"><dt className="text-gray-400">Ops/sec</dt><dd className="font-medium text-gray-700">{redis.ops_per_second?.toLocaleString()}</dd></div>
                  <div className="flex justify-between text-xs"><dt className="text-gray-400">Connections</dt><dd className="font-medium text-gray-700">{redis.connected_clients}</dd></div>
                </dl>
              ) : <p className="text-xs text-red-500">{redis.error ?? 'Unavailable'}</p>}
            </div>

            {/* PostgreSQL */}
            <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
              <div className="flex items-center gap-2">
                <StatusDot status={pg.status ?? 'error'} />
                <span className="text-sm font-semibold text-gray-700">PostgreSQL</span>
              </div>
              {pg.status === 'ok' ? (
                <dl className="space-y-1">
                  <div className="flex justify-between text-xs"><dt className="text-gray-400">Ping</dt><dd className="font-medium text-gray-700">{pg.query_time_ms}ms</dd></div>
                  {Object.entries(pg.table_counts ?? {}).map(([tbl, cnt]) => (
                    <div key={tbl} className="flex justify-between text-xs">
                      <dt className="text-gray-400">{tbl}</dt>
                      <dd className="font-medium text-gray-700">{(cnt as number).toLocaleString()}</dd>
                    </div>
                  ))}
                </dl>
              ) : <p className="text-xs text-red-500">{pg.error ?? 'Unavailable'}</p>}
            </div>

            {/* MongoDB */}
            <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
              <div className="flex items-center gap-2">
                <StatusDot status={mongo.status ?? 'error'} />
                <span className="text-sm font-semibold text-gray-700">MongoDB</span>
              </div>
              {mongo.status === 'ok' ? (
                <dl className="space-y-1">
                  <div className="flex justify-between text-xs"><dt className="text-gray-400">Ping</dt><dd className="font-medium text-gray-700">{mongo.query_time_ms}ms</dd></div>
                  <div className="flex justify-between text-xs"><dt className="text-gray-400">Order events</dt><dd className="font-medium text-gray-700">{mongo.order_events_count?.toLocaleString()}</dd></div>
                  <div className="flex justify-between text-xs"><dt className="text-gray-400">Error events</dt><dd className="font-medium text-gray-700">{mongo.error_events_count?.toLocaleString()}</dd></div>
                  <div className="flex justify-between text-xs"><dt className="text-gray-400">Open issues</dt><dd className={`font-medium ${(mongo.open_issues ?? 0) > 0 ? 'text-red-600' : 'text-gray-700'}`}>{mongo.open_issues ?? 0}</dd></div>
                </dl>
              ) : <p className="text-xs text-red-500">{mongo.error ?? 'Unavailable'}</p>}
            </div>

            {/* Elasticsearch */}
            <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
              <div className="flex items-center gap-2">
                <StatusDot status={es.status ?? 'error'} />
                <span className="text-sm font-semibold text-gray-700">Elasticsearch</span>
              </div>
              {es.status && es.status !== 'error' && es.status !== 'unavailable' ? (
                <dl className="space-y-1">
                  <div className="flex justify-between text-xs"><dt className="text-gray-400">Cluster</dt><dd className={`font-medium capitalize ${es.status === 'green' ? 'text-green-600' : es.status === 'yellow' ? 'text-amber-600' : 'text-red-600'}`}>{es.status}</dd></div>
                  <div className="flex justify-between text-xs"><dt className="text-gray-400">Shards</dt><dd className="font-medium text-gray-700">{es.active_shards}</dd></div>
                  <div className="flex justify-between text-xs"><dt className="text-gray-400">Orders idx</dt><dd className="font-medium text-gray-700">{es.orders_index_count?.toLocaleString()}</dd></div>
                </dl>
              ) : <p className="text-xs text-gray-400">{es.error ?? es.status ?? 'Unavailable'}</p>}
            </div>
          </div>
        )}
      </div>

      {/* Queue depths */}
      <div className="bg-white border border-gray-200 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
          <Zap className="w-4 h-4" />Worker Queue Depths
          <span className="text-xs text-gray-400 font-normal ml-1">(tasks waiting)</span>
        </h3>
        <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
          {Object.entries(queueDepths).map(([queue, depth]) => (
            <div key={queue} className="text-center">
              <div className="relative h-16 flex items-end justify-center mb-1">
                <div
                  className="w-full rounded-t transition-all"
                  style={{ height: `${Math.max((depth / maxQueueDepth) * 56, depth > 0 ? 4 : 0)}px`, backgroundColor: QUEUE_COLORS[queue] ?? '#6b7280', opacity: depth === 0 ? 0.25 : 1 }}
                />
              </div>
              <p className={`text-lg font-bold ${depth > 10 ? 'text-red-600' : depth > 0 ? 'text-amber-600' : 'text-gray-400'}`}>{depth < 0 ? '?' : depth}</p>
              <p className="text-xs text-gray-400 capitalize">{queue}</p>
            </div>
          ))}
        </div>
        {Object.keys(queueDepths).length === 0 && <p className="text-sm text-gray-400 text-center py-4">Queue data unavailable</p>}
      </div>

      {/* Order pipeline */}
      <div>
        <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
          <GitMerge className="w-4 h-4" />Order Pipeline
          <span className="text-xs text-gray-400 font-normal ml-1">(last {filters.hours >= 168 ? `${Math.round(filters.hours / 24)}d` : `${filters.hours}h`})</span>
        </h3>
        {pipeLoading ? (
          <p className="text-sm text-gray-400 text-center py-4">Loading pipeline metrics…</p>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-3 lg:grid-cols-6 gap-3">
              {[
                { key: 'created', label: 'Created', color: 'text-blue-600', bg: 'bg-blue-50 border-blue-100' },
                { key: 'sourced', label: 'Sourced', color: 'text-emerald-600', bg: 'bg-emerald-50 border-emerald-100' },
                { key: 'shipped', label: 'Shipped', color: 'text-violet-600', bg: 'bg-violet-50 border-violet-100' },
                { key: 'delivered', label: 'Delivered', color: 'text-green-600', bg: 'bg-green-50 border-green-100' },
                { key: 'backordered', label: 'Backordered', color: 'text-amber-600', bg: 'bg-amber-50 border-amber-100' },
                { key: 'cancelled', label: 'Cancelled', color: 'text-red-600', bg: 'bg-red-50 border-red-100' },
              ].map(({ key, label, color, bg }) => (
                <div key={key} className={`border rounded-xl p-4 text-center ${bg}`}>
                  <p className={`text-2xl font-bold ${color}`}>{(funnel as Record<string, number>)[key] ?? 0}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{label}</p>
                </div>
              ))}
            </div>
            {/* Returns card */}
            {returnsHealth && (
              <div className="grid grid-cols-2 gap-3">
                <div className="border border-orange-100 bg-orange-50 rounded-xl p-4 flex items-center justify-between">
                  <div>
                    <p className="text-xs text-gray-500">Returns (30d)</p>
                    <p className="text-2xl font-bold text-orange-600 mt-0.5">{returnsHealth.total ?? 0}</p>
                  </div>
                  <RotateCcw className="w-6 h-6 text-orange-300" />
                </div>
                <div className="border border-orange-100 bg-orange-50 rounded-xl p-4 flex items-center justify-between">
                  <div>
                    <p className="text-xs text-gray-500">Return Rate (30d)</p>
                    <p className={`text-2xl font-bold mt-0.5 ${
                      (funnel as Record<string, number>)['delivered'] > 0 &&
                      (returnsHealth.total / ((funnel as Record<string, number>)['delivered'] || 1)) * 100 > 10
                        ? 'text-red-600' : 'text-orange-600'
                    }`}>
                      {(funnel as Record<string, number>)['delivered'] > 0
                        ? `${((returnsHealth.total / (funnel as Record<string, number>)['delivered']) * 100).toFixed(1)}%`
                        : '—'}
                    </p>
                  </div>
                  <RotateCcw className="w-6 h-6 text-orange-300" />
                </div>
              </div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="bg-white border border-gray-200 rounded-xl p-4">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Success Rates</p>
                <div className="space-y-2.5">
                  {([
                    { label: 'Sourcing Success', key: 'sourcing_success_rate', ok: 90, invert: false },
                    { label: 'Fulfillment Rate', key: 'fulfillment_rate', ok: 90, invert: false },
                    { label: 'Delivery Rate', key: 'delivery_rate', ok: 85, invert: false },
                    { label: 'Backorder Rate', key: 'backorder_rate', ok: 10, invert: true },
                  ] as Array<{ label: string; key: string; ok: number; invert: boolean }>).map(({ label, key, ok, invert }) => {
                    const v: number = (rates as Record<string, number>)[key] ?? 0
                    const good = invert ? v <= ok : v >= ok
                    return (
                      <div key={key}>
                        <div className="flex justify-between text-xs mb-1">
                          <span className="text-gray-500">{label}</span>
                          <span className={`font-semibold ${good ? 'text-green-600' : 'text-red-600'}`}>{v}%</span>
                        </div>
                        <div className="h-1.5 bg-gray-100 rounded-full">
                          <div className={`h-1.5 rounded-full ${good ? 'bg-green-400' : 'bg-red-400'}`} style={{ width: `${Math.min(v, 100)}%` }} />
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
              <div className="bg-white border border-gray-200 rounded-xl p-4">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Avg Stage Duration</p>
                <div className="space-y-3">
                  {([
                    { label: 'Created → Sourced', key: 'created_to_sourced', icon: '⚡', target: 30 },
                    { label: 'Sourced → Shipped', key: 'sourced_to_shipped', icon: '📦', target: 120 },
                    { label: 'Shipped → Delivered', key: 'shipped_to_delivered', icon: '🚚', target: 300 },
                  ] as Array<{ label: string; key: string; icon: string; target: number }>).map(({ label, key, icon, target }) => {
                    const val = (durations as Record<string, number | null>)[key]
                    const n = (pipe?.sample_sizes as Record<string, number> | undefined)?.[key] ?? 0
                    return (
                      <div key={key} className="flex items-center gap-3">
                        <span className="text-lg w-7 flex-shrink-0">{icon}</span>
                        <div className="flex-1">
                          <p className="text-xs text-gray-500">{label}</p>
                          {n > 0 && <p className="text-[10px] text-gray-400">{n} sample{n !== 1 ? 's' : ''}</p>}
                        </div>
                        <span className={`text-base font-bold ${val === null || val === undefined ? 'text-gray-300' : val <= target ? 'text-green-600' : 'text-amber-600'}`}>
                          {fmtDuration(val)}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Throughput chart */}
      <div className="bg-white border border-gray-200 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
          <TrendingUp className="w-4 h-4" />Order Throughput
          <span className="text-xs text-gray-400 font-normal ml-1">({filters.hours <= 48 ? 'hourly' : filters.hours <= 168 ? '4-hour' : 'daily'} buckets)</span>
        </h3>
        {chartData.length === 0 ? (
          <div className="text-center py-10">
            <Box className="w-8 h-8 text-gray-200 mx-auto mb-2" />
            <p className="text-sm text-gray-400">No order events in this period</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#9ca3af' }} interval="preserveStartEnd" tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: '#9ca3af' }} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }} labelStyle={{ fontWeight: 600, color: '#374151' }} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="created" stroke="#3b82f6" strokeWidth={2} dot={false} name="Created" />
              <Line type="monotone" dataKey="shipped" stroke="#8b5cf6" strokeWidth={2} dot={false} name="Shipped" />
              <Line type="monotone" dataKey="delivered" stroke="#10b981" strokeWidth={2} dot={false} name="Delivered" />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

// ─── Live Logs tab ────────────────────────────────────────────────────────────

const LOG_LEVEL_COLOR: Record<string, string> = {
  DEBUG: 'text-gray-400', INFO: 'text-blue-400', WARN: 'text-yellow-400',
  WARNING: 'text-yellow-400', ERROR: 'text-red-400', CRITICAL: 'text-red-300',
}

function LiveLogsTab({ onTrace, onAnalyze }: {
  onTrace: (id: string) => void
  onAnalyze: (fp?: string, oid?: string) => void
}) {
  const [service, setService] = useState('')
  const [level, setLevel] = useState('WARN')
  const [search, setSearch] = useState('')
  const [sinceMinutes, setSinceMinutes] = useState(30)
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['ops-logs', service, level, search, sinceMinutes],
    queryFn: () => api.get<{ items: LogLine[]; total: number }>('/ops/logs', {
      params: { service: service || undefined, level: level || undefined, search: search || undefined, since_minutes: sinceMinutes, tail: 300 },
    }).then(r => r.data),
    refetchInterval: 10_000,
  })

  const lines = data?.items ?? []

  return (
    <div className="p-4 space-y-3">
      <div className="flex flex-wrap gap-2 items-center">
        <select className="select text-sm" value={service} onChange={e => setService(e.target.value)}>
          <option value="">All services</option>
          {DOCKER_SERVICES.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="select text-sm" value={level} onChange={e => setLevel(e.target.value)}>
          <option value="">All levels</option>
          <option value="DEBUG">DEBUG+</option>
          <option value="INFO">INFO+</option>
          <option value="WARN">WARN+</option>
          <option value="ERROR">ERROR only</option>
        </select>
        <select className="select text-sm" value={sinceMinutes} onChange={e => setSinceMinutes(Number(e.target.value))}>
          <option value={15}>Last 15 min</option>
          <option value={30}>Last 30 min</option>
          <option value={60}>Last 1 hour</option>
          <option value={360}>Last 6 hours</option>
        </select>
        <div className="relative flex-1 min-w-[180px]">
          <Search className="absolute left-2 top-2 w-4 h-4 text-gray-400" />
          <input className="input pl-8 text-sm w-full" placeholder="Keyword or order ID…" value={search} onChange={e => setSearch(e.target.value)} />
        </div>
        <button onClick={() => refetch()} className="btn-secondary text-xs flex items-center gap-1">
          <RefreshCw className="w-3 h-3" /> Refresh
        </button>
        <span className="text-xs text-gray-400">{data?.total ?? 0} lines</span>
      </div>

      <div className="font-mono text-xs bg-gray-950 rounded-lg overflow-hidden">
        {isLoading && <div className="p-4 text-gray-400">Loading logs…</div>}
        {!isLoading && lines.length === 0 && <div className="p-4 text-gray-400">No log lines matching filters</div>}
        {lines.map((line, i) => (
          <div key={i} className={`border-b border-gray-800 ${['ERROR','CRITICAL'].includes((line.level||'').toUpperCase()) ? 'bg-red-950/20' : ''}`}>
            <div
              className="flex items-start gap-2 px-3 py-1.5 cursor-pointer hover:bg-gray-900"
              onClick={() => setExpandedIdx(expandedIdx === i ? null : i)}
            >
              <span className="text-gray-500 w-16 shrink-0">{fmtTs(line.ts)}</span>
              <span className={`w-14 shrink-0 ${LOG_LEVEL_COLOR[(line.level||'INFO').toUpperCase()] || 'text-gray-300'}`}>
                {(line.level||'INFO').toUpperCase()}
              </span>
              <span className="text-purple-400 w-24 shrink-0 truncate">{line.container}</span>
              <span className="text-gray-200 flex-1 truncate">{line.msg}</span>
              <div className="flex gap-2 shrink-0 items-center">
                {line.order_id && (
                  <button onClick={e => { e.stopPropagation(); onTrace(line.order_id!) }} className="text-blue-400 hover:text-blue-300 text-xs">trace</button>
                )}
                {line.fingerprint && (
                  <button onClick={e => { e.stopPropagation(); onAnalyze(line.fingerprint, line.order_id) }} className="text-green-400 hover:text-green-300 text-xs">analyze</button>
                )}
              </div>
            </div>
            {expandedIdx === i && (
              <div className="px-3 pb-3 bg-gray-900 space-y-2 border-l-2 border-red-500/40">
                {/* Full message */}
                <div className="pt-2">
                  <p className="text-gray-500 text-[10px] uppercase tracking-wider mb-1">Message</p>
                  <p className="text-gray-200 text-xs break-all">{line.msg}</p>
                </div>
                {/* Meta row */}
                <div className="flex flex-wrap gap-3 text-[10px]">
                  {line.order_id && <span className="text-blue-400">order: {line.order_id}</span>}
                  {line.fingerprint && <span className="text-yellow-400">fp: {line.fingerprint}</span>}
                  {line.container && <span className="text-purple-400">service: {line.container}</span>}
                  <span className="text-gray-500">{line.ts}</span>
                </div>
                {/* Stack trace */}
                {line.exc && (
                  <div>
                    <p className="text-gray-500 text-[10px] uppercase tracking-wider mb-1">Stack Trace</p>
                    <pre className="text-red-300 text-xs whitespace-pre-wrap bg-gray-950 rounded p-2 overflow-auto max-h-48">{line.exc}</pre>
                  </div>
                )}
                {/* Raw JSON */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-gray-500 text-[10px] uppercase tracking-wider">Raw Log</p>
                    <button onClick={() => navigator.clipboard.writeText(line.raw || '')} className="text-gray-500 hover:text-gray-300 flex items-center gap-1 text-[10px]">
                      <Copy className="w-3 h-3" />Copy
                    </button>
                  </div>
                  <pre className="text-gray-400 text-xs whitespace-pre-wrap bg-gray-950 rounded p-2 overflow-auto max-h-48">
                    {(() => { try { return JSON.stringify(JSON.parse(line.raw || '{}'), null, 2) } catch { return line.raw } })()}
                  </pre>
                </div>
                {/* Action buttons */}
                <div className="flex gap-2 pt-1">
                  {line.order_id && (
                    <button onClick={() => onTrace(line.order_id!)} className="text-xs px-2 py-1 rounded bg-blue-900/40 text-blue-300 hover:bg-blue-900/60 flex items-center gap-1">
                      <ArrowRight className="w-3 h-3" />Trace Order
                    </button>
                  )}
                  {line.fingerprint && (
                    <button onClick={() => onAnalyze(line.fingerprint, line.order_id)} className="text-xs px-2 py-1 rounded bg-green-900/40 text-green-300 hover:bg-green-900/60 flex items-center gap-1">
                      <Bot className="w-3 h-3" />Analyze with KubeAI
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Order Trace tab ──────────────────────────────────────────────────────────

function OrderTraceTab({ initialOrderId, onAnalyze }: {
  initialOrderId?: string
  onAnalyze: (fp?: string, oid?: string, q?: string) => void
}) {
  const [orderId, setOrderId] = useState(initialOrderId || '')
  const [activeId, setActiveId] = useState(initialOrderId || '')
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  useEffect(() => {
    if (initialOrderId) { setOrderId(initialOrderId); setActiveId(initialOrderId) }
  }, [initialOrderId])

  const { data, isLoading, error } = useQuery({
    queryKey: ['ops-trace', activeId],
    queryFn: () => api.get<TraceData>(`/ops/trace/${activeId}`).then(r => r.data),
    enabled: !!activeId,
  })

  return (
    <div className="p-4 space-y-4">
      <div className="flex gap-2">
        <input
          className="input flex-1"
          placeholder="Enter Order ID or UUID…"
          value={orderId}
          onChange={e => setOrderId(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && orderId.trim() && setActiveId(orderId.trim())}
        />
        <button onClick={() => orderId.trim() && setActiveId(orderId.trim())} className="btn-primary flex items-center gap-2">
          <Search className="w-4 h-4" /> Trace
        </button>
      </div>

      {!activeId && (
        <div className="text-center py-16 text-gray-400">
          <GitBranch className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p>Enter an order ID to see its full lifecycle trace</p>
        </div>
      )}

      {isLoading && <div className="p-8 text-center text-gray-500">Loading trace…</div>}
      {error && <div className="p-4 bg-red-50 border border-red-200 rounded text-red-700 text-sm">Order not found or no events recorded</div>}

      {data && (
        <div className="space-y-4">
          <div className="card p-4 flex items-center justify-between">
            <div>
              <p className="text-xs text-gray-500 font-mono">{data.order_id}</p>
              <div className="flex items-center gap-3 mt-1">
                <span className={`text-sm font-semibold px-2 py-0.5 rounded ${data.last_error ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'}`}>
                  {data.last_status || 'Unknown'}
                </span>
                <span className="text-xs text-gray-500">{data.audit_count} audit events · {data.error_count} errors</span>
              </div>
            </div>
            <button
              onClick={() => onAnalyze(undefined, data.order_id, `Why is order ${data.order_id} stuck in ${data.last_status} state?`)}
              className="btn-secondary text-xs flex items-center gap-1"
            >
              <Bot className="w-3 h-3" /> Analyze with KubeAI
            </button>
          </div>

          <div className="card p-0 overflow-hidden">
            <div className="px-4 py-3 bg-gray-50 border-b">
              <h3 className="text-sm font-semibold text-gray-700">Event Timeline</h3>
            </div>
            {data.timeline.length === 0
              ? <p className="p-4 text-sm text-gray-400">No events recorded for this order</p>
              : (
                <div className="divide-y">
                  {data.timeline.map((ev, i) => (
                    <div key={i}>
                      <div
                        className={`flex items-start gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50 ${!ev.ok ? 'bg-red-50' : ''}`}
                        onClick={() => setExpandedIdx(expandedIdx === i ? null : i)}
                      >
                        <div className="mt-0.5 shrink-0">
                          {ev.ok ? <CheckCircle className="w-4 h-4 text-green-500" /> : <XCircle className="w-4 h-4 text-red-500" />}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-xs font-mono text-gray-400">{fmtTs(ev.ts)}</span>
                            <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${ev.ok ? 'bg-blue-100 text-blue-700' : 'bg-red-100 text-red-700'}`}>
                              {ev.event_type}
                            </span>
                            {ev.status && <span className="text-xs text-gray-500">→ <span className="font-medium text-gray-700">{ev.status}</span></span>}
                            <span className="text-xs text-gray-400">via {ev.worker}</span>
                          </div>
                          {!ev.ok && ev.message && <p className="text-xs text-red-700 mt-0.5 truncate">{ev.message}</p>}
                        </div>
                        <ChevronDown className={`w-4 h-4 text-gray-400 shrink-0 transition-transform ${expandedIdx === i ? '' : '-rotate-90'}`} />
                      </div>
                      {expandedIdx === i && (
                        <div className="px-4 pb-3 bg-gray-50 border-t">
                          {ev.stack_trace && (
                            <pre className="text-red-300 text-xs bg-red-950 rounded p-2 mb-2 whitespace-pre-wrap overflow-auto max-h-48">{ev.stack_trace}</pre>
                          )}
                          <pre className="text-xs text-gray-600 whitespace-pre-wrap overflow-auto max-h-48">{JSON.stringify(ev.data, null, 2)}</pre>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )
            }
          </div>
        </div>
      )}
    </div>
  )
}

// ─── AI Analyzer tab ──────────────────────────────────────────────────────────

function AIAnalyzerTab({ initialCtx }: { initialCtx?: { fp?: string; oid?: string; q?: string } }) {
  const [orderId, setOrderId] = useState(initialCtx?.oid || '')
  const [fingerprint, setFingerprint] = useState(initialCtx?.fp || '')
  const [question, setQuestion] = useState(initialCtx?.q || '')
  const [contextMinutes, setContextMinutes] = useState(60)
  const [messages, setMessages] = useState<Array<{ role: 'user' | 'assistant'; content: string }>>([])
  const [streaming, setStreaming] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (initialCtx && (initialCtx.oid || initialCtx.fp || initialCtx.q)) {
      setOrderId(initialCtx.oid || '')
      setFingerprint(initialCtx.fp || '')
      setQuestion(initialCtx.q || '')
    }
  }, [initialCtx])

  useEffect(() => { scrollRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, streaming])

  const analyze = useCallback(async () => {
    if (streaming) return
    const userMsg = question || 'What went wrong? Identify the root cause and suggest a fix.'
    setMessages(prev => [...prev, { role: 'user', content: userMsg }])
    setQuestion('')
    setStreaming(true)
    let assistantMsg = ''
    setMessages(prev => [...prev, { role: 'assistant', content: '' }])

    try {
      const apiBase = (api.defaults.baseURL || '').replace(/\/$/, '')
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      const envId = localStorage.getItem('oms_environment_id')
      if (envId) headers['X-OMS-Environment'] = envId

      const resp = await fetch(`${apiBase}/ops/analyze`, {
        method: 'POST',
        credentials: 'include',
        headers,
        body: JSON.stringify({ order_id: orderId || undefined, fingerprint: fingerprint || undefined, question: userMsg, context_minutes: contextMinutes }),
      })

      const reader = resp.body?.getReader()
      const decoder = new TextDecoder()
      if (!reader) throw new Error('No response stream')

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        for (const line of decoder.decode(value, { stream: true }).split('\n')) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (raw === '[DONE]') break
          try {
            const obj = JSON.parse(raw)
            if (obj.type === 'text') {
              assistantMsg += obj.text
              setMessages(prev => { const u = [...prev]; u[u.length - 1] = { role: 'assistant', content: assistantMsg }; return u })
            }
          } catch { /* skip */ }
        }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setMessages(prev => { const u = [...prev]; u[u.length - 1] = { role: 'assistant', content: `Error: ${msg}` }; return u })
    } finally {
      setStreaming(false)
    }
  }, [streaming, question, orderId, fingerprint, contextMinutes])

  return (
    <div className="p-4 flex flex-col" style={{ minHeight: '600px' }}>
      <div className="card p-3 mb-4">
        <p className="text-xs font-semibold text-gray-600 mb-2">Analysis Context</p>
        <div className="flex flex-wrap gap-2">
          <input className="input text-sm flex-1 min-w-[180px]" placeholder="Order ID (optional)" value={orderId} onChange={e => setOrderId(e.target.value)} />
          <input className="input text-sm flex-1 min-w-[180px]" placeholder="Error fingerprint (optional)" value={fingerprint} onChange={e => setFingerprint(e.target.value)} />
          <select className="select text-sm" value={contextMinutes} onChange={e => setContextMinutes(Number(e.target.value))}>
            <option value={30}>30 min context</option>
            <option value={60}>1 hour context</option>
            <option value={360}>6 hour context</option>
          </select>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto space-y-4 mb-4 min-h-[300px]">
        {messages.length === 0 && (
          <div className="text-center py-16 text-gray-400">
            <Bot className="w-16 h-16 mx-auto mb-3 opacity-20" />
            <p className="text-lg font-medium text-gray-500">KubeAI SRE Assistant</p>
            <p className="text-sm mt-1">Ask about errors, stuck orders, or system health</p>
            <div className="flex flex-wrap justify-center gap-2 mt-4">
              {[
                'What went wrong in the last hour?',
                'Why are orders stuck in CONFIRMED?',
                'Which service has the most errors?',
                'What is the current return rate and why are returns high?',
                'Show open RMAs and which brands have the most returns',
                'Are there brand-specific sourcing failures in the last 24h?',
              ].map(q => (
                <button key={q} onClick={() => setQuestion(q)} className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-600 px-3 py-1.5 rounded-full">{q}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-3xl rounded-xl px-4 py-3 ${msg.role === 'user' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-800'}`}>
              {msg.role === 'assistant' && (
                <div className="flex items-center gap-1.5 mb-2">
                  <Bot className="w-3.5 h-3.5 text-blue-600" />
                  <span className="text-xs font-semibold text-blue-600">KubeAI</span>
                </div>
              )}
              <div className="text-sm whitespace-pre-wrap">
                {msg.content || (streaming && i === messages.length - 1
                  ? <span className="inline-block w-2 h-4 bg-gray-400 animate-pulse" />
                  : null)}
              </div>
              {msg.role === 'assistant' && msg.content && (
                <button onClick={() => navigator.clipboard.writeText(msg.content)} className="mt-2 text-gray-400 hover:text-gray-600"><Copy className="w-3 h-3" /></button>
              )}
            </div>
          </div>
        ))}
        <div ref={scrollRef} />
      </div>

      <div className="flex gap-2">
        <input
          className="input flex-1"
          placeholder="Ask KubeAI about your system… (Enter to send)"
          value={question}
          onChange={e => setQuestion(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !streaming && analyze()}
          disabled={streaming}
        />
        <button onClick={analyze} disabled={streaming} className="btn-primary flex items-center gap-2">
          {streaming ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          {streaming ? 'Analyzing…' : 'Send'}
        </button>
      </div>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Monitoring() {
  const [tab, setTab] = useState<TabId>('issues')
  const [filters, setFilters] = useState<Filters>({
    hours: 24, level: '', source: '', errType: '', orderId: '', issueStatus: 'open', brandId: '',
  })
  const [traceOrderId, setTraceOrderId] = useState<string | undefined>()
  const [analyzerCtx, setAnalyzerCtx] = useState<{ fp?: string; oid?: string; q?: string } | undefined>()

  const { data: brandsData } = useQuery({
    queryKey: ['brands', 'active'],
    queryFn: () => getBrands({ is_active: true }),
  })
  const brands: Brand[] = brandsData ?? []

  const { data: summary } = useQuery<Summary>({
    queryKey: ['monitoring-summary'],
    queryFn: () => api.get('/monitoring/summary').then(r => r.data),
    refetchInterval: 30_000,
  })

  const requeueMutation = useMutation({
    mutationFn: () => api.post('/ops/requeue-stuck').then(r => r.data),
  })

  const handleTrace = (id: string) => {
    setTraceOrderId(id)
    setTab('trace')
  }

  const handleAnalyze = (fp?: string, oid?: string, q?: string) => {
    setAnalyzerCtx({ fp, oid, q })
    setTab('analyzer')
  }

  const patchFilters = (patch: Partial<Filters>) => setFilters(f => ({ ...f, ...patch }))

  const TABS = [
    { id: 'issues' as TabId,     label: 'Issues',       icon: AlertTriangle },
    { id: 'events' as TabId,     label: 'Events',       icon: Activity },
    { id: 'metrics' as TabId,    label: 'Metrics',      icon: BarChart2 },
    { id: 'performance' as TabId,label: 'Performance',  icon: Server },
    { id: 'live_logs' as TabId,  label: 'Live Logs',    icon: Terminal },
    { id: 'trace' as TabId,      label: 'Order Trace',  icon: GitBranch },
    { id: 'analyzer' as TabId,   label: 'AI Analyzer',  icon: Bot },
  ]

  const showFilterBar = FILTER_TABS.includes(tab)

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Monitoring &amp; TechOps</h1>
          <p className="text-sm text-gray-500 mt-0.5">Error traceability, live logs, order traces, and AI root cause analysis</p>
        </div>
        {summary && (
          <div className="flex items-center gap-4">
            <div className="text-center">
              <p className="text-xl font-bold text-red-600">{summary.errors_last_1h}</p>
              <p className="text-xs text-gray-400">errors / 1h</p>
            </div>
            <div className="text-center">
              <p className="text-xl font-bold text-orange-500">{summary.errors_last_24h}</p>
              <p className="text-xs text-gray-400">errors / 24h</p>
            </div>
            <div className="text-center">
              <p className="text-xl font-bold text-amber-600">{summary.warnings_last_24h}</p>
              <p className="text-xs text-gray-400">warnings / 24h</p>
            </div>
            <div className="text-center">
              <p className="text-xl font-bold text-gray-700">{summary.open_issues}</p>
              <p className="text-xs text-gray-400">open issues</p>
            </div>
          </div>
        )}
      </div>

      {/* Tab bar */}
      <div className="border-b border-gray-200 overflow-x-auto">
        <nav className="flex gap-0 min-w-max">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                tab === id ? 'border-blue-600 text-blue-700' : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              <Icon className="w-4 h-4" />{label}
            </button>
          ))}
        </nav>
      </div>

      {/* Content */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {showFilterBar && <FilterBar filters={filters} onChange={patchFilters} tab={tab} brands={brands} />}
        {tab === 'issues'      && <IssuesTab filters={filters} />}
        {tab === 'events'      && <EventsTab filters={filters} onTrace={handleTrace} />}
        {tab === 'metrics'     && <MetricsTab filters={filters} />}
        {tab === 'performance' && <PerformanceTab filters={filters} onRequeue={() => requeueMutation.mutate()} />}
        {tab === 'live_logs'   && <LiveLogsTab onTrace={handleTrace} onAnalyze={handleAnalyze} />}
        {tab === 'trace'       && <OrderTraceTab initialOrderId={traceOrderId} onAnalyze={handleAnalyze} />}
        {tab === 'analyzer'    && <AIAnalyzerTab initialCtx={analyzerCtx} />}
      </div>

      {requeueMutation.isSuccess && (
        <div className="fixed bottom-4 right-4 bg-green-600 text-white text-sm px-4 py-2 rounded-lg shadow-lg">
          Re-queued stuck orders across {(requeueMutation.data as { triggered: number })?.triggered ?? 0} environment(s)
        </div>
      )}
    </div>
  )
}
