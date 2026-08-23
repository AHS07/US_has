/**
 * Admin — Patient Accounts
 *
 * Lists all patients who have at least one appointment at this hospital.
 * Shows appointment count, last visit date, and last appointment status.
 * Supports search by name.
 *
 * Route: /admin/patients
 */
import { useCallback, useEffect, useState } from 'react'
import { listAdminPatients, type AdminPatient, type HFApiError } from '@/lib/api'

// ─── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ s }: { s: string | null }) {
  if (!s) return <span className="text-xs text-[#A0A09A]">—</span>
  const map: Record<string, string> = {
    confirmed:  'bg-[#EEF3EF] text-[#697C70]',
    completed:  'bg-[#D6E8F0] text-[#2A6080]',
    held:       'bg-[#FDE8C0] text-[#7A4A00]',
    cancelled:  'bg-[#F5D0CC] text-[#8B1A1A]',
    no_show:    'bg-[#F5D0CC] text-[#8B1A1A]',
    reassigned: 'bg-[#FDE8C0] text-[#7A4A00]',
  }
  const label: Record<string, string> = {
    confirmed: 'Confirmed', completed: 'Completed', held: 'Hold',
    cancelled: 'Cancelled', no_show: 'No show', reassigned: 'Reassigned',
  }
  return (
    <span className={`text-[10px] font-medium px-2.5 py-0.5 rounded-full ${map[s] ?? 'bg-[#F2EFE2] text-[#697C70]'}`}>
      {label[s] ?? s}
    </span>
  )
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function PatientAccounts() {
  const [patients, setPatients] = useState<AdminPatient[]>([])
  const [loading,  setLoading]  = useState(true)
  const [search,   setSearch]   = useState('')
  const [error,    setError]    = useState('')

  const load = useCallback(async (q: string) => {
    setLoading(true)
    setError('')
    try {
      const data = await listAdminPatients(q || undefined)
      setPatients(data)
    } catch (err) {
      setError((err as HFApiError).message ?? 'Failed to load patients.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load('') }, [load])

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    await load(search)
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <h2 className="text-base font-semibold text-[#2D3536]">Patient accounts</h2>
        <p className="text-xs text-[#697C70] mt-0.5">
          {loading ? 'Loading…' : `${patients.length} patient${patients.length !== 1 ? 's' : ''} at this hospital`}
        </p>
      </div>

      {/* Search */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="relative flex-1">
          <svg
            className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#A0A09A]"
            width="14" height="14" fill="none" viewBox="0 0 24 24"
            stroke="currentColor" strokeWidth="2" aria-hidden="true"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.35-4.35" strokeLinecap="round" />
          </svg>
          <input
            type="search"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search by patient name…"
            aria-label="Search patients"
            className="w-full bg-white border border-[#D8D2C4] rounded-xl pl-9 pr-4 py-2.5 text-sm text-[#2D3536] placeholder-[#B8B4AC] focus:outline-none focus:border-[#98AA9D] transition-all"
          />
        </div>
        <button
          type="submit"
          className="bg-[#2D3536] text-white text-sm px-4 py-2 rounded-xl font-medium hover:bg-[#3D4546] transition-colors"
        >
          Search
        </button>
      </form>

      {/* Error */}
      {error && (
        <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3">
          {error}
        </p>
      )}

      {/* Table */}
      <div className="bg-white border border-[#E8E4DA] rounded-2xl overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-sm text-[#697C70]">Loading patients…</div>
        ) : patients.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-sm text-[#697C70]">
              {search
                ? 'No patients found matching your search.'
                : 'No patients have booked appointments at this hospital yet.'}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="bg-[#F7F6F3] text-[10px] text-[#697C70] uppercase tracking-wider">
                  <th className="px-5 py-3 text-left font-medium">Patient</th>
                  <th className="px-4 py-3 text-left font-medium">Email</th>
                  <th className="px-4 py-3 text-center font-medium">Appointments</th>
                  <th className="px-4 py-3 text-center font-medium">Last visit</th>
                  <th className="px-4 py-3 text-center font-medium">Last status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F2EFE2]">
                {patients.map(p => (
                  <tr key={p.id} className="hover:bg-[#F7F6F3] transition-colors">
                    {/* Patient */}
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-2.5">
                        <div
                          className="w-8 h-8 rounded-full bg-[#EEF3EF] flex items-center justify-center text-[#697C70] text-sm font-semibold shrink-0"
                          aria-hidden="true"
                        >
                          {p.name.charAt(0)}
                        </div>
                        <div>
                          <p className="font-medium text-[#2D3536]">{p.name}</p>
                          {p.phone && <p className="text-xs text-[#A0A09A]">{p.phone}</p>}
                        </div>
                      </div>
                    </td>
                    {/* Email */}
                    <td className="px-4 py-3.5 text-[#697C70] text-xs">{p.email}</td>
                    {/* Appointment count */}
                    <td className="px-4 py-3.5 text-center font-mono font-semibold text-[#2D3536]">
                      {p.appointment_count}
                    </td>
                    {/* Last visit date */}
                    <td className="px-4 py-3.5 text-center text-xs text-[#697C70]">
                      {formatDate(p.last_appointment_date)}
                    </td>
                    {/* Last status */}
                    <td className="px-4 py-3.5 text-center">
                      <StatusBadge s={p.last_appointment_status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
