import sys
from django.db import migrations


def seed_credential_types(apps, schema_editor):
    if 'pytest' in sys.modules or any('test' in arg for arg in sys.argv):
        return

    CredentialType = apps.get_model('credentials', 'CredentialType')

    credential_types = [
        {
            'id': 1,
            'code': 'TOR',
            'doc_code': '1',
            'name': 'Transcript of Records (TOR)',
            'description': 'Official record of courses taken and grades earned.',
            'price': '125.00',
            'processing_days': 7,
            'is_active': True,
        },
        {
            'id': 2,
            'code': 'HD',
            'doc_code': '2',
            'name': 'Honorable Dismissal',
            'description': 'Honorable dismissal and transfer credentials.',
            'price': '100.00',
            'processing_days': 5,
            'is_active': True,
        },
        {
            'id': 3,
            'code': 'EVAL',
            'doc_code': '5',
            'name': 'Evaluation',
            'description': 'Curriculum evaluation of academic credits and standing.',
            'price': '50.00',
            'processing_days': 3,
            'is_active': True,
        },
        {
            'id': 4,
            'code': 'CAR',
            'doc_code': '4F',
            'name': 'Certification - CAR',
            'description': 'Cumulative Academic Record (CAR) academic history.',
            'price': '80.00',
            'processing_days': 5,
            'is_active': True,
        },
        {
            'id': 5,
            'code': 'COE',
            'doc_code': '4A',
            'name': 'Certification - Officially enrolled',
            'description': 'Certificate verifying active enrollment and academic load.',
            'price': '80.00',
            'processing_days': 3,
            'is_active': True,
        },
        {
            'code': 'GPA',
            'doc_code': '4B',
            'name': 'Certification - GPA',
            'description': 'Official certification of overall Grade Point Average.',
            'price': '80.00',
            'processing_days': 3,
            'is_active': True,
        },
        {
            'code': 'UNITS',
            'doc_code': '4D',
            'name': 'Certification - Earned Units',
            'description': 'Certification of academic units completed toward degree.',
            'price': '80.00',
            'processing_days': 3,
            'is_active': True,
        },
        {
            'code': 'GRADES',
            'doc_code': '4G',
            'name': 'Certification - Subjects w/ grades',
            'description': 'Certification of enrolled courses and grades earned.',
            'price': '80.00',
            'processing_days': 3,
            'is_active': True,
        },
        {
            'code': 'CERT',
            'doc_code': '4',
            'name': 'Certification',
            'description': 'University certification for academic or professional use.',
            'price': '80.00',
            'processing_days': 3,
            'is_active': True,
        },
        {
            'code': 'AUTH',
            'doc_code': '4',
            'name': 'Authentication',
            'description': 'Official verification of university records.',
            'price': '5.00',
            'processing_days': 2,
            'is_active': True,
        },
        {
            'code': 'ENDORSE',
            'doc_code': '4',
            'name': 'Certification - Endorsement',
            'description': 'Official university letter of endorsement.',
            'price': '80.00',
            'processing_days': 3,
            'is_active': True,
        },
    ]

    for item in credential_types:
        code = item['code']
        explicit_id = item.get('id')
        defaults = {
            'doc_code': item['doc_code'],
            'name': item['name'],
            'description': item['description'],
            'price': item['price'],
            'processing_days': item['processing_days'],
            'is_active': item['is_active'],
        }

        # Check if record with this code already exists
        existing = CredentialType.objects.filter(code=code).first()
        if existing:
            for k, v in defaults.items():
                setattr(existing, k, v)
            existing.save()
        else:
            # If explicit id is available and unassigned, use it
            if explicit_id and not CredentialType.objects.filter(
                pk=explicit_id
            ).exists():
                defaults['id'] = explicit_id
            defaults['code'] = code
            CredentialType.objects.create(**defaults)


def unseed_credential_types(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        (
            'credentials',
            '0009_credentialrequest_course_credentialtype_doc_code_and_more',
        ),
    ]

    operations = [
        migrations.RunPython(seed_credential_types, unseed_credential_types),
    ]
