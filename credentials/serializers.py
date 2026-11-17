from django.db import models
from rest_framework import serializers
from django.urls import reverse
from accounts.models import Role
from .models import (
    CredentialType,
    CredentialRequest,
    RequirementDocument,
    StudentClearance,
    Payment,
    PaymentStatus,
    RequestStatus,
    ClearanceStatus,
    RegistrarSettings
)


class CredentialTypeSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a CredentialType.
    """
    class Meta:
        model = CredentialType
        fields = [
            'id', 'code', 'doc_code', 'name', 'description',
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
            'code', 'doc_code', 'name', 'description',
            'price', 'processing_days', 'is_active'
        ]
        extra_kwargs = {
            'doc_code': {'required': False}
        }


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


class CredentialTypeRelatedField(serializers.PrimaryKeyRelatedField):
    """
    Flexible related field that accepts:
    - Primary Key integer / numeric string ID (e.g. 1, '1')
    - CredentialType code (e.g. 'TOR', 'HD', 'COE')
    - CredentialType name (e.g. 'Transcript of Records (TOR)')
    """
    def to_internal_value(self, data):
        if isinstance(data, CredentialType):
            return data

        if isinstance(data, str) and not data.isdigit():
            clean = data.strip()
            ctype = CredentialType.objects.filter(
                models.Q(code__iexact=clean) | models.Q(name__iexact=clean)
            ).first()
            if not ctype:
                ctype = CredentialType.objects.filter(
                    models.Q(name__icontains=clean) | models.Q(code__icontains=clean)
                ).first()
            if ctype:
                return ctype
        return super().to_internal_value(data)


class CredentialRequestSerializer(serializers.ModelSerializer):
    """
    Representation of a CredentialRequest.
    """
    credential_type = CredentialTypeRelatedField(
        queryset=CredentialType.objects.all()
    )
    documents = NestedRequirementDocumentSerializer(many=True, read_only=True)
    payments = NestedPaymentSerializer(many=True, read_only=True)
    custom_doc_code = serializers.CharField(
        max_length=20, required=False, write_only=True
    )
    student_name = serializers.SerializerMethodField()
    student_id = serializers.SerializerMethodField()
    student_email = serializers.SerializerMethodField()
    credential_name = serializers.SerializerMethodField()
    credential_code = serializers.SerializerMethodField()
    assigned_staff = serializers.SerializerMethodField()
    assigned_to = serializers.SerializerMethodField()
    in_process_queue = serializers.BooleanField(read_only=True)
    clearance_id = serializers.SerializerMethodField()
    clearance_status = serializers.SerializerMethodField()
    clearance_preview = serializers.SerializerMethodField()
    clearance_file_name = serializers.SerializerMethodField()
    clearance_is_pdf = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    approved_by = serializers.PrimaryKeyRelatedField(read_only=True)
    approved_at = serializers.DateTimeField(read_only=True)
    is_approved = serializers.BooleanField(read_only=True)
    is_auto_approved = serializers.BooleanField(read_only=True)

    class Meta:
        model = CredentialRequest
        fields = [
            'id', 'user', 'course', 'credential_type', 'status',
            'tracking_number', 'remarks', 'created_at', 'updated_at',
            'documents', 'payments', 'custom_doc_code',
            'student_name', 'student_id', 'student_email',
            'credential_name', 'credential_code', 'assigned_staff',
            'assigned_to', 'in_process_queue',
            'clearance_id', 'clearance_status', 'clearance_preview',
            'clearance_file_name', 'clearance_is_pdf',
            'approved_by', 'approved_by_name', 'approved_at',
            'is_approved', 'is_auto_approved'
        ]
        read_only_fields = [
            'user', 'status', 'tracking_number', 'created_at', 'updated_at',
            'documents', 'payments', 'student_name', 'student_id',
            'student_email', 'credential_name', 'credential_code',
            'assigned_staff', 'assigned_to', 'in_process_queue',
            'clearance_id', 'clearance_status', 'clearance_preview',
            'clearance_file_name', 'clearance_is_pdf',
            'approved_by', 'approved_by_name', 'approved_at',
            'is_approved', 'is_auto_approved'
        ]

    def get_student_name(self, obj):
        user = obj.get('user') if isinstance(obj, dict) else getattr(obj, 'user', None)
        if not user:
            return 'Student'
        first = getattr(user, 'first_name', '')
        last = getattr(user, 'last_name', '')
        name = f"{first} {last}".strip()
        return name or getattr(user, 'username', '') or 'Student'

    def get_student_id(self, obj):
        user = obj.get('user') if isinstance(obj, dict) else getattr(obj, 'user', None)
        if not user:
            return ''
        return getattr(user, 'username', '') or ''

    def get_student_email(self, obj):
        user = obj.get('user') if isinstance(obj, dict) else getattr(obj, 'user', None)
        if not user:
            return ''
        return getattr(user, 'email', '') or ''

    def get_credential_name(self, obj):
        ct = (
            obj.get('credential_type')
            if isinstance(obj, dict)
            else getattr(obj, 'credential_type', None)
        )
        if ct:
            return getattr(ct, 'name', '')
        return ''

    def get_credential_code(self, obj):
        ct = (
            obj.get('credential_type')
            if isinstance(obj, dict)
            else getattr(obj, 'credential_type', None)
        )
        if ct:
            return getattr(ct, 'code', '')
        return ''

    def get_assigned_staff(self, obj):
        staff = (
            obj.get('assigned_staff')
            if isinstance(obj, dict)
            else getattr(obj, 'assigned_staff', None)
        )
        if staff:
            if hasattr(staff, 'username'):
                return staff.username
            if isinstance(staff, str):
                return staff
        remarks = (
            obj.get('remarks')
            if isinstance(obj, dict)
            else getattr(obj, 'remarks', '')
        )
        remarks = remarks or ''
        import re
        match = re.search(
            r'\[Assigned(?:\s+to)?:\s*([^\]]+)\]', remarks, re.IGNORECASE
        )
        if match:
            return match.group(1).strip()
        match2 = re.search(
            r'Assigned(?:\s+to)?:\s*([^|\n\r;]+)', remarks, re.IGNORECASE
        )
        if match2:
            return match2.group(1).strip()
        return ''

    def get_assigned_to(self, obj):
        staff = (
            obj.get('assigned_staff')
            if isinstance(obj, dict)
            else getattr(obj, 'assigned_staff', None)
        )
        if staff and hasattr(staff, 'id'):
            return staff.id
        return None

    def _get_clearance(self, obj):
        user = obj.get('user') if isinstance(obj, dict) else getattr(obj, 'user', None)
        if not user:
            return None
        if hasattr(user, 'clearance'):
            try:
                return user.clearance
            except Exception:
                pass
        if isinstance(user, int):
            return StudentClearance.objects.filter(user_id=user).first()
        return StudentClearance.objects.filter(user=user).first()

    def get_clearance_id(self, obj):
        clearance = self._get_clearance(obj)
        return str(clearance.id) if clearance else None

    def get_clearance_status(self, obj):
        clearance = self._get_clearance(obj)
        return clearance.status if clearance else 'NOT_ATTACHED'

    def get_clearance_preview(self, obj):
        clearance = self._get_clearance(obj)
        if not clearance or not clearance.file:
            return None
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(
                reverse('studentclearance-download', kwargs={'pk': clearance.pk})
            )
        return None

    def get_clearance_file_name(self, obj):
        clearance = self._get_clearance(obj)
        if not clearance or not clearance.file or not clearance.file.name:
            return None
        from pathlib import Path
        return Path(clearance.file.name).name

    def get_clearance_is_pdf(self, obj):
        clearance = self._get_clearance(obj)
        if not clearance or not clearance.file or not clearance.file.name:
            return False
        return clearance.file.name.lower().endswith('.pdf')

    def get_approved_by_name(self, obj):
        name = (
            obj.get('approved_by_name')
            if isinstance(obj, dict)
            else getattr(obj, 'approved_by_name', '')
        )
        if name:
            return name
        appr_by = (
            obj.get('approved_by')
            if isinstance(obj, dict)
            else getattr(obj, 'approved_by', None)
        )
        if appr_by:
            first = getattr(appr_by, 'first_name', '')
            last = getattr(appr_by, 'last_name', '')
            full = f"{first} {last}".strip()
            return full or getattr(appr_by, 'username', '')
        is_appr = (
            obj.get('is_approved')
            if isinstance(obj, dict)
            else getattr(obj, 'is_approved', False)
        )
        if is_appr:
            signatory_name, _ = RegistrarSettings.get_active_signatory()
            return signatory_name
        return ''

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

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        request = self.context.get('request')
        file_obj = getattr(instance, 'file', None)
        if request and file_obj and file_obj.name:
            ret['file'] = request.build_absolute_uri(
                reverse('requirementdocument-download', kwargs={'pk': instance.pk})
            )
        return ret

    def validate_request(self, value):
        request_obj = self.context.get('request')
        if request_obj and hasattr(request_obj, 'user'):
            user = request_obj.user
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
    status = serializers.CharField(max_length=50)
    remarks = serializers.CharField(
        required=False, allow_blank=True, default=''
    )

    class Meta:
        model = StudentClearance
        fields = ['status', 'remarks']

    def validate_status(self, value):
        val = str(value).strip().upper()
        if val in ['VERIFIED', 'APPROVED', ClearanceStatus.APPROVED]:
            return ClearanceStatus.APPROVED
        if val in ['REJECTED', 'NOT_VERIFIED', ClearanceStatus.REJECTED]:
            return ClearanceStatus.REJECTED
        if val in ['PENDING', 'RESET', ClearanceStatus.PENDING]:
            return ClearanceStatus.PENDING
        raise serializers.ValidationError(
            f"Invalid clearance status '{value}'. "
            "Allowed values are APPROVED, REJECTED, or PENDING."
        )

    def validate(self, attrs):
        status_val = attrs.get('status')
        remarks_val = attrs.get('remarks', '')
        remarks_clean = str(remarks_val).strip() if remarks_val is not None else ''
        if status_val == ClearanceStatus.REJECTED and not remarks_clean:
            raise serializers.ValidationError(
                {'remarks': "Remarks are required when rejecting a clearance."}
            )
        return attrs


class PaymentSerializer(serializers.ModelSerializer):
    """
    Representation of a Payment.
    """
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

    def to_internal_value(self, data):
        if hasattr(data, '_mutable'):
            data = data.copy()
        elif isinstance(data, dict):
            data = data.copy()

        amount_val = data.get('amount') if isinstance(data, dict) else None
        if amount_val is not None:
            if isinstance(amount_val, str):
                import re
                cleaned = re.sub(r'[^\d.]', '', amount_val)
                data['amount'] = cleaned if cleaned else '0.00'

        return super().to_internal_value(data)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        request = self.context.get('request')
        receipt_image = getattr(instance, 'receipt_image', None)
        if request and receipt_image and receipt_image.name:
            ret['receipt_image'] = request.build_absolute_uri(
                reverse('payment-download', kwargs={'pk': instance.pk})
            )
        return ret

    def validate_request(self, value):
        request_obj = self.context.get('request')
        if request_obj and hasattr(request_obj, 'user'):
            user = request_obj.user
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

        receipt_ref = data.get('receipt_reference_number')
        if receipt_ref and str(receipt_ref).strip():
            ref_clean = str(receipt_ref).strip()
            existing_payment = Payment.objects.filter(
                receipt_reference_number__iexact=ref_clean
            ).exclude(status=PaymentStatus.REJECTED)
            if self.instance:
                existing_payment = existing_payment.exclude(pk=self.instance.pk)
            if existing_payment.exists():
                raise serializers.ValidationError(
                    {
                        'receipt_reference_number': (
                            f"Receipt / O.R. reference number '{ref_clean}' has "
                            "already been used for another payment."
                        )
                    }
                )

        return data


class RegistrarSettingsSerializer(serializers.ModelSerializer):
    active_registrar_name = serializers.SerializerMethodField()

    class Meta:
        model = RegistrarSettings
        fields = [
            'auto_approve_requests',
            'default_signatory_name',
            'default_signatory_title',
            'active_registrar_name',
            'updated_at'
        ]
        read_only_fields = ['active_registrar_name', 'updated_at']

    def get_active_registrar_name(self, obj):
        name, _ = RegistrarSettings.get_active_signatory()
        return name
