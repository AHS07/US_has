/**
 * Patient — Notifications feed
 *
 * Shows the last 50 in-app notifications with unread count badge.
 * Tapping a notification marks it read; "Mark all read" clears the badge.
 * Event-type icons provide quick visual context.
 *
 * Route: /patient/notifications
 */
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getNotifications,
  markNotificationRead,
  markAllNotificationsRead,
  type AppNotification,
  type NotificationEventType,
  type HFApiError,
} from '@/lib/api'

// ─── Icons per event type ─────────────────────────────────────────────────────

function EventIcon({ type }: { type: NotificationEventType }) {
  const icons: Record<NotificationEventType, React.ReactNode> = {
    booking_confirmed: (
      <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="#98AA9D" strokeWidth="1.8" aria-hidden="true">
        <path d="M20 6 9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    booking_cancelled: (
      <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="#C84B4B" strokeWidth="1.8" aria-hidden="true">
        <path d="M18 6 6 18M6 6l12 12" strokeLinecap="round" />
      </svg>
    ),
    booking_rescheduled: (
      <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="#E8A838" strokeWidth="1.8" aria-hidden="true">
        <path d="M1 4v6h6M23 20v-6h-6" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15" strokeLinecap="round" />
      </svg>
    ),
    doctor_absent: (
      <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="#E8A838" strokeWidth="1.8" aria-hidden="true">
        <circle cx="12" cy="12" r="10" /><path d="M12 8v4M12 16h.01" strokeLinecap="round" />
      </svg>
    ),
    reschedule_offer: (
      <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="#697C70" strokeWidth="1.8" aria-hidden="true">
        <rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" strokeLinecap="round" />
      </svg>
    ),
    running_late: (
      <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="#E8A838" strokeWidth="1.8" aria-hidden="true">
        <circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" strokeLinecap="round" />
      </svg>
    ),
    follow_up_available: (
      <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="#697C70" strokeWidth="1.8" aria-hidden="true">
        <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6" strokeLinecap="round" />
      </svg>
    ),
    visit_summary_ready: (
      <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="#98AA9D" strokeWidth="1.8" aria-hidden="true">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" strokeLinecap="round" />
      </svg>
    ),
  }
  return <>{icons[type] ?? null}</>
}

function iconBg(type: NotificationEventType): string {
  switch (type) {
    case 'booking_confirmed':
    case 'visit_summary_ready':
      return 'bg-[#EEF3EF]'
    case 'booking_cancelled':
      return 'bg-[#F5D0CC]'
    case 'booking_rescheduled':
    case 'doctor_absent':
    case 'running_late':
      return 'bg-[#FDE8C0]'
    default:
      return 'bg-[#F2EFE2]'
  }
}

function timeAgo(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60)    return 'Just now'
  if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

// ─── Notification row ─────────────────────────────────────────────────────────

function NotifRow({
  notif,
  onRead,
}: {
  notif: AppNotification
  onRead: (id: string) => void
}) {
  const navigate = useNavigate()

  function handleClick() {
    if (!notif.is_read) onRead(notif.id)
    if (notif.appointment_id) {
      if (notif.event_type === 'visit_summary_ready') {
        navigate(`/patient/appointments/${notif.appointment_id}/summary`)
      } else {
        navigate('/patient/appointments')
      }
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      className={`w-full text-left flex items-start gap-3 px-4 py-3.5 border-b border-[#F2EFE2] transition-colors hover:bg-[#F5F8F5] ${
        !notif.is_read ? 'bg-white' : 'bg-[#FAFAF8]'
      }`}
      aria-label={`${notif.title}${notif.is_read ? '' : ' (unread)'}`}
    >
      {/* Icon */}
      <div className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${iconBg(notif.event_type)}`}>
        <EventIcon type={notif.event_type} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <p className={`text-sm leading-snug ${notif.is_read ? 'text-[#697C70]' : 'text-[#2D3536] font-medium'}`}>
            {notif.title}
          </p>
          <span className="text-[10px] text-[#A0A09A] shrink-0 mt-0.5">{timeAgo(notif.created_at)}</span>
        </div>
        {notif.body && (
          <p className="text-xs text-[#A0A09A] mt-0.5 line-clamp-2">{notif.body}</p>
        )}
      </div>

      {/* Unread dot */}
      {!notif.is_read && (
        <span
          className="w-2 h-2 rounded-full bg-[#98AA9D] shrink-0 mt-2"
          aria-hidden="true"
        />
      )}
    </button>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function Notifications() {
  const [notifications, setNotifications] = useState<AppNotification[]>([])
  const [unreadCount,   setUnreadCount]   = useState(0)
  const [loading,       setLoading]       = useState(true)
  const [error,         setError]         = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getNotifications()
      setNotifications(data.notifications)
      setUnreadCount(data.unread_count)
    } catch (err) {
      setError((err as HFApiError).message ?? 'Failed to load notifications.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  async function handleRead(id: string) {
    try {
      await markNotificationRead(id)
      setNotifications(prev =>
        prev.map(n => n.id === id ? { ...n, is_read: true } : n)
      )
      setUnreadCount(c => Math.max(0, c - 1))
    } catch { /* best effort */ }
  }

  async function handleMarkAllRead() {
    try {
      await markAllNotificationsRead()
      setNotifications(prev => prev.map(n => ({ ...n, is_read: true })))
      setUnreadCount(0)
    } catch { /* best effort */ }
  }

  return (
    <div className="pb-8">
      {/* Header */}
      <div className="px-4 pt-5 pb-3 flex items-center justify-between border-b border-[#E8E4DA]">
        <div className="flex items-center gap-2">
          <h2 className="text-xl font-semibold text-[#2D3536] font-serif">Alerts</h2>
          {unreadCount > 0 && (
            <span className="bg-[#98AA9D] text-white text-[11px] font-bold px-2 py-0.5 rounded-full">
              {unreadCount}
            </span>
          )}
        </div>
        {unreadCount > 0 && (
          <button
            type="button"
            onClick={handleMarkAllRead}
            className="text-xs text-[#697C70] hover:text-[#2D3536] font-medium transition-colors"
          >
            Mark all read
          </button>
        )}
      </div>

      {/* Error */}
      {error && (
        <p role="alert" className="mx-4 mt-3 text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3">
          {error}
        </p>
      )}

      {/* List */}
      {loading ? (
        <div className="space-y-1 mt-2">
          {[1, 2, 3].map(i => (
            <div key={i} className="mx-4 h-16 rounded-xl bg-[#E8E4DA] animate-pulse" />
          ))}
        </div>
      ) : notifications.length === 0 ? (
        <div className="px-4 py-12 text-center">
          <p className="text-sm text-[#697C70]">No alerts yet.</p>
          <p className="text-xs text-[#A0A09A] mt-1">
            Appointment confirmations and updates will appear here.
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-2xl border border-[#E8E4DA] mx-4 mt-3 overflow-hidden">
          {notifications.map(n => (
            <NotifRow key={n.id} notif={n} onRead={handleRead} />
          ))}
        </div>
      )}
    </div>
  )
}
