import { useState, useEffect } from 'react'
import { useShopifyEmbedded } from '../providers/ShopifyAppBridgeProvider'

interface SessionTokenResult {
  accessToken: string | null
  isLoading: boolean
  error: string | null
}

/**
 * Exchanges a Shopify session token for an OMS bearer token.
 *
 * Uses window.shopify.idToken() — the modern App Bridge global injected by
 * Shopify's admin iframe. No SDK required; Shopify injects this automatically
 * when the app is embedded.
 */
export function useShopifySessionToken(): SessionTokenResult {
  const { isEmbedded, shop } = useShopifyEmbedded()
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!isEmbedded || !shop) return

    async function exchangeToken() {
      setIsLoading(true)
      try {
        // window.shopify is injected by Shopify Admin when running in iframe
        const shopifyGlobal = (window as any).shopify
        if (!shopifyGlobal?.idToken) {
          throw new Error('window.shopify.idToken not available — is this app running inside Shopify Admin?')
        }
        const shopifyToken: string = await shopifyGlobal.idToken()
        if (!shopifyToken) throw new Error('Shopify returned empty session token')

        // Exchange Shopify session token for OMS bearer token
        const resp = await fetch('/shopify/auth/session-token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_token: shopifyToken, shop }),
        })
        if (!resp.ok) throw new Error(`Session exchange failed: ${resp.status}`)
        const data = await resp.json()
        setAccessToken(data.access_token)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error')
      } finally {
        setIsLoading(false)
      }
    }

    exchangeToken()
    // Refresh every 50 minutes (OMS tokens expire at 60min)
    const interval = setInterval(exchangeToken, 50 * 60 * 1000)
    return () => clearInterval(interval)
  }, [isEmbedded, shop])

  return { accessToken, isLoading, error }
}
