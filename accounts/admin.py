from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User
from .forms import CustomUserCreationForm, CustomUserChangeForm


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm

    list_display = ('username', 'email', 'role', 'is_staff', 'is_active')
    list_filter = ('role', 'is_staff', 'is_active', 'force_password_change')
    fieldsets = UserAdmin.fieldsets + (
        ('Custom Role & Security', {'fields': ('role', 'force_password_change')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Custom Role & Security', {'fields': ('role', 'force_password_change')}),
    )
