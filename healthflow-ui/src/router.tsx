import { createBrowserRouter, Navigate } from 'react-router-dom'
import ProtectedRoute from '@/components/ProtectedRoute'

// Landing
import Landing from '@/pages/Landing'

// Patient
import PatientLayout from '@/pages/patient/PatientLayout'
import PatientLogin from '@/pages/patient/PatientLogin'
import ResetPassword from '@/pages/patient/ResetPassword'
import DoctorSearch from '@/pages/patient/DoctorSearch'
import DoctorDetail from '@/pages/patient/DoctorDetail'        // Phase 3
import SymptomForm from '@/pages/patient/SymptomForm'          // Phase 3
import BookingConfirmation from '@/pages/patient/BookingConfirmation' // Phase 3
import Appointments from '@/pages/patient/Appointments'
import Notifications from '@/pages/patient/Notifications'
import Profile from '@/pages/patient/Profile'
import PostVisitSummary from '@/pages/patient/PostVisitSummary'        // Phase 5

// Doctor
import DoctorLayout from '@/pages/doctor/DoctorLayout'
import DoctorLogin from '@/pages/doctor/DoctorLogin'
import DayView from '@/pages/doctor/DayView'
import PatientDetail from '@/pages/doctor/PatientDetail'
import ConsultationScreen from '@/pages/doctor/ConsultationScreen'    // Phase 5
import SummaryReview from '@/pages/doctor/SummaryReview'              // Phase 5

// Admin
import AdminLayout from '@/pages/admin/AdminLayout'
import AdminLogin from '@/pages/admin/AdminLogin'
import Dashboard from '@/pages/admin/Dashboard'
import DoctorManagement from '@/pages/admin/DoctorManagement'
import AttendanceSheet from '@/pages/admin/AttendanceSheet'
import LeaveCalendar from '@/pages/admin/LeaveCalendar'   // Phase 2
import PatientAccounts from '@/pages/admin/PatientAccounts'
import MedicineCatalog from '@/pages/admin/MedicineCatalog'

export const router = createBrowserRouter([
  // Root → Landing
  { path: '/', element: <Landing /> },

  // ─── Patient portal ─────────────────────────────────────────────────────
  {
    path: '/patient',
    element: <PatientLayout />,
    children: [
      { index: true, element: <Navigate to="/patient/login" replace /> },
      { path: 'login', element: <PatientLogin /> },
      // Forced reset — accessible even when must_reset_password=true
      { path: 'reset-password', element: <ResetPassword /> },
      {
        path: 'search',
        element: <ProtectedRoute role="patient"><DoctorSearch /></ProtectedRoute>,
      },
      // Phase 3: booking flow
      {
        path: 'doctors/:doctorId',
        element: <ProtectedRoute role="patient"><DoctorDetail /></ProtectedRoute>,
      },
      {
        path: 'symptom-form',
        element: <ProtectedRoute role="patient"><SymptomForm /></ProtectedRoute>,
      },
      {
        path: 'booking-confirmation',
        element: <ProtectedRoute role="patient"><BookingConfirmation /></ProtectedRoute>,
      },
      {
        path: 'appointments',
        element: <ProtectedRoute role="patient"><Appointments /></ProtectedRoute>,
      },
      // Phase 5: post-visit summary
      {
        path: 'appointments/:appointmentId/summary',
        element: <ProtectedRoute role="patient"><PostVisitSummary /></ProtectedRoute>,
      },
      {
        path: 'notifications',
        element: <ProtectedRoute role="patient"><Notifications /></ProtectedRoute>,
      },
      {
        path: 'profile',
        element: <ProtectedRoute role="patient"><Profile /></ProtectedRoute>,
      },
    ],
  },

  // ─── Doctor portal ──────────────────────────────────────────────────────
  {
    path: '/doctor',
    element: <DoctorLayout />,
    children: [
      { index: true, element: <Navigate to="/doctor/login" replace /> },
      { path: 'login', element: <DoctorLogin /> },
      {
        path: 'day-view',
        element: <ProtectedRoute role="doctor"><DayView /></ProtectedRoute>,
      },
      // Phase 2: patient detail / pre-visit briefing
      {
        path: 'appointments/:appointmentId',
        element: <ProtectedRoute role="doctor"><PatientDetail /></ProtectedRoute>,
      },
      // Phase 5: consultation + summary review
      {
        path: 'consultation/:appointmentId',
        element: <ProtectedRoute role="doctor"><ConsultationScreen /></ProtectedRoute>,
      },
      {
        path: 'summary-review/:appointmentId',
        element: <ProtectedRoute role="doctor"><SummaryReview /></ProtectedRoute>,
      },
    ],
  },

  // ─── Admin portal ───────────────────────────────────────────────────────
  {
    path: '/admin',
    element: <AdminLayout />,
    children: [
      { index: true, element: <Navigate to="/admin/login" replace /> },
      { path: 'login', element: <AdminLogin /> },
      {
        path: 'dashboard',
        element: <ProtectedRoute role="admin"><Dashboard /></ProtectedRoute>,
      },
      {
        path: 'doctors',
        element: <ProtectedRoute role="admin"><DoctorManagement /></ProtectedRoute>,
      },
      {
        path: 'attendance',
        element: <ProtectedRoute role="admin"><AttendanceSheet /></ProtectedRoute>,
      },
      // Phase 2: leave calendar
      {
        path: 'leave',
        element: <ProtectedRoute role="admin"><LeaveCalendar /></ProtectedRoute>,
      },
      {
        path: 'patients',
        element: <ProtectedRoute role="admin"><PatientAccounts /></ProtectedRoute>,
      },
      {
        path: 'medicine-catalog',
        element: <ProtectedRoute role="admin"><MedicineCatalog /></ProtectedRoute>,
      },
    ],
  },

  // Catch-all
  { path: '*', element: <Navigate to="/" replace /> },
])
