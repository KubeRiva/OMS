interface BadgeProps {
  value: string
  className?: string
  size?: 'sm' | 'md'
}

const sizeClasses = {
  sm: 'px-1.5 py-0.5 text-[10px]',
  md: 'px-2 py-0.5 text-xs',
}

const statusColors: Record<string, string> = {
  // Order statuses
  PENDING: 'bg-gray-100 text-gray-700',
  CONFIRMED: 'bg-blue-100 text-blue-700',
  SOURCING: 'bg-purple-100 text-purple-700',
  SOURCED: 'bg-indigo-100 text-indigo-700',
  BACKORDERED: 'bg-amber-100 text-amber-800',
  PICKING: 'bg-yellow-100 text-yellow-700',
  PACKING: 'bg-orange-100 text-orange-700',
  READY_TO_SHIP: 'bg-cyan-100 text-cyan-700',
  SHIPPED: 'bg-sky-100 text-sky-700',
  OUT_FOR_DELIVERY: 'bg-teal-100 text-teal-700',
  DELIVERED: 'bg-green-100 text-green-700',
  READY_FOR_PICKUP: 'bg-lime-100 text-lime-700',
  PICKED_UP: 'bg-teal-100 text-teal-700',
  CANCELLED: 'bg-red-100 text-red-700',
  RETURNED: 'bg-pink-100 text-pink-700',
  REFUNDED: 'bg-rose-100 text-rose-700',
  FAILED: 'bg-orange-100 text-orange-700',
  // Payment
  AUTHORIZED: 'bg-cyan-100 text-cyan-700',
  CAPTURED: 'bg-green-100 text-green-700',
  // Node types
  DISTRIBUTION_CENTER: 'bg-blue-100 text-blue-700',
  RETAIL_STORE: 'bg-green-100 text-green-700',
  DARK_STORE: 'bg-purple-100 text-purple-700',
  WAREHOUSE: 'bg-gray-100 text-gray-700',
  // Channels
  WEB: 'bg-blue-100 text-blue-700',
  MOBILE: 'bg-violet-100 text-violet-700',
  POS: 'bg-amber-100 text-amber-700',
  API: 'bg-gray-100 text-gray-700',
  MARKETPLACE: 'bg-orange-100 text-orange-700',
  // Strategies
  DISTANCE_OPTIMAL: 'bg-blue-100 text-blue-700',
  COST_OPTIMAL: 'bg-green-100 text-green-700',
  STORE_NEAREST: 'bg-teal-100 text-teal-700',
  INVENTORY_RESERVATION: 'bg-purple-100 text-purple-700',
  LEAST_COST_SPLIT: 'bg-orange-100 text-orange-700',
  // Node status
  ACTIVE: 'bg-green-100 text-green-700',
  INACTIVE: 'bg-gray-100 text-gray-500',
  MAINTENANCE: 'bg-yellow-100 text-yellow-700',
  CLOSED: 'bg-red-100 text-red-700',
  // Allocation
  ALLOCATED: 'bg-indigo-100 text-indigo-700',
  PICKING_A: 'bg-yellow-100 text-yellow-700',
  PACKED: 'bg-orange-100 text-orange-700',
  DELIVERED_A: 'bg-green-100 text-green-700',
  // Webhook delivery
  RETRYING: 'bg-yellow-100 text-yellow-700',
  ABANDONED: 'bg-gray-100 text-gray-500',
}

export function StatusBadge({ value, className = '', size = 'md' }: BadgeProps) {
  const color = statusColors[value] ?? 'bg-gray-100 text-gray-700'
  return (
    <span className={`inline-flex items-center rounded-full font-semibold ${sizeClasses[size]} ${color} ${className}`}>
      {value.replace(/_/g, ' ')}
    </span>
  )
}

export function ChannelBadge({ value, size }: BadgeProps) {
  return <StatusBadge value={value} size={size} />
}
