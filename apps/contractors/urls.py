from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("check/", views.check_contractor, name="check"),
    path("contractors/<int:pk>/", views.contractor_card, name="contractor_card"),
    path("contractors/<int:pk>/request/", views.counterparty_request, name="counterparty_request"),
]
