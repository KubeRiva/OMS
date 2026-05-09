import { Navigate, useLocation } from 'react-router-dom'
import { useAuth, isPlatformOwner } from '../context/AuthContext'

interface ProtectedRouteProps {
  children: React.ReactNode
  permission?: string
  requireSuperadmin?: boolean
  requirePlatformOwner?: boolean
}

export default function ProtectedRoute({
  children,
  permission,
  requireSuperadmin = false,
  requirePlatformOwner = false,
}: ProtectedRouteProps) {
  const { isAuthenticated, hasPermission, user } = useAuth()
  const location = useLocation()

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  if (requirePlatformOwner && !isPlatformOwner(user)) {
    return (
      <div className="flex flex-col items-center justify-center h-full py-24 text-center">
        <div className="w-16 h-16 bg-purple-100 rounded-full flex items-center justify-center mb-4">
          <svg className="w-8 h-8 text-purple-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
          </svg>
        </div>
        <h2 className="text-xl font-semibold text-gray-900 mb-2">Platform Owner Only</h2>
        <p className="text-gray-500">This section is restricted to Platform Owners.</p>
      </div>
    )
  }

  if (requireSuperadmin && !user?.is_superadmin) {
    return (
      <div className="flex flex-col items-center justify-center h-full py-24 text-center px-4">
        <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mb-4">
          <svg className="w-8 h-8 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          </svg>
        </div>
        <h2 className="text-xl font-semibold text-gray-900 mb-2">Access Restricted</h2>
        <p className="text-gray-500 max-w-sm">This section requires administrator privileges. Your current role does not include access to this area.</p>
        <p className="text-gray-400 text-sm mt-2">Contact your platform administrator for assistance.</p>
      </div>
    )
  }

  if (permission && !hasPermission(permission)) {
    return (
      <div className="flex flex-col items-center justify-center h-full py-24 text-center px-4">
        <div className="w-16 h-16 bg-amber-100 rounded-full flex items-center justify-center mb-4">
          <svg className="w-8 h-8 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
          </svg>
        </div>
        <h2 className="text-xl font-semibold text-gray-900 mb-2">Access Restricted</h2>
        <p className="text-gray-500 max-w-sm">
          Your account does not have access to this section.
          The <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">{permission}</code> permission is required.
        </p>
        <p className="text-gray-400 text-sm mt-2">Contact your administrator to request access to this feature.</p>
      </div>
    )
  }

  return <>{children}</>
}
