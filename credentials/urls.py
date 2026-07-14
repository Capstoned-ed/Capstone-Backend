from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CredentialTypeViewSet,
    CredentialRequestViewSet,
    RequirementDocumentViewSet,
    StudentClearanceViewSet
)

router = DefaultRouter()
router.register(r'credential-types', CredentialTypeViewSet, basename='credentialtype')
router.register(r'requests', CredentialRequestViewSet, basename='credentialrequest')
router.register(
    r'documents', RequirementDocumentViewSet, basename='requirementdocument'
)
router.register(
    r'clearances', StudentClearanceViewSet, basename='studentclearance'
)

urlpatterns = [
    path('', include(router.urls)),
]
