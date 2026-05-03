import { Outlet, useLocation } from 'react-router-dom'
import { TitleBar } from '@shopify/app-bridge-react'

// Maps routes to page titles
const PAGE_TITLES: Record<string, string> = {
  '/embedded/dashboard': 'Dashboard',
  '/embedded/orders': 'Orders',
  '/embedded/inventory': 'Inventory',
  '/embedded/analytics': 'Analytics',
  '/embedded/sourcing-rules': 'Sourcing Rules',
  '/embedded/ai': 'AI Assistant',
  '/embedded/architect': 'AI Architect',
}

export default function EmbeddedLayout() {
  const location = useLocation()
  const title = PAGE_TITLES[location.pathname] || 'KubeRiva'

  return (
    <div className="min-h-screen bg-gray-50">
      <TitleBar title={title} />
      <main className="p-4">
        <Outlet />
      </main>
    </div>
  )
}
