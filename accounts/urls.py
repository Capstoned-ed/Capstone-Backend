from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserViewSet, CurrentUserView, StaffDirectoryView

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')

urlpatterns = [
    path('users/me/', CurrentUserView.as_view(), name='current-user'),
    path('users/staff-directory/', StaffDirectoryView.as_view(), name='staff-directory'),
    path('', include(router.urls)),
]
