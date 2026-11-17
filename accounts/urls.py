from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    UserViewSet,
    CurrentUserView,
    StaffDirectoryView,
    ChangePasswordView,
)

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')

urlpatterns = [
    path('users/me/', CurrentUserView.as_view(), name='current-user'),
    path(
        'users/staff-directory/',
        StaffDirectoryView.as_view(),
        name='staff-directory'
    ),
    path(
        'auth/change-password/',
        ChangePasswordView.as_view(),
        name='change-password'
    ),
    path('', include(router.urls)),
]
