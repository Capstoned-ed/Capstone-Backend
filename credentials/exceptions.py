from rest_framework.exceptions import APIException
from rest_framework import status


class InvalidStateTransitionException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Invalid state transition.'
    default_code = 'invalid_state_transition'
