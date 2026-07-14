from rest_framework import serializers
from .models import (
    CredentialType,
    CredentialRequest,
    RequirementDocument,
    StudentClearance
)


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


class RequirementDocumentSerializer(serializers.ModelSerializer):
    """
    Representation of a RequirementDocument.
    """
    class Meta:
        model = RequirementDocument
        fields = ['id', 'request', 'document_type', 'file', 'uploaded_at']
        read_only_fields = ['id', 'uploaded_at']

    def validate_request(self, value):
        user = self.context['request'].user
        from accounts.models import Role
        if user.role == Role.STUDENT and value.user != user:
            raise serializers.ValidationError(
                "You can only upload documents to your own credential requests."
            )
        return value


class StudentClearanceSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a StudentClearance.
    """
    class Meta:
        model = StudentClearance
        fields = [
            'id', 'user', 'status', 'file', 'remarks',
            'reviewed_by', 'reviewed_at', 'uploaded_at', 'updated_at'
        ]
        read_only_fields = fields


class StudentClearanceSubmitSerializer(serializers.ModelSerializer):
    """
    Validation layer for a student submitting an e-Clearance.
    """
    class Meta:
        model = StudentClearance
        fields = ['file']


class StudentClearanceReviewSerializer(serializers.ModelSerializer):
    """
    Validation layer for staff reviewing a student clearance.
    """
    class Meta:
        model = StudentClearance
        fields = ['status', 'remarks']
