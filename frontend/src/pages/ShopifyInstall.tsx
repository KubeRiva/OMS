import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Check, Loader2, AlertCircle } from 'lucide-react'
import {
  fetchShopifyBillingPlans,
  subscribeShopifyPlan,
  type ShopifyBillingPlan as BillingPlan,
  type ShopifySubscribeResponse as SubscribeResponse,
} from '../api/client'

// ─── Plan card metadata ───────────────────────────────────────────────────────

const PLAN_META: Record<string, {
  badge?: string
  highlighted?: boolean
  ctaClass: string
  description: string
}> = {
  STARTER: {
    ctaClass: 'btn-secondary',
    description: 'For small shops getting started with order management.',
  },
  GROWTH: {
    badge: 'Most Popular',
    highlighted: true,
    ctaClass: 'btn-primary',
    description: 'For growing merchants who need advanced sourcing and analytics.',
  },
  ENTERPRISE: {
    ctaClass: 'btn-secondary',
    description: 'For high-volume operations with custom requirements.',
  },
}

// ─── Skeleton card ────────────────────────────────────────────────────────────

function PlanCardSkeleton() {
  return (
    <div className="card flex flex-col gap-4 animate-pulse">
      <div className="h-5 bg-gray-200 rounded w-24" />
      <div className="h-8 bg-gray-200 rounded w-32" />
      <div className="h-4 bg-gray-100 rounded w-full" />
      <div className="space-y-2 mt-2">
        {[1, 2, 3, 4].map(i => (
          <div key={i} className="flex items-center gap-2">
            <div className="w-4 h-4 rounded-full bg-gray-200 flex-shrink-0" />
            <div className="h-4 bg-gray-100 rounded w-3/4" />
          </div>
        ))}
      </div>
      <div className="mt-auto h-9 bg-gray-200 rounded" />
    </div>
  )
}

// ─── Plan card ────────────────────────────────────────────────────────────────

interface PlanCardProps {
  plan: BillingPlan
  isLoading: boolean
  onSelect: (planName: string) => void
}

