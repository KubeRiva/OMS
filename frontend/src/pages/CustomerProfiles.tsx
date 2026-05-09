import { useState } from 'react'
import { NavLink, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchCustomerProfiles, createCustomerProfile, updateCustomerProfile,
  deleteCustomerProfile, syncCustomerProfileStats, fetchCustomerProfileOrders,
  addCustomerProfileAddress, deleteCustomerProfileAddress, getBrands,
  type CustomerProfile,
} from '../api/client'
import { useAuth } from '../context/AuthContext'
import { StatusBadge } from '../components/Badge'
import {
  User, Plus, Search, ChevronDown, ChevronUp, Pencil, Trash2,
  RefreshCw, MapPin, ShoppingBag, Shield,
} from 'lucide-react'

const PAGE_SIZE = 20

type ModalMode = 'create' | 'edit' | null

interface ProfileForm {
  email: string
  first_name: string
  last_name: string
  phone: string
  brand_id: string
  tags: string
  email_opt_in: boolean
  sms_opt_in: boolean
  preferred_language: string
  notes: string
}

const EMPTY_FORM: ProfileForm = {
  email: '',
  first_name: '',
  last_name: '',
  phone: '',
  brand_id: '',
  tags: '',
  email_opt_in: true,
  sms_opt_in: false,
  preferred_language: 'en-US',
  notes: '',
}

interface AddressForm {
  label: string
  is_default: boolean
  first_name: string
  last_name: string
  address1: string
  address2: string
  city: string
  state: string
  postal_code: string
  country: string
  phone: string
}

const EMPTY_ADDRESS_FORM: AddressForm = {
  label: '',
  is_default: false,
  first_name: '',
  last_name: '',
  address1: '',
  address2: '',
  city: '',
  state: '',
  postal_code: '',
  country: 'US',
  phone: '',
}

