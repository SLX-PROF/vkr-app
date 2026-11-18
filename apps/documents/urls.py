from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("upload/", views.document_upload, name="upload"),
    path("review/<uuid:pk>/", views.document_review, name="review"),
    path("verify/", views.document_verify, name="verify"),
    path("<int:pk>/file/", views.document_file, name="file"),
    path("<int:pk>/signature/", views.document_signature, name="signature"),
    path("<int:pk>/", views.document_result, name="result"),
]
