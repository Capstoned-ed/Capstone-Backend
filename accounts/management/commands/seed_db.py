from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from accounts.models import Role
from accounts.services import AccountService
from audit.models import AuditLog

User = get_user_model()


class Command(BaseCommand):
    help = 'Seeds the database with initial development data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing data before seeding',
        )

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write('Clearing existing users and audit logs...')
            AuditLog.objects.all().delete()
            User.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('Cleared database.'))

        # Check if users already exist
        if User.objects.exists():
            self.stdout.write(
                self.style.WARNING(
                    'Users already exist. Use --clear to wipe data first. Aborting.'
                )
            )
            return

        self.stdout.write('Seeding database...')

        # 1. Create superuser (Admin) directly
        admin_username = 'admin'
        self.stdout.write(f'Creating superuser: {admin_username}...')
        admin_user = User.objects.create_superuser(
            username=admin_username,
            email='admin@example.com',
            password='password123'
        )

        # 2. Use AccountService to create other roles, using Admin as the actor
        roles_to_seed = [
            (Role.STUDENT, 'student', 'student@example.com'),
            (Role.STAFF, 'staff', 'staff@example.com'),
            (Role.REGISTRAR, 'registrar', 'registrar@example.com')
        ]

        for role, username, email in roles_to_seed:
            self.stdout.write(f'Creating {role} user: {username}...')
            AccountService.create_user(
                actor=admin_user,
                username=username,
                email=email,
                password='password123',
                role=role
            )

        self.stdout.write(
            self.style.SUCCESS('Database seeding completed successfully!')
        )
