from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CredentialTypeViewSet

router = DefaultRouter()
router.register(r'credential-types', CredentialTypeViewSet, basename='credentialtype')

urlpatterns = [
    path('', include(router.urls)),
]
