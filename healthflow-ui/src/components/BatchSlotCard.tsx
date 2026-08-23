export interface BatchSlot {
  id: string
  time: string
  endTime: string
  capacity: number
  booked: number
  status: 'open' | 'full' | 'unavailable'
  date: string
}

interface Props {
  slot: BatchSlot
  selected?: boolean
  onClick?: () => void
}

export default function BatchSlotCard({ slot, selected = false, onClick }: Props) {
  const remaining = slot.capacity - slot.booked
  const isDisabled = slot.status !== 'open'

  let borderClass = ''
  let bgClass = ''
  let statusLabel = ''
  let statusClass = ''

  if (slot.status === 'full') {
    statusLabel = 'Full'
    statusClass = 'text-[#8B1A1A] bg-[#F5D0CC]'
    borderClass = 'border-[#F5D0CC]'
    bgClass = 'bg-white opacity-70'
  } else if (slot.status === 'unavailable') {
    statusLabel = 'Unavailable'
    statusClass = 'text-[#697C70] bg-[#E8E4DA]'
    borderClass = 'border-[#D8D4CA]'
    bgClass = 'bg-[#F5F3EE] opacity-70'
  } else if (selected) {
    borderClass = 'border-[#98AA9D]'
    bgClass = 'bg-[#EEF3EF]'
  } else {
    borderClass = 'border-[#D8D2C4]'
    bgClass = 'bg-white hover:border-[#98AA9D] hover:bg-[#F5F8F5]'
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isDisabled}
      aria-pressed={selected}
      aria-label={`${slot.time}–${slot.endTime}, ${remaining} of ${slot.capacity} seats available`}
      className={`w-full text-left rounded-xl border-2 p-4 transition-all duration-150
        ${bgClass} ${borderClass}
        ${isDisabled ? 'cursor-not-allowed' : 'cursor-pointer'}
        ${selected ? 'ring-2 ring-[#98AA9D] ring-offset-1' : ''}
      `}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-[#2D3536] font-mono">
            {slot.time} – {slot.endTime}
          </p>
          {slot.status === 'open' && (
            <p className="text-xs text-[#697C70] mt-0.5">{remaining} of {slot.capacity} seats open</p>
          )}
          {slot.status === 'unavailable' && (
            <p className="text-xs text-[#697C70] mt-0.5">Doctor unavailable this window</p>
          )}
          {slot.status === 'full' && (
            <p className="text-xs text-[#8B1A1A] mt-0.5">No seats remaining</p>
          )}
        </div>
        {statusLabel && (
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full shrink-0 ${statusClass}`}>
            {statusLabel}
          </span>
        )}
        {slot.status === 'open' && selected && (
          <span className="text-xs font-medium px-2 py-0.5 rounded-full shrink-0 bg-[#98AA9D] text-white">
            Selected
          </span>
        )}
      </div>

      {slot.status === 'open' && (
        <div className="mt-3" aria-hidden="true">
          <div className="flex gap-1">
            {Array.from({ length: slot.capacity }).map((_, i) => (
              <div
                key={i}
                className={`h-1.5 flex-1 rounded-full transition-colors ${
                  i < slot.booked ? 'bg-[#697C70]' : 'bg-[#D8D2C4]'
                }`}
              />
            ))}
          </div>
        </div>
      )}
    </button>
  )
}
