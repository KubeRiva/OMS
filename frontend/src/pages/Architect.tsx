import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Brain, ChevronDown, ChevronUp, CheckCircle, XCircle, PlayCircle,
  RotateCcw, GitBranch, BarChart2, Zap, AlertCircle, TrendingUp,
  Clock, Package, Layers, FlaskConical, PauseCircle,
} from 'lucide-react'
import api, { getBrands, type Brand } from '../api/client'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Proposal {
  id: string
  proposal_type: string
  title: string
  description: string | null
  rationale: string | null
  confidence_score: number
  status: string
  generated_by: string | null
  approved_by: string | null
  applied_at: string | null
  rejection_reason: string | null
  proposal_data: Record<string, unknown> | null
  rollback_data: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

interface NodePerf {
  node_id: string
  node_name: string
  period_days: number
  orders_fulfilled: number
  avg_outcome_score: number
  avg_delivery_hours: number
  avg_cost_actual: number
  backorder_rate_pct: number
  return_rate_pct: number
  computed_at: string
}

interface Pattern {
  cluster_key: string
  channel: string
  region: string
  amount_bucket: string
  fulfillment_type: string
  sample_count: number
  best_node_id: string | null
  computed_at: string
  node_performance: Array<{
    node_id: string
    node_name: string
    avg_outcome_score: number
    avg_delivery_hours: number
    avg_cost: number
    selection_count: number
  }>
}

interface AIPerformance {
  total_outcomes: number
  labeled_outcomes: number
  unlabeled_outcomes: number
  ai_improvement_pct: number | null
  by_strategy: Array<{
    strategy: string
    count: number
    avg_outcome_score: number
    avg_delivery_hours: number
    backorder_rate_pct: number
  }>
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  pending:     'bg-yellow-100 text-yellow-800',
  approved:    'bg-blue-100 text-blue-800',
  rejected:    'bg-red-100 text-red-800',
  applied:     'bg-emerald-100 text-emerald-800',
  rolled_back: 'bg-gray-100 text-gray-600',
}

const TYPE_STYLES: Record<string, string> = {
  sourcing_rule:     'bg-violet-100 text-violet-800',
  custom_attribute:  'bg-cyan-100 text-cyan-800',
  ui_widget:         'bg-orange-100 text-orange-800',
  schema_migration:  'bg-pink-100 text-pink-800',
  sourcing_experiment: 'bg-indigo-100 text-indigo-800',
  config_change:     'bg-gray-100 text-gray-700',
}

function ConfidenceBar({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color = pct >= 70 ? 'bg-emerald-400' : pct >= 40 ? 'bg-yellow-400' : 'bg-red-400'
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-1.5 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-gray-600">{pct}%</span>
    </div>
  )
}

function ScoreBar({ score, max = 1 }: { score: number; max?: number }) {
  const pct = Math.min(100, Math.round((score / max) * 100))
  const color = pct >= 70 ? 'bg-emerald-400' : pct >= 40 ? 'bg-yellow-400' : 'bg-red-400'
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-gray-600">{score.toFixed(3)}</span>
    </div>
  )
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

// ─── Proposals Tab ────────────────────────────────────────────────────────────

const STATUS_FILTERS = ['all', 'pending', 'approved', 'rejected', 'applied', 'rolled_back'] as const

function ProposalsTab() {
  const qc = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [rejectId, setRejectId] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)

  const { data: proposals = [], isLoading } = useQuery<Proposal[]>({
    queryKey: ['architect:proposals', statusFilter],
    queryFn: () =>
      api.get('/architect/proposals', {
        params: statusFilter !== 'all' ? { status: statusFilter } : {},
      }).then(r => r.data),
    refetchInterval: 15000,
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['architect:proposals'] })

  const approveMutation = useMutation({
    mutationFn: (id: string) => api.post(`/architect/proposals/${id}/approve`).then(r => r.data),
    onSuccess: () => { setActionError(null); invalidate() },
    onError: (e: unknown) => setActionError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Approve failed'),
  })

  const rejectMutation = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      api.post(`/architect/proposals/${id}/reject`, { reason }).then(r => r.data),
    onSuccess: () => { setActionError(null); setRejectId(null); setRejectReason(''); invalidate() },
    onError: (e: unknown) => setActionError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Reject failed'),
  })

  const applyMutation = useMutation({
    mutationFn: (id: string) => api.post(`/architect/proposals/${id}/apply`).then(r => r.data),
    onSuccess: () => { setActionError(null); invalidate() },
    onError: (e: unknown) => setActionError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Apply failed'),
  })

  const rollbackMutation = useMutation({
    mutationFn: (id: string) => api.post(`/architect/proposals/${id}/rollback`).then(r => r.data),
    onSuccess: () => { setActionError(null); invalidate() },
    onError: (e: unknown) => setActionError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Rollback failed'),
  })

  return (
    <div className="space-y-4">
      {/* Status filter */}
      <div className="flex flex-wrap gap-2">
        {STATUS_FILTERS.map(s => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`px-3 py-1 rounded-full text-xs font-semibold capitalize transition-colors ${
              statusFilter === s
                ? 'bg-indigo-600 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {s === 'rolled_back' ? 'Rolled back' : s}
          </button>
        ))}
      </div>

      {actionError && (
        <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {actionError}
          <button className="ml-auto text-red-400 hover:text-red-600" onClick={() => setActionError(null)}>✕</button>
        </div>
      )}

      {isLoading ? (
        <div className="text-center py-12 text-gray-400 text-sm">Loading proposals...</div>
      ) : proposals.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <Brain className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm font-medium">No proposals yet</p>
          <p className="text-xs mt-1 text-gray-300">
            Proposals are auto-generated nightly by the Pattern Discovery pipeline once enough outcome data accumulates.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {proposals.map(p => (
            <div key={p.id} className="card overflow-hidden">
              {/* Header row */}
              <button
                className="w-full px-4 py-3 flex items-start gap-3 hover:bg-gray-50 transition-colors text-left"
                onClick={() => setExpandedId(expandedId === p.id ? null : p.id)}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2 mb-1">
                    <span className={`text-[10px] font-semibold rounded px-1.5 py-0.5 capitalize ${TYPE_STYLES[p.proposal_type] || 'bg-gray-100 text-gray-600'}`}>
                      {p.proposal_type.replace(/_/g, ' ')}
                    </span>
                    <span className={`text-[10px] font-semibold rounded-full px-2 py-0.5 capitalize ${STATUS_STYLES[p.status] || 'bg-gray-100 text-gray-600'}`}>
                      {p.status.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <p className="text-sm font-semibold text-gray-800 leading-snug">{p.title}</p>
                  <p className="text-xs text-gray-400 mt-0.5 line-clamp-1">{p.description}</p>
                </div>
                <div className="flex-shrink-0 flex flex-col items-end gap-1.5">
                  <ConfidenceBar score={p.confidence_score} />
                  <p className="text-[10px] text-gray-400">{formatDate(p.created_at)}</p>
                </div>
                {expandedId === p.id
                  ? <ChevronUp className="w-4 h-4 text-gray-400 mt-1 flex-shrink-0" />
                  : <ChevronDown className="w-4 h-4 text-gray-400 mt-1 flex-shrink-0" />
                }
              </button>

              {/* Expanded detail */}
              {expandedId === p.id && (
                <div className="border-t border-gray-100 px-4 py-4 space-y-4 bg-gray-50">
                  {/* Rationale */}
                  {p.rationale && (
                    <div>
                      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Evidence & Rationale</p>
                      <pre className="text-xs text-gray-700 whitespace-pre-wrap font-sans bg-white border border-gray-200 rounded-lg p-3 leading-relaxed">
                        {p.rationale}
                      </pre>
                    </div>
                  )}

                  {/* Proposed change */}
                  {p.proposal_data && (
                    <div>
                      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Proposed Change</p>
                      <div className="bg-white border border-gray-200 rounded-lg p-3 space-y-1.5">
                        {p.proposal_type === 'sourcing_rule' && (() => {
                          const d = p.proposal_data as Record<string, unknown>
                          return (
                            <>
                              <div className="flex flex-wrap gap-2 text-xs">
                                <span className="font-semibold text-gray-700">Name:</span>
                                <span className="font-mono text-indigo-700">{String(d.name ?? '—')}</span>
                              </div>
                              <div className="flex flex-wrap gap-2 text-xs">
                                <span className="font-semibold text-gray-700">Strategy:</span>
                                <span className="font-mono bg-violet-100 text-violet-800 rounded px-1.5 py-0.5">{String(d.strategy ?? '—')}</span>
                                <span className="text-gray-400">·</span>
                                <span className="font-semibold text-gray-700">Priority:</span>
                                <span className="font-mono">{String(d.priority ?? '—')}</span>
                                <span className="text-gray-400">·</span>
                                <span className="font-semibold text-gray-700">Max split:</span>
                                <span className="font-mono">{String(d.max_split_nodes ?? '—')}</span>
                              </div>
                              {d.brand_id != null && (
                                <div className="flex flex-wrap gap-2 text-xs">
                                  <span className="font-semibold text-gray-700">Brand ID:</span>
                                  <span className="font-mono bg-blue-50 text-blue-700 border border-blue-200 rounded px-1.5 py-0.5">{String(d.brand_id)}</span>
                                </div>
                              )}
                              {Array.isArray(d.conditions) && d.conditions.length > 0 && (
                                <div>
                                  <p className="text-xs text-gray-500 mb-1">Conditions:</p>
                                  <div className="flex flex-wrap gap-1">
                                    {(d.conditions as Array<Record<string, unknown>>).map((c, i) => (
                                      <span key={i} className="text-[10px] font-mono bg-gray-100 text-gray-700 rounded px-2 py-0.5">
                                        {String(c.field)} {String(c.operator)} {JSON.stringify(c.value)}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}
                              <p className="text-[10px] text-amber-700 bg-amber-50 rounded px-2 py-1">
                                Rule will be created as <strong>inactive</strong>. Enable it manually in Sourcing Rules after reviewing.
                              </p>
                            </>
                          )
                        })()}
                        {p.proposal_type !== 'sourcing_rule' && (
                          <pre className="text-xs font-mono text-gray-700 whitespace-pre-wrap overflow-x-auto">
                            {JSON.stringify(p.proposal_data, null, 2)}
                          </pre>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Rejection reason */}
                  {p.rejection_reason && (
                    <div className="flex items-start gap-2 p-2.5 bg-red-50 rounded-lg border border-red-100">
                      <XCircle className="w-4 h-4 text-red-400 mt-0.5 flex-shrink-0" />
                      <div>
                        <p className="text-xs font-semibold text-red-700">Rejection reason</p>
                        <p className="text-xs text-red-600 mt-0.5">{p.rejection_reason}</p>
                      </div>
                    </div>
                  )}

                  {/* Rollback info */}
                  {p.rollback_data && (
                    <div className="flex items-start gap-2 p-2.5 bg-gray-100 rounded-lg border border-gray-200">
                      <RotateCcw className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" />
                      <p className="text-xs text-gray-600">
                        Applied at {p.applied_at ? formatDate(p.applied_at) : '—'} · approved by {p.approved_by || '—'}
                      </p>
                    </div>
                  )}

                  {/* Reject inline form */}
                  {rejectId === p.id && (
                    <div className="space-y-2">
                      <input
                        className="input w-full text-sm"
                        placeholder="Reason for rejection..."
                        value={rejectReason}
                        onChange={e => setRejectReason(e.target.value)}
                        autoFocus
                      />
                      <div className="flex gap-2">
                        <button
                          className="btn-danger text-xs px-3 py-1.5"
                          disabled={!rejectReason.trim() || rejectMutation.isPending}
                          onClick={() => rejectMutation.mutate({ id: p.id, reason: rejectReason })}
                        >
                          Confirm Reject
                        </button>
                        <button
                          className="btn-secondary text-xs px-3 py-1.5"
                          onClick={() => { setRejectId(null); setRejectReason('') }}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Action buttons */}
                  <div className="flex flex-wrap gap-2 pt-1">
                    {p.status === 'pending' && (
                      <>
                        <button
                          className="btn-primary text-xs px-3 py-1.5 flex items-center gap-1.5"
                          disabled={approveMutation.isPending}
                          onClick={() => approveMutation.mutate(p.id)}
                        >
                          <CheckCircle className="w-3.5 h-3.5" /> Approve
                        </button>
                        <button
                          className="btn-danger text-xs px-3 py-1.5 flex items-center gap-1.5"
                          onClick={() => { setRejectId(p.id); setRejectReason('') }}
                        >
                          <XCircle className="w-3.5 h-3.5" /> Reject
                        </button>
                      </>
                    )}
                    {p.status === 'approved' && (
                      <>
                        <button
                          className="btn-primary text-xs px-3 py-1.5 flex items-center gap-1.5"
                          disabled={applyMutation.isPending}
                          onClick={() => applyMutation.mutate(p.id)}
                        >
                          <PlayCircle className="w-3.5 h-3.5" /> Apply
                        </button>
                        <button
                          className="btn-danger text-xs px-3 py-1.5 flex items-center gap-1.5"
                          onClick={() => { setRejectId(p.id); setRejectReason('') }}
                        >
                          <XCircle className="w-3.5 h-3.5" /> Reject
                        </button>
                      </>
                    )}
                    {p.status === 'applied' && (
                      <button
                        className="btn-secondary text-xs px-3 py-1.5 flex items-center gap-1.5"
                        disabled={rollbackMutation.isPending}
                        onClick={() => rollbackMutation.mutate(p.id)}
                      >
                        <RotateCcw className="w-3.5 h-3.5" /> Rollback
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Patterns Tab ─────────────────────────────────────────────────────────────

function PatternsTab() {
  const [brandFilter, setBrandFilter] = useState('')

  const { data: brands = [] } = useQuery<Brand[]>({
    queryKey: ['brands'],
    queryFn: () => getBrands(),
  })

  const { data: patterns = [], isLoading } = useQuery<Pattern[]>({
    queryKey: ['architect:patterns'],
    queryFn: () => api.get('/architect/patterns').then(r => r.data),
    refetchInterval: 60000,
  })

  const filteredPatterns = brandFilter
    ? patterns.filter(p => p.cluster_key.startsWith(brandFilter + '|'))
    : patterns

  if (isLoading) return <div className="text-center py-12 text-gray-400 text-sm">Loading patterns...</div>

  if (patterns.length === 0) {
    return (
      <div className="text-center py-16 text-gray-400">
        <GitBranch className="w-10 h-10 mx-auto mb-3 opacity-30" />
        <p className="text-sm font-medium">No patterns discovered yet</p>
        <p className="text-xs mt-1 text-gray-300">
          Patterns are discovered nightly from labeled sourcing outcomes. They appear here once orders are delivered and outcome scores are computed.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {/* Cluster key format note */}
      <div className="flex items-start gap-2 p-3 bg-indigo-50 border border-indigo-100 rounded-lg">
        <Layers className="w-3.5 h-3.5 text-indigo-500 mt-0.5 flex-shrink-0" />
        <p className="text-xs text-indigo-700">
          Cluster keys include brand slug:{' '}
          <code className="font-mono bg-indigo-100 px-1 rounded">brand_slug|channel|region|amount_bucket|fulfillment_type</code>.
          Legacy patterns (migrated before brand support) use <code className="font-mono bg-indigo-100 px-1 rounded">default</code> as brand slug.
        </p>
      </div>

      {/* Brand filter */}
      <div className="flex items-center gap-3">
        <select
          className="select text-sm max-w-xs"
          value={brandFilter}
          onChange={e => setBrandFilter(e.target.value)}
        >
          <option value="">All brands</option>
          {brands.map(b => (
            <option key={b.id} value={b.slug}>{b.name} ({b.slug})</option>
          ))}
        </select>
        <p className="text-xs text-gray-500">
          {filteredPatterns.length} cluster{filteredPatterns.length !== 1 ? 's' : ''} discovered
          {brandFilter && ` for brand "${brandFilter}"`}
        </p>
      </div>
      {filteredPatterns.map(p => (
        <div key={p.cluster_key} className="card p-4">
          <div className="flex items-start justify-between gap-3 mb-3">
            <div>
              <p className="text-sm font-semibold font-mono text-gray-800">{p.cluster_key}</p>
              <div className="flex flex-wrap gap-1.5 mt-1">
                {p.channel && <span className="text-[10px] bg-indigo-100 text-indigo-700 rounded px-1.5 py-0.5">{p.channel}</span>}
                {p.fulfillment_type && <span className="text-[10px] bg-violet-100 text-violet-700 rounded px-1.5 py-0.5">{p.fulfillment_type.replace(/_/g, ' ')}</span>}
                {p.region && p.region !== 'UNKNOWN' && <span className="text-[10px] bg-emerald-100 text-emerald-700 rounded px-1.5 py-0.5">{p.region}</span>}
                {p.amount_bucket && <span className="text-[10px] bg-amber-100 text-amber-700 rounded px-1.5 py-0.5">${p.amount_bucket}</span>}
              </div>
            </div>
            <div className="text-right flex-shrink-0">
              <p className="text-lg font-bold text-gray-800">{p.sample_count.toLocaleString()}</p>
              <p className="text-[10px] text-gray-400">orders</p>
            </div>
          </div>

          {p.node_performance.length > 0 && (
            <div className="overflow-x-auto rounded border border-gray-100">
              <table className="w-full text-xs">
                <thead className="bg-gray-50">
                  <tr>
                    {['#', 'Node', 'Avg Score', 'Avg Delivery', 'Selections'].map(h => (
                      <th key={h} className="px-3 py-1.5 text-left font-semibold text-gray-500 whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {p.node_performance.slice(0, 5).map((n, i) => (
                    <tr key={n.node_id} className={i === 0 ? 'bg-emerald-50' : ''}>
                      <td className="px-3 py-1.5 font-mono text-gray-400">#{i + 1}</td>
                      <td className="px-3 py-1.5">
                        <p className="font-semibold text-gray-700">{n.node_name || n.node_id}</p>
                      </td>
                      <td className="px-3 py-1.5"><ScoreBar score={n.avg_outcome_score} /></td>
                      <td className="px-3 py-1.5 text-gray-600">{n.avg_delivery_hours.toFixed(1)}h</td>
                      <td className="px-3 py-1.5 text-gray-600">{n.selection_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ─── AI Performance Tab ───────────────────────────────────────────────────────

function PerformanceTab() {
  const [period, setPeriod] = useState<7 | 30>(7)
  const [brandSlug, setBrandSlug] = useState('')

  const { data: brands = [] } = useQuery<Brand[]>({
    queryKey: ['brands'],
    queryFn: () => getBrands(),
  })

  const { data: perf, isLoading: perfLoading } = useQuery<AIPerformance>({
    queryKey: ['architect:ai-perf', brandSlug],
    queryFn: () => api.get('/architect/ai-sourcing/performance', {
      params: brandSlug ? { brand_slug: brandSlug } : {},
    }).then(r => r.data),
    refetchInterval: 60000,
  })

  const { data: nodePerf = [], isLoading: nodeLoading } = useQuery<NodePerf[]>({
    queryKey: ['architect:node-perf', period, brandSlug],
    queryFn: () => api.get('/architect/node-performance', {
      params: { period_days: period, ...(brandSlug ? { brand_slug: brandSlug } : {}) },
    }).then(r => r.data),
    refetchInterval: 60000,
  })

  const ai = perf?.by_strategy.find(s => s.strategy === 'AI_ADAPTIVE')
  const baseline = perf?.by_strategy.find(s => s.strategy === 'DISTANCE_OPTIMAL')

  return (
    <div className="space-y-5">
      {/* Brand filter */}
      <div className="flex items-center gap-3">
        <label className="text-xs text-gray-500 font-medium whitespace-nowrap">Filter by brand:</label>
        <select
          className="select text-sm max-w-xs"
          value={brandSlug}
          onChange={e => setBrandSlug(e.target.value)}
        >
          <option value="">All brands</option>
          {brands.map(b => (
            <option key={b.id} value={b.slug}>{b.name} ({b.slug})</option>
          ))}
        </select>
      </div>

      {/* Summary cards */}
      {perfLoading ? (
        <div className="text-center py-8 text-gray-400 text-sm">Loading performance data...</div>
      ) : perf ? (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="card p-4">
              <p className="text-xs text-gray-500 mb-1">Total Outcomes</p>
              <p className="text-2xl font-bold text-gray-800">{perf.total_outcomes.toLocaleString()}</p>
              <p className="text-[10px] text-gray-400 mt-0.5">{perf.labeled_outcomes} labeled · {perf.unlabeled_outcomes} pending</p>
            </div>
            <div className="card p-4">
              <p className="text-xs text-gray-500 mb-1">AI Improvement</p>
              {perf.ai_improvement_pct != null ? (
                <>
                  <p className={`text-2xl font-bold ${perf.ai_improvement_pct > 0 ? 'text-emerald-600' : 'text-red-500'}`}>
                    {perf.ai_improvement_pct > 0 ? '+' : ''}{perf.ai_improvement_pct}%
                  </p>
                  <p className="text-[10px] text-gray-400 mt-0.5">AI vs DISTANCE_OPTIMAL</p>
                </>
              ) : (
                <>
                  <p className="text-2xl font-bold text-gray-300">—</p>
                  <p className="text-[10px] text-gray-400 mt-0.5">No AI data yet</p>
                </>
              )}
            </div>
            <div className="card p-4">
              <p className="text-xs text-gray-500 mb-1">AI Avg Score</p>
              {ai ? (
                <>
                  <p className="text-2xl font-bold text-indigo-600">{ai.avg_outcome_score.toFixed(3)}</p>
                  <p className="text-[10px] text-gray-400 mt-0.5">{ai.count} orders</p>
                </>
              ) : (
                <p className="text-2xl font-bold text-gray-300">—</p>
              )}
            </div>
            <div className="card p-4">
              <p className="text-xs text-gray-500 mb-1">Baseline Avg Score</p>
              {baseline ? (
                <>
                  <p className="text-2xl font-bold text-gray-700">{baseline.avg_outcome_score.toFixed(3)}</p>
                  <p className="text-[10px] text-gray-400 mt-0.5">{baseline.count} orders</p>
                </>
              ) : (
                <p className="text-2xl font-bold text-gray-300">—</p>
              )}
            </div>
          </div>

          {/* Strategy comparison table */}
          {perf.by_strategy.length > 0 && (
            <div className="card overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-100">
                <p className="text-sm font-semibold text-gray-700">Outcome Score by Strategy</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50">
                    <tr>
                      {['Strategy', 'Orders', 'Avg Score', 'Avg Delivery', 'Backorder %'].map(h => (
                        <th key={h} className="px-4 py-2.5 text-left font-semibold text-gray-500">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {perf.by_strategy.map(s => (
                      <tr key={s.strategy} className={s.strategy === 'AI_ADAPTIVE' ? 'bg-indigo-50' : ''}>
                        <td className="px-4 py-2.5">
                          <span className={`font-mono font-semibold text-xs rounded px-1.5 py-0.5 ${
                            s.strategy === 'AI_ADAPTIVE' || s.strategy === 'AI_HYBRID'
                              ? 'bg-violet-100 text-violet-800'
                              : 'bg-gray-100 text-gray-700'
                          }`}>{s.strategy}</span>
                        </td>
                        <td className="px-4 py-2.5 text-gray-700">{s.count.toLocaleString()}</td>
                        <td className="px-4 py-2.5"><ScoreBar score={s.avg_outcome_score} /></td>
                        <td className="px-4 py-2.5 text-gray-600">
                          <span className="flex items-center gap-1">
                            <Clock className="w-3 h-3 text-gray-400" />{s.avg_delivery_hours.toFixed(1)}h
                          </span>
                        </td>
                        <td className="px-4 py-2.5">
                          <span className={s.backorder_rate_pct > 5 ? 'text-red-600 font-semibold' : 'text-gray-600'}>
                            {s.backorder_rate_pct.toFixed(1)}%
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      ) : null}

      {/* Node performance */}
      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
          <p className="text-sm font-semibold text-gray-700">Node Performance</p>
          <div className="flex gap-1.5">
            {([7, 30] as const).map(d => (
              <button
                key={d}
                onClick={() => setPeriod(d)}
                className={`px-2.5 py-1 rounded text-xs font-semibold transition-colors ${
                  period === d ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>

        {nodeLoading ? (
          <div className="py-8 text-center text-gray-400 text-sm">Loading node metrics...</div>
        ) : nodePerf.length === 0 ? (
          <div className="py-10 text-center text-gray-400">
            <Package className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p className="text-sm">No node performance data yet</p>
            <p className="text-xs text-gray-300 mt-1">Updated every 4 hours from labeled outcomes</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-50">
                <tr>
                  {['Node', 'Orders', 'Avg Score', 'Avg Delivery', 'Backorder %', 'Return %'].map(h => (
                    <th key={h} className="px-4 py-2.5 text-left font-semibold text-gray-500 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {nodePerf.map(n => (
                  <tr key={`${n.node_id}-${n.period_days}`} className="hover:bg-gray-50">
                    <td className="px-4 py-2.5">
                      <p className="font-semibold text-gray-800">{n.node_name || n.node_id}</p>
                    </td>
                    <td className="px-4 py-2.5 text-gray-700">{n.orders_fulfilled}</td>
                    <td className="px-4 py-2.5"><ScoreBar score={n.avg_outcome_score} /></td>
                    <td className="px-4 py-2.5">
                      <span className="flex items-center gap-1 text-gray-600">
                        <Clock className="w-3 h-3 text-gray-400" />{n.avg_delivery_hours.toFixed(1)}h
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={n.backorder_rate_pct > 5 ? 'text-red-600 font-semibold' : 'text-gray-600'}>
                        {n.backorder_rate_pct.toFixed(1)}%
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-gray-600">{n.return_rate_pct.toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Experiments Tab ──────────────────────────────────────────────────────────

interface Experiment {
  id: string
  name: string
  description: string | null
  strategy_a: string
  strategy_b: string
  traffic_split_pct: number
  filter_conditions: Record<string, unknown>
  status: string
  started_at: string | null
  ended_at: string | null
  winner: string | null
  results: Record<string, unknown> | null
  created_at: string
}

const EXP_STATUS_STYLES: Record<string, string> = {
  running:   'bg-emerald-100 text-emerald-800',
  paused:    'bg-yellow-100 text-yellow-800',
  completed: 'bg-blue-100 text-blue-800',
}

function ExperimentsTab() {
  const qc = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [createForm, setCreateForm] = useState({
    name: '', description: '', strategy_a: 'DISTANCE_OPTIMAL', strategy_b: 'AI_ADAPTIVE',
    traffic_split_pct: 10, filter_conditions: '{}',
  })
  const [createError, setCreateError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data: experiments = [], isLoading } = useQuery<Experiment[]>({
    queryKey: ['architect:experiments'],
    queryFn: () => api.get('/architect/experiments').then(r => r.data),
    refetchInterval: 15000,
  })

  const { data: expandedResults } = useQuery({
    queryKey: ['architect:exp-results', expandedId],
    queryFn: () => expandedId
      ? api.get(`/architect/experiments/${expandedId}/results`).then(r => r.data)
      : null,
    enabled: !!expandedId,
    refetchInterval: 30000,
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['architect:experiments'] })

  const createMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.post('/architect/experiments', data).then(r => r.data),
    onSuccess: () => { setCreateError(null); setShowCreate(false); invalidate() },
    onError: (e: unknown) => setCreateError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Create failed'),
  })

  const pauseMutation = useMutation({
    mutationFn: (id: string) => api.post(`/architect/experiments/${id}/pause`).then(r => r.data),
    onSuccess: invalidate,
  })

  const resumeMutation = useMutation({
    mutationFn: (id: string) => api.post(`/architect/experiments/${id}/resume`).then(r => r.data),
    onSuccess: invalidate,
  })

  const handleCreate = () => {
    let fc: Record<string, unknown> = {}
    try { fc = JSON.parse(createForm.filter_conditions) } catch {
      setCreateError('filter_conditions must be valid JSON'); return
    }
    createMutation.mutate({
      name: createForm.name,
      description: createForm.description || undefined,
      strategy_a: createForm.strategy_a,
      strategy_b: createForm.strategy_b,
      traffic_split_pct: createForm.traffic_split_pct,
      filter_conditions: fc,
    })
  }

  return (
    <div className="space-y-4">
      {/* Header + create button */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500">{experiments.length} experiment{experiments.length !== 1 ? 's' : ''}</p>
        <button className="btn-primary text-xs px-3 py-1.5 flex items-center gap-1.5" onClick={() => setShowCreate(s => !s)}>
          <FlaskConical className="w-3.5 h-3.5" /> New Experiment
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="card p-4 space-y-3 border-indigo-200 border-2">
          <p className="text-sm font-semibold text-gray-700">New A/B Experiment</p>
          {createError && (
            <div className="text-xs text-red-600 bg-red-50 rounded p-2">{createError}</div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="label text-xs">Experiment name *</label>
              <input className="input w-full text-sm" value={createForm.name} onChange={e => setCreateForm(f => ({...f, name: e.target.value}))} placeholder="e.g. AI vs baseline on WEB orders" />
            </div>
            <div>
              <label className="label text-xs">Strategy A (control)</label>
              <select className="select w-full text-sm" value={createForm.strategy_a} onChange={e => setCreateForm(f => ({...f, strategy_a: e.target.value}))}>
                {['DISTANCE_OPTIMAL','COST_OPTIMAL','STORE_NEAREST','INVENTORY_RESERVATION','LEAST_COST_SPLIT','AI_ADAPTIVE','AI_HYBRID'].map(s => <option key={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className="label text-xs">Strategy B (treatment)</label>
              <select className="select w-full text-sm" value={createForm.strategy_b} onChange={e => setCreateForm(f => ({...f, strategy_b: e.target.value}))}>
                {['AI_ADAPTIVE','AI_HYBRID','DISTANCE_OPTIMAL','COST_OPTIMAL','STORE_NEAREST','INVENTORY_RESERVATION','LEAST_COST_SPLIT'].map(s => <option key={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className="label text-xs">Traffic split to B (%)</label>
              <input type="number" min={1} max={50} className="input w-full text-sm" value={createForm.traffic_split_pct} onChange={e => setCreateForm(f => ({...f, traffic_split_pct: Number(e.target.value)}))} />
            </div>
            <div>
              <label className="label text-xs">Filter conditions (JSON)</label>
              <input className="input w-full text-sm font-mono" value={createForm.filter_conditions} onChange={e => setCreateForm(f => ({...f, filter_conditions: e.target.value}))} placeholder='{"channel":"WEB"}' />
            </div>
          </div>
          <p className="text-[10px] text-gray-400">
            filter_conditions keys: channel, fulfillment_type, region, amount_min, amount_max. Leave as <code>{'{}'}</code> for all orders.
          </p>
          <div className="flex gap-2">
            <button className="btn-primary text-xs px-3 py-1.5" disabled={!createForm.name || createMutation.isPending} onClick={handleCreate}>
              Start Experiment
            </button>
            <button className="btn-secondary text-xs px-3 py-1.5" onClick={() => setShowCreate(false)}>Cancel</button>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="text-center py-12 text-gray-400 text-sm">Loading experiments...</div>
      ) : experiments.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <FlaskConical className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm font-medium">No experiments yet</p>
          <p className="text-xs mt-1 text-gray-300">Create an experiment to A/B test sourcing strategies.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {experiments.map(exp => (
            <div key={exp.id} className="card overflow-hidden">
              <button
                className="w-full px-4 py-3 flex items-start gap-3 hover:bg-gray-50 transition-colors text-left"
                onClick={() => setExpandedId(expandedId === exp.id ? null : exp.id)}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2 mb-1">
                    <span className={`text-[10px] font-semibold rounded-full px-2 py-0.5 capitalize ${EXP_STATUS_STYLES[exp.status] || 'bg-gray-100 text-gray-600'}`}>
                      {exp.status}
                    </span>
                    {exp.winner && (
                      <span className="text-[10px] bg-emerald-100 text-emerald-800 rounded-full px-2 py-0.5 font-semibold">
                        Winner: {exp.winner}
                      </span>
                    )}
                  </div>
                  <p className="text-sm font-semibold text-gray-800">{exp.name}</p>
                  <div className="flex flex-wrap gap-2 mt-1">
                    <span className="text-[10px] font-mono bg-gray-100 text-gray-600 rounded px-1.5 py-0.5">{exp.strategy_a}</span>
                    <span className="text-[10px] text-gray-400">vs</span>
                    <span className="text-[10px] font-mono bg-violet-100 text-violet-700 rounded px-1.5 py-0.5">{exp.strategy_b}</span>
                    <span className="text-[10px] text-gray-400">·</span>
                    <span className="text-[10px] text-gray-500">{exp.traffic_split_pct}% to B</span>
                  </div>
                </div>
                <div className="flex-shrink-0 text-right">
                  <p className="text-[10px] text-gray-400">{exp.started_at ? formatDate(exp.started_at) : '—'}</p>
                </div>
                {expandedId === exp.id ? <ChevronUp className="w-4 h-4 text-gray-400 mt-1 flex-shrink-0" /> : <ChevronDown className="w-4 h-4 text-gray-400 mt-1 flex-shrink-0" />}
              </button>

              {expandedId === exp.id && (
                <div className="border-t border-gray-100 px-4 py-4 space-y-4 bg-gray-50">
                  {/* Live results */}
                  {expandedResults && expandedResults.arms && (
                    <div>
                      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Live Results</p>
                      <div className="grid grid-cols-2 gap-3">
                        {(expandedResults.arms as Array<Record<string, unknown>>).map((arm) => {
                          const isWinner = arm.strategy === exp.winner
                          return (
                            <div key={String(arm.strategy)} className={`rounded-lg border p-3 ${isWinner ? 'border-emerald-300 bg-emerald-50' : 'border-gray-200 bg-white'}`}>
                              <div className="flex items-center gap-2 mb-2">
                                <span className={`text-[10px] font-mono font-semibold rounded px-1.5 py-0.5 ${arm.strategy === exp.strategy_b ? 'bg-violet-100 text-violet-800' : 'bg-gray-100 text-gray-700'}`}>
                                  {String(arm.strategy)}
                                </span>
                                {isWinner && <span className="text-[10px] text-emerald-700 font-semibold">Winner</span>}
                              </div>
                              <div className="space-y-1 text-xs text-gray-600">
                                <p>Total orders: <strong>{String(arm.total_orders ?? 0)}</strong></p>
                                <p>Labeled: <strong>{String(arm.labeled_orders ?? 0)}</strong></p>
                                {arm.avg_outcome_score != null && (
                                  <p>Avg score: <strong className="font-mono">{Number(arm.avg_outcome_score).toFixed(4)}</strong></p>
                                )}
                                {arm.avg_delivery_hours != null && (
                                  <p>Avg delivery: <strong>{Number(arm.avg_delivery_hours).toFixed(1)}h</strong></p>
                                )}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                      {expandedResults.winner && (
                        <p className="text-xs text-emerald-700 font-semibold mt-2">
                          Experiment completed — winner: {String(expandedResults.winner)}
                        </p>
                      )}
                    </div>
                  )}

                  {/* Filter conditions */}
                  {Object.keys(exp.filter_conditions).length > 0 && (
                    <div>
                      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1">Filter Conditions</p>
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(exp.filter_conditions).map(([k, v]) => (
                          <span key={k} className="text-[10px] font-mono bg-white border border-gray-200 rounded px-2 py-0.5">
                            {k} = {JSON.stringify(v)}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Actions */}
                  <div className="flex gap-2">
                    {exp.status === 'running' && (
                      <button
                        className="btn-secondary text-xs px-3 py-1.5 flex items-center gap-1.5"
                        disabled={pauseMutation.isPending}
                        onClick={() => pauseMutation.mutate(exp.id)}
                      >
                        <PauseCircle className="w-3.5 h-3.5" /> Pause
                      </button>
                    )}
                    {exp.status === 'paused' && (
                      <button
                        className="btn-primary text-xs px-3 py-1.5 flex items-center gap-1.5"
                        disabled={resumeMutation.isPending}
                        onClick={() => resumeMutation.mutate(exp.id)}
                      >
                        <PlayCircle className="w-3.5 h-3.5" /> Resume
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

type Tab = 'proposals' | 'patterns' | 'experiments' | 'performance'

const TABS: Array<{ id: Tab; label: string; icon: React.ElementType }> = [
  { id: 'proposals', label: 'Proposals', icon: CheckCircle },
  { id: 'patterns', label: 'Patterns', icon: GitBranch },
  { id: 'experiments', label: 'Experiments', icon: FlaskConical },
  { id: 'performance', label: 'AI Performance', icon: TrendingUp },
]

export default function Architect() {
  const [tab, setTab] = useState<Tab>('proposals')

  const { data: proposals = [] } = useQuery<Proposal[]>({
    queryKey: ['architect:proposals', 'pending'],
    queryFn: () => api.get('/architect/proposals', { params: { status: 'pending' } }).then(r => r.data),
    refetchInterval: 30000,
  })
  const pendingCount = proposals.length

  return (
    <div className="p-6 space-y-5 max-w-5xl mx-auto">
      {/* Page header */}
      <div className="flex items-center gap-3">
        <div className="p-2 bg-indigo-100 rounded-lg">
          <Brain className="w-6 h-6 text-indigo-600" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-gray-900">AI Architect</h1>
          <p className="text-sm text-gray-500">
            Pattern discovery · Auto-generated proposals · Sourcing performance
          </p>
        </div>
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-3 p-3.5 bg-indigo-50 border border-indigo-100 rounded-lg">
        <Zap className="w-4 h-4 text-indigo-500 mt-0.5 flex-shrink-0" />
        <p className="text-xs text-indigo-700 leading-relaxed">
          The learning pipeline runs nightly and generates sourcing rule proposals when it detects that AI_ADAPTIVE
          achieves ≥10% better outcomes than the baseline strategy across ≥50 labeled orders.
          All proposals require your approval before any changes are made.
        </p>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <div className="flex gap-1">
          {TABS.map(t => {
            const Icon = t.icon
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                  tab === t.id
                    ? 'border-indigo-600 text-indigo-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                <Icon className="w-4 h-4" />
                {t.label}
                {t.id === 'proposals' && pendingCount > 0 && (
                  <span className="ml-1 bg-yellow-400 text-yellow-900 text-[10px] font-bold rounded-full px-1.5 py-0.5">
                    {pendingCount}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Tab content */}
      {tab === 'proposals' && <ProposalsTab />}
      {tab === 'patterns' && <PatternsTab />}
      {tab === 'experiments' && <ExperimentsTab />}
      {tab === 'performance' && <PerformanceTab />}
    </div>
  )
}
