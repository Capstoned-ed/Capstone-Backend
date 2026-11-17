import sys
from django.db import migrations


DOC_CODE_UPDATES = {
    'TOR': '1',
    'HD': '2',
    'EVAL': '5',
    'AUTH': '10',
    'CAR': '4f',
    'COE': '4a',
    'GPA': '4b',
    'UNITS': '4d',
    'ENDORSE': '4m',
    'GRADES': '4g',
}


def update_credential_doc_codes(apps, schema_editor):
    if 'pytest' in sys.modules or any('test' in arg for arg in sys.argv):
        return

    CredentialType = apps.get_model('credentials', 'CredentialType')
    CredentialRequest = apps.get_model('credentials', 'CredentialRequest')

    for code, doc_code in DOC_CODE_UPDATES.items():
        CredentialType.objects.filter(code__iexact=code).update(
            doc_code=doc_code
        )

    cert_types = CredentialType.objects.filter(code__iexact='CERT')
    for cert in cert_types:
        has_requests = CredentialRequest.objects.filter(
            credential_type=cert
        ).exists()
        if has_requests:
            cert.is_active = False
            cert.save(update_fields=['is_active'])
        else:
            cert.delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('credentials', '0012_credentialrequest_approved_at_and_more'),
    ]

    operations = [
        migrations.RunPython(update_credential_doc_codes, noop_reverse),
    ]
