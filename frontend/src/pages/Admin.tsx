import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Users, Shield, Plus, Pencil, Trash2, X, Check,
  Building2, Globe, Key, ChevronRight, AlertTriangle,
  LayoutDashboard, ShoppingCart, Package, BarChart2,
  MapPin, Zap, GitBranch, Search, Sparkles, Layers,
  UserCheck, Lock, Eye, Settings,
} from 'lucide-react'
import api, {
  fetchAdminUsers, createAdminUser, updateAdminUser, deleteAdminUser,
  fetchAdminGroups, createAdminGroup, updateAdminGroup, deleteAdminGroup,
  type AdminUser, type AdminGroup,
} from '../api/client'
import Modal from '../components/Modal'

// ── Types ─────────────────────────────────────────────────────────────────────

interface UserAccess {
  user_id: string
  email: string
  full_name: string | null
  platform_role: string
  group_id: string | null
  group_name: string | null
  org_roles: OrgRoleEntry[]
  env_roles: EnvRoleEntry[]
}

interface OrgRoleEntry {
  org_id: string
  org_name: string
  org_slug: string
  role: string
  granted_at: string
}

interface EnvRoleEntry {
  env_id: string
  env_name: string
  env_type: string
  env_status: string
  org_id: string
  org_name: string
  role: string
  granted_at: string
}

interface OrgInfo { id: string; name: string; slug: string }
interface EnvInfo { id: string; name: string; env_type: string; organization_id: string; organization_name: string; status: string }

// ── Permission definitions ────────────────────────────────────────────────────

const PERMISSION_FEATURES = [
  { key: 'dashboard',     label: 'Dashboard',      icon: LayoutDashboard, actions: [{ key: 'view',   label: 'View' }] },
  { key: 'orders',        label: 'Orders',          icon: ShoppingCart,   actions: [{ key: 'view',   label: 'View' }, { key: 'manage', label: 'Manage' }] },
  { key: 'inventory',     label: 'Inventory',       icon: Package,        actions: [{ key: 'view',   label: 'View' }, { key: 'adjust', label: 'Adjust' }] },
  { key: 'analytics',     label: 'Analytics',       icon: BarChart2,      actions: [{ key: 'view',   label: 'View' }] },
  { key: 'nodes',         label: 'Nodes',           icon: MapPin,         actions: [{ key: 'view',   label: 'View' }, { key: 'manage', label: 'Manage' }] },
  { key: 'sourcing_rules',label: 'Sourcing Rules',  icon: Zap,            actions: [{ key: 'view',   label: 'View' }, { key: 'manage', label: 'Manage' }] },
  { key: 'lifecycles',    label: 'Lifecycles',      icon: GitBranch,      actions: [{ key: 'view',   label: 'View' }, { key: 'manage', label: 'Manage' }] },
  { key: 'search',        label: 'Search',          icon: Search,         actions: [{ key: 'use',    label: 'Use' }] },
  { key: 'ai',            label: 'AI Assistant',    icon: Sparkles,       actions: [{ key: 'use',    label: 'Use' }] },
  { key: 'monitoring',   label: 'Monitoring & TechOps', icon: AlertTriangle, actions: [{ key: 'view', label: 'View' }] },
]

// ── Role metadata ─────────────────────────────────────────────────────────────

const PLATFORM_ROLES = [
  { value: 'USER',           label: 'User',           color: 'bg-gray-100 text-gray-700 border-gray-200',      desc: 'Access via org/env grants only' },
  { value: 'SUPERADMIN',     label: 'Superadmin',     color: 'bg-blue-100 text-blue-700 border-blue-200',      desc: 'Admin access to all orgs and environments' },
  { value: 'PLATFORM_OWNER', label: 'Platform Owner', color: 'bg-purple-100 text-purple-700 border-purple-200',desc: 'Full platform control, billing, and user management' },
]

const ORG_ROLES = [
  { value: 'ORG_MEMBER', label: 'Member', color: 'bg-gray-100 text-gray-600 border-gray-200',      desc: 'Access to explicitly granted environments' },
  { value: 'ORG_ADMIN',  label: 'Admin',  color: 'bg-blue-100 text-blue-700 border-blue-200',      desc: 'Create environments, manage org members' },
  { value: 'ORG_OWNER',  label: 'Owner',  color: 'bg-purple-100 text-purple-700 border-purple-200',desc: 'Full org control including deletion' },
]

const ENV_ROLES = [
  { value: 'VIEWER', label: 'Viewer', color: 'bg-gray-100 text-gray-600 border-gray-200',      desc: 'Read-only access to all features' },
  { value: 'MEMBER', label: 'Member', color: 'bg-green-100 text-green-700 border-green-200',    desc: 'Full access per permission group' },
  { value: 'ADMIN',  label: 'Admin',  color: 'bg-blue-100 text-blue-700 border-blue-200',      desc: 'Full access + can manage environment members' },
  { value: 'OWNER',  label: 'Owner',  color: 'bg-purple-100 text-purple-700 border-purple-200',desc: 'Full control including environment deletion' },
]

const ENV_TYPE_COLORS: Record<string, string> = {
  DEV: 'bg-blue-500', QA: 'bg-yellow-500', STAGING: 'bg-orange-500', PROD: 'bg-red-500',
}

// ── Badge components ──────────────────────────────────────────────────────────

function PlatformRoleBadge({ role }: { role: string }) {
  const meta = PLATFORM_ROLES.find(r => r.value === role) ?? PLATFORM_ROLES[0]
  return <span className={`inline-flex items-center text-xs font-medium border rounded-full px-2 py-0.5 ${meta.color}`}>{meta.label}</span>
}

function OrgRoleBadge({ role }: { role: string }) {
  const meta = ORG_ROLES.find(r => r.value === role) ?? ORG_ROLES[0]
  return <span className={`inline-flex items-center text-xs font-medium border rounded-full px-2 py-0.5 ${meta.color}`}>{meta.label}</span>
}

function EnvRoleBadge({ role }: { role: string }) {
  const meta = ENV_ROLES.find(r => r.value === role) ?? ENV_ROLES[0]
  return <span className={`inline-flex items-center text-xs font-medium border rounded-full px-2 py-0.5 ${meta.color}`}>{meta.label}</span>
}

function EnvTypeDot({ type }: { type: string }) {
  return <span className={`inline-block w-2 h-2 rounded-full ${ENV_TYPE_COLORS[type] ?? 'bg-gray-400'}`} />
}

function PermissionBadge({ perm }: { perm: string }) {
  return (
    <span className="inline-flex items-center text-[10px] font-medium bg-blue-50 text-blue-700 border border-blue-200 rounded px-1.5 py-0.5">
      {perm}
    </span>
  )
}

// ── Permission grid ───────────────────────────────────────────────────────────

