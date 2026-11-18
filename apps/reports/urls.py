from django.urls import path

from .views import contractor_report

app_name = "reports"
urlpatterns = [path("checks/<int:pk>/pdf/", contractor_report, name="contractor_pdf")]
