from django.db import OperationalError
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler


class Conflict(APIException):
    status_code = 409
    default_detail = 'Request trùng mã nhưng khác nội dung.'


def api_exception_handler(exc, context):
    if isinstance(exc, OperationalError):
        return Response({'detail': 'Không truy cập được MySQL hoặc có xung đột tạm thời. Kiểm tra cấu hình DB; thử lại cùng mã request.', 'code': 'DATABASE_UNAVAILABLE'}, status=503)
    return exception_handler(exc, context)
