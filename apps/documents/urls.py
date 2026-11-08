from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("verify/", views.document_verify, name="verify"),
    path("<int:pk>/", views.document_result, name="result"),
]
