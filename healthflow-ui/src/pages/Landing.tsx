import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { animate, stagger } from 'animejs'

type Portal = 'patient' | 'doctor' | 'admin'

const portals: {
  key: Portal
  label: string
  description: string
  color: string
  textColor: string
  descColor: string
  accent: string
  icon: React.ReactNode
}[] = [
  {
    key: 'patient',
    label: 'Patient',
    description: 'Book appointments, track visits, and read your care summaries',
    color: 'bg-[#EEF3EF] hover:bg-[#E0EBE0] border-[#C8D8C8]',
    textColor: 'text-[#2D3536]',
    descColor: 'text-[#697C70]',
    accent: '#98AA9D',
    icon: (
      <svg width="28" height="28" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
        <circle cx="12" cy="8" r="4" />
        <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    key: 'doctor',
    label: 'Doctor',
    description: 'Manage your day\'s schedule, patients, and post-visit summaries',
    color: 'bg-[#2D3536] hover:bg-[#3D4546] border-[#3D4546]',
    textColor: 'text-white',
    descColor: 'text-[#8A9A8E]',
    accent: '#B3C9D6',
    icon: (
      <svg width="28" height="28" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
        <path d="M12 4v6m0 0c0 2.2-1.8 4-4 4H6a4 4 0 0 1-4-4V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v4a4 4 0 0 1-4 4h-2z" />
        <path d="M12 10v10M8 16h8" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    key: 'admin',
    label: 'Admin',
    description: 'Run clinic operations — doctors, schedules, attendance, and more',
    color: 'bg-white hover:bg-[#F7F6F3] border-[#E8E4DA]',
    textColor: 'text-[#2D3536]',
    descColor: 'text-[#697C70]',
    accent: '#697C70',
    icon: (
      <svg width="28" height="28" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
        <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
      </svg>
    ),
  },
]

export default function Landing() {
  const navigate = useNavigate()
  const heroRef = useRef<HTMLDivElement>(null)
  const cardsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (heroRef.current) {
      animate(heroRef.current, {
        opacity: [0, 1],
        translateY: [-16, 0],
        duration: 700,
        easing: 'easeOutCubic',
      })
    }
    if (cardsRef.current) {
      const cards = cardsRef.current.querySelectorAll('.portal-card')
      animate(cards, {
        opacity: [0, 1],
        translateY: [24, 0],
        delay: stagger(100, { start: 300 }),
        duration: 500,
        easing: 'easeOutCubic',
      })
    }
  }, [])

  return (
    <div className="min-h-screen bg-[#2D3536] flex flex-col items-center justify-center p-8">
      {/* Background rings */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none" aria-hidden="true">
        <div className="absolute top-20 right-20 w-64 h-64 rounded-full border border-[#3A4546] opacity-40" />
        <div className="absolute top-32 right-32 w-40 h-40 rounded-full border border-[#3A4546] opacity-30" />
        <div className="absolute bottom-20 left-20 w-48 h-48 rounded-full border border-[#3A4546] opacity-20" />
      </div>

      <div className="relative w-full max-w-2xl">
        {/* Header */}
        <div ref={heroRef} className="text-center mb-12" style={{ opacity: 0 }}>
          <div className="flex items-center justify-center gap-3 mb-6">
            <div className="w-11 h-11 rounded-2xl bg-[#98AA9D] flex items-center justify-center">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M12 4v16M4 12h16" stroke="white" strokeWidth="2.5" strokeLinecap="round" />
              </svg>
            </div>
            <span className="text-white text-2xl font-semibold tracking-tight">HealthFlow</span>
          </div>
          <h1 className="text-white text-4xl leading-tight mb-3 font-serif">
            Your clinic,<br />thoughtfully designed.
          </h1>
          <p className="text-[#8A9A8E] text-base max-w-md mx-auto leading-relaxed">
            A clinic appointment platform built for Indian outpatient clinics — batch booking,
            AI-assisted care summaries, and calm, clear communication.
          </p>
        </div>

        {/* Portal cards */}
        <div ref={cardsRef} className="grid grid-cols-1 gap-3" role="list">
          {portals.map(({ key, label, description, color, textColor, descColor, accent, icon }) => (
            <button
              key={key}
              type="button"
              role="listitem"
              onClick={() => navigate(`/${key}/login`)}
              className={`portal-card w-full text-left flex items-center gap-5 rounded-2xl border p-5 transition-all duration-200 active:scale-[0.99] ${color}`}
              style={{ opacity: 0 }}
            >
              <div
                className="w-14 h-14 rounded-2xl flex items-center justify-center shrink-0"
                style={{ background: `${accent}20`, color: accent }}
                aria-hidden="true"
              >
                {icon}
              </div>
              <div className="flex-1 min-w-0">
                <p className={`text-lg font-semibold mb-1 font-serif ${textColor}`}>
                  {label} portal
                </p>
                <p className={`text-sm leading-relaxed ${descColor}`}>{description}</p>
              </div>
              <svg
                width="20" height="20" fill="none" viewBox="0 0 24 24"
                stroke="currentColor" strokeWidth="2"
                className="shrink-0 text-[#697C70]"
                aria-hidden="true"
              >
                <path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          ))}
        </div>

        <p className="text-center text-[#697C70] text-xs mt-8">
          HealthFlow · Clinic appointment management
        </p>
      </div>
    </div>
  )
}
