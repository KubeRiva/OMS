import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchCustomerAccounts, createCustomerAccount, updateCustomerAccount,
  adjustCustomerCredit, deactivateCustomerAccount, getBrands,
  type CustomerAccount, type AccountType, type PricingTier,
} from '../api/client'
import { Building2, Plus, Search, ChevronDown, ChevronUp, DollarSign, Ban, Pencil } from 'lucide-react'

const ACCOUNT_TYPES: AccountType[] = ['PROSPECT', 'ACTIVE', 'INACTIVE', 'ON_HOLD']
const PRICING_TIERS: PricingTier[] = ['STANDARD', 'BRONZE', 'SILVER', 'GOLD', 'PLATINUM']
const PAYMENT_TERMS = ['PREPAID', 'NET_15', 'NET_30', 'NET_60', 'NET_90', 'COD', 'UPON_RECEIPT']

const ACCOUNT_TYPE_COLORS: Record<AccountType, string> = {
  PROSPECT: 'bg-gray-100 text-gray-700',
  ACTIVE: 'bg-green-100 text-green-700',
  INACTIVE: 'bg-red-100 text-red-600',
  ON_HOLD: 'bg-amber-100 text-amber-700',
}

type ModalMode = 'create' | 'edit' | 'credit' | null

interface FormState {
  company_name: string
  trading_name: string
  industry: string
  website: string
  account_type: AccountType
  pricing_tier: PricingTier
  payment_terms: string
  contact_name: string
  contact_email: string
  contact_phone: string
  credit_limit: string
  approval_threshold: string
  tax_exempt: boolean
  billing_name: string
  billing_address1: string
  billing_city: string
  billing_state: string
  billing_postal_code: string
  billing_country: string
  notes: string
  brand_id: string
}

const EMPTY_FORM: FormState = {
  company_name: '', trading_name: '', industry: '', website: '',
  account_type: 'PROSPECT', pricing_tier: 'STANDARD', payment_terms: 'NET_30',
  contact_name: '', contact_email: '', contact_phone: '',
  credit_limit: '10000', approval_threshold: '',
  tax_exempt: false,
  billing_name: '', billing_address1: '', billing_city: '',
  billing_state: '', billing_postal_code: '', billing_country: 'US',
  notes: '',
  brand_id: '',
}

