from rest_framework import serializers
from django.urls import reverse
from accounts.models import Role
from .models import (
    CredentialType,
    CredentialRequest,
    RequirementDocument,
    StudentClearance,
    Payment,
    RequestStatus
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


class NestedPaymentSerializer(serializers.ModelSerializer):
    """
    Read-only, minimal representation of a Payment
    for embedding inside a CredentialRequest payload.
    """
    receipt_image = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            'id', 'amount', 'receipt_reference_number', 'receipt_image',
            'status', 'remarks', 'verified_at', 'uploaded_at'
        ]
        read_only_fields = fields

    def get_receipt_image(self, obj):
        request = self.context.get('request')
        if request and obj.receipt_image:
            return request.build_absolute_uri(
                reverse('payment-download', kwargs={'pk': obj.pk})
            )
        return None


class NestedRequirementDocumentSerializer(serializers.ModelSerializer):
    """
    Read-only, minimal representation of a RequirementDocument
    for embedding inside a CredentialRequest payload.
    """
    file = serializers.SerializerMethodField()

    class Meta:
        model = RequirementDocument
        fields = ['id', 'document_type', 'file', 'uploaded_at']
        read_only_fields = fields

    def get_file(self, obj):
        request = self.context.get('request')
        if request and obj.file:
            return request.build_absolute_uri(
                reverse('requirementdocument-download', kwargs={'pk': obj.pk})
            )
        return None


class CredentialRequestSerializer(serializers.ModelSerializer):
    """
    Representation of a CredentialRequest.
    """
    documents = NestedRequirementDocumentSerializer(many=True, read_only=True)
    payments = NestedPaymentSerializer(many=True, read_only=True)

    class Meta:
        model = CredentialRequest
        fields = [
            'id', 'user', 'credential_type', 'status',
            'tracking_number', 'remarks', 'created_at', 'updated_at',
            'documents', 'payments'
        ]
        read_only_fields = [
            'user', 'status', 'tracking_number', 'created_at', 'updated_at',
            'documents', 'payments'
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
    file = serializers.SerializerMethodField()

    class Meta:
        model = RequirementDocument
        fields = ['id', 'request', 'document_type', 'file', 'uploaded_at']
        read_only_fields = ['id', 'uploaded_at']

    def get_file(self, obj):
        request = self.context.get('request')
        if request and obj.file:
            return request.build_absolute_uri(
                reverse('requirementdocument-download', kwargs={'pk': obj.pk})
            )
        return None

    def validate_request(self, value):
        user = self.context['request'].user
        if user.role == Role.STUDENT and value.user != user:
            raise serializers.ValidationError(
                "You can only upload documents to your own credential requests."
            )

        UPLOADABLE_STATUSES = [
            RequestStatus.PENDING,
            RequestStatus.REQUIREMENTS_VERIFICATION,
            RequestStatus.REQUIREMENTS_REJECTED,
        ]
        if value.status not in UPLOADABLE_STATUSES:
            raise serializers.ValidationError(
                "Documents cannot be uploaded to a request in its current status."
            )
        return value


class StudentClearanceSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a StudentClearance.
    """
    file = serializers.SerializerMethodField()

    class Meta:
        model = StudentClearance
        fields = [
            'id', 'user', 'status', 'file', 'remarks',
            'reviewed_by', 'reviewed_at', 'uploaded_at', 'updated_at'
        ]
        read_only_fields = fields

    def get_file(self, obj):
        request = self.context.get('request')
        if request and obj.file:
            return request.build_absolute_uri(
                reverse('studentclearance-download', kwargs={'pk': obj.pk})
            )
        return None


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


class PaymentSerializer(serializers.ModelSerializer):
    """
    Representation of a Payment.
    """
    receipt_image = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            'id', 'request', 'amount', 'receipt_reference_number',
            'receipt_image', 'status', 'remarks', 'verified_by', 'verified_at',
            'uploaded_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'status', 'remarks', 'verified_by', 'verified_at',
            'uploaded_at', 'updated_at'
        ]

    def get_receipt_image(self, obj):
        request = self.context.get('request')
        if request and obj.receipt_image:
            return request.build_absolute_uri(
                reverse('payment-download', kwargs={'pk': obj.pk})
            )
        return None

    def validate_request(self, value):
        user = self.context['request'].user
        if user.role == Role.STUDENT and value.user != user:
            raise serializers.ValidationError(
                "You can only submit payments for your own requests."
            )
        return value

    def validate(self, data):
        req = data.get('request')
        amount = data.get('amount')

        if amount is not None and amount <= 0:
            raise serializers.ValidationError(
                {'amount': 'Payment amount must be a positive value.'}
            )

        if req and amount and amount < req.credential_type.price:
            raise serializers.ValidationError(
                {
                    'amount': (
                        f'Amount {amount} is less than the required '
                        f'price of {req.credential_type.price}.'
                    )
                }
            )

        return data
