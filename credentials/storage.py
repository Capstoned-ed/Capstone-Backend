from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible
from django.conf import settings


@deconstructible
class PrivateMediaStorage(FileSystemStorage):
    def __init__(self, **kwargs):
        kwargs['location'] = settings.PRIVATE_ROOT
        super().__init__(**kwargs)


private_storage = PrivateMediaStorage()
