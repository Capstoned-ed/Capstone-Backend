from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        # Allow authenticating with either username or registered email
        username_or_email = attrs.get(self.username_field)
        if username_or_email:
            user = (
                User.objects.filter(email__iexact=username_or_email).first() or
                User.objects.filter(username__iexact=username_or_email).first()
            )
            if user:
                attrs[self.username_field] = user.username
        return super().validate(attrs)

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # Add custom claims
        token['username'] = user.username
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
            'first_name', 'last_name',
            'course_name', 'course_code',
            'is_active', 'force_password_change',
            'date_joined', 'last_login'
        ]
        read_only_fields = fields


class UserCreateSerializer(serializers.ModelSerializer):
    """
    Validation layer for creating a new user.
    Note: Password hashing is delegated to AccountService.create_user (which calls
    create_user()), so no custom create() override is needed here.
    """
    class Meta:
        model = User
        fields = [
            'username', 'email', 'password', 'role',
            'course_name', 'course_code'
        ]
        extra_kwargs = {
            'password': {'write_only': True},
            'course_name': {'required': False},
            'course_code': {'required': False}
        }


class UserUpdateSerializer(serializers.ModelSerializer):
    """
    Validation layer for updating an existing user.
    """
    class Meta:
        model = User
        fields = [
            'email', 'role', 'first_name', 'last_name',
            'course_name', 'course_code', 'is_active'
        ]
        extra_kwargs = {
            'course_name': {'required': False},
            'course_code': {'required': False}
        }


class PasswordResetRequestSerializer(serializers.Serializer):
    """
    Request payload to trigger an OTP email.
    """
    email = serializers.CharField(
        required=True,
        help_text="Registered email address or username."
    )


class PasswordResetVerifySerializer(serializers.Serializer):
    """
    Payload to verify that an OTP code is valid.
    """
    email = serializers.CharField(required=True)
    otp = serializers.CharField(
        min_length=6,
        max_length=6,
        required=True,
        help_text="6-digit numeric OTP code."
    )


class PasswordResetConfirmSerializer(serializers.Serializer):
    """
    Payload to confirm OTP and set a new password.
    """
    email = serializers.CharField(required=True)
    otp = serializers.CharField(
        min_length=6,
        max_length=6,
        required=True,
        help_text="6-digit numeric OTP code."
    )
    new_password = serializers.CharField(
        min_length=6,
        write_only=True,
        required=True,
        help_text="New password (minimum 6 characters)."
    )
