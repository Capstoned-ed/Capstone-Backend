from ..models import RegistrarSettings


def get_registrar_settings():
    """
    Returns the singleton RegistrarSettings instance.
    """
    return RegistrarSettings.get_settings()