function PermissionGrid({ selected, onChange }: { selected: string[]; onChange: (p: string[]) => void }) {
  const toggle = (perm: string) =>
    onChange(selected.includes(perm) ? selected.filter(p => p !== perm) : [...selected, perm])

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-50">
            <th className="text-left px-3 py-2 text-gray-500 font-medium text-xs uppercase tracking-wider w-44">Feature</th>
            {['View', 'Manage', 'Adjust', 'Use'].map(a => (
              <th key={a} className="text-center px-2 py-2 text-gray-500 font-medium text-xs uppercase tracking-wider">{a}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {PERMISSION_FEATURES.map(feat => {
            const Icon = feat.icon
            return (
              <tr key={feat.key} className="hover:bg-gray-50/50">
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <Icon className="w-3.5 h-3.5 text-gray-400" />
                    <span className="font-medium text-gray-700">{feat.label}</span>
                  </div>
                </td>
                {['view', 'manage', 'adjust', 'use'].map(action => {
                  const perm = `${feat.key}:${action}`
                  const hasAction = feat.actions.some(a => a.key === action)
                  return (
                    <td key={action} className="text-center px-2 py-2">
                      {hasAction ? (
                        <input
                          type="checkbox"
                          checked={selected.includes(perm)}
                          onChange={() => toggle(perm)}
                          className="w-4 h-4 text-blue-600 border-gray-300 rounded cursor-pointer"
                        />
                      ) : (
                        <span className="text-gray-200">—</span>
                      )}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── User Access Drawer ────────────────────────────────────────────────────────

function UserAccessDrawer({
  userId, onClose, groups, orgs, envs,
}: {
  userId: string
  onClose: () => void
  groups: AdminGroup[]
  orgs: OrgInfo[]
  envs: EnvInfo[]
}) {
  const qc = useQueryClient()
  const [addOrgRole, setAddOrgRole] = useState(false)
  const [addEnvRole, setAddEnvRole] = useState(false)
  const [newOrgId, setNewOrgId] = useState('')
  const [newOrgRole, setNewOrgRole] = useState('ORG_MEMBER')
  const [newEnvId, setNewEnvId] = useState('')
  const [newEnvRole, setNewEnvRole] = useState('MEMBER')

  const { data: access, isLoading } = useQuery<UserAccess>({
    queryKey: ['user-access', userId],
    queryFn: () => api.get<UserAccess>(`/admin/users/${userId}/access`).then(r => r.data),
  })

  const grantOrgMut = useMutation({
    mutationFn: (p: { org_id: string; role: string }) =>
      api.post(`/admin/users/${userId}/org-roles`, p).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['user-access', userId] }); setAddOrgRole(false); setNewOrgId('') },
  })

  const revokeOrgMut = useMutation({
    mutationFn: (orgId: string) => api.delete(`/admin/users/${userId}/org-roles/${orgId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['user-access', userId] }),
  })

  const grantEnvMut = useMutation({
    mutationFn: (p: { env_id: string; role: string }) =>
      api.post(`/admin/users/${userId}/env-roles`, p).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['user-access', userId] }); setAddEnvRole(false); setNewEnvId('') },
  })

  const revokeEnvMut = useMutation({
    mutationFn: (envId: string) => api.delete(`/admin/users/${userId}/env-roles/${envId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['user-access', userId] }),
  })

  if (isLoading || !access) return (
    <div className="fixed inset-y-0 right-0 w-[480px] bg-white shadow-2xl z-50 flex items-center justify-center border-l">
      <div className="text-gray-400 text-sm">Loading…</div>
    </div>
  )

  return (
    <div className="fixed inset-y-0 right-0 w-[480px] bg-white shadow-2xl z-50 flex flex-col border-l">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b bg-gray-50">
        <div>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-white font-semibold text-sm">
              {(access.full_name ?? access.email)[0].toUpperCase()}
            </div>
            <div>
              <div className="font-semibold text-gray-900 text-sm">{access.full_name ?? '(no name)'}</div>
              <div className="text-xs text-gray-500">{access.email}</div>
            </div>
          </div>
        </div>
        <button onClick={onClose} className="p-1.5 hover:bg-gray-200 rounded"><X className="w-4 h-4" /></button>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-6">
        {/* Platform role */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Lock className="w-4 h-4 text-gray-400" />
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Platform Role</span>
          </div>
          <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg border">
            <PlatformRoleBadge role={access.platform_role} />
            <span className="text-xs text-gray-500">
              {PLATFORM_ROLES.find(r => r.value === access.platform_role)?.desc}
            </span>
          </div>
        </div>

        {/* Permission group */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Shield className="w-4 h-4 text-gray-400" />
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Permission Group</span>
          </div>
          {access.group_name ? (
            <div className="flex items-center gap-2 p-3 bg-gray-50 rounded-lg border">
              <span className="text-sm font-medium text-gray-700">{access.group_name}</span>
              <span className="text-xs text-gray-400">(defines feature access)</span>
            </div>
          ) : (
            <div className="p-3 bg-yellow-50 rounded-lg border border-yellow-200 text-xs text-yellow-700">
              No permission group assigned — user has no feature access unless they are a superadmin.
            </div>
          )}
        </div>

        {/* Org roles */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Building2 className="w-4 h-4 text-gray-400" />
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Organization Roles</span>
            </div>
            <button onClick={() => setAddOrgRole(true)} className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1">
              <Plus className="w-3 h-3" /> Add
            </button>
          </div>

          {addOrgRole && (
            <div className="mb-3 p-3 bg-blue-50 rounded-lg border border-blue-200 space-y-2">
              <div className="flex gap-2">
                <select
                  value={newOrgId}
                  onChange={e => setNewOrgId(e.target.value)}
                  className="flex-1 text-xs border-gray-300 rounded px-2 py-1.5 border"
                >
                  <option value="">Select organization…</option>
                  {orgs.filter(o => !access.org_roles.find(r => r.org_id === o.id))
                    .map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
                <select
                  value={newOrgRole}
                  onChange={e => setNewOrgRole(e.target.value)}
                  className="text-xs border-gray-300 rounded px-2 py-1.5 border"
                >
                  {ORG_ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
              </div>
              <div className="flex gap-2 justify-end">
                <button onClick={() => setAddOrgRole(false)} className="text-xs text-gray-500 hover:text-gray-700 px-2 py-1">Cancel</button>
                <button
                  onClick={() => newOrgId && grantOrgMut.mutate({ org_id: newOrgId, role: newOrgRole })}
                  disabled={!newOrgId || grantOrgMut.isPending}
                  className="text-xs bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700 disabled:opacity-50"
                >
                  Grant
                </button>
              </div>
            </div>
          )}

          {access.org_roles.length === 0 ? (
            <div className="text-xs text-gray-400 italic p-2">No organization roles assigned</div>
          ) : (
            <div className="space-y-1.5">
              {access.org_roles.map(r => (
                <div key={r.org_id} className="flex items-center justify-between p-2.5 bg-gray-50 rounded border hover:bg-gray-100">
                  <div>
                    <div className="text-sm font-medium text-gray-700">{r.org_name}</div>
                    <div className="text-xs text-gray-400">{r.org_slug}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <OrgRoleBadge role={r.role} />
                    <button
                      onClick={() => revokeOrgMut.mutate(r.org_id)}
                      className="p-1 text-gray-400 hover:text-red-500 rounded"
                      title="Revoke"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Env roles */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Globe className="w-4 h-4 text-gray-400" />
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Environment Roles</span>
            </div>
            <button onClick={() => setAddEnvRole(true)} className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1">
              <Plus className="w-3 h-3" /> Add
            </button>
          </div>

          {addEnvRole && (
            <div className="mb-3 p-3 bg-blue-50 rounded-lg border border-blue-200 space-y-2">
              <div className="flex gap-2">
                <select
                  value={newEnvId}
                  onChange={e => setNewEnvId(e.target.value)}
                  className="flex-1 text-xs border-gray-300 rounded px-2 py-1.5 border"
                >
                  <option value="">Select environment…</option>
                  {envs.filter(e => !access.env_roles.find(r => r.env_id === e.id))
                    .map(e => (
                      <option key={e.id} value={e.id}>
                        {e.organization_name} / {e.name} ({e.env_type})
                      </option>
                    ))}
                </select>
                <select
                  value={newEnvRole}
                  onChange={e => setNewEnvRole(e.target.value)}
                  className="text-xs border-gray-300 rounded px-2 py-1.5 border"
                >
                  {ENV_ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
              </div>
              <div className="flex gap-2 justify-end">
                <button onClick={() => setAddEnvRole(false)} className="text-xs text-gray-500 hover:text-gray-700 px-2 py-1">Cancel</button>
                <button
                  onClick={() => newEnvId && grantEnvMut.mutate({ env_id: newEnvId, role: newEnvRole })}
                  disabled={!newEnvId || grantEnvMut.isPending}
                  className="text-xs bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700 disabled:opacity-50"
                >
                  Grant
                </button>
              </div>
            </div>
          )}

          {access.env_roles.length === 0 ? (
            <div className="text-xs text-gray-400 italic p-2">No environment roles assigned</div>
          ) : (
            <div className="space-y-1.5">
              {access.env_roles.map(r => (
                <div key={r.env_id} className="flex items-center justify-between p-2.5 bg-gray-50 rounded border hover:bg-gray-100">
                  <div>
                    <div className="flex items-center gap-1.5">
                      <EnvTypeDot type={r.env_type} />
                      <span className="text-sm font-medium text-gray-700">{r.env_name}</span>
                      <span className="text-xs text-gray-400">·</span>
                      <span className="text-xs text-gray-400">{r.org_name}</span>
                    </div>
                    <div className="text-[10px] text-gray-400 mt-0.5 pl-3.5">
                      {r.role === 'VIEWER' ? 'Read-only' :
                       r.role === 'MEMBER' ? 'Full access via permission group' :
                       r.role === 'ADMIN' ? 'Full access + manage members' : 'Full control'}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <EnvRoleBadge role={r.role} />
                    <button
                      onClick={() => revokeEnvMut.mutate(r.env_id)}
                      className="p-1 text-gray-400 hover:text-red-500 rounded"
                      title="Revoke"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Users Tab ─────────────────────────────────────────────────────────────────

type OrgRoleDraft = { org_id: string; role: string }
type EnvRoleDraft = { env_id: string; role: string }

const BLANK_CREATE_FORM = { email: '', full_name: '', password: '', group_id: '', is_superadmin: false }

function UsersTab({
  groups, orgs, envs,
}: {
  groups: AdminGroup[]
  orgs: OrgInfo[]
  envs: EnvInfo[]
}) {
  const qc = useQueryClient()
  const { data: users = [], isLoading } = useQuery({ queryKey: ['admin-users'], queryFn: fetchAdminUsers })
  const [accessUserId, setAccessUserId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [createStep, setCreateStep] = useState<1 | 2>(1)
  const [editUser, setEditUser] = useState<AdminUser | null>(null)
  const [form, setForm] = useState(BLANK_CREATE_FORM)
  const [orgRoleDrafts, setOrgRoleDrafts] = useState<OrgRoleDraft[]>([])
  const [envRoleDrafts, setEnvRoleDrafts] = useState<EnvRoleDraft[]>([])
  const [addingOrgDraft, setAddingOrgDraft] = useState(false)
  const [addingEnvDraft, setAddingEnvDraft] = useState(false)
  const [draftOrgId, setDraftOrgId] = useState('')
  const [draftOrgRole, setDraftOrgRole] = useState('ORG_MEMBER')
  const [draftEnvId, setDraftEnvId] = useState('')
  const [draftEnvRole, setDraftEnvRole] = useState('MEMBER')
  const [editForm, setEditForm] = useState({ full_name: '', group_id: '', is_active: true, is_superadmin: false, password: '' })
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)

  const resetCreateModal = () => {
    setCreating(false)
    setCreateStep(1)
    setForm(BLANK_CREATE_FORM)
    setOrgRoleDrafts([])
    setEnvRoleDrafts([])
    setAddingOrgDraft(false)
    setAddingEnvDraft(false)
    setDraftOrgId('')
    setDraftEnvId('')
  }

  const createMut = useMutation({
    mutationFn: async () => {
      const user = await createAdminUser({
        email: form.email,
        full_name: form.full_name || undefined,
        password: form.password,
        group_id: form.group_id || undefined,
        is_superadmin: form.is_superadmin,
      })
      await Promise.all(orgRoleDrafts.map(r => api.post(`/admin/users/${user.id}/org-roles`, r)))
      await Promise.all(envRoleDrafts.map(r => api.post(`/admin/users/${user.id}/env-roles`, r)))
      return user
    },
    onSuccess: (user) => {
      qc.invalidateQueries({ queryKey: ['admin-users'] })
      resetCreateModal()
      setAccessUserId(user.id)
    },
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof updateAdminUser>[1] }) => updateAdminUser(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-users'] }); setEditUser(null) },
  })

  const deleteMut = useMutation({
    mutationFn: deleteAdminUser,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-users'] }); setDeleteConfirm(null) },
  })

  const openEdit = (u: AdminUser) => {
    setEditForm({ full_name: u.full_name ?? '', group_id: u.group_id ?? '', is_active: u.is_active, is_superadmin: u.is_superadmin, password: '' })
    setEditUser(u)
  }

  if (isLoading) return <div className="flex items-center justify-center h-48 text-gray-400 text-sm">Loading users…</div>

  return (
    <div className="relative">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Users</h2>
          <p className="text-xs text-gray-500 mt-0.5">{users.length} total — create assigns org/env roles in step 2 · click any row to update access later</p>
        </div>
        <button onClick={() => setCreating(true)} className="btn-primary flex items-center gap-1.5 text-sm py-1.5 px-3">
          <Plus className="w-4 h-4" /> New User
        </button>
      </div>

      <div className="card overflow-hidden p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-gray-50">
              <th className="table-header">User</th>
              <th className="table-header">Platform Role</th>
              <th className="table-header">Permission Group</th>
              <th className="table-header text-center">Status</th>
              <th className="table-header text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {users.map(u => (
              <tr
                key={u.id}
                className="hover:bg-gray-50 cursor-pointer"
                onClick={() => setAccessUserId(u.id)}
              >
                <td className="table-cell">
                  <div className="flex items-center gap-2.5">
                    <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-semibold text-xs shrink-0">
                      {(u.full_name ?? u.email)[0].toUpperCase()}
                    </div>
                    <div>
                      <div className="font-medium text-gray-900">{u.full_name ?? <span className="text-gray-400 italic">No name</span>}</div>
                      <div className="text-xs text-gray-500">{u.email}</div>
                    </div>
                  </div>
                </td>
                <td className="table-cell">
                  <PlatformRoleBadge role={(u as AdminUser & { platform_role?: string }).platform_role ?? (u.is_superadmin ? 'SUPERADMIN' : 'USER')} />
                </td>
                <td className="table-cell">
                  {u.group_name
                    ? <span className="inline-flex items-center gap-1 text-xs bg-indigo-50 text-indigo-700 border border-indigo-200 rounded px-2 py-0.5"><Shield className="w-3 h-3" />{u.group_name}</span>
                    : <span className="text-xs text-gray-400 italic">None</span>}
                </td>
                <td className="table-cell text-center">
                  {u.is_active
                    ? <span className="inline-flex items-center gap-1 text-xs text-green-700 bg-green-50 border border-green-200 rounded-full px-2 py-0.5"><Check className="w-3 h-3" />Active</span>
                    : <span className="inline-flex items-center gap-1 text-xs text-red-700 bg-red-50 border border-red-200 rounded-full px-2 py-0.5"><X className="w-3 h-3" />Inactive</span>}
                </td>
                <td className="table-cell text-right" onClick={e => e.stopPropagation()}>
                  <div className="flex items-center gap-1 justify-end">
                    <button
                      onClick={() => setAccessUserId(u.id)}
                      className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded"
                      title="Manage Access"
                    >
                      <UserCheck className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => openEdit(u)}
                      className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded"
                      title="Edit"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => setDeleteConfirm(u.id)}
                      className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded"
                      title="Delete"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Create User Modal — 2-step */}
      {creating && (
        <Modal open={true} title={createStep === 1 ? 'New User — Account' : 'New User — Assign Access'} onClose={resetCreateModal}>
          {/* Step indicator */}
          <div className="flex items-center gap-2 px-4 pt-3 pb-1">
            {[1, 2].map(s => (
              <div key={s} className="flex items-center gap-2">
                <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold ${createStep === s ? 'bg-blue-600 text-white' : s < createStep ? 'bg-green-500 text-white' : 'bg-gray-200 text-gray-500'}`}>{s}</div>
                <span className={`text-xs ${createStep === s ? 'text-blue-700 font-medium' : 'text-gray-400'}`}>{s === 1 ? 'Account' : 'Access'}</span>
                {s < 2 && <ChevronRight className="w-3.5 h-3.5 text-gray-300" />}
              </div>
            ))}
          </div>

          {createStep === 1 && (
            <div className="space-y-3 p-4">
              <div><label className="label">Email *</label><input className="input" type="email" value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))} /></div>
              <div><label className="label">Full Name</label><input className="input" value={form.full_name} onChange={e => setForm(f => ({ ...f, full_name: e.target.value }))} /></div>
              <div><label className="label">Password *</label><input className="input" type="password" value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))} /></div>
              <div>
                <label className="label">Permission Group</label>
                <select className="select" value={form.group_id} onChange={e => setForm(f => ({ ...f, group_id: e.target.value }))}>
                  <option value="">None</option>
                  {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                </select>
              </div>
              <div className="flex items-center gap-2">
                <input type="checkbox" id="is-superadmin" checked={form.is_superadmin} onChange={e => setForm(f => ({ ...f, is_superadmin: e.target.checked }))} className="w-4 h-4 text-blue-600 border-gray-300 rounded" />
                <label htmlFor="is-superadmin" className="text-sm text-gray-700">Superadmin</label>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button onClick={resetCreateModal} className="btn-secondary text-sm">Cancel</button>
                <button onClick={() => setCreateStep(2)} disabled={!form.email || !form.password} className="btn-primary text-sm">
                  Next: Assign Access →
                </button>
              </div>
            </div>
          )}

          {createStep === 2 && (
            <div className="p-4 space-y-5">
              {/* Org roles */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Building2 className="w-4 h-4 text-gray-400" />
                    <span className="text-xs font-semibold text-gray-600 uppercase tracking-wider">Organization Roles</span>
                  </div>
                  <button onClick={() => { setAddingOrgDraft(true); setDraftOrgId(''); setDraftOrgRole('ORG_MEMBER') }} className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1">
                    <Plus className="w-3 h-3" /> Add
                  </button>
                </div>
                {addingOrgDraft && (
                  <div className="mb-2 p-2.5 bg-blue-50 rounded border border-blue-200 flex items-center gap-2">
                    <select value={draftOrgId} onChange={e => setDraftOrgId(e.target.value)} className="flex-1 text-xs border-gray-300 rounded px-2 py-1.5 border">
                      <option value="">Select org…</option>
                      {orgs.filter(o => !orgRoleDrafts.find(r => r.org_id === o.id)).map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                    </select>
                    <select value={draftOrgRole} onChange={e => setDraftOrgRole(e.target.value)} className="text-xs border-gray-300 rounded px-2 py-1.5 border">
                      {ORG_ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                    </select>
                    <button onClick={() => { if (draftOrgId) { setOrgRoleDrafts(d => [...d, { org_id: draftOrgId, role: draftOrgRole }]); setAddingOrgDraft(false) } }} disabled={!draftOrgId} className="text-xs bg-blue-600 text-white px-2 py-1 rounded hover:bg-blue-700 disabled:opacity-50">Add</button>
                    <button onClick={() => setAddingOrgDraft(false)} className="text-xs text-gray-400 hover:text-gray-600 px-1">✕</button>
                  </div>
                )}
                {orgRoleDrafts.length === 0 ? (
                  <div className="text-xs text-gray-400 italic">No org roles — user will only access environments they are granted directly</div>
                ) : (
                  <div className="space-y-1">
                    {orgRoleDrafts.map((r, i) => (
                      <div key={i} className="flex items-center justify-between p-2 bg-gray-50 rounded border text-xs">
                        <span className="font-medium text-gray-700">{orgs.find(o => o.id === r.org_id)?.name}</span>
                        <div className="flex items-center gap-2">
                          <OrgRoleBadge role={r.role} />
                          <button onClick={() => setOrgRoleDrafts(d => d.filter((_, j) => j !== i))} className="text-gray-300 hover:text-red-500"><X className="w-3 h-3" /></button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Env roles */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Globe className="w-4 h-4 text-gray-400" />
                    <span className="text-xs font-semibold text-gray-600 uppercase tracking-wider">Environment Roles</span>
                  </div>
                  <button onClick={() => { setAddingEnvDraft(true); setDraftEnvId(''); setDraftEnvRole('MEMBER') }} className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1">
                    <Plus className="w-3 h-3" /> Add
                  </button>
                </div>
                {addingEnvDraft && (
                  <div className="mb-2 p-2.5 bg-blue-50 rounded border border-blue-200 flex items-center gap-2">
                    <select value={draftEnvId} onChange={e => setDraftEnvId(e.target.value)} className="flex-1 text-xs border-gray-300 rounded px-2 py-1.5 border">
                      <option value="">Select environment…</option>
                      {envs.filter(e => !envRoleDrafts.find(r => r.env_id === e.id)).map(e => (
                        <option key={e.id} value={e.id}>{e.organization_name} / {e.name} ({e.env_type})</option>
                      ))}
                    </select>
                    <select value={draftEnvRole} onChange={e => setDraftEnvRole(e.target.value)} className="text-xs border-gray-300 rounded px-2 py-1.5 border">
                      {ENV_ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                    </select>
                    <button onClick={() => { if (draftEnvId) { setEnvRoleDrafts(d => [...d, { env_id: draftEnvId, role: draftEnvRole }]); setAddingEnvDraft(false) } }} disabled={!draftEnvId} className="text-xs bg-blue-600 text-white px-2 py-1 rounded hover:bg-blue-700 disabled:opacity-50">Add</button>
                    <button onClick={() => setAddingEnvDraft(false)} className="text-xs text-gray-400 hover:text-gray-600 px-1">✕</button>
                  </div>
                )}
                {envRoleDrafts.length === 0 ? (
                  <div className="text-xs text-gray-400 italic">No environment roles — user won't be able to switch to any environment</div>
                ) : (
                  <div className="space-y-1">
                    {envRoleDrafts.map((r, i) => {
                      const env = envs.find(e => e.id === r.env_id)
                      return (
                        <div key={i} className="flex items-center justify-between p-2 bg-gray-50 rounded border text-xs">
                          <div className="flex items-center gap-1.5">
                            <EnvTypeDot type={env?.env_type ?? ''} />
                            <span className="font-medium text-gray-700">{env?.organization_name} / {env?.name}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <EnvRoleBadge role={r.role} />
                            <button onClick={() => setEnvRoleDrafts(d => d.filter((_, j) => j !== i))} className="text-gray-300 hover:text-red-500"><X className="w-3 h-3" /></button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>

              {createMut.isError && <div className="text-xs text-red-600 p-2 bg-red-50 rounded">Failed to create user. Check details and try again.</div>}
              <div className="flex justify-between gap-2 pt-1 border-t">
                <button onClick={() => setCreateStep(1)} className="btn-secondary text-sm">← Back</button>
                <div className="flex gap-2">
                  <button onClick={resetCreateModal} className="btn-secondary text-sm">Cancel</button>
                  <button onClick={() => createMut.mutate()} disabled={createMut.isPending} className="btn-primary text-sm">
                    {createMut.isPending ? 'Creating…' : `Create User${orgRoleDrafts.length + envRoleDrafts.length > 0 ? ` + ${orgRoleDrafts.length + envRoleDrafts.length} role${orgRoleDrafts.length + envRoleDrafts.length > 1 ? 's' : ''}` : ''}`}
                  </button>
                </div>
              </div>
            </div>
          )}
        </Modal>
      )}

      {/* Edit User Modal */}
      {editUser && (
        <Modal open={true} title={`Edit: ${editUser.full_name ?? editUser.email}`} onClose={() => setEditUser(null)}>
          <div className="space-y-3 p-4">
            <div><label className="label">Full Name</label><input className="input" value={editForm.full_name} onChange={e => setEditForm(f => ({ ...f, full_name: e.target.value }))} /></div>
            <div>
              <label className="label">Permission Group</label>
              <select className="select" value={editForm.group_id} onChange={e => setEditForm(f => ({ ...f, group_id: e.target.value }))}>
                <option value="">None</option>
                {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
              </select>
            </div>
            <div><label className="label">New Password (leave blank to keep current)</label><input className="input" type="password" value={editForm.password} onChange={e => setEditForm(f => ({ ...f, password: e.target.value }))} /></div>
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input type="checkbox" checked={editForm.is_active} onChange={e => setEditForm(f => ({ ...f, is_active: e.target.checked }))} className="w-4 h-4 text-blue-600 border-gray-300 rounded" />
                Active
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input type="checkbox" checked={editForm.is_superadmin} onChange={e => setEditForm(f => ({ ...f, is_superadmin: e.target.checked }))} className="w-4 h-4 text-blue-600 border-gray-300 rounded" />
                Superadmin
              </label>
            </div>
            {updateMut.isError && <div className="text-xs text-red-600 p-2 bg-red-50 rounded">Failed to update user.</div>}
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setEditUser(null)} className="btn-secondary text-sm">Cancel</button>
              <button
                onClick={() => updateMut.mutate({ id: editUser.id, data: { full_name: editForm.full_name || undefined, group_id: editForm.group_id || '', is_active: editForm.is_active, is_superadmin: editForm.is_superadmin, password: editForm.password || undefined } })}
                disabled={updateMut.isPending}
                className="btn-primary text-sm"
              >
                {updateMut.isPending ? 'Saving…' : 'Save Changes'}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* Delete Confirm */}
      {deleteConfirm && (
        <Modal open={true} title="Delete User" onClose={() => setDeleteConfirm(null)}>
          <div className="p-4 space-y-3">
            <p className="text-sm text-gray-700">This will permanently delete the user and all their role assignments. Are you sure?</p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setDeleteConfirm(null)} className="btn-secondary text-sm">Cancel</button>
              <button onClick={() => deleteMut.mutate(deleteConfirm)} disabled={deleteMut.isPending} className="btn-danger text-sm">
                {deleteMut.isPending ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* Access Drawer */}
      {accessUserId && (
        <>
          <div className="fixed inset-0 bg-black/20 z-40" onClick={() => setAccessUserId(null)} />
          <UserAccessDrawer
            userId={accessUserId}
            onClose={() => setAccessUserId(null)}
            groups={groups}
            orgs={orgs}
            envs={envs}
          />
        </>
      )}
    </div>
  )
}

// ── Groups Tab ────────────────────────────────────────────────────────────────

function GroupsTab() {
  const qc = useQueryClient()
  const { data: groups = [], isLoading } = useQuery({ queryKey: ['admin-groups'], queryFn: fetchAdminGroups })
  const [creating, setCreating] = useState(false)
  const [editGroup, setEditGroup] = useState<AdminGroup | null>(null)
  const [newGroupForm, setNewGroupForm] = useState({ name: '', description: '', permissions: [] as string[] })
  const [editPerms, setEditPerms] = useState<string[]>([])
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)

  const createMut = useMutation({
    mutationFn: createAdminGroup,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-groups'] }); setCreating(false); setNewGroupForm({ name: '', description: '', permissions: [] }) },
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof updateAdminGroup>[1] }) => updateAdminGroup(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-groups'] }); setEditGroup(null) },
  })

  const deleteMut = useMutation({
    mutationFn: deleteAdminGroup,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-groups'] }); setDeleteConfirm(null) },
  })

  const openEdit = (g: AdminGroup) => { setEditPerms([...g.permissions]); setEditGroup(g) }

  if (isLoading) return <div className="flex items-center justify-center h-48 text-gray-400 text-sm">Loading groups…</div>

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Permission Groups</h2>
          <p className="text-xs text-gray-500 mt-0.5">Groups define what features users can access when their environment role is MEMBER or above</p>
        </div>
        <button onClick={() => setCreating(true)} className="btn-primary flex items-center gap-1.5 text-sm py-1.5 px-3">
          <Plus className="w-4 h-4" /> New Group
        </button>
      </div>

      {/* Role hierarchy legend */}
      <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
        <div className="text-xs font-semibold text-blue-800 mb-2 flex items-center gap-1"><Eye className="w-3.5 h-3.5" /> Environment Role × Permission Group</div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-blue-700">
          <div><EnvRoleBadge role="VIEWER" /> → read-only regardless of group</div>
          <div><EnvRoleBadge role="MEMBER" /> → group permissions apply</div>
          <div><EnvRoleBadge role="ADMIN" /> → group permissions + member management</div>
          <div><EnvRoleBadge role="OWNER" /> → full control + environment settings</div>
        </div>
      </div>

      <div className="grid gap-4">
        {groups.map(g => (
          <div key={g.id} className="card">
            <div className="flex items-start justify-between mb-3">
              <div>
                <div className="flex items-center gap-2">
                  <Shield className="w-4 h-4 text-indigo-500" />
                  <span className="font-semibold text-gray-900">{g.name}</span>
                  <span className="text-xs text-gray-500 bg-gray-100 rounded-full px-2 py-0.5">{g.user_count} users</span>
                </div>
                {g.description && <div className="text-xs text-gray-500 mt-0.5 ml-6">{g.description}</div>}
              </div>
              <div className="flex gap-1">
                <button onClick={() => openEdit(g)} className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded"><Pencil className="w-4 h-4" /></button>
                <button onClick={() => setDeleteConfirm(g.id)} className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded"><Trash2 className="w-4 h-4" /></button>
              </div>
            </div>
            <div className="flex flex-wrap gap-1">
              {g.permissions.includes('*')
                ? <span className="inline-flex items-center text-xs bg-purple-100 text-purple-700 border border-purple-200 rounded px-2 py-0.5 font-medium">⭐ All permissions</span>
                : g.permissions.length > 0
                  ? g.permissions.map(p => <PermissionBadge key={p} perm={p} />)
                  : <span className="text-xs text-gray-400 italic">No permissions</span>
              }
            </div>
          </div>
        ))}
      </div>

      {/* Create Group Modal */}
      {creating && (
        <Modal open={true} title="Create Permission Group" onClose={() => setCreating(false)}>
          <div className="space-y-4 p-4">
            <div><label className="label">Name *</label><input className="input" value={newGroupForm.name} onChange={e => setNewGroupForm(f => ({ ...f, name: e.target.value }))} /></div>
            <div><label className="label">Description</label><input className="input" value={newGroupForm.description} onChange={e => setNewGroupForm(f => ({ ...f, description: e.target.value }))} /></div>
            <div><label className="label">Permissions</label><PermissionGrid selected={newGroupForm.permissions} onChange={p => setNewGroupForm(f => ({ ...f, permissions: p }))} /></div>
            {createMut.isError && <div className="text-xs text-red-600 p-2 bg-red-50 rounded">Failed to create group.</div>}
            <div className="flex justify-end gap-2">
              <button onClick={() => setCreating(false)} className="btn-secondary text-sm">Cancel</button>
              <button onClick={() => createMut.mutate({ name: newGroupForm.name, description: newGroupForm.description || undefined, permissions: newGroupForm.permissions })} disabled={createMut.isPending || !newGroupForm.name} className="btn-primary text-sm">
                {createMut.isPending ? 'Creating…' : 'Create Group'}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* Edit Group Modal */}
      {editGroup && (
        <Modal open={true} title={`Edit: ${editGroup.name}`} onClose={() => setEditGroup(null)}>
          <div className="space-y-4 p-4">
            <PermissionGrid selected={editPerms} onChange={setEditPerms} />
            {updateMut.isError && <div className="text-xs text-red-600 p-2 bg-red-50 rounded">Failed to update group.</div>}
            <div className="flex justify-end gap-2">
              <button onClick={() => setEditGroup(null)} className="btn-secondary text-sm">Cancel</button>
              <button onClick={() => updateMut.mutate({ id: editGroup.id, data: { permissions: editPerms } })} disabled={updateMut.isPending} className="btn-primary text-sm">
                {updateMut.isPending ? 'Saving…' : 'Save Permissions'}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* Delete Confirm */}
      {deleteConfirm && (
        <Modal open={true} title="Delete Group" onClose={() => setDeleteConfirm(null)}>
          <div className="p-4 space-y-3">
            <p className="text-sm text-gray-700">Delete this permission group? Users in this group will lose their permissions.</p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setDeleteConfirm(null)} className="btn-secondary text-sm">Cancel</button>
              <button onClick={() => deleteMut.mutate(deleteConfirm)} disabled={deleteMut.isPending} className="btn-danger text-sm">
                {deleteMut.isPending ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}

// ── Access Control Tab ────────────────────────────────────────────────────────

function AccessControlTab({ orgs, envs, users }: { orgs: OrgInfo[]; envs: EnvInfo[]; users: AdminUser[] }) {
  const qc = useQueryClient()
  const [view, setView] = useState<'orgs' | 'envs'>('orgs')
  const [addMember, setAddMember] = useState<{ type: 'org' | 'env'; id: string; name: string } | null>(null)
  const [newUserId, setNewUserId] = useState('')
  const [newRole, setNewRole] = useState('ORG_MEMBER')

  // Org members
  const orgMembersQueries = orgs.map(org => ({
    id: org.id,
    name: org.name,
    query: useQuery({
      queryKey: ['org-members', org.id],
      queryFn: () => api.get<Array<{ user_id: string; user_email: string; user_name: string | null; role: string; granted_at: string }>>(`/organizations/${org.id}/members`).then(r => r.data),
    }),
  }))

  // Env members
  const envMembersQueries = envs.map(env => ({
    id: env.id,
    name: env.name,
    env_type: env.env_type,
    org_name: env.organization_name,
    query: useQuery({
      queryKey: ['env-members', env.id],
      queryFn: () => api.get<Array<{ id: string; user_id: string; user_email: string; user_name: string; role: string; created_at: string }>>(`/environments/${env.id}/members`).then(r => r.data),
    }),
  }))

  const grantOrgMut = useMutation({
    mutationFn: ({ orgId, userId, role }: { orgId: string; userId: string; role: string }) =>
      api.post(`/organizations/${orgId}/members`, { user_id: userId, role }),
    onSuccess: (_, { orgId }) => { qc.invalidateQueries({ queryKey: ['org-members', orgId] }); setAddMember(null); setNewUserId('') },
  })

  const revokeOrgMut = useMutation({
    mutationFn: ({ orgId, userId }: { orgId: string; userId: string }) =>
      api.delete(`/organizations/${orgId}/members/${userId}`),
    onSuccess: (_, { orgId }) => qc.invalidateQueries({ queryKey: ['org-members', orgId] }),
  })

  const grantEnvMut = useMutation({
    mutationFn: ({ envId, userId, role }: { envId: string; userId: string; role: string }) =>
      api.post(`/environments/${envId}/members`, { user_id: userId, role }),
    onSuccess: (_, { envId }) => { qc.invalidateQueries({ queryKey: ['env-members', envId] }); setAddMember(null); setNewUserId('') },
  })

  const revokeEnvMut = useMutation({
    mutationFn: ({ envId, userId }: { envId: string; userId: string }) =>
      api.delete(`/environments/${envId}/members/${userId}`),
    onSuccess: (_, { envId }) => qc.invalidateQueries({ queryKey: ['env-members', envId] }),
  })

  const openAdd = (type: 'org' | 'env', id: string, name: string) => {
    setNewRole(type === 'org' ? 'ORG_MEMBER' : 'MEMBER')
    setNewUserId('')
    setAddMember({ type, id, name })
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Access Control</h2>
          <p className="text-xs text-gray-500 mt-0.5">Manage who can access each organization and environment</p>
        </div>
        <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
          <button onClick={() => setView('orgs')} className={`px-3 py-1.5 flex items-center gap-1.5 ${view === 'orgs' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>
            <Building2 className="w-3.5 h-3.5" /> Organizations
          </button>
          <button onClick={() => setView('envs')} className={`px-3 py-1.5 flex items-center gap-1.5 ${view === 'envs' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>
            <Globe className="w-3.5 h-3.5" /> Environments
          </button>
        </div>
      </div>

      {view === 'orgs' && (
        <div className="space-y-4">
          {orgMembersQueries.map(({ id, name, query }) => (
            <div key={id} className="card">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Building2 className="w-4 h-4 text-gray-400" />
                  <span className="font-semibold text-gray-900">{name}</span>
                  <span className="text-xs text-gray-400">({query.data?.length ?? 0} members)</span>
                </div>
                <button onClick={() => openAdd('org', id, name)} className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1">
                  <Plus className="w-3.5 h-3.5" /> Add member
                </button>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="table-header">User</th>
                    <th className="table-header">Org Role</th>
                    <th className="table-header">Granted</th>
                    <th className="table-header w-8"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {(query.data ?? []).map(m => (
                    <tr key={m.user_id} className="hover:bg-gray-50">
                      <td className="table-cell">
                        <div className="font-medium text-gray-800">{m.user_name ?? m.user_email}</div>
                        {m.user_name && <div className="text-xs text-gray-500">{m.user_email}</div>}
                      </td>
                      <td className="table-cell"><OrgRoleBadge role={m.role} /></td>
                      <td className="table-cell text-xs text-gray-400">{new Date(m.granted_at).toLocaleDateString()}</td>
                      <td className="table-cell">
                        <button onClick={() => revokeOrgMut.mutate({ orgId: id, userId: m.user_id })} className="p-1 text-gray-300 hover:text-red-500 rounded"><X className="w-3.5 h-3.5" /></button>
                      </td>
                    </tr>
                  ))}
                  {!query.isLoading && (query.data ?? []).length === 0 && (
                    <tr><td colSpan={4} className="table-cell text-xs text-gray-400 italic text-center py-3">No members yet</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      {view === 'envs' && (
        <div className="space-y-4">
          {envMembersQueries.map(({ id, name, env_type, org_name, query }) => (
            <div key={id} className="card">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <EnvTypeDot type={env_type} />
                  <span className="font-semibold text-gray-900">{name}</span>
                  <span className="text-xs text-gray-400">· {org_name}</span>
                  <span className="text-xs text-gray-300">({query.data?.length ?? 0})</span>
                </div>
                <button onClick={() => openAdd('env', id, name)} className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1">
                  <Plus className="w-3.5 h-3.5" /> Add member
                </button>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="table-header">User</th>
                    <th className="table-header">Env Role</th>
                    <th className="table-header">Effective Access</th>
                    <th className="table-header">Granted</th>
                    <th className="table-header w-8"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {(query.data ?? []).map(m => (
                    <tr key={m.user_id} className="hover:bg-gray-50">
                      <td className="table-cell">
                        <div className="font-medium text-gray-800">{m.user_name ?? m.user_email}</div>
                        {m.user_name && <div className="text-xs text-gray-500">{m.user_email}</div>}
                      </td>
                      <td className="table-cell"><EnvRoleBadge role={m.role} /></td>
                      <td className="table-cell text-xs text-gray-500">
                        {m.role === 'VIEWER' ? '👁 Read-only' :
                         m.role === 'MEMBER' ? '✏️ Group permissions' :
                         m.role === 'ADMIN' ? '⚙️ Full + manage members' : '👑 Full control'}
                      </td>
                      <td className="table-cell text-xs text-gray-400">{new Date(m.created_at).toLocaleDateString()}</td>
                      <td className="table-cell">
                        <button onClick={() => revokeEnvMut.mutate({ envId: id, userId: m.user_id })} className="p-1 text-gray-300 hover:text-red-500 rounded"><X className="w-3.5 h-3.5" /></button>
                      </td>
                    </tr>
                  ))}
                  {!query.isLoading && (query.data ?? []).length === 0 && (
                    <tr><td colSpan={5} className="table-cell text-xs text-gray-400 italic text-center py-3">No members yet</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      {/* Add Member Modal */}
      {addMember && (
        <Modal open={true} title={`Add member to ${addMember.name}`} onClose={() => setAddMember(null)}>
          <div className="space-y-3 p-4">
            <div>
              <label className="label">User</label>
              <select className="select" value={newUserId} onChange={e => setNewUserId(e.target.value)}>
                <option value="">Select user…</option>
                {users.map(u => <option key={u.id} value={u.id}>{u.full_name ? `${u.full_name} (${u.email})` : u.email}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Role</label>
              <div className="space-y-1.5">
                {(addMember.type === 'org' ? ORG_ROLES : ENV_ROLES).map(r => (
                  <label key={r.value} className={`flex items-center gap-3 p-2.5 rounded-lg border cursor-pointer transition-colors ${newRole === r.value ? 'border-blue-400 bg-blue-50' : 'border-gray-200 hover:bg-gray-50'}`}>
                    <input type="radio" name="role" value={r.value} checked={newRole === r.value} onChange={() => setNewRole(r.value)} className="text-blue-600" />
                    <div>
                      <div className="flex items-center gap-2">
                        {addMember.type === 'org' ? <OrgRoleBadge role={r.value} /> : <EnvRoleBadge role={r.value} />}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">{r.desc}</div>
                    </div>
                  </label>
                ))}
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <button onClick={() => setAddMember(null)} className="btn-secondary text-sm">Cancel</button>
              <button
                onClick={() => {
                  if (!newUserId) return
                  if (addMember.type === 'org') grantOrgMut.mutate({ orgId: addMember.id, userId: newUserId, role: newRole })
                  else grantEnvMut.mutate({ envId: addMember.id, userId: newUserId, role: newRole })
                }}
                disabled={!newUserId || grantOrgMut.isPending || grantEnvMut.isPending}
                className="btn-primary text-sm"
              >
                Grant Access
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}

// ── Access Matrix Tab ─────────────────────────────────────────────────────────

function MatrixTab({ users, envs }: { users: AdminUser[]; envs: EnvInfo[] }) {
  const envAccessQueries = envs.map(env => ({
    env,
    query: useQuery({
      queryKey: ['env-members', env.id],
      queryFn: () => api.get<Array<{ user_id: string; role: string }>>(`/environments/${env.id}/members`).then(r => r.data),
    }),
  }))

  const getRoleForUser = (userId: string, envId: string): string | null => {
    const envQuery = envAccessQueries.find(q => q.env.id === envId)
    return envQuery?.query.data?.find(m => m.user_id === userId)?.role ?? null
  }

  return (
    <div>
      <div className="mb-4">
        <h2 className="text-base font-semibold text-gray-900">Access Matrix</h2>
        <p className="text-xs text-gray-500 mt-0.5">At-a-glance view of who has access to each environment</p>
      </div>
      <div className="card overflow-x-auto p-0">
        <table className="text-xs min-w-full">
          <thead>
            <tr className="border-b bg-gray-50">
              <th className="text-left px-3 py-2.5 text-gray-500 font-medium sticky left-0 bg-gray-50 min-w-[160px]">User</th>
              {envs.map(env => (
                <th key={env.id} className="text-center px-2 py-2.5 text-gray-500 font-medium min-w-[100px]">
                  <div className="flex flex-col items-center gap-1">
                    <EnvTypeDot type={env.env_type} />
                    <span className="text-[10px] leading-tight">{env.name}</span>
                    <span className="text-[9px] text-gray-400">{env.organization_name}</span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {users.map(u => {
              const platformRole = (u as AdminUser & { platform_role?: string }).platform_role ?? (u.is_superadmin ? 'SUPERADMIN' : 'USER')
              const isSuperadmin = u.is_superadmin
              return (
                <tr key={u.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2 sticky left-0 bg-white hover:bg-gray-50">
                    <div className="font-medium text-gray-800">{u.full_name ?? u.email}</div>
                    <PlatformRoleBadge role={platformRole} />
                  </td>
                  {envs.map(env => {
                    const role = getRoleForUser(u.id, env.id)
                    return (
                      <td key={env.id} className="text-center px-2 py-2">
                        {isSuperadmin
                          ? <span className="text-[10px] text-purple-600 font-medium">all access</span>
                          : role
                          ? <EnvRoleBadge role={role} />
                          : <span className="text-gray-200">—</span>}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Main Admin Page ───────────────────────────────────────────────────────────

const TABS = [
  { id: 'users',   label: 'Users',          icon: Users },
  { id: 'groups',  label: 'Groups & Permissions', icon: Shield },
  { id: 'access',  label: 'Access Control', icon: Layers },
  { id: 'matrix',  label: 'Access Matrix',  icon: Settings },
]

export default function Admin() {
  const [tab, setTab] = useState('users')

  const { data: users = [] } = useQuery({ queryKey: ['admin-users'], queryFn: fetchAdminUsers })
  const { data: groups = [] } = useQuery({ queryKey: ['admin-groups'], queryFn: fetchAdminGroups })
  const { data: orgs = [] } = useQuery<OrgInfo[]>({
    queryKey: ['organizations'],
    queryFn: () => api.get<OrgInfo[]>('/organizations').then(r => r.data),
  })
  const { data: envs = [] } = useQuery<EnvInfo[]>({
    queryKey: ['environments'],
    queryFn: () => api.get<EnvInfo[]>('/environments').then(r => r.data),
  })

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-gray-900">Admin Console</h1>
        <p className="text-sm text-gray-500 mt-1">Manage users, permission groups, and access control across organizations and environments</p>
      </div>

      {/* Role hierarchy callout */}
      <div className="mb-5 p-3 bg-gray-50 border border-gray-200 rounded-lg flex items-start gap-3">
        <Key className="w-4 h-4 text-gray-400 mt-0.5 shrink-0" />
        <div className="text-xs text-gray-600 space-y-0.5">
          <div className="font-medium text-gray-700 mb-1">Permission hierarchy</div>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <span><PlatformRoleBadge role="PLATFORM_OWNER" /> → God mode, full access everywhere</span>
            <span><PlatformRoleBadge role="SUPERADMIN" /> → Admin access to all orgs/envs</span>
            <span><PlatformRoleBadge role="USER" /> → Access via Org Role + Env Role only</span>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1">
            <span><OrgRoleBadge role="ORG_OWNER" /> → Manage org, create/delete envs</span>
            <span><OrgRoleBadge role="ORG_ADMIN" /> → Create envs, manage members</span>
            <span><OrgRoleBadge role="ORG_MEMBER" /> → Access to granted envs</span>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1">
            <span><EnvRoleBadge role="OWNER" /> → Full env control</span>
            <span><EnvRoleBadge role="ADMIN" /> → Full + manage members</span>
            <span><EnvRoleBadge role="MEMBER" /> → Group permissions</span>
            <span><EnvRoleBadge role="VIEWER" /> → Read-only</span>
          </div>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 mb-6 border-b border-gray-200">
        {TABS.map(t => {
          const Icon = t.icon
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
                tab === t.id
                  ? 'border-blue-600 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              <Icon className="w-4 h-4" /> {t.label}
            </button>
          )
        })}
      </div>

      {tab === 'users' && <UsersTab groups={groups} orgs={orgs} envs={envs} />}
      {tab === 'groups' && <GroupsTab />}
      {tab === 'access' && <AccessControlTab orgs={orgs} envs={envs} users={users} />}
      {tab === 'matrix' && <MatrixTab users={users} envs={envs} />}
    </div>
  )
}
