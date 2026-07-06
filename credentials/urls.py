from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CredentialTypeViewSet, CredentialRequestViewSet

router = DefaultRouter()
router.register(r'credential-types', CredentialTypeViewSet, basename='credentialtype')
router.register(r'requests', CredentialRequestViewSet, basename='credentialrequest')

urlpatterns = [
    path('', include(router.urls)),
]