function PlanCard({ plan, isLoading, onSelect }: PlanCardProps) {
  const meta = PLAN_META[plan.name] ?? { ctaClass: 'btn-secondary', description: '' }

  const formattedPrice = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: plan.currency ?? 'USD',
    minimumFractionDigits: 0,
  }).format(plan.price)

  return (
    <div
      className={[
        'card flex flex-col gap-4 relative transition-shadow',
        meta.highlighted
          ? 'ring-2 ring-blue-500 shadow-lg'
          : 'hover:shadow-md',
      ].join(' ')}
    >
      {meta.badge && (
        <span className="absolute -top-3 left-1/2 -translate-x-1/2 bg-blue-600 text-white text-xs font-semibold px-3 py-0.5 rounded-full whitespace-nowrap">
          {meta.badge}
        </span>
      )}

      <div>
        <h3 className="text-base font-semibold text-gray-900 capitalize">
          {plan.display_name || plan.name}
        </h3>
        <p className="text-xs text-gray-500 mt-0.5">{meta.description}</p>
      </div>

      <div className="flex items-end gap-1">
        <span className="text-3xl font-bold text-gray-900">{formattedPrice}</span>
        <span className="text-sm text-gray-500 mb-1">/ {plan.interval?.toLowerCase() ?? 'mo'}</span>
      </div>

      {plan.trial_days > 0 && (
        <p className="text-xs font-medium text-green-600 -mt-2">
          {plan.trial_days}-day free trial
        </p>
      )}

      <ul className="space-y-2 flex-1">
        {plan.features.map((feature, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
            <Check className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
            <span>{feature}</span>
          </li>
        ))}
      </ul>

      <button
        className={`${meta.ctaClass} w-full mt-auto flex items-center justify-center gap-2`}
        onClick={() => onSelect(plan.name)}
        disabled={isLoading}
      >
        {isLoading && <Loader2 className="w-4 h-4 animate-spin" />}
        Start Free Trial
      </button>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function ShopifyInstall() {
  const [searchParams] = useSearchParams()
  const shopDomain = searchParams.get('shop') ?? ''
  const [subscribingPlan, setSubscribingPlan] = useState<string | null>(null)
  const [subscribeError, setSubscribeError] = useState<string | null>(null)

  const {
    data: plans,
    isLoading: plansLoading,
    isError: plansError,
    refetch,
  } = useQuery<BillingPlan[]>({
    queryKey: ['shopify-plans'],
    queryFn: fetchShopifyBillingPlans,
    retry: 2,
  })

  const subscribeMutation = useMutation<SubscribeResponse, Error, string>({
    mutationFn: (plan: string) => subscribeShopifyPlan(shopDomain, plan),
    onMutate: (plan) => {
      setSubscribingPlan(plan)
      setSubscribeError(null)
    },
    onSuccess: (data) => {
      window.location.href = data.confirmation_url
    },
    onError: (err: unknown) => {
      setSubscribingPlan(null)
      const detail =
        (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      if (Array.isArray(detail)) {
        setSubscribeError(detail.map((d: { msg?: string }) => d.msg ?? String(d)).join('; '))
      } else if (typeof detail === 'string') {
        setSubscribeError(detail)
      } else {
        setSubscribeError('Failed to start subscription. Please try again.')
      }
    },
  })

  const handleSelect = (planName: string) => {
    subscribeMutation.mutate(planName)
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Top bar */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-3">
        <img src="/kuberiva-logo.svg" alt="KubeRiva" className="h-7 w-auto" />
        <div>
          <p className="text-xs text-gray-500 leading-tight">Order Management System</p>
        </div>
        {shopDomain && (
          <span className="ml-auto text-xs text-gray-500 font-mono bg-gray-100 px-2 py-1 rounded">
            {shopDomain}
          </span>
        )}
      </header>

      {/* Hero */}
      <div className="text-center px-4 pt-12 pb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">
          Welcome to KubeRiva — Choose Your Plan
        </h1>
        <p className="text-gray-500 text-base max-w-xl mx-auto">
          14-day free trial on all plans. No credit card required. Cancel anytime.
        </p>
      </div>

      {/* Plans content */}
      <div className="flex-1 px-4 pb-12">
        <div className="max-w-5xl mx-auto">

          {/* Error loading plans */}
          {plansError && (
            <div className="flex flex-col items-center gap-3 py-16 text-center">
              <div className="w-12 h-12 bg-red-100 rounded-full flex items-center justify-center">
                <AlertCircle className="w-6 h-6 text-red-500" />
              </div>
              <p className="text-gray-700 font-medium">Could not load billing plans</p>
              <p className="text-gray-500 text-sm">
                There was a problem fetching available plans. Please try again.
              </p>
              <button className="btn-secondary mt-2" onClick={() => refetch()}>
                Retry
              </button>
            </div>
          )}

          {/* Subscribe error */}
          {subscribeError && (
            <div className="mb-6 flex items-start gap-3 bg-red-50 border border-red-200 rounded-lg px-4 py-3 max-w-2xl mx-auto">
              <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0" />
              <p className="text-sm text-red-700">{subscribeError}</p>
            </div>
          )}

          {/* Skeleton loading */}
          {plansLoading && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-4">
              <PlanCardSkeleton />
              <PlanCardSkeleton />
              <PlanCardSkeleton />
            </div>
          )}

          {/* Plan cards */}
          {plans && plans.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-4">
              {plans.map(plan => (
                <PlanCard
                  key={plan.name}
                  plan={plan}
                  isLoading={subscribingPlan === plan.name && subscribeMutation.isPending}
                  onSelect={handleSelect}
                />
              ))}
            </div>
          )}

          {/* Empty state — plans loaded but array is empty */}
          {plans && plans.length === 0 && (
            <div className="flex flex-col items-center gap-3 py-16 text-center">
              <p className="text-gray-500 text-sm">No billing plans are currently available.</p>
              <p className="text-gray-400 text-xs">Please contact support.</p>
            </div>
          )}

          {/* Footer note */}
          <p className="text-center text-xs text-gray-400 mt-10">
            Billed through Shopify. By selecting a plan you agree to our terms of service.
            A 20% revenue share applies to app-generated orders.
          </p>
        </div>
      </div>
    </div>
  )
}
