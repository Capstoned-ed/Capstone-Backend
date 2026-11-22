from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    default_error_messages = {
        'no_active_account': 'Invalid credentials.'
    }

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
        token['first_name'] = user.first_name
        token['middle_name'] = getattr(user, 'middle_name', '')
        token['last_name'] = user.last_name
        token['name_extension'] = getattr(user, 'name_extension', '')
        name_parts = [user.first_name, getattr(user, 'middle_name', ''), user.last_name]
        full_name = " ".join(p for p in name_parts if p).strip()
        if getattr(user, 'name_extension', ''):
            full_name = f"{full_name} {user.name_extension}".strip()
        token['full_name'] = full_name or user.username
        token['force_password_change'] = user.force_password_change

        return token


User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a User.
    Hides password entirely.
    """
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'role',
            'first_name', 'middle_name', 'last_name', 'name_extension', 'full_name',
            'course_name', 'course_code',
            'birth_date', 'contact_number', 'year_level',
            'is_active', 'force_password_change',
            'date_joined', 'last_login'
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        parts = [getattr(obj, 'first_name', ''), getattr(obj, 'middle_name', ''), getattr(obj, 'last_name', '')]
        name = " ".join(p for p in parts if p).strip()
        ext = getattr(obj, 'name_extension', '')
        if ext:
            name = f"{name} {ext}".strip()
        return name or getattr(obj, 'username', '')


class UserCreateSerializer(serializers.ModelSerializer):
    """
    Validation layer for creating a new user.
    Note: Password hashing is delegated to AccountService.create_user (which calls
    create_user()), so no custom create() override is needed here.
    """
    first_name = serializers.CharField(
        max_length=150, required=False, allow_blank=True, default=''
    )
    middle_name = serializers.CharField(
        max_length=150, required=False, allow_blank=True, default=''
    )
    last_name = serializers.CharField(
        max_length=150, required=False, allow_blank=True, default=''
    )
    name_extension = serializers.CharField(
        max_length=30, required=False, allow_blank=True, default=''
    )

    class Meta:
        model = User
        fields = [
            'username', 'email', 'password', 'role',
            'first_name', 'middle_name', 'last_name', 'name_extension',
            'course_name', 'course_code',
            'birth_date', 'contact_number', 'year_level',
        ]
        extra_kwargs = {
            'password': {'write_only': True, 'required': False},
            'first_name': {'required': False},
            'middle_name': {'required': False},
            'last_name': {'required': False},
            'name_extension': {'required': False},
            'course_name': {'required': False},
            'course_code': {'required': False},
            'birth_date': {'required': False, 'allow_null': True},
            'contact_number': {'required': False},
            'year_level': {'required': False},
        }

    def validate_role(self, value):
        from .models import Role
        val = str(value).strip().lower()
        if val not in Role.values:
            raise serializers.ValidationError(
                f"Invalid role '{value}'. Choices: {', '.join(Role.values)}"
            )
        return val

    def validate(self, attrs):
        if not attrs.get('password'):
            attrs['password'] = attrs.get('username')
        return attrs


class UserUpdateSerializer(serializers.ModelSerializer):
    """
    Validation layer for updating an existing user.
    """
    first_name = serializers.CharField(
        max_length=150, required=False, allow_blank=True, default=''
    )
    middle_name = serializers.CharField(
        max_length=150, required=False, allow_blank=True, default=''
    )
    last_name = serializers.CharField(
        max_length=150, required=False, allow_blank=True, default=''
    )
    name_extension = serializers.CharField(
        max_length=30, required=False, allow_blank=True, default=''
    )

    class Meta:
        model = User
        fields = [
            'email', 'role', 'first_name', 'middle_name', 'last_name', 'name_extension',
            'course_name', 'course_code',
            'birth_date', 'contact_number', 'year_level',
            'is_active',
        ]
        extra_kwargs = {
            'first_name': {'required': False},
            'middle_name': {'required': False},
            'last_name': {'required': False},
            'name_extension': {'required': False},
            'course_name': {'required': False},
            'course_code': {'required': False},
            'birth_date': {'required': False, 'allow_null': True},
            'contact_number': {'required': False},
            'year_level': {'required': False},
        }


class SelfProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Allows an authenticated user to update their own contact & profile info.
    """
    class Meta:
        model = User
        fields = ['email', 'birth_date', 'contact_number', 'year_level', 'middle_name', 'name_extension']
        extra_kwargs = {
            'email': {'required': False},
            'birth_date': {'required': False, 'allow_null': True},
            'contact_number': {'required': False},
            'year_level': {'required': False},
            'middle_name': {'required': False},
            'name_extension': {'required': False},
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


class ChangePasswordSerializer(serializers.Serializer):
    """
    Payload for authenticated user to update their account password.
    """
    current_password = serializers.CharField(
        required=True, write_only=True
    )
    new_password = serializers.CharField(
        min_length=6,
        write_only=True,
        required=True,
        help_text="New password (minimum 6 characters)."
    )
    confirm_password = serializers.CharField(
        min_length=6,
        write_only=True,
        required=True,
        help_text="Confirm new password."
    )

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError(
                {'confirm_password': 'New password and confirmation do not match.'}
            )
        if attrs['current_password'] == attrs['new_password']:
            raise serializers.ValidationError(
                {
                    'new_password': (
                        'New password must be different from current password.'
                    )
                }
            )
        return attrs
