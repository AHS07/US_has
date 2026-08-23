"""
scheduling/urls.py

Routes included under the root urlconf at path "".

Doctor portal:
  GET  /doctor/slots                               DoctorDayView
"""
from django.urls import path

from apps.scheduling.views import DoctorDayView

app_name = "scheduling"

urlpatterns = [
    # Doctor portal — day view
    path("doctor/slots", DoctorDayView.as_view(), name="doctor-day-view"),
]
