import json
import re
from decimal import Decimal, InvalidOperation
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


def _to_decimal(val, fallback=Decimal('0.00')):
    if val is None or val == '':
        return fallback
    try:
        cleaned = re.sub(r'[^\d.]', '', str(val))
        if not cleaned:
            return fallback
        return Decimal(cleaned).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, TypeError):
        return fallback


def _extract_copies_from_remarks(remarks):
    match = re.search(r'\[Copies:\s*(\d+)', str(remarks or ''), re.IGNORECASE)
    if match:
        try:
            val = int(match.group(1))
            if val >= 1:
                return val
        except (TypeError, ValueError):
            pass
    return 1


def _resolve_credential_type_record(item):
    raw_id = item.get('credential_type_id') or item.get('id')
    if raw_id is not None and str(raw_id).isdigit():
        ct = CredentialType.objects.filter(pk=int(raw_id)).first()
        if ct:
            return ct
    raw_code = str(item.get('code') or '').strip()
    if raw_code:
        ct = CredentialType.objects.filter(code__iexact=raw_code).first()
        if ct:
            return ct
    raw_name = str(item.get('name') or item.get('title') or '').strip()
    if raw_name:
        ct = CredentialType.objects.filter(name__iexact=raw_name).first()
        if ct:
            return ct
        ct = CredentialType.objects.filter(name__icontains=raw_name).first()
        if ct:
            return ct
    return None


def extract_request_document_items(obj):
    """
    Extract the full structured list of requested documents with copies and
    unit_price from a CredentialRequest (or dict), supporting multi-document
    requests without requiring destructive DB migrations.
    """
    remarks = (
        obj.get('remarks')
        if isinstance(obj, dict)
        else getattr(obj, 'remarks', '')
    ) or ''
    primary_ct = (
        obj.get('credential_type')
        if isinstance(obj, dict)
        else getattr(obj, 'credential_type', None)
    )
    if primary_ct is not None and not isinstance(primary_ct, CredentialType):
        if str(primary_ct).isdigit():
            primary_ct = CredentialType.objects.filter(pk=int(primary_ct)).first()
        else:
            primary_ct = None

    # 1. Structured [Items:[...]] JSON payload persisted in remarks
    items_match = re.search(
        r'\[Items:(\[[\s\S]*?\])\]', str(remarks), re.IGNORECASE
    )
    if items_match:
        try:
            parsed = json.loads(items_match.group(1))
            if isinstance(parsed, list) and len(parsed) > 0:
                normalized = []
                for it in parsed:
                    if not isinstance(it, dict):
                        continue
                    copies = max(1, int(it.get('copies') or 1))
                    unit_price = _to_decimal(
                        it.get('unit_price'),
                        fallback=_to_decimal(
                            primary_ct.price if primary_ct else None
                        ),
                    )
                    subtotal = (unit_price * copies).quantize(Decimal('0.01'))
                    normalized.append({
                        'credential_type_id': it.get('credential_type_id')
                        or it.get('id'),
                        'code': str(it.get('code') or ''),
                        'name': str(
                            it.get('name') or it.get('title') or 'Document'
                        ),
                        'copies': copies,
                        'unit_price': f"{unit_price:.2f}",
                        'subtotal': f"{subtotal:.2f}",
                    })
                if normalized:
                    return normalized
        except (ValueError, TypeError):
            pass

    # 2. Fallback: parse multi-doc breakdown in [Copies: N | DocA: 2, DocB: 1]
    multi_match = re.search(
        r'\[Copies:\s*\d+\s*\|\s*([^\]]+)\]', str(remarks), re.IGNORECASE
    )
    if multi_match:
        parts = [p.strip() for p in multi_match.group(1).split(',') if p.strip()]
        normalized = []
        for part in parts:
            m = re.match(r'^(.+?):\s*(\d+)$', part)
            if not m:
                continue
            doc_name = m.group(1).strip()
            copies = max(1, int(m.group(2)))
            ct = _resolve_credential_type_record({'name': doc_name})
            unit_price = _to_decimal(
                ct.price if ct else (primary_ct.price if primary_ct else None)
            )
            subtotal = (unit_price * copies).quantize(Decimal('0.01'))
            normalized.append({
                'credential_type_id': ct.id if ct else None,
                'code': ct.code if ct else '',
                'name': ct.name if ct else doc_name,
                'copies': copies,
                'unit_price': f"{unit_price:.2f}",
                'subtotal': f"{subtotal:.2f}",
            })
        if normalized:
            return normalized

    # 3. Single-document fallback from primary credential_type + extracted copies
    copies = _extract_copies_from_remarks(remarks)
    unit_price = _to_decimal(primary_ct.price if primary_ct else None)
    subtotal = (unit_price * copies).quantize(Decimal('0.01'))
    return [{
        'credential_type_id': primary_ct.id if primary_ct else None,
        'code': primary_ct.code if primary_ct else '',
        'name': primary_ct.name if primary_ct else 'Document Request',
        'copies': copies,
        'unit_price': f"{unit_price:.2f}",
        'subtotal': f"{subtotal:.2f}",
    }]


