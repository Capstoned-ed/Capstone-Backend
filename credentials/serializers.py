from rest_framework import serializers
from .models import CredentialType, CredentialRequest


class CredentialTypeSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a CredentialType.
    """
    class Meta:
        model = CredentialType
        fields = [
            'id', 'code', 'name', 'description',
            'price', 'processing_days', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = fields


class CredentialTypeCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Validation layer for creating or updating a CredentialType.
    """
    class Meta:
        model = CredentialType
        fields = [
            'code', 'name', 'description',
            'price', 'processing_days', 'is_active'
        ]


class CredentialRequestSerializer(serializers.ModelSerializer):
    """
    Representation of a CredentialRequest.
    """
    class Meta:
        model = CredentialRequest
        fields = [
            'id', 'user', 'credential_type', 'status',
            'tracking_number', 'remarks', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'user', 'status', 'tracking_number', 'created_at', 'updated_at'
        ]

    def validate_credential_type(self, value):
        if not value.is_active:
            raise serializers.ValidationError(
                "Cannot request an inactive credential type."
            )
        return value
