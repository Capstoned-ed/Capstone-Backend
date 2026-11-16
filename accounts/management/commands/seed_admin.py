import os
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from accounts.models import Role
from credentials.models import CredentialType

User = get_user_model()


class Command(BaseCommand):
    help = (
        'Cleanly seeds ONLY the single administrative account '
        'and essential credential types.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--clean',
            action='store_true',
            help='Wipe all non-admin users and request records before seeding',
        )
        parser.add_argument(
            '--id',
            '--username',
            dest='username',
            default=None,
            help='Admin ID Number / Username (defaults to ADMIN_ID env var)',
        )
        parser.add_argument(
            '--password',
            dest='password',
            default=None,
            help='Admin password (defaults to ADMIN_PASSWORD env var)',
        )
        parser.add_argument(
            '--email',
            dest='email',
            default=None,
            help='Admin email (defaults to ADMIN_EMAIL env var)',
        )

    def handle(self, *args, **options):
        username = (
            options.get('username') or
            os.environ.get('ADMIN_ID') or
            ''
        ).strip()
        password = (
            options.get('password') or
            os.environ.get('ADMIN_PASSWORD') or
            ''
        ).strip()
        email = (
            options.get('email') or
            os.environ.get('ADMIN_EMAIL') or
            ''
        ).strip()

        if not username or not password:
            raise CommandError(
                "ADMIN_ID and ADMIN_PASSWORD environment variables must be set."
            )

        if not email:
            email = f'{username}@ustp.edu.ph'
        clean = options['clean']

        if clean:
            self.stdout.write(self.style.WARNING(
                'Cleaning database: removing non-admin accounts and requests...'
            ))
            # Delete credential requests and related child tables
            from credentials.models import (
                CredentialRequest, StudentClearance, RequirementDocument, Payment
            )
            Payment.objects.all().delete()
            RequirementDocument.objects.all().delete()
            StudentClearance.objects.all().delete()
            CredentialRequest.objects.all().delete()

            # Delete all non-admin users
            User.objects.exclude(username=username).delete()

        # 1. Update or create the single Admin account
        admin_user, created = User.objects.update_or_create(
            username=username,
            defaults={
                'email': email,
                'role': Role.ADMIN,
                'first_name': 'System',
                'last_name': 'Administrator',
                'is_staff': True,
                'is_superuser': True,
                'is_active': True,
                'force_password_change': False,
            }
        )
        admin_user.set_password(password)
        admin_user.save()

        # 2. Seed / Ensure Essential In-Scope Credential Types
        doc_types = [
            {
                'code': 'TOR',
                'doc_code': '1',
                'name': 'Transcript of Records (TOR)',
                'description': 'Official record of courses taken and grades earned.',
                'price': '125.00',
                'processing_days': 7,
                'is_active': True,
            },
            {
                'code': 'HD',
                'doc_code': '2',
                'name': 'Honorable Dismissal',
                'description': 'Honorable dismissal and transfer credentials.',
                'price': '100.00',
                'processing_days': 5,
                'is_active': True,
            },
            {
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
                'code': 'CAR',
                'doc_code': '4F',
                'name': 'Certification - CAR',
                'description': (
                    'Cumulative Academic Record (CAR) academic history.'
                ),
                'price': '80.00',
                'processing_days': 5,
                'is_active': True,
            },
            {
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
                'description': (
                    'Official certification of overall Grade Point Average.'
                ),
                'price': '80.00',
                'processing_days': 3,
                'is_active': True,
            },
        ]

        seeded_types = 0
        for item in doc_types:
            CredentialType.objects.update_or_create(
                code=item['code'],
                defaults=item
            )
            seeded_types += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('REGQUEST CLEAN ADMIN SEED COMPLETE'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(f'Admin ID / Username : {username}')
        self.stdout.write(f'Admin Password      : {"*" * len(password)}')
        self.stdout.write(f'Admin Email         : {email}')
        self.stdout.write(f'Admin Role          : {admin_user.role}')
        self.stdout.write(f'Credential Types    : {seeded_types} in-scope types ready')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write('')
