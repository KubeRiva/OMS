import { Outlet } from 'react-router-dom'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, ShoppingCart, Package, Boxes, BarChart2,
  MapPin, Settings, Search, Zap, BookOpen, GitBranch, Sparkles,
  Shield, LogOut, User, Webhook, Plug, AlertTriangle, TestTube, Brain, Server, Crown, ShoppingBag,
} from 'lucide-react'
import { useAuth, isPlatformOwner } from '../context/AuthContext'
import EnvironmentSwitcher from './EnvironmentSwitcher'
import { useEnvironment } from '../contexts/EnvironmentContext'

const navItems = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard', permission: 'dashboard:view' },
  { to: '/orders', icon: ShoppingCart, label: 'Orders', permission: 'orders:view' },
  { to: '/inventory', icon: Package, label: 'Inventory', permission: 'inventory:view' },
  { to: '/products', icon: Boxes, label: 'Products', permission: 'inventory:view' },
  { to: '/analytics', icon: BarChart2, label: 'Analytics', permission: 'analytics:view' },
  { to: '/nodes', icon: MapPin, label: 'Nodes', permission: 'nodes:view' },
  { to: '/sourcing-rules', icon: Zap, label: 'Sourcing Rules', permission: 'sourcing_rules:view' },
  { to: '/lifecycles', icon: GitBranch, label: 'Lifecycles', permission: 'lifecycles:view' },
  { to: '/search', icon: Search, label: 'Search', permission: 'search:use' },
  { to: '/ai', icon: Sparkles, label: 'AI Assistant', permission: 'ai:use' },
]

export default function Layout() {
  const { user, logout, hasPermission } = useAuth()
  const { currentEnv } = useEnvironment()

  const visibleNav = navItems.filter(item => hasPermission(item.permission))
  const isProd = currentEnv?.env_type === 'PROD'
  const isOwner = isPlatformOwner(user)

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-gray-50">
      {/* Production warning banner */}
      {isProd && (
        <div className="flex-shrink-0 bg-red-600 text-white text-xs font-semibold flex items-center justify-center gap-2 py-1.5 z-50">
          <AlertTriangle className="w-3.5 h-3.5" />
          Production Environment — changes affect live customers
        </div>
      )}
      <div className="flex flex-1 overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 bg-gray-900 flex flex-col">
        {/* Logo + Env Switcher */}
        <div className="px-4 py-4 border-b border-white/10 space-y-3">
          <div className="flex items-center gap-2.5">
            <img src="/kuberiva-logo.svg" alt="KubeRiva" className="h-7 w-auto" />
          </div>
          <EnvironmentSwitcher />
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          {visibleNav.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `sidebar-link ${isActive ? 'active' : ''}`
              }
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              <span>{label}</span>
            </NavLink>
          ))}

          {/* Environments — all authenticated users */}
          <div className="border-t border-white/10 my-2" />
          <NavLink to="/environments" className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}>
            <Server className="w-4 h-4 flex-shrink-0" />
            <span>Environments</span>
          </NavLink>

          {/* Platform Owner section */}
          {isOwner && (
            <>
              <div className="border-t border-white/10 my-2" />
              <p className="px-3 text-[11px] font-semibold text-purple-400 uppercase tracking-widest mb-1">Platform</p>
              <NavLink
                to="/platform"
                className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
              >
                <Crown className="w-4 h-4 flex-shrink-0" />
                <span>Platform Console</span>
              </NavLink>
            </>
          )}

          {/* Monitoring — permission-based */}
          {(user?.is_superadmin || hasPermission('monitoring:view')) && (
            <>
              <div className="border-t border-white/10 my-2" />
              <NavLink
                to="/monitoring"
                className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
              >
                <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                <span>Monitoring</span>
              </NavLink>
            </>
          )}

          {/* Admin section — superadmin only */}
          {user?.is_superadmin && (
            <>
              <div className="border-t border-white/10 my-2" />
              <NavLink
                to="/admin"
                className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
              >
                <Shield className="w-4 h-4 flex-shrink-0" />
                <span>Admin Console</span>
              </NavLink>
              <NavLink
                to="/webhooks"
                className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
              >
                <Webhook className="w-4 h-4 flex-shrink-0" />
                <span>Webhooks</span>
              </NavLink>
              <NavLink
                to="/connectors"
                className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
              >
                <Plug className="w-4 h-4 flex-shrink-0" />
                <span>Connectors</span>
              </NavLink>
              <NavLink
                to="/shopify/install"
                className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
              >
                <ShoppingBag className="w-4 h-4 flex-shrink-0" />
                <span>Shopify App</span>
              </NavLink>
              <NavLink
                to="/testing"
                className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
              >
                <TestTube className="w-4 h-4 flex-shrink-0" />
                <span>E2E Testing</span>
              </NavLink>
              <NavLink
                to="/architect"
                className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
              >
                <Brain className="w-4 h-4 flex-shrink-0" />
                <span>AI Architect</span>
              </NavLink>
            </>
          )}
        </nav>

        {/* Bottom */}
        <div className="px-3 py-4 border-t border-white/10 space-y-1">
          {/* Logged-in user */}
          {user && (
            <div className="px-3 py-2 mb-2 bg-white/5 rounded-lg">
              <div className="flex items-center gap-2 min-w-0">
                <div className="w-6 h-6 bg-blue-600 rounded-full flex items-center justify-center flex-shrink-0">
                  <User className="w-3 h-3 text-white" />
                </div>
                <div className="min-w-0">
                  <p className="text-white text-xs font-medium truncate leading-tight">
                    {user.full_name || user.email}
                  </p>
                  {user.full_name && (
                    <p className="text-gray-400 text-[10px] truncate leading-tight">{user.email}</p>
                  )}
                </div>
              </div>
              {isOwner ? (
                <div className="mt-1 flex items-center gap-1">
                  <Crown className="w-2.5 h-2.5 text-yellow-400" />
                  <span className="text-yellow-400 text-[11px] font-medium uppercase tracking-wider">Platform Owner</span>
                </div>
              ) : user.is_superadmin && (
                <div className="mt-1 flex items-center gap-1">
                  <Shield className="w-2.5 h-2.5 text-purple-400" />
                  <span className="text-purple-400 text-[11px] font-medium uppercase tracking-wider">Superadmin</span>
                </div>
              )}
            </div>
          )}

          <a
            href="/docs.html"
            target="_blank"
            rel="noopener noreferrer"
            className="sidebar-link text-xs"
          >
            <BookOpen className="w-4 h-4" />
            <span>Documentation</span>
          </a>
          <a
            href="/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="sidebar-link text-xs"
          >
            <Settings className="w-4 h-4" />
            <span>API Docs</span>
          </a>

          {/* Logout */}
          <button
            onClick={logout}
            className="sidebar-link text-xs w-full text-red-400 hover:text-red-300 hover:bg-red-900/20"
          >
            <LogOut className="w-4 h-4" />
            <span>Sign Out</span>
          </button>

          <div className="mt-2 px-3">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              <span className="text-gray-400 text-[10px]">All systems operational</span>
            </div>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
      </div>
    </div>
  )
}
