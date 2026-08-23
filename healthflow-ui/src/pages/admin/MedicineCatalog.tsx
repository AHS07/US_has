/**
 * Admin — Medicine Catalog
 *
 * Pending-review queue: medicines created ad-hoc by doctors during consultations.
 * Admin can approve (optionally rename to canonical name) or reject each entry.
 * Also shows the full active catalog with search.
 *
 * Route: /admin/medicine-catalog
 */
import { useCallback, useEffect, useState } from 'react'
import {
  searchMedicines,
  updateMedicineStatus,
  type MedicineCatalogItem,
  type HFApiError,
} from '@/lib/api'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: MedicineCatalogItem['status'] }) {
  const map = {
    active:         'bg-[#EEF3EF] text-[#697C70]',
    pending_review: 'bg-[#FDE8C0] text-[#7A4A00]',
    rejected:       'bg-[#F5D0CC] text-[#8B1A1A]',
  }
  const label = {
    active:         'Active',
    pending_review: 'Pending review',
    rejected:       'Rejected',
  }
  return (
    <span className={`text-[11px] font-medium px-2.5 py-0.5 rounded-full ${map[status]}`}>
      {label[status]}
    </span>
  )
}

// ─── Approve / merge modal ────────────────────────────────────────────────────

function ApproveModal({
  medicine,
  onClose,
  onApproved,
}: {
  medicine: MedicineCatalogItem
  onClose: () => void
  onApproved: (updated: MedicineCatalogItem) => void
}) {
  const [name,    setName]    = useState(medicine.name)
  const [saving,  setSaving]  = useState(false)
  const [error,   setError]   = useState('')

  async function handleApprove() {
    setSaving(true)
    setError('')
    try {
      const updated = await updateMedicineStatus(medicine.id, {
        status: 'active',
        name: name.trim() || medicine.name,
      })
      onApproved(updated)
      onClose()
    } catch (err) {
      setError((err as HFApiError).message ?? 'Approval failed.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden="true" />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-sm mx-4 p-6 space-y-4">
        <h3 className="font-semibold text-[#2D3536]">Approve medicine</h3>
        {error && (
          <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-3 py-2">
            {error}
          </p>
        )}
        <div>
          <label htmlFor="approve-name" className="block text-xs text-[#697C70] mb-1.5 uppercase tracking-wider">
            Canonical name (edit to merge)
          </label>
          <input
            id="approve-name"
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            className="w-full bg-[#F7F6F3] border border-[#D8D2C4] rounded-xl px-3 py-2.5 text-[#2D3536] focus:outline-none focus:border-[#98AA9D] text-sm"
          />
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 border border-[#D8D2C4] text-[#697C70] rounded-xl py-2.5 text-sm font-medium hover:bg-[#F7F6F3] transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleApprove}
            disabled={saving || !name.trim()}
            className="flex-1 bg-[#98AA9D] text-white rounded-xl py-2.5 text-sm font-semibold hover:bg-[#7A9080] transition-colors disabled:opacity-60"
          >
            {saving ? 'Approving…' : 'Approve'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function MedicineCatalog() {
  const [tab,        setTab]        = useState<'pending' | 'active'>('pending')
  const [medicines,  setMedicines]  = useState<MedicineCatalogItem[]>([])
  const [loading,    setLoading]    = useState(true)
  const [search,     setSearch]     = useState('')
  const [approving,  setApproving]  = useState<MedicineCatalogItem | null>(null)
  const [rejecting,  setRejecting]  = useState<string | null>(null)
  const [error,      setError]      = useState('')

  const load = useCallback(async (t: 'pending' | 'active', q = '') => {
    setLoading(true)
    setError('')
    try {
      const data = await searchMedicines(q, t === 'pending' ? 'pending' : 'active')
      setMedicines(data)
    } catch (err) {
      setError((err as HFApiError).message ?? 'Failed to load medicines.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load(tab, search) }, [tab, load])

  async function handleSearch() { await load(tab, search) }

  async function handleReject(med: MedicineCatalogItem) {
    setRejecting(med.id)
    try {
      const updated = await updateMedicineStatus(med.id, { status: 'rejected' })
      setMedicines(prev => prev.filter(m => m.id !== updated.id))
    } catch (err) {
      setError((err as HFApiError).message ?? 'Rejection failed.')
    } finally {
      setRejecting(null)
    }
  }

  function handleApproved(updated: MedicineCatalogItem) {
    setMedicines(prev => prev.filter(m => m.id !== updated.id))
  }

  const pendingCount = tab === 'pending' ? medicines.length : null
  void pendingCount  // reserved for future badge display

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <h2 className="text-base font-semibold text-[#2D3536]">Medicine catalog</h2>
        <p className="text-xs text-[#697C70] mt-0.5">
          Review medicines added by doctors during consultations.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex bg-[#E8E4DA] rounded-xl p-1 gap-1 w-fit">
        {(['pending', 'active'] as const).map(t => (
          <button
            key={t}
            type="button"
            onClick={() => { setTab(t); setSearch('') }}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${
              tab === t
                ? 'bg-white text-[#2D3536] shadow-sm'
                : 'text-[#697C70] hover:text-[#2D3536]'
            }`}
          >
            {t === 'pending' ? 'Pending review' : 'Active catalog'}
          </button>
        ))}
      </div>

      {error && (
        <p role="alert" className="text-sm text-[#8B1A1A] bg-[#F5D0CC] rounded-xl px-4 py-3">
          {error}
        </p>
      )}

      {/* Search (active tab only) */}
      {tab === 'active' && (
        <div className="flex gap-2">
          <div className="relative flex-1">
            <svg className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#A0A09A]" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" strokeLinecap="round" />
            </svg>
            <input
              type="search"
              value={search}
              onChange={e => setSearch(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder="Search active medicines…"
              aria-label="Search medicines"
              className="w-full bg-white border border-[#D8D2C4] rounded-xl pl-9 pr-4 py-2.5 text-sm text-[#2D3536] placeholder-[#B8B4AC] focus:outline-none focus:border-[#98AA9D]"
            />
          </div>
          <button
            type="button"
            onClick={handleSearch}
            className="bg-[#2D3536] text-white text-sm px-4 py-2 rounded-xl font-medium hover:bg-[#3D4546] transition-colors"
          >
            Search
          </button>
        </div>
      )}

      {/* Table */}
      <div className="bg-white border border-[#E8E4DA] rounded-2xl overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-sm text-[#697C70]">Loading…</div>
        ) : medicines.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-sm text-[#697C70]">
              {tab === 'pending'
                ? 'No medicines pending review.'
                : 'No medicines found.'}
            </p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-[#F7F6F3] text-[10px] text-[#697C70] uppercase tracking-wider">
                <th className="px-5 py-3 text-left font-medium">Name</th>
                <th className="px-4 py-3 text-left font-medium">Generic name</th>
                <th className="px-4 py-3 text-left font-medium">Default dosage</th>
                <th className="px-4 py-3 text-center font-medium">Status</th>
                {tab === 'pending' && (
                  <th className="px-4 py-3 text-left font-medium">Actions</th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F2EFE2]">
              {medicines.map(med => (
                <tr key={med.id} className="hover:bg-[#F7F6F3] transition-colors">
                  <td className="px-5 py-3.5 font-medium text-[#2D3536]">{med.name}</td>
                  <td className="px-4 py-3.5 text-[#697C70]">{med.generic_name || '—'}</td>
                  <td className="px-4 py-3.5 text-[#697C70] font-mono text-xs">{med.default_dosage || '—'}</td>
                  <td className="px-4 py-3.5 text-center">
                    <StatusBadge status={med.status} />
                  </td>
                  {tab === 'pending' && (
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-3 text-xs">
                        <button
                          type="button"
                          onClick={() => setApproving(med)}
                          className="text-[#697C70] hover:text-[#98AA9D] font-medium transition-colors"
                        >
                          Approve
                        </button>
                        <span className="text-[#E8E4DA]" aria-hidden="true">·</span>
                        <button
                          type="button"
                          onClick={() => handleReject(med)}
                          disabled={rejecting === med.id}
                          className="text-[#697C70] hover:text-[#8B1A1A] font-medium transition-colors disabled:opacity-60"
                        >
                          {rejecting === med.id ? 'Rejecting…' : 'Reject'}
                        </button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Approve modal */}
      {approving && (
        <ApproveModal
          medicine={approving}
          onClose={() => setApproving(null)}
          onApproved={handleApproved}
        />
      )}
    </div>
  )
}
