from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'is_staff', 'is_active')
    list_filter = ('role', 'is_staff', 'is_active', 'force_password_change')
    fieldsets = UserAdmin.fieldsets + (
        ('Custom Role & Security', {'fields': ('role', 'force_password_change')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Custom Role & Security', {'fields': ('role', 'force_password_change')}),
    )