function formatDate(s?: string): string {
  if (!s) return '—'
  return new Date(s).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function formatCurrency(val: string | number | undefined): string {
  const n = parseFloat(String(val ?? 0))
  return isNaN(n) ? '$0.00' : `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function getErrMsg(e: unknown): string {
  const err = e as { response?: { data?: { detail?: unknown } } }
  const detail = err.response?.data?.detail
  if (Array.isArray(detail)) return detail.map((d: { msg: string }) => d.msg).join(', ')
  if (typeof detail === 'string') return detail
  return 'An error occurred'
}

// ─── Expanded row subcomponent ────────────────────────────────────────────────

interface ExpandedRowProps {
  profile: CustomerProfile
  onAddressAdded: () => void
}

function ExpandedRow({ profile, onAddressAdded }: ExpandedRowProps) {
  const qc = useQueryClient()
  const [showAddressForm, setShowAddressForm] = useState(false)
  const [addressForm, setAddressForm] = useState<AddressForm>(EMPTY_ADDRESS_FORM)
  const [addressError, setAddressError] = useState('')
  const [syncing, setSyncing] = useState(false)

  const { data: orders, isLoading: ordersLoading } = useQuery({
    queryKey: ['customer-profile-orders', profile.id],
    queryFn: () => fetchCustomerProfileOrders(profile.id, { skip: 0, limit: 5 }),
  })

  const addAddressMutation = useMutation({
    mutationFn: (data: AddressForm) => addCustomerProfileAddress(profile.id, {
      label: data.label || undefined,
      is_default: data.is_default,
      first_name: data.first_name || undefined,
      last_name: data.last_name || undefined,
      address1: data.address1,
      address2: data.address2 || undefined,
      city: data.city,
      state: data.state,
      postal_code: data.postal_code,
      country: data.country || 'US',
      phone: data.phone || undefined,
    }),
    onSuccess: () => {
      setShowAddressForm(false)
      setAddressForm(EMPTY_ADDRESS_FORM)
      setAddressError('')
      qc.invalidateQueries({ queryKey: ['customer-profiles'] })
      onAddressAdded()
    },
    onError: (e: unknown) => setAddressError(getErrMsg(e)),
  })

  const deleteAddressMutation = useMutation({
    mutationFn: (addressId: string) => deleteCustomerProfileAddress(profile.id, addressId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['customer-profiles'] })
      onAddressAdded()
    },
  })

  function af(field: keyof AddressForm) {
    return (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = e.target.type === 'checkbox' ? (e.target as HTMLInputElement).checked : e.target.value
      setAddressForm(prev => ({ ...prev, [field]: val }))
    }
  }

  function handleAddAddress() {
    if (!addressForm.address1.trim() || !addressForm.city.trim() || !addressForm.state.trim() || !addressForm.postal_code.trim()) {
      setAddressError('Address, city, state, and postal code are required')
      return
    }
    setAddressError('')
    addAddressMutation.mutate(addressForm)
  }

  async function handleSync() {
    setSyncing(true)
    try {
      await syncCustomerProfileStats(profile.id)
      qc.invalidateQueries({ queryKey: ['customer-profiles'] })
    } finally {
      setSyncing(false)
    }
  }

  return (
    <tr className="bg-gray-50">
      <td colSpan={9} className="px-6 py-4">
        <div className="grid grid-cols-2 gap-6">
          {/* Left: Addresses */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs font-semibold text-gray-400 uppercase flex items-center gap-1.5">
                <MapPin className="w-3.5 h-3.5" /> Saved Addresses
              </div>
              <button
                className="text-xs text-blue-600 hover:text-blue-700 font-medium"
                onClick={() => { setShowAddressForm(!showAddressForm); setAddressError('') }}
              >
                {showAddressForm ? 'Cancel' : '+ Add Address'}
              </button>
            </div>

            {profile.addresses.length === 0 && !showAddressForm && (
              <p className="text-xs text-gray-400 italic">No saved addresses</p>
            )}

            <div className="space-y-2">
              {profile.addresses.map(addr => (
                <div key={addr.id} className="flex items-start justify-between bg-white rounded border border-gray-100 px-3 py-2 text-xs">
                  <div>
                    <div className="flex items-center gap-1.5 mb-0.5">
                      {addr.label && <span className="font-medium text-gray-700">{addr.label}</span>}
                      {addr.is_default && (
                        <span className="inline-flex px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 text-[10px] font-medium">Default</span>
                      )}
                    </div>
                    {(addr.first_name || addr.last_name) && (
                      <div className="text-gray-600">{[addr.first_name, addr.last_name].filter(Boolean).join(' ')}</div>
                    )}
                    <div className="text-gray-600">{addr.address1}{addr.address2 ? `, ${addr.address2}` : ''}</div>
                    <div className="text-gray-500">{[addr.city, addr.state, addr.postal_code].filter(Boolean).join(', ')} {addr.country}</div>
                  </div>
                  <button
                    className="p-1 rounded hover:bg-red-50 text-gray-400 hover:text-red-600 flex-shrink-0 ml-2"
                    title="Delete address"
                    onClick={() => {
                      if (confirm('Delete this address?')) {
                        deleteAddressMutation.mutate(addr.id)
                      }
                    }}
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>

            {showAddressForm && (
              <div className="mt-3 bg-white border border-gray-200 rounded-lg p-3 space-y-2 text-xs">
                <div className="text-xs font-semibold text-gray-500 uppercase mb-1">New Address</div>
                {addressError && <div className="text-red-600 bg-red-50 px-2 py-1 rounded">{addressError}</div>}
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="label text-[11px]">Label</label>
                    <input className="input w-full text-xs py-1" placeholder="Home, Work..." value={addressForm.label} onChange={af('label')} />
                  </div>
                  <div className="flex items-end pb-1">
                    <label className="flex items-center gap-1.5 cursor-pointer">
                      <input type="checkbox" checked={addressForm.is_default} onChange={af('is_default')} className="rounded" />
                      <span className="text-gray-700 text-xs">Set as default</span>
                    </label>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="label text-[11px]">First Name</label>
                    <input className="input w-full text-xs py-1" value={addressForm.first_name} onChange={af('first_name')} />
                  </div>
                  <div>
                    <label className="label text-[11px]">Last Name</label>
                    <input className="input w-full text-xs py-1" value={addressForm.last_name} onChange={af('last_name')} />
                  </div>
                </div>
                <div>
                  <label className="label text-[11px]">Address *</label>
                  <input className="input w-full text-xs py-1" value={addressForm.address1} onChange={af('address1')} />
                </div>
                <div>
                  <label className="label text-[11px]">Address 2</label>
                  <input className="input w-full text-xs py-1" value={addressForm.address2} onChange={af('address2')} />
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <label className="label text-[11px]">City *</label>
                    <input className="input w-full text-xs py-1" value={addressForm.city} onChange={af('city')} />
                  </div>
                  <div>
                    <label className="label text-[11px]">State *</label>
                    <input className="input w-full text-xs py-1" value={addressForm.state} onChange={af('state')} />
                  </div>
                  <div>
                    <label className="label text-[11px]">ZIP *</label>
                    <input className="input w-full text-xs py-1" value={addressForm.postal_code} onChange={af('postal_code')} />
                  </div>
                </div>
                <div className="flex justify-end gap-2 pt-1">
                  <button
                    className="btn-secondary text-xs py-1 px-3"
                    onClick={() => { setShowAddressForm(false); setAddressError('') }}
                  >
                    Cancel
                  </button>
                  <button
                    className="btn-primary text-xs py-1 px-3"
                    disabled={addAddressMutation.isPending}
                    onClick={handleAddAddress}
                  >
                    {addAddressMutation.isPending ? 'Saving...' : 'Save Address'}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Right: Recent Orders + Sync */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs font-semibold text-gray-400 uppercase flex items-center gap-1.5">
                <ShoppingBag className="w-3.5 h-3.5" /> Recent Orders
              </div>
              <button
                className="text-xs text-gray-500 hover:text-blue-600 flex items-center gap-1 font-medium"
                onClick={handleSync}
                disabled={syncing}
                title="Sync order stats"
              >
                <RefreshCw className={`w-3 h-3 ${syncing ? 'animate-spin' : ''}`} />
                Sync Stats
              </button>
            </div>

            {ordersLoading ? (
              <div className="text-xs text-gray-400">Loading orders...</div>
            ) : !orders?.length ? (
              <p className="text-xs text-gray-400 italic">No orders found</p>
            ) : (
              <div className="space-y-1.5">
                {orders.map(order => (
                  <div key={order.id} className="flex items-center justify-between bg-white rounded border border-gray-100 px-3 py-2 text-xs">
                    <div>
                      <span className="font-mono font-medium text-gray-800">{order.order_number}</span>
                      <span className="text-gray-400 ml-2">{formatDate(order.created_at)}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-gray-700">{formatCurrency(order.total_amount)}</span>
                      <StatusBadge value={order.status} />
                    </div>
                  </div>
                ))}
              </div>
            )}

            {profile.total_orders > 5 && (
              <Link
                to={`/orders?customer_email=${encodeURIComponent(profile.email)}`}
                className="mt-2 inline-block text-xs text-blue-600 hover:text-blue-700 font-medium"
              >
                View all {profile.total_orders} orders →
              </Link>
            )}
          </div>
        </div>
      </td>
    </tr>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function CustomerProfiles() {
  const qc = useQueryClient()
  const { user } = useAuth()

  const [emailFilter, setEmailFilter] = useState('')
  const [brandFilter, setBrandFilter] = useState('')
  const [activeFilter, setActiveFilter] = useState<'true' | 'false' | ''>('')
  const [skip, setSkip] = useState(0)

  const [modal, setModal] = useState<ModalMode>(null)
  const [selectedProfile, setSelectedProfile] = useState<CustomerProfile | null>(null)
  const [form, setForm] = useState<ProfileForm>(EMPTY_FORM)
  const [error, setError] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Access control
  if (!user?.is_superadmin) {
    return (
      <div className="flex flex-col items-center justify-center h-96 gap-4 text-center">
        <Shield className="w-10 h-10 text-gray-300" />
        <div>
          <p className="text-lg font-semibold text-gray-600">Access Restricted</p>
          <p className="text-sm text-gray-400 mt-1">Contact your administrator to access B2C Profiles.</p>
        </div>
      </div>
    )
  }

  const { data: brandsData } = useQuery({
    queryKey: ['brands', 'active'],
    queryFn: () => getBrands({ is_active: true }),
  })

  const { data, isLoading } = useQuery({
    queryKey: ['customer-profiles', emailFilter, brandFilter, activeFilter, skip],
    queryFn: () => fetchCustomerProfiles({
      email: emailFilter || undefined,
      brand_id: brandFilter || undefined,
      is_active: activeFilter === '' ? undefined : activeFilter === 'true',
      skip,
      limit: PAGE_SIZE,
    }),
    placeholderData: prev => prev,
  })

  const createMutation = useMutation({
    mutationFn: createCustomerProfile,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['customer-profiles'] }); closeModal() },
    onError: (e: unknown) => setError(getErrMsg(e)),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof updateCustomerProfile>[1] }) =>
      updateCustomerProfile(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['customer-profiles'] }); closeModal() },
    onError: (e: unknown) => setError(getErrMsg(e)),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteCustomerProfile,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['customer-profiles'] }),
    onError: (e: unknown) => setError(getErrMsg(e)),
  })

  function openCreate() {
    setForm(EMPTY_FORM)
    setError('')
    setModal('create')
  }

  function openEdit(profile: CustomerProfile) {
    setSelectedProfile(profile)
    setForm({
      email: profile.email,
      first_name: profile.first_name ?? '',
      last_name: profile.last_name ?? '',
      phone: profile.phone ?? '',
      brand_id: profile.brand_id ?? '',
      tags: profile.tags.join(', '),
      email_opt_in: profile.email_opt_in,
      sms_opt_in: profile.sms_opt_in,
      preferred_language: profile.preferred_language ?? 'en-US',
      notes: profile.notes ?? '',
    })
    setError('')
    setModal('edit')
  }

  function closeModal() {
    setModal(null)
    setSelectedProfile(null)
    setError('')
  }

  function f(field: keyof ProfileForm) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
      const val = e.target.type === 'checkbox'
        ? (e.target as HTMLInputElement).checked
        : e.target.value
      setForm(prev => ({ ...prev, [field]: val }))
    }
  }

  function handleSubmit() {
    if (!form.email.trim()) { setError('Email is required'); return }
    setError('')
    const tags = form.tags.split(',').map(t => t.trim()).filter(Boolean)
    const payload = {
      email: form.email.trim(),
      first_name: form.first_name || undefined,
      last_name: form.last_name || undefined,
      phone: form.phone || undefined,
      brand_id: form.brand_id || undefined,
      tags,
      email_opt_in: form.email_opt_in,
      sms_opt_in: form.sms_opt_in,
      preferred_language: form.preferred_language || undefined,
      notes: form.notes || undefined,
    }
    if (modal === 'create') {
      createMutation.mutate(payload)
    } else if (modal === 'edit' && selectedProfile) {
      const { email: _email, ...updatePayload } = payload
      updateMutation.mutate({ id: selectedProfile.id, data: updatePayload })
    }
  }

  const isPending = createMutation.isPending || updateMutation.isPending

  const currentPage = Math.floor(skip / PAGE_SIZE) + 1
  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 1

  const columns = ['Name', 'Email', 'Brand', 'Tags', 'Orders', 'Total Spent', 'Last Order', 'Status', '']

  return (
    <div className="space-y-6">
      {/* Tab strip */}
      <div className="flex border-b border-gray-200 -mb-6">
        <NavLink
          to="/customers"
          end
          className={({ isActive }) =>
            `px-4 py-2.5 text-sm font-medium border-b-2 -mb-px ${isActive ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`
          }
        >
          B2B Accounts
        </NavLink>
        <NavLink
          to="/customers/profiles"
          className={({ isActive }) =>
            `px-4 py-2.5 text-sm font-medium border-b-2 -mb-px ${isActive ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`
          }
        >
          B2C Profiles
        </NavLink>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <User className="w-6 h-6 text-blue-600" />
          <div>
            <h1 className="text-xl font-semibold text-gray-900">B2C Profiles</h1>
            <p className="text-sm text-gray-500">Consumer customer profiles</p>
          </div>
        </div>
        <button className="btn-primary flex items-center gap-2" onClick={openCreate}>
          <Plus className="w-4 h-4" /> New Profile
        </button>
      </div>

      {/* Filters */}
      <div className="card flex flex-wrap gap-3 items-center">
        <div className="flex-1 min-w-48 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            className="input pl-9 w-full"
            placeholder="Search by email..."
            value={emailFilter}
            onChange={e => { setEmailFilter(e.target.value); setSkip(0) }}
          />
        </div>
        {brandsData && brandsData.length > 0 && (
          <select
            className="select max-w-44"
            value={brandFilter}
            onChange={e => { setBrandFilter(e.target.value); setSkip(0) }}
          >
            <option value="">All Brands</option>
            {brandsData.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        )}
        <select
          className="select"
          value={activeFilter}
          onChange={e => { setActiveFilter(e.target.value as 'true' | 'false' | ''); setSkip(0) }}
        >
          <option value="">All</option>
          <option value="true">Active</option>
          <option value="false">Inactive</option>
        </select>
        {data && (
          <span className="text-sm text-gray-500 ml-auto">{data.total} profiles</span>
        )}
      </div>

      {/* Table */}
      <div className="card overflow-hidden p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100">
              {columns.map(h => (
                <th key={h} className="table-header">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {isLoading ? (
              <tr>
                <td colSpan={9} className="text-center py-12 text-gray-400">Loading...</td>
              </tr>
            ) : !data?.items.length ? (
              <tr>
                <td colSpan={9} className="text-center py-12 text-gray-400">No customer profiles found</td>
              </tr>
            ) : data.items.map(profile => (
              <>
                <tr
                  key={profile.id}
                  className={`hover:bg-gray-50 cursor-pointer ${!profile.is_active ? 'opacity-60' : ''}`}
                  onClick={() => setExpandedId(expandedId === profile.id ? null : profile.id)}
                >
                  {/* Name */}
                  <td className="table-cell">
                    <div className="flex items-center gap-2">
                      {expandedId === profile.id
                        ? <ChevronUp className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                        : <ChevronDown className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                      }
                      <div>
                        <div className="font-medium text-gray-900">
                          {[profile.first_name, profile.last_name].filter(Boolean).join(' ') || '—'}
                        </div>
                        {profile.phone && (
                          <div className="text-xs text-gray-400">{profile.phone}</div>
                        )}
                      </div>
                    </div>
                  </td>

                  {/* Email */}
                  <td className="table-cell text-gray-700 font-mono text-xs">{profile.email}</td>

                  {/* Brand */}
                  <td className="table-cell">
                    {profile.brand_id && brandsData ? (() => {
                      const brand = brandsData.find(b => b.id === profile.brand_id)
                      return brand ? (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-50 text-purple-700">
                          {brand.name}
                        </span>
                      ) : null
                    })() : <span className="text-gray-400">—</span>}
                  </td>

                  {/* Tags */}
                  <td className="table-cell">
                    <div className="flex flex-wrap gap-1 max-w-36">
                      {profile.tags.length === 0
                        ? <span className="text-gray-400">—</span>
                        : profile.tags.slice(0, 3).map(tag => (
                          <span key={tag} className="inline-flex px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 text-[10px]">
                            {tag}
                          </span>
                        ))
                      }
                      {profile.tags.length > 3 && (
                        <span className="text-[10px] text-gray-400">+{profile.tags.length - 3}</span>
                      )}
                    </div>
                  </td>

                  {/* Orders */}
                  <td className="table-cell text-gray-700">{profile.total_orders}</td>

                  {/* Total Spent */}
                  <td className="table-cell text-gray-700">{formatCurrency(profile.total_spent)}</td>

                  {/* Last Order */}
                  <td className="table-cell text-gray-500 text-xs">{formatDate(profile.last_order_at)}</td>

                  {/* Status */}
                  <td className="table-cell">
                    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${profile.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                      {profile.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>

                  {/* Actions */}
                  <td className="table-cell" onClick={e => e.stopPropagation()}>
                    <div className="flex items-center gap-1">
                      <button
                        title="Edit"
                        className="p-1.5 rounded hover:bg-gray-100 text-gray-500 hover:text-gray-700"
                        onClick={() => openEdit(profile)}
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      {user?.is_superadmin && (
                        <button
                          title="Delete profile"
                          className="p-1.5 rounded hover:bg-red-50 text-gray-500 hover:text-red-600"
                          onClick={() => {
                            if (confirm(`Delete profile for ${profile.email}? This will deactivate their account.`)) {
                              deleteMutation.mutate(profile.id)
                            }
                          }}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>

                {expandedId === profile.id && (
                  <ExpandedRow
                    key={`${profile.id}-detail`}
                    profile={profile}
                    onAddressAdded={() => qc.invalidateQueries({ queryKey: ['customer-profiles'] })}
                  />
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {data && data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm text-gray-500">
          <span>Page {currentPage} of {totalPages}</span>
          <div className="flex gap-2">
            <button
              className="btn-secondary"
              disabled={skip === 0}
              onClick={() => setSkip(s => Math.max(0, s - PAGE_SIZE))}
            >
              Previous
            </button>
            <button
              className="btn-secondary"
              disabled={skip + PAGE_SIZE >= (data?.total ?? 0)}
              onClick={() => setSkip(s => s + PAGE_SIZE)}
            >
              Next
            </button>
          </div>
        </div>
      )}

      {/* Create / Edit Modal */}
      {(modal === 'create' || modal === 'edit') && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <div className="p-6 border-b border-gray-100">
              <h2 className="text-lg font-semibold">
                {modal === 'create' ? 'New Customer Profile' : 'Edit Profile'}
              </h2>
            </div>
            <div className="p-6 space-y-5">
              {error && (
                <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">{error}</div>
              )}

              {/* Email */}
              <div>
                <label className="label">Email *</label>
                <input
                  className="input w-full"
                  type="email"
                  value={form.email}
                  onChange={f('email')}
                  disabled={modal === 'edit'}
                  placeholder="customer@example.com"
                />
              </div>

              {/* Name */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">First Name</label>
                  <input className="input w-full" value={form.first_name} onChange={f('first_name')} />
                </div>
                <div>
                  <label className="label">Last Name</label>
                  <input className="input w-full" value={form.last_name} onChange={f('last_name')} />
                </div>
              </div>

              {/* Phone */}
              <div>
                <label className="label">Phone</label>
                <input className="input w-full" type="tel" value={form.phone} onChange={f('phone')} placeholder="+1 555 000 0000" />
              </div>

              {/* Brand */}
              {brandsData && brandsData.length > 0 && (
                <div>
                  <label className="label">Brand</label>
                  <select className="select w-full" value={form.brand_id} onChange={f('brand_id')}>
                    <option value="">— No brand —</option>
                    {brandsData.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
                  </select>
                </div>
              )}

              {/* Tags */}
              <div>
                <label className="label">Tags</label>
                <input
                  className="input w-full"
                  value={form.tags}
                  onChange={f('tags')}
                  placeholder="vip, loyalty, wholesale (comma-separated)"
                />
                <p className="text-xs text-gray-400 mt-1">Separate multiple tags with commas</p>
              </div>

              {/* Opt-ins */}
              <div className="border-t pt-4">
                <div className="text-xs font-semibold text-gray-400 uppercase mb-3">Communication Preferences</div>
                <div className="flex gap-6">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" checked={form.email_opt_in} onChange={f('email_opt_in')} className="rounded" />
                    <span className="text-sm text-gray-700">Email opt-in</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" checked={form.sms_opt_in} onChange={f('sms_opt_in')} className="rounded" />
                    <span className="text-sm text-gray-700">SMS opt-in</span>
                  </label>
                </div>
              </div>

              {/* Preferred Language */}
              <div>
                <label className="label">Preferred Language</label>
                <input
                  className="input w-full"
                  value={form.preferred_language}
                  onChange={f('preferred_language')}
                  placeholder="en-US"
                />
              </div>

              {/* Notes */}
              <div>
                <label className="label">Notes</label>
                <textarea
                  className="input w-full h-20 resize-none"
                  value={form.notes}
                  onChange={f('notes')}
                  placeholder="Internal notes about this customer..."
                />
              </div>
            </div>

            <div className="p-6 border-t border-gray-100 flex justify-end gap-3">
              <button className="btn-secondary" onClick={closeModal}>Cancel</button>
              <button
                className="btn-primary"
                disabled={isPending || !form.email.trim()}
                onClick={handleSubmit}
              >
                {isPending ? 'Saving...' : modal === 'create' ? 'Create Profile' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
