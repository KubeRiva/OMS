import { useEffect, useState } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { Loader2, AlertCircle, CheckCircle2 } from 'lucide-react'
import { confirmShopifyBilling } from '../api/client'

type ConfirmState = 'loading' | 'success' | 'error'

export default function ShopifyBillingConfirm() {
  const [searchParams] = useSearchParams()
  const shop = searchParams.get('shop') ?? ''
  const plan = searchParams.get('plan') ?? ''
  const chargeId = searchParams.get('charge_id') ?? ''

  const [state, setState] = useState<ConfirmState>('loading')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!shop && !chargeId) {
      // No params — came here directly, just redirect to dashboard
      window.location.href = '/'
      return
    }

    confirmShopifyBilling({
      shop: shop || undefined,
      plan: plan || undefined,
      charge_id: chargeId || undefined,
    })
      .then(() => {
        setState('success')
        // Backend may have already redirected, but if we receive a 200 here
        // we redirect to the dashboard ourselves after a brief delay.
        setTimeout(() => {
          window.location.href = '/'
        }, 1500)
      })
      .catch((err: unknown) => {
        setState('error')
        const detail =
          (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
        if (Array.isArray(detail)) {
          setErrorMessage(
            detail.map((d: { msg?: string }) => d.msg ?? String(d)).join('; ')
          )
        } else if (typeof detail === 'string') {
          setErrorMessage(detail)
        } else {
          setErrorMessage('Plan activation failed. Please try again or contact support.')
        }
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="card max-w-sm w-full text-center py-12 flex flex-col items-center gap-4">
        {state === 'loading' && (
          <>
            <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
            <h2 className="text-lg font-semibold text-gray-900">Activating your plan...</h2>
            <p className="text-sm text-gray-500">
              Please wait while we confirm your billing with Shopify.
            </p>
          </>
        )}

        {state === 'success' && (
          <>
            <CheckCircle2 className="w-10 h-10 text-green-500" />
            <h2 className="text-lg font-semibold text-gray-900">Plan activated!</h2>
            <p className="text-sm text-gray-500">Redirecting you to the dashboard...</p>
          </>
        )}

        {state === 'error' && (
          <>
            <div className="w-12 h-12 bg-red-100 rounded-full flex items-center justify-center">
              <AlertCircle className="w-6 h-6 text-red-500" />
            </div>
            <h2 className="text-lg font-semibold text-gray-900">Activation failed</h2>
            {errorMessage && (
              <p className="text-sm text-red-600">{errorMessage}</p>
            )}
            <p className="text-sm text-gray-500">
              Your subscription could not be confirmed.
            </p>
            <div className="flex flex-col gap-2 w-full mt-2">
              <Link
                to={`/shopify/install${shop ? `?shop=${shop}` : ''}`}
                className="btn-primary text-center"
              >
                Try Again
              </Link>
              <Link to="/" className="btn-secondary text-center">
                Go to Dashboard
              </Link>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
