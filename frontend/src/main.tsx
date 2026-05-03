import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App.tsx'
import { AuthProvider } from './context/AuthContext.tsx'
import './index.css'

// If arriving via an environment-switch redirect, the source pod appended
// ?_oms_token=<jwt>&_oms_user=<json> to the URL.  Write them into localStorage
// before AuthProvider mounts so the user is immediately authenticated.
;(function bootstrapFromUrl() {
  const params = new URLSearchParams(window.location.search)
  const token = params.get('_oms_token')
  const userRaw = params.get('_oms_user')
  if (token && userRaw) {
    localStorage.setItem('oms_auth_token', token)
    localStorage.setItem('oms_auth_user', userRaw)
    // Strip the params from the URL so they don't appear in browser history
    params.delete('_oms_token')
    params.delete('_oms_user')
    const clean = params.toString()
    const newUrl = window.location.pathname + (clean ? '?' + clean : '') + window.location.hash
    window.history.replaceState({}, '', newUrl)
  }
})()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)
