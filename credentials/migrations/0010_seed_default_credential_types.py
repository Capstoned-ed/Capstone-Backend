import sys
from django.db import migrations


def sync_postgres_sequence(schema_editor, table_name, pk_field='id'):
    """
    Synchronize the PostgreSQL auto-increment sequence with MAX(pk_field).
    Safely no-ops on SQLite, MySQL, and other database engines.
    """
    connection = schema_editor.connection
    if connection.vendor != 'postgresql':
        return

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_serial_sequence(%s, %s);", [table_name, pk_field]
        )
        result = cursor.fetchone()
        seq_name = result[0] if result else None

        if seq_name:
            cursor.execute(
                f"""
                SELECT setval(
                    '{seq_name}',
                    COALESCE((SELECT MAX({pk_field}) FROM {table_name}), 1),
                    (SELECT COUNT(*) > 0 FROM {table_name})
                );
                """
            )


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
            'description': (
                'Curriculum evaluation of academic credits and standing.'
            ),
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
            'description': (
                'Certificate verifying active enrollment and academic load.'
            ),
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
            'description': (
                'Certification of academic units completed toward degree.'
            ),
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
            'description': (
                'University certification for academic or professional use.'
            ),
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

        # 1. Lookup by natural unique key 'code'
        existing_by_code = CredentialType.objects.filter(code=code).first()
        if existing_by_code:
            for k, v in defaults.items():
                setattr(existing_by_code, k, v)
            existing_by_code.save()
            continue

        # 2. Check if a record exists with the desired explicit_id
        if explicit_id:
            existing_by_id = CredentialType.objects.filter(pk=explicit_id).first()
            if existing_by_id:
                existing_by_id.code = code
                for k, v in defaults.items():
                    setattr(existing_by_id, k, v)
                existing_by_id.save()
                continue

            # Neither code nor explicit_id exists; create using explicit_id
            CredentialType.objects.update_or_create(
                id=explicit_id,
                defaults={'code': code, **defaults}
            )
        else:
            # No explicit id; create or update by natural key 'code'
            CredentialType.objects.update_or_create(
                code=code,
                defaults=defaults
            )

        # Synchronize PostgreSQL sequence after every insert
        sync_postgres_sequence(schema_editor, 'credentials_credentialtype', 'id')

    # Final post-seeding sequence synchronization
    sync_postgres_sequence(schema_editor, 'credentials_credentialtype', 'id')


def unseed_credential_types(apps, schema_editor):
    """
    Reversible migration rollback.
    Deletes seeded credential types if they are not referenced by existing requests.
    """
    if 'pytest' in sys.modules or any('test' in arg for arg in sys.argv):
        return

    CredentialType = apps.get_model('credentials', 'CredentialType')
    CredentialRequest = apps.get_model('credentials', 'CredentialRequest')

    seed_codes = [
        'TOR', 'HD', 'EVAL', 'CAR', 'COE', 'GPA',
        'UNITS', 'GRADES', 'CERT', 'AUTH', 'ENDORSE'
    ]

    for code in seed_codes:
        cred_type = CredentialType.objects.filter(code=code).first()
        if cred_type:
            # Only delete if not referenced by existing user requests
            if not CredentialRequest.objects.filter(
                credential_type=cred_type
            ).exists():
                cred_type.delete()

    sync_postgres_sequence(schema_editor, 'credentials_credentialtype', 'id')


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

