import { LucideIcon } from 'lucide-react'

interface StatCardProps {
  title: string
  value: string | number
  subtitle?: string
  icon: LucideIcon
  iconColor?: string
  trend?: { value: number; label: string }
  loading?: boolean
}

const iconBgColors: Record<string, string> = {
  'text-blue-600': 'bg-blue-50',
  'text-green-600': 'bg-green-50',
  'text-purple-600': 'bg-purple-50',
  'text-amber-600': 'bg-amber-50',
  'text-red-600': 'bg-red-50',
  'text-indigo-600': 'bg-indigo-50',
  'text-cyan-600': 'bg-cyan-50',
  'text-teal-600': 'bg-teal-50',
}

export default function StatCard({ title, value, subtitle, icon: Icon, iconColor = 'text-blue-600', trend, loading }: StatCardProps) {
  const iconBg = iconBgColors[iconColor] || 'bg-gray-50'

  if (loading) {
    return (
      <div className="card p-5 animate-pulse">
        <div className="h-4 bg-gray-200 rounded w-2/3 mb-3" />
        <div className="h-8 bg-gray-200 rounded w-1/2" />
      </div>
    )
  }
  return (
    <div className="card p-5 fade-in">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">{title}</p>
          <p className="mt-1.5 text-2xl font-bold text-gray-900">{value}</p>
          {subtitle && <p className="mt-0.5 text-xs text-gray-500">{subtitle}</p>}
          {trend && (
            <p className={`mt-1 text-xs font-medium ${trend.value >= 0 ? 'text-green-600' : 'text-red-600'}`}>
              {trend.value >= 0 ? '↑' : '↓'} {Math.abs(trend.value)}% {trend.label}
            </p>
          )}
        </div>
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${iconBg}`}>
          <Icon className={`w-5 h-5 ${iconColor}`} />
        </div>
      </div>
    </div>
  )
}
