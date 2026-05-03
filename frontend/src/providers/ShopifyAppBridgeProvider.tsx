/**
 * Shopify embedded-mode context provider.
 *
 * Detects whether the app is running inside the Shopify Admin iframe (embedded)
 * or as a standalone web app. Provides shop/host values to child components via
 * useShopifyEmbedded().
 *
 * App Bridge initialisation (window.shopify) is handled automatically by
 * Shopify's admin iframe injection — no SDK wrapper component is needed.
 */
import { ReactNode, createContext, useContext, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

interface ShopifyEmbeddedContextValue {
  isEmbedded: boolean
  shop: string
  host: string
}

const ShopifyEmbeddedContext = createContext<ShopifyEmbeddedContextValue>({
  isEmbedded: false,
  shop: '',
  host: '',
})

export function useShopifyEmbedded() {
  return useContext(ShopifyEmbeddedContext)
}

interface Props {
  children: ReactNode
  apiKey: string
}

export function ShopifyAppBridgeProvider({ children, apiKey: _apiKey }: Props) {
  const [params] = useSearchParams()
  const shop = params.get('shop') || ''
  const host = params.get('host') || ''
  const isEmbedded =
    params.get('embedded') === '1' ||
    (typeof window !== 'undefined' && window.self !== window.top)

  const contextValue = useMemo(
    () => ({ isEmbedded, shop, host }),
    [isEmbedded, shop, host],
  )

  return (
    <ShopifyEmbeddedContext.Provider value={contextValue}>
      {children}
    </ShopifyEmbeddedContext.Provider>
  )
}