def extract_request_total_amount(obj):
    """
    Compute exact Decimal total_amount = sum(unit_price * copies) across all
    requested documents on a CredentialRequest.
    """
    items = extract_request_document_items(obj)
    items_sum = sum(
        (_to_decimal(it.get('unit_price')) * max(1, int(it.get('copies') or 1)))
        for it in items
    )
    items_sum = Decimal(items_sum).quantize(Decimal('0.01'))

    remarks = (
        obj.get('remarks')
        if isinstance(obj, dict)
        else getattr(obj, 'remarks', '')
    ) or ''
    total_match = re.search(
        r'\[Total:\s*([\d.]+)\]', str(remarks), re.IGNORECASE
    )
    if total_match:
        tagged_total = _to_decimal(total_match.group(1), fallback=Decimal('0.00'))
        if tagged_total > Decimal('0.00') and items_sum <= Decimal('0.00'):
            return tagged_total

    if items_sum > Decimal('0.00'):
        return items_sum

    primary_ct = (
        obj.get('credential_type')
        if isinstance(obj, dict)
        else getattr(obj, 'credential_type', None)
    )
    if isinstance(primary_ct, CredentialType) and primary_ct.price is not None:
        return _to_decimal(primary_ct.price)
    return Decimal('0.00')


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
    copies = serializers.IntegerField(
        required=False, min_value=1, max_value=99, write_only=True
    )
    document_items = serializers.ListField(
        child=serializers.DictField(), required=False, write_only=True
    )
    total_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, write_only=True
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
    or_number = serializers.SerializerMethodField()
    receipt_reference_number = serializers.SerializerMethodField()
    receipt_image = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()

    class Meta:
        model = CredentialRequest
        fields = [
            'id', 'user', 'course', 'credential_type', 'status',
            'tracking_number', 'remarks', 'created_at', 'updated_at',
            'documents', 'payments', 'custom_doc_code', 'copies',
            'document_items', 'total_amount',
            'student_name', 'student_id', 'student_email',
            'credential_name', 'credential_code', 'assigned_staff',
            'assigned_to', 'in_process_queue',
            'clearance_id', 'clearance_status', 'clearance_preview',
            'clearance_file_name', 'clearance_is_pdf',
            'approved_by', 'approved_by_name', 'approved_at',
            'is_approved', 'is_auto_approved',
            'or_number', 'receipt_reference_number', 'receipt_image',
            'payment_status'
        ]
        read_only_fields = [
            'user', 'status', 'tracking_number', 'created_at', 'updated_at',
            'documents', 'payments', 'student_name', 'student_id',
            'student_email', 'credential_name', 'credential_code',
            'assigned_staff', 'assigned_to', 'in_process_queue',
            'clearance_id', 'clearance_status', 'clearance_preview',
            'clearance_file_name', 'clearance_is_pdf',
            'approved_by', 'approved_by_name', 'approved_at',
            'is_approved', 'is_auto_approved',
            'or_number', 'receipt_reference_number', 'receipt_image',
            'payment_status'
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
            if hasattr(staff, 'first_name') and hasattr(staff, 'last_name'):
                full_name = f"{staff.first_name} {staff.last_name}".strip()
                if full_name:
                    return full_name
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
        req_id = (
            obj.get('id') if isinstance(obj, dict) else getattr(obj, 'id', None)
        )
        if req_id:
            clr = (
                StudentClearance.objects
                .filter(credential_request_id=req_id)
                .order_by('-uploaded_at')
                .first()
            )
            if clr:
                return clr
        user = (
            obj.get('user')
            if isinstance(obj, dict)
            else getattr(obj, 'user', None)
        )
        if not user:
            return None
        if hasattr(user, 'clearances'):
            try:
                clr = (
                    user.clearances
                    .filter(credential_request_id=req_id)
                    .order_by('-uploaded_at')
                    .first()
                )
                if clr:
                    return clr
            except Exception:
                pass
        if isinstance(user, int):
            return (
                StudentClearance.objects
                .filter(user_id=user, credential_request__isnull=True)
                .order_by('-uploaded_at')
                .first()
            )
        return (
            StudentClearance.objects
            .filter(user=user, credential_request__isnull=True)
            .order_by('-uploaded_at')
            .first()
        )

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

    def _get_latest_payment(self, obj):
        if isinstance(obj, dict):
            payments = obj.get('payments')
            if payments and isinstance(payments, list):
                return payments[-1]
            return None
        if hasattr(obj, 'payments'):
            return obj.payments.order_by('uploaded_at', 'id').last()
        return None

    def get_or_number(self, obj):
        payment = self._get_latest_payment(obj)
        if payment:
            return getattr(payment, 'receipt_reference_number', '') or ''
        return ''

    def get_receipt_reference_number(self, obj):
        return self.get_or_number(obj)

    def get_receipt_image(self, obj):
        payment = self._get_latest_payment(obj)
        if payment and getattr(payment, 'receipt_image', None):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(
                    reverse('payment-download', kwargs={'pk': payment.pk})
                )
        return None

    def get_payment_status(self, obj):
        status_val = (
            obj.get('status')
            if isinstance(obj, dict)
            else getattr(obj, 'status', None)
        )
        if status_val in [
            RequestStatus.PAYMENT_VERIFIED,
            RequestStatus.PROCESSING,
            RequestStatus.READY_FOR_RELEASE,
            RequestStatus.RELEASED,
        ]:
            return 'VERIFIED'
        payment = self._get_latest_payment(obj)
        if payment:
            return getattr(payment, 'status', 'PENDING')
        return 'NOT_SUBMITTED'

    def validate_credential_type(self, value):
        if not value.is_active:
            raise serializers.ValidationError(
                f"The requested credential '{value.name}' is currently unavailable."
            )
        return value

    def validate_assigned_staff(self, value):
        if value:
            if value.role != Role.STAFF or not value.is_active:
                raise serializers.ValidationError(
                    "Only active staff members can be assigned to requests."
                )
        return value

    def validate_assigned_to(self, value):
        return self.validate_assigned_staff(value)

    def validate(self, attrs):
        copies_val = attrs.pop('copies', None)
        raw_items = attrs.pop('document_items', None)
        attrs.pop('total_amount', None)
        primary_ct = attrs.get('credential_type')
        remarks = str(attrs.get('remarks') or '').strip()

        normalized_items = []
        if isinstance(raw_items, list) and len(raw_items) > 0:
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                ct = _resolve_credential_type_record(item)
                copies = max(1, int(item.get('copies') or 1))
                unit_price = (
                    _to_decimal(ct.price)
                    if ct
                    else _to_decimal(
                        item.get('unit_price'),
                        fallback=_to_decimal(
                            primary_ct.price if primary_ct else None
                        ),
                    )
                )
                name = (
                    ct.name
                    if ct
                    else str(
                        item.get('name') or item.get('title') or 'Document'
                    ).strip()
                )
                normalized_items.append({
                    'credential_type_id': ct.id
                    if ct
                    else item.get('credential_type_id'),
                    'code': ct.code if ct else str(item.get('code') or ''),
                    'name': name,
                    'copies': copies,
                    'unit_price': f"{Decimal(unit_price):.2f}",
                })

        if normalized_items:
            total_copies = sum(it['copies'] for it in normalized_items)
            computed_total = sum(
                _to_decimal(it['unit_price']) * it['copies']
                for it in normalized_items
            )
            computed_total = Decimal(computed_total).quantize(Decimal('0.01'))

            # Replace any existing [Items:...] / [Total:...] / [Copies:...] tags
            clean_rem = re.sub(
                r'\[Items:\[[\s\S]*?\]\]', '', remarks, flags=re.IGNORECASE
            )
            clean_rem = re.sub(
                r'\[Total:[^\]]*\]', '', clean_rem, flags=re.IGNORECASE
            )
            clean_rem = re.sub(
                r'\[Copies:[^\]]*\]', '', clean_rem, flags=re.IGNORECASE
            ).strip()

            if len(normalized_items) > 1:
                summary = ', '.join(
                    f"{it['name']}: {it['copies']}" for it in normalized_items
                )
                copies_tag = f"[Copies: {total_copies} | {summary}]"
            else:
                copies_tag = f"[Copies: {total_copies}]"

            items_json = json.dumps(normalized_items, separators=(',', ':'))
            items_tag = f"[Items:{items_json}]"
            total_tag = f"[Total:{computed_total:.2f}]"
            attrs['remarks'] = ' '.join(
                p for p in [clean_rem, copies_tag, total_tag, items_tag] if p
            ).strip()
        else:
            effective_copies = max(
                1,
                int(copies_val)
                if copies_val is not None
                else _extract_copies_from_remarks(remarks),
            )
            if copies_val is not None and not re.search(
                r'\[Copies:\s*\d+', remarks, re.IGNORECASE
            ):
                remarks = f"{remarks} [Copies: {effective_copies}]".strip()
            if primary_ct and not re.search(
                r'\[Total:\s*[\d.]+', remarks, re.IGNORECASE
            ):
                computed_total = (
                    _to_decimal(primary_ct.price) * effective_copies
                ).quantize(Decimal('0.01'))
                remarks = f"{remarks} [Total:{computed_total:.2f}]".strip()
            attrs['remarks'] = remarks

        return super().validate(attrs)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        items = extract_request_document_items(instance)
        total_amt = extract_request_total_amount(instance)
        total_copies = sum(int(it.get('copies') or 1) for it in items) or 1
        ret['document_items'] = items
        ret['copies'] = total_copies
        ret['total_amount'] = f"{total_amt:.2f}"
        ret['assessed_amount'] = f"{total_amt:.2f}"
        return ret


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
            'id', 'user', 'credential_request', 'status', 'file', 'remarks',
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
    credential_request = serializers.PrimaryKeyRelatedField(
        queryset=CredentialRequest.objects.all(),
        required=False,
        allow_null=True
    )

    class Meta:
        model = StudentClearance
        fields = ['file', 'credential_request']


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
    or_number = serializers.CharField(
        required=False, allow_blank=True, write_only=True
    )

    class Meta:
        model = Payment
        fields = [
            'id', 'request', 'amount', 'receipt_reference_number',
            'or_number', 'receipt_image', 'status', 'remarks', 'verified_by',
            'verified_at', 'uploaded_at', 'updated_at'
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

        if isinstance(data, dict):
            if data.get('or_number') and not data.get('receipt_reference_number'):
                data['receipt_reference_number'] = data.get('or_number')

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

        if req and amount is not None:
            required_total = extract_request_total_amount(req)
            tolerance = Decimal('0.01')
            if Decimal(amount) + tolerance < required_total:
                raise serializers.ValidationError(
                    {
                        'amount': (
                            f'Amount {Decimal(amount):.2f} is less than the '
                            f'required total price of {required_total:.2f}.'
                        )
                    }
                )

        receipt_ref = data.get('receipt_reference_number') or data.get('or_number')
        if receipt_ref and str(receipt_ref).strip():
            ref_clean = str(receipt_ref).strip()
            existing_payment = Payment.objects.filter(
                receipt_reference_number__iexact=ref_clean
            ).exclude(status=PaymentStatus.REJECTED)
            if self.instance:
                existing_payment = existing_payment.exclude(pk=self.instance.pk)
            if existing_payment.exists():
                err_msg = "This Official Receipt (O.R.) number is already in use."
                raise serializers.ValidationError(
                    {
                        'or_number': [err_msg],
                        'receipt_reference_number': [
                            f"Receipt / O.R. reference number '{ref_clean}' has "
                            "already been used for another payment."
                        ]
                    }
                )

        return data


class RegistrarSettingsSerializer(serializers.ModelSerializer):
    active_registrar_name = serializers.SerializerMethodField()
    auto_approve = serializers.BooleanField(
        source='auto_approve_requests', read_only=True
    )

    class Meta:
        model = RegistrarSettings
        fields = [
            'auto_approve_requests',
            'auto_approve',
            'default_signatory_name',
            'default_signatory_title',
            'active_registrar_name',
            'updated_at'
        ]
        read_only_fields = ['active_registrar_name', 'auto_approve', 'updated_at']

    def get_active_registrar_name(self, obj):
        request = self.context.get('request')
        actor = request.user if request and getattr(request, 'user', None) else None
        name, _ = RegistrarSettings.get_active_signatory(actor=actor)
        return name
