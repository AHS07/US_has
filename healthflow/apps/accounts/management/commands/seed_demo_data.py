"""
Django management command to seed demo data for HealthFlow.

Creates:
  - Default Hospital ("City General Hospital")
  - Admin account (admin@healthflow.local / AdminPass123!)
  - 4 Specialist Doctors with shift configs and 7-day slot generation:
      1. Dr. Rajesh Sharma (Cardiology)
      2. Dr. Ananya Patel (Dermatology)
      3. Dr. Vikram Gupta (General Medicine)
      4. Dr. Sunita Rao (Pediatrics)
  - 2 Patient accounts:
      1. Raj Kumar (patient.raj@healthflow.local / PatientPass123!)
      2. Priya Sharma (patient.priya@healthflow.local / PatientPass123!)
  - Starter medicine catalog for the hospital
"""
import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Hospital, User, UserRole
from apps.clinical.models import MedicineCatalog, MedicineStatus
from apps.scheduling.models import DoctorProfile, ShiftConfig
from apps.scheduling.services import generate_slots_for_doctor


class Command(BaseCommand):
    help = "Seeds initial demo hospital, admin, doctors with batch slots, patients, and medicines."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding HealthFlow demo data..."))

        # 1. Hospital
        hospital, created = Hospital.objects.get_or_create(
            name="City General Hospital",
            defaults={
                "address": "100 Medical Center Way, Sector 4",
                "contact_email": "contact@citygeneral.local",
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created hospital: {hospital.name}"))
        else:
            self.stdout.write(f"Hospital already exists: {hospital.name}")

        # 2. Admin User
        admin_email = "admin@healthflow.local"
        admin, created = User.objects.get_or_create(
            email=admin_email,
            defaults={
                "name": "Hospital Admin",
                "role": UserRole.ADMIN,
                "hospital": hospital,
                "must_reset_password": False,
            },
        )
        admin.set_password("AdminPass123!")
        admin.must_reset_password = False
        admin.role = UserRole.ADMIN
        admin.hospital = hospital
        admin.save()
        self.stdout.write(self.style.SUCCESS(f"Admin ready: {admin_email} (Pass: AdminPass123!)"))

        # 3. Doctors
        doctors_data = [
            ("dr.sharma@healthflow.local", "Dr. Rajesh Sharma", "Cardiology"),
            ("dr.patel@healthflow.local", "Dr. Ananya Patel", "Dermatology"),
            ("dr.gupta@healthflow.local", "Dr. Vikram Gupta", "General Medicine"),
            ("dr.rao@healthflow.local", "Dr. Sunita Rao", "Pediatrics"),
        ]

        today = timezone.now().date()
        date_to = today + datetime.timedelta(days=7)

        for email, name, specialization in doctors_data:
            doc_user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "name": name,
                    "role": UserRole.DOCTOR,
                    "hospital": hospital,
                    "must_reset_password": False,
                    "created_by": admin,
                },
            )
            doc_user.set_password("DoctorPass123!")
            doc_user.must_reset_password = False
            doc_user.role = UserRole.DOCTOR
            doc_user.hospital = hospital
            doc_user.save()

            profile, _ = DoctorProfile.objects.get_or_create(
                user=doc_user,
                defaults={
                    "specialization": specialization,
                    "slot_duration_minutes": 60,
                    "slot_capacity": 5,
                    "is_active": True,
                },
            )
            profile.specialization = specialization
            profile.is_active = True
            profile.save()

            shift, _ = ShiftConfig.objects.get_or_create(
                doctor=profile,
                defaults={
                    "shift_1_start": datetime.time(9, 0),
                    "shift_1_end": datetime.time(13, 0),
                    "shift_2_start": datetime.time(14, 0),
                    "shift_2_end": datetime.time(17, 0),
                    "working_days": [1, 2, 3, 4, 5, 6],
                },
            )

            result = generate_slots_for_doctor(profile, today, date_to)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Doctor {name} ({specialization}) ready — Generated {result.created} slots."
                )
            )

        # 4. Patients
        patients_data = [
            ("patient.raj@healthflow.local", "Raj Kumar", "+919876543210"),
            ("patient.priya@healthflow.local", "Priya Sharma", "+919876543211"),
        ]

        for email, name, phone in patients_data:
            patient, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "name": name,
                    "phone": phone,
                    "role": UserRole.PATIENT,
                    "hospital": None,
                    "must_reset_password": False,
                    "created_by": admin,
                },
            )
            patient.set_password("PatientPass123!")
            patient.must_reset_password = False
            patient.role = UserRole.PATIENT
            patient.hospital = None
            patient.save()
            self.stdout.write(self.style.SUCCESS(f"Patient ready: {email} (Pass: PatientPass123!)"))

        # 5. Medicine Catalog
        sample_medicines = [
            ("Paracetamol", "Acetaminophen", "500mg"),
            ("Amoxicillin", "Amoxicillin Trihydrate", "500mg"),
            ("Azithromycin", "Azithromycin", "500mg"),
            ("Metformin", "Metformin Hydrochloride", "500mg"),
            ("Atorvastatin", "Atorvastatin Calcium", "10mg"),
            ("Pantoprazole", "Pantoprazole Sodium", "40mg"),
            ("Cetirizine", "Cetirizine Dihydrochloride", "10mg"),
            ("Ibuprofen", "Ibuprofen", "400mg"),
            ("Telmisartan", "Telmisartan", "40mg"),
            ("Omeprazole", "Omeprazole", "20mg"),
            ("Montelukast", "Montelukast Sodium", "10mg"),
            ("Amlodipine", "Amlodipine Besylate", "5mg"),
            ("Ciprofloxacin", "Ciprofloxacin Hydrochloride", "500mg"),
            ("Losartan", "Losartan Potassium", "50mg"),
            ("Levothyroxine", "Levothyroxine Sodium", "50mcg"),
        ]

        added_meds = 0
        for name, generic, dosage in sample_medicines:
            _, created = MedicineCatalog.objects.get_or_create(
                hospital=hospital,
                name=name,
                defaults={
                    "generic_name": generic,
                    "default_dosage": dosage,
                    "status": MedicineStatus.ACTIVE,
                    "created_by": admin,
                },
            )
            if created:
                added_meds += 1

        self.stdout.write(self.style.SUCCESS(f"Seeded {added_meds} medicines in catalog."))
        self.stdout.write(self.style.SUCCESS("All demo data seeded successfully!"))
