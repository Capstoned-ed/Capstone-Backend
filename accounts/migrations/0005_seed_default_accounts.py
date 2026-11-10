import os
import sys
from django.contrib.auth.hashers import make_password
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


def seed_default_accounts(apps, schema_editor):
    if 'pytest' in sys.modules or any('test' in arg for arg in sys.argv):
        return

    User = apps.get_model('accounts', 'User')
    default_password = os.environ.get('SEED_PASSWORD', 'password123')
    hashed_password = make_password(default_password)

    accounts_to_seed = [
        {
            'username': 'admin',
            'email': 'admin@example.com',
            'role': 'admin',
            'is_staff': True,
            'is_superuser': True,
            'is_active': True,
            'force_password_change': False,
        },
        {
            'username': 'registrar',
            'email': 'registrar@example.com',
            'role': 'registrar',
            'is_staff': False,
            'is_superuser': False,
            'is_active': True,
            'force_password_change': False,
        },
        {
            'username': 'staff',
            'email': 'staff@example.com',
            'role': 'staff',
            'is_staff': False,
            'is_superuser': False,
            'is_active': True,
            'force_password_change': False,
        },
        {
            'username': 'student',
            'email': 'student@example.com',
            'role': 'student',
            'course_name': 'Bachelor of Science in Information Technology',
            'course_code': 'IT',
            'is_staff': False,
            'is_superuser': False,
            'is_active': True,
            'force_password_change': False,
        },
    ]

    for acc in accounts_to_seed:
        username = acc['username']
        existing = User.objects.filter(username=username).first()
        if existing:
            # Account already exists; preserve password and update roles
            existing.role = acc['role']
            existing.is_staff = acc['is_staff']
            existing.is_superuser = acc['is_superuser']
            existing.is_active = True
            existing.save()
        else:
            User.objects.create(
                username=username,
                password=hashed_password,
                email=acc['email'],
                role=acc['role'],
                is_staff=acc['is_staff'],
                is_superuser=acc['is_superuser'],
                is_active=True,
                force_password_change=False,
                course_name=acc.get('course_name', ''),
                course_code=acc.get('course_code', ''),
            )

    sync_postgres_sequence(schema_editor, 'accounts_user', 'id')


def unseed_default_accounts(apps, schema_editor):
    if 'pytest' in sys.modules or any('test' in arg for arg in sys.argv):
        return

    User = apps.get_model('accounts', 'User')
    try:
        User.objects.filter(
            username__in=['admin', 'registrar', 'staff', 'student']
        ).delete()
    except Exception:
        pass

    sync_postgres_sequence(schema_editor, 'accounts_user', 'id')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_passwordresetotp'),
    ]

    operations = [
        migrations.RunPython(seed_default_accounts, unseed_default_accounts),
    ]