function formatCurrency(val: string | number | undefined): string {
  const n = parseFloat(String(val ?? 0))
  return isNaN(n) ? '$0.00' : `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function creditPct(account: CustomerAccount): number {
  const limit = parseFloat(account.credit_limit)
  const used = parseFloat(account.credit_used)
  if (!limit) return 0
  return Math.min(100, Math.round((used / limit) * 100))
}

export default function Customers() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [filterType, setFilterType] = useState<AccountType | ''>('')
  const [filterActive, setFilterActive] = useState<'true' | 'false' | ''>('')
  const [filterBrand, setFilterBrand] = useState('')
  const [page, setPage] = useState(1)
  const [modal, setModal] = useState<ModalMode>(null)
  const [selectedAccount, setSelectedAccount] = useState<CustomerAccount | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [creditAmount, setCreditAmount] = useState('')
  const [creditReason, setCreditReason] = useState('')
  const [error, setError] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data: brandsData } = useQuery({
    queryKey: ['brands', 'active'],
    queryFn: () => getBrands({ is_active: true }),
  })

  const { data, isLoading } = useQuery({
    queryKey: ['customers', search, filterType, filterActive, filterBrand, page],
    queryFn: () => fetchCustomerAccounts({
      search: search || undefined,
      account_type: filterType || undefined,
      is_active: filterActive === '' ? undefined : filterActive === 'true',
      brand_id: filterBrand || undefined,
      page,
      page_size: 20,
    }),
    placeholderData: prev => prev,
  })

  const createMutation = useMutation({
    mutationFn: createCustomerAccount,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['customers'] }); closeModal() },
    onError: (e: unknown) => setError(getErrMsg(e)),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof updateCustomerAccount>[1] }) =>
      updateCustomerAccount(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['customers'] }); closeModal() },
    onError: (e: unknown) => setError(getErrMsg(e)),
  })

  const creditMutation = useMutation({
    mutationFn: ({ id, amount, reason }: { id: string; amount: number; reason: string }) =>
      adjustCustomerCredit(id, amount, reason),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['customers'] }); closeModal() },
    onError: (e: unknown) => setError(getErrMsg(e)),
  })

  const deactivateMutation = useMutation({
    mutationFn: deactivateCustomerAccount,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['customers'] }),
    onError: (e: unknown) => setError(getErrMsg(e)),
  })

  function getErrMsg(e: unknown): string {
    const err = e as { response?: { data?: { detail?: unknown } } }
    const detail = err.response?.data?.detail
    if (Array.isArray(detail)) return detail.map((d: { msg: string }) => d.msg).join(', ')
    if (typeof detail === 'string') return detail
    return 'An error occurred'
  }

  function openCreate() {
    setForm(EMPTY_FORM)
    setError('')
    setModal('create')
  }

  function openEdit(account: CustomerAccount) {
    setSelectedAccount(account)
    setForm({
      company_name: account.company_name,
      trading_name: account.trading_name ?? '',
      industry: account.industry ?? '',
      website: account.website ?? '',
      account_type: account.account_type,
      pricing_tier: account.pricing_tier,
      payment_terms: account.payment_terms,
      contact_name: account.contact_name ?? '',
      contact_email: account.contact_email ?? '',
      contact_phone: account.contact_phone ?? '',
      credit_limit: account.credit_limit,
      approval_threshold: account.approval_threshold ?? '',
      tax_exempt: account.tax_exempt,
      billing_name: account.billing_name ?? '',
      billing_address1: account.billing_address1 ?? '',
      billing_city: account.billing_city ?? '',
      billing_state: account.billing_state ?? '',
      billing_postal_code: account.billing_postal_code ?? '',
      billing_country: account.billing_country ?? 'US',
      notes: account.notes ?? '',
      brand_id: account.brand_id ?? '',
    })
    setError('')
    setModal('edit')
  }

  function openCredit(account: CustomerAccount) {
    setSelectedAccount(account)
    setCreditAmount('')
    setCreditReason('')
    setError('')
    setModal('credit')
  }

  function closeModal() {
    setModal(null)
    setSelectedAccount(null)
    setError('')
  }

  function f(field: keyof FormState) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
      const val = e.target.type === 'checkbox'
        ? (e.target as HTMLInputElement).checked
        : e.target.value
      setForm(prev => ({ ...prev, [field]: val }))
    }
  }

  function handleSubmit() {
    setError('')
    const payload = {
      company_name: form.company_name.trim(),
      brand_id: form.brand_id || undefined,
      trading_name: form.trading_name || undefined,
      industry: form.industry || undefined,
      website: form.website || undefined,
      account_type: form.account_type,
      pricing_tier: form.pricing_tier,
      payment_terms: form.payment_terms,
      contact_name: form.contact_name || undefined,
      contact_email: form.contact_email || undefined,
      contact_phone: form.contact_phone || undefined,
      credit_limit: form.credit_limit || '0',
      approval_threshold: form.approval_threshold || undefined,
      tax_exempt: form.tax_exempt,
      billing_name: form.billing_name || undefined,
      billing_address1: form.billing_address1 || undefined,
      billing_city: form.billing_city || undefined,
      billing_state: form.billing_state || undefined,
      billing_postal_code: form.billing_postal_code || undefined,
      billing_country: form.billing_country || 'US',
      notes: form.notes || undefined,
    }
    if (modal === 'create') {
      createMutation.mutate(payload)
    } else if (modal === 'edit' && selectedAccount) {
      updateMutation.mutate({ id: selectedAccount.id, data: payload })
    }
  }

  function handleCreditSubmit() {
    if (!selectedAccount) return
    const amount = parseFloat(creditAmount)
    if (isNaN(amount) || amount === 0) { setError('Enter a non-zero amount'); return }
    if (!creditReason || creditReason.length < 10) { setError('Reason must be at least 10 characters'); return }
    creditMutation.mutate({ id: selectedAccount.id, amount, reason: creditReason })
  }

  const isPending = createMutation.isPending || updateMutation.isPending || creditMutation.isPending

  return (
    <div className="space-y-6">
      {/* Tab strip */}
      <div className="flex border-b border-gray-200 -mb-6">
        <NavLink to="/customers" end className={({ isActive }) => `px-4 py-2.5 text-sm font-medium border-b-2 -mb-px ${isActive ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
          B2B Accounts
        </NavLink>
        <NavLink to="/customers/profiles" className={({ isActive }) => `px-4 py-2.5 text-sm font-medium border-b-2 -mb-px ${isActive ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
          B2C Profiles
        </NavLink>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Building2 className="w-6 h-6 text-blue-600" />
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Customer Accounts</h1>
            <p className="text-sm text-gray-500">B2B account management</p>
          </div>
        </div>
        <button className="btn-primary flex items-center gap-2" onClick={openCreate}>
          <Plus className="w-4 h-4" /> New Account
        </button>
      </div>

      {/* Filters */}
      <div className="card flex flex-wrap gap-3 items-center">
        <div className="flex-1 min-w-48 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            className="input pl-9 w-full"
            placeholder="Search company, email, account #..."
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
          />
        </div>
        <select className="select" value={filterType} onChange={e => { setFilterType(e.target.value as AccountType | ''); setPage(1) }}>
          <option value="">All types</option>
          {ACCOUNT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <select className="select" value={filterActive} onChange={e => { setFilterActive(e.target.value as 'true' | 'false' | ''); setPage(1) }}>
          <option value="">All statuses</option>
          <option value="true">Active</option>
          <option value="false">Inactive</option>
        </select>
        {brandsData && brandsData.length > 0 && (
          <select className="select max-w-44" value={filterBrand} onChange={e => { setFilterBrand(e.target.value); setPage(1) }}>
            <option value="">All Brands</option>
            {brandsData.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        )}
        {data && (
          <span className="text-sm text-gray-500 ml-auto">{data.total} accounts</span>
        )}
      </div>

      {/* Table */}
      <div className="card overflow-hidden p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100">
              {['Account', 'Type', 'Contact', 'Credit', 'Terms', 'Status', ''].map(h => (
                <th key={h} className="table-header">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {isLoading ? (
              <tr><td colSpan={7} className="text-center py-12 text-gray-400">Loading...</td></tr>
            ) : !data?.items.length ? (
              <tr><td colSpan={7} className="text-center py-12 text-gray-400">No customer accounts found</td></tr>
            ) : data.items.map(account => (
              <>
                <tr
                  key={account.id}
                  className={`hover:bg-gray-50 cursor-pointer ${!account.is_active ? 'opacity-60' : ''}`}
                  onClick={() => setExpandedId(expandedId === account.id ? null : account.id)}
                >
                  <td className="table-cell">
                    <div className="flex items-center gap-2">
                      {expandedId === account.id
                        ? <ChevronUp className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                        : <ChevronDown className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                      }
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-gray-900">{account.company_name}</span>
                          {account.brand_id && brandsData && (() => {
                            const brand = brandsData.find(b => b.id === account.brand_id)
                            return brand ? (
                              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-50 text-purple-700 font-mono">
                                {brand.name}
                              </span>
                            ) : null
                          })()}
                        </div>
                        <div className="text-xs text-gray-400">{account.account_number}</div>
                      </div>
                    </div>
                  </td>
                  <td className="table-cell">
                    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${ACCOUNT_TYPE_COLORS[account.account_type]}`}>
                      {account.account_type}
                    </span>
                  </td>
                  <td className="table-cell">
                    <div className="text-gray-700">{account.contact_name || '—'}</div>
                    <div className="text-xs text-gray-400">{account.contact_email || ''}</div>
                  </td>
                  <td className="table-cell">
                    <div className="text-gray-700">{formatCurrency(account.credit_limit)} limit</div>
                    <div className="flex items-center gap-2 mt-1">
                      <div className="flex-1 bg-gray-200 rounded-full h-1.5 max-w-20">
                        <div
                          className={`h-1.5 rounded-full ${creditPct(account) > 80 ? 'bg-red-500' : 'bg-blue-500'}`}
                          style={{ width: `${creditPct(account)}%` }}
                        />
                      </div>
                      <span className="text-xs text-gray-400">{creditPct(account)}%</span>
                    </div>
                  </td>
                  <td className="table-cell text-gray-600">{account.payment_terms.replace('_', ' ')}</td>
                  <td className="table-cell">
                    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${account.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                      {account.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="table-cell" onClick={e => e.stopPropagation()}>
                    <div className="flex items-center gap-1">
                      <button
                        title="Edit"
                        className="p-1.5 rounded hover:bg-gray-100 text-gray-500 hover:text-gray-700"
                        onClick={() => openEdit(account)}
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      <button
                        title="Credit adjustment"
                        className="p-1.5 rounded hover:bg-gray-100 text-gray-500 hover:text-green-700"
                        onClick={() => openCredit(account)}
                      >
                        <DollarSign className="w-3.5 h-3.5" />
                      </button>
                      {account.is_active && (
                        <button
                          title="Deactivate"
                          className="p-1.5 rounded hover:bg-gray-100 text-gray-500 hover:text-red-600"
                          onClick={() => {
                            if (confirm(`Deactivate ${account.company_name}?`)) {
                              deactivateMutation.mutate(account.id)
                            }
                          }}
                        >
                          <Ban className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
                {expandedId === account.id && (
                  <tr key={`${account.id}-detail`} className="bg-gray-50">
                    <td colSpan={7} className="px-6 py-4">
                      <div className="grid grid-cols-3 gap-6 text-sm">
                        <div>
                          <div className="text-xs font-semibold text-gray-400 uppercase mb-2">Credit</div>
                          <div className="space-y-1 text-gray-600">
                            <div className="flex justify-between"><span>Limit</span><span className="font-medium">{formatCurrency(account.credit_limit)}</span></div>
                            <div className="flex justify-between"><span>Used</span><span className="font-medium text-orange-600">{formatCurrency(account.credit_used)}</span></div>
                            <div className="flex justify-between"><span>Available</span><span className="font-medium text-green-600">{formatCurrency(account.available_credit)}</span></div>
                            {account.approval_threshold && (
                              <div className="flex justify-between"><span>Approval threshold</span><span className="font-medium">{formatCurrency(account.approval_threshold)}</span></div>
                            )}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs font-semibold text-gray-400 uppercase mb-2">Billing</div>
                          <div className="text-gray-600 space-y-0.5">
                            {account.billing_name && <div>{account.billing_name}</div>}
                            {account.billing_address1 && <div>{account.billing_address1}</div>}
                            {(account.billing_city || account.billing_state) && (
                              <div>{[account.billing_city, account.billing_state, account.billing_postal_code].filter(Boolean).join(', ')}</div>
                            )}
                            {account.billing_country && <div>{account.billing_country}</div>}
                            {!account.billing_address1 && <div className="text-gray-400">No billing address</div>}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs font-semibold text-gray-400 uppercase mb-2">Details</div>
                          <div className="space-y-1 text-gray-600">
                            <div className="flex justify-between"><span>Pricing tier</span><span className="font-medium">{account.pricing_tier}</span></div>
                            <div className="flex justify-between"><span>Tax exempt</span><span className="font-medium">{account.tax_exempt ? 'Yes' : 'No'}</span></div>
                            {account.industry && <div className="flex justify-between"><span>Industry</span><span className="font-medium">{account.industry}</span></div>}
                            {account.notes && <div className="mt-2 text-xs text-gray-500 italic">{account.notes}</div>}
                          </div>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {data && data.total_pages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-500">
          <span>Page {data.page} of {data.total_pages}</span>
          <div className="flex gap-2">
            <button className="btn-secondary" disabled={page === 1} onClick={() => setPage(p => p - 1)}>Previous</button>
            <button className="btn-secondary" disabled={page >= data.total_pages} onClick={() => setPage(p => p + 1)}>Next</button>
          </div>
        </div>
      )}

      {/* Create / Edit Modal */}
      {(modal === 'create' || modal === 'edit') && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <div className="p-6 border-b border-gray-100">
              <h2 className="text-lg font-semibold">{modal === 'create' ? 'New Customer Account' : 'Edit Account'}</h2>
            </div>
            <div className="p-6 space-y-5">
              {error && <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">{error}</div>}

              {/* Company */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">Company Name *</label>
                  <input className="input w-full" value={form.company_name} onChange={f('company_name')} />
                </div>
                <div>
                  <label className="label">Trading Name</label>
                  <input className="input w-full" value={form.trading_name} onChange={f('trading_name')} />
                </div>
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

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="label">Account Type</label>
                  <select className="select w-full" value={form.account_type} onChange={f('account_type')}>
                    {ACCOUNT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Pricing Tier</label>
                  <select className="select w-full" value={form.pricing_tier} onChange={f('pricing_tier')}>
                    {PRICING_TIERS.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Payment Terms</label>
                  <select className="select w-full" value={form.payment_terms} onChange={f('payment_terms')}>
                    {PAYMENT_TERMS.map(t => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}
                  </select>
                </div>
              </div>

              {/* Contact */}
              <div className="border-t pt-4">
                <div className="text-xs font-semibold text-gray-400 uppercase mb-3">Contact</div>
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <label className="label">Name</label>
                    <input className="input w-full" value={form.contact_name} onChange={f('contact_name')} />
                  </div>
                  <div>
                    <label className="label">Email</label>
                    <input className="input w-full" type="email" value={form.contact_email} onChange={f('contact_email')} />
                  </div>
                  <div>
                    <label className="label">Phone</label>
                    <input className="input w-full" value={form.contact_phone} onChange={f('contact_phone')} />
                  </div>
                </div>
              </div>

              {/* Credit */}
              <div className="border-t pt-4">
                <div className="text-xs font-semibold text-gray-400 uppercase mb-3">Credit & Approval</div>
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <label className="label">Credit Limit ($)</label>
                    <input className="input w-full" type="number" min="0" value={form.credit_limit} onChange={f('credit_limit')} />
                  </div>
                  <div>
                    <label className="label">Approval Threshold ($)</label>
                    <input className="input w-full" type="number" min="0" placeholder="Auto-approve below this" value={form.approval_threshold} onChange={f('approval_threshold')} />
                  </div>
                  <div className="flex items-end pb-1">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" checked={form.tax_exempt} onChange={f('tax_exempt')} className="rounded" />
                      <span className="text-sm text-gray-700">Tax Exempt</span>
                    </label>
                  </div>
                </div>
              </div>

              {/* Billing address */}
              <div className="border-t pt-4">
                <div className="text-xs font-semibold text-gray-400 uppercase mb-3">Billing Address</div>
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="label">Billing Name</label>
                      <input className="input w-full" value={form.billing_name} onChange={f('billing_name')} />
                    </div>
                    <div>
                      <label className="label">Address</label>
                      <input className="input w-full" value={form.billing_address1} onChange={f('billing_address1')} />
                    </div>
                  </div>
                  <div className="grid grid-cols-4 gap-3">
                    <div className="col-span-2">
                      <label className="label">City</label>
                      <input className="input w-full" value={form.billing_city} onChange={f('billing_city')} />
                    </div>
                    <div>
                      <label className="label">State</label>
                      <input className="input w-full" value={form.billing_state} onChange={f('billing_state')} />
                    </div>
                    <div>
                      <label className="label">ZIP</label>
                      <input className="input w-full" value={form.billing_postal_code} onChange={f('billing_postal_code')} />
                    </div>
                  </div>
                </div>
              </div>

              {/* Notes */}
              <div>
                <label className="label">Notes</label>
                <textarea className="input w-full h-16 resize-none" value={form.notes} onChange={f('notes')} />
              </div>
            </div>

            <div className="p-6 border-t border-gray-100 flex justify-end gap-3">
              <button className="btn-secondary" onClick={closeModal}>Cancel</button>
              <button className="btn-primary" disabled={isPending || !form.company_name.trim()} onClick={handleSubmit}>
                {isPending ? 'Saving...' : modal === 'create' ? 'Create Account' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Credit Adjustment Modal */}
      {modal === 'credit' && selectedAccount && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-md">
            <div className="p-6 border-b border-gray-100">
              <h2 className="text-lg font-semibold">Credit Adjustment</h2>
              <p className="text-sm text-gray-500 mt-1">{selectedAccount.company_name}</p>
            </div>
            <div className="p-6 space-y-4">
              {error && <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">{error}</div>}

              <div className="bg-gray-50 rounded-lg p-3 grid grid-cols-3 gap-2 text-sm text-center">
                <div>
                  <div className="text-gray-400 text-xs">Limit</div>
                  <div className="font-semibold">{formatCurrency(selectedAccount.credit_limit)}</div>
                </div>
                <div>
                  <div className="text-gray-400 text-xs">Used</div>
                  <div className="font-semibold text-orange-600">{formatCurrency(selectedAccount.credit_used)}</div>
                </div>
                <div>
                  <div className="text-gray-400 text-xs">Available</div>
                  <div className="font-semibold text-green-600">{formatCurrency(selectedAccount.available_credit)}</div>
                </div>
              </div>

              <div>
                <label className="label">Amount ($)</label>
                <input
                  className="input w-full"
                  type="number"
                  placeholder="Positive = increase used, Negative = release credit"
                  value={creditAmount}
                  onChange={e => setCreditAmount(e.target.value)}
                />
                <p className="text-xs text-gray-400 mt-1">E.g. -500 to release $500 of credit after payment</p>
              </div>
              <div>
                <label className="label">Reason (min 10 chars)</label>
                <input
                  className="input w-full"
                  placeholder="e.g. Invoice #12345 payment received"
                  value={creditReason}
                  onChange={e => setCreditReason(e.target.value)}
                />
              </div>
            </div>
            <div className="p-6 border-t border-gray-100 flex justify-end gap-3">
              <button className="btn-secondary" onClick={closeModal}>Cancel</button>
              <button className="btn-primary" disabled={isPending} onClick={handleCreditSubmit}>
                {isPending ? 'Applying...' : 'Apply Adjustment'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
