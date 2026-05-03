import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import { EnvironmentProvider } from './contexts/EnvironmentContext'
import { ShopifyAppBridgeProvider } from './providers/ShopifyAppBridgeProvider'

const Login        = lazy(() => import('./pages/Login'))
const Dashboard    = lazy(() => import('./pages/Dashboard'))
const Orders       = lazy(() => import('./pages/Orders'))
const OrderDetail  = lazy(() => import('./pages/OrderDetail'))
const Inventory    = lazy(() => import('./pages/Inventory'))
const Products     = lazy(() => import('./pages/Products'))
const Analytics    = lazy(() => import('./pages/Analytics'))
const Nodes        = lazy(() => import('./pages/Nodes'))
const SourcingRules = lazy(() => import('./pages/SourcingRules'))
const Lifecycles   = lazy(() => import('./pages/Lifecycles'))
const Search       = lazy(() => import('./pages/Search'))
const AIAssistant  = lazy(() => import('./pages/AIAssistant'))
const Admin        = lazy(() => import('./pages/Admin'))
const Webhooks     = lazy(() => import('./pages/Webhooks'))
const Connectors   = lazy(() => import('./pages/Connectors'))
const Monitoring   = lazy(() => import('./pages/Monitoring'))
const Testing      = lazy(() => import('./pages/Testing'))
const Architect    = lazy(() => import('./pages/Architect'))
const Platform          = lazy(() => import('./pages/Platform'))
const Environments      = lazy(() => import('./pages/Environments'))
const ShopifyInstall    = lazy(() => import('./pages/ShopifyInstall'))
const ShopifyBillingConfirm = lazy(() => import('./pages/ShopifyBillingConfirm'))

// Embedded (Shopify App Bridge) pages
const EmbeddedLayout    = lazy(() => import('./components/EmbeddedLayout'))
const EmbeddedDashboard = lazy(() => import('./pages/embedded/EmbeddedDashboard'))

// The Shopify API key is injected at build time via Vite env
const SHOPIFY_API_KEY = import.meta.env.VITE_SHOPIFY_API_KEY || ''

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <ShopifyAppBridgeProvider apiKey={SHOPIFY_API_KEY}>
      <EnvironmentProvider>
      <Suspense fallback={<PageLoader />}>
      <Routes>
        {/* Public routes */}
        <Route path="/login" element={<Login />} />
        <Route path="/shopify/install" element={<ShopifyInstall />} />
        <Route path="/shopify/billing/confirm" element={<ShopifyBillingConfirm />} />

        {/* Shopify embedded routes — auth via App Bridge session token, no OMS sidebar */}
        <Route path="/embedded" element={<EmbeddedLayout />}>
          <Route index element={<Navigate to="/embedded/dashboard" replace />} />
          <Route path="dashboard" element={<EmbeddedDashboard />} />
          <Route path="orders" element={<Orders />} />
          <Route path="inventory" element={<Inventory />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="sourcing-rules" element={<SourcingRules />} />
          <Route path="ai" element={<AIAssistant />} />
        </Route>

        {/* All other routes require authentication */}
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<ProtectedRoute permission="dashboard:view"><Dashboard /></ProtectedRoute>} />
          <Route path="orders" element={<ProtectedRoute permission="orders:view"><Orders /></ProtectedRoute>} />
          <Route path="orders/:id" element={<ProtectedRoute permission="orders:view"><OrderDetail /></ProtectedRoute>} />
          <Route path="inventory" element={<ProtectedRoute permission="inventory:view"><Inventory /></ProtectedRoute>} />
          <Route path="products" element={<ProtectedRoute permission="inventory:view"><Products /></ProtectedRoute>} />
          <Route path="analytics" element={<ProtectedRoute permission="analytics:view"><Analytics /></ProtectedRoute>} />
          <Route path="nodes" element={<ProtectedRoute permission="nodes:view"><Nodes /></ProtectedRoute>} />
          <Route path="sourcing-rules" element={<ProtectedRoute permission="sourcing_rules:view"><SourcingRules /></ProtectedRoute>} />
          <Route path="lifecycles" element={<ProtectedRoute permission="lifecycles:view"><Lifecycles /></ProtectedRoute>} />
          <Route path="search" element={<ProtectedRoute permission="search:use"><Search /></ProtectedRoute>} />
          <Route path="ai" element={<ProtectedRoute permission="ai:use"><AIAssistant /></ProtectedRoute>} />
          <Route path="admin" element={<ProtectedRoute requireSuperadmin><Admin /></ProtectedRoute>} />
          <Route path="webhooks" element={<ProtectedRoute requireSuperadmin><Webhooks /></ProtectedRoute>} />
          <Route path="connectors" element={<ProtectedRoute requireSuperadmin><Connectors /></ProtectedRoute>} />
          <Route path="monitoring" element={<ProtectedRoute permission="monitoring:view"><Monitoring /></ProtectedRoute>} />
          <Route path="testing" element={<ProtectedRoute requireSuperadmin><Testing /></ProtectedRoute>} />
          <Route path="architect" element={<ProtectedRoute requireSuperadmin><Architect /></ProtectedRoute>} />
          <Route path="environments" element={<ProtectedRoute><Environments /></ProtectedRoute>} />
          <Route path="platform" element={<ProtectedRoute requirePlatformOwner><Platform /></ProtectedRoute>} />
        </Route>
      </Routes>
      </Suspense>
      </EnvironmentProvider>
      </ShopifyAppBridgeProvider>
    </BrowserRouter>
  )
}
