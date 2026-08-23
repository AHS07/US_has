export type UrgencyLevel = 'Low' | 'Medium' | 'High'

interface Props {
  level: UrgencyLevel
  size?: 'sm' | 'md'
}

const configs: Record<UrgencyLevel, { bg: string; text: string; icon: string }> = {
  Low:    { bg: 'bg-[#D6E8F0]', text: 'text-[#2A6080]', icon: '●' },
  Medium: { bg: 'bg-[#FDE8C0]', text: 'text-[#7A4A00]', icon: '▲' },
  High:   { bg: 'bg-[#F5D0CC]', text: 'text-[#8B1A1A]', icon: '⚠' },
}

export default function UrgencyBadge({ level, size = 'md' }: Props) {
  const c = configs[level]
  const sizeClass = size === 'sm' ? 'text-xs px-2 py-0.5 gap-1' : 'text-xs px-2.5 py-1 gap-1.5'
  return (
    <span
      className={`inline-flex items-center rounded-full font-mono font-medium ${c.bg} ${c.text} ${sizeClass}`}
      aria-label={`Urgency: ${level}`}
    >
      <span aria-hidden="true" className="text-[10px]">{c.icon}</span>
      {level}
    </span>
  )
}
