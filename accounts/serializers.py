from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # Add custom claims
        token['role'] = user.role
        token['force_password_change'] = user.force_password_change

        return token


User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a User.
    Hides password entirely.
    """
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'role',
            'is_active', 'force_password_change',
            'date_joined', 'last_login'
        ]
        read_only_fields = fields


class UserCreateSerializer(serializers.ModelSerializer):
    """
    Validation layer for creating a new user.
    """
    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'role']
        extra_kwargs = {
            'password': {'write_only': True}
        }


class UserUpdateSerializer(serializers.ModelSerializer):
    """
    Validation layer for updating an existing user.
    """
    class Meta:
        model = User
        fields = ['email', 'role', 'is_active']
