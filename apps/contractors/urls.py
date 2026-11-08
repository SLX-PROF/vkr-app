from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("check/", views.check_contractor, name="check"),
    path("contractors/<int:pk>/", views.contractor_card, name="contractor_card"),
]
