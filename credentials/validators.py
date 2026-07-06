import os
import mimetypes
from django.core.exceptions import ValidationError

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_EXTENSIONS = ['.pdf', '.jpg', '.jpeg', '.png']
ALLOWED_MIME_TYPES = ['application/pdf', 'image/jpeg', 'image/png']


def validate_file_size(file):
    if file.size > MAX_FILE_SIZE:
        max_mb = MAX_FILE_SIZE / (1024 * 1024)
        raise ValidationError(f"File size exceeds the {max_mb:.0f}MB limit.")


def validate_file_extension(file):
    ext = os.path.splitext(file.name)[1]
    if not ext.lower() in ALLOWED_EXTENSIONS:
        allowed = ', '.join(ALLOWED_EXTENSIONS)
        raise ValidationError(f"Unsupported file extension. Allowed: {allowed}")


def validate_mime_type(file):
    content_type = getattr(file, 'content_type', None)
    if not content_type:
        content_type, _ = mimetypes.guess_type(file.name)

    if content_type not in ALLOWED_MIME_TYPES:
        allowed = ', '.join(ALLOWED_MIME_TYPES)
        raise ValidationError(f"Unsupported file MIME type. Allowed: {allowed}")
