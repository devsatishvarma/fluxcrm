"""API pagination and error mapping shared by lead and deal endpoints."""

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import exception_handler

from core.exceptions import VersionConflict

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


class CappedPagination(PageNumberPagination):
    page_size = DEFAULT_PAGE_SIZE
    page_size_query_param = "page_size"
    max_page_size = MAX_PAGE_SIZE


def parse_page_size(raw):
    if raw in (None, ""):
        return DEFAULT_PAGE_SIZE
    try:
        size = int(raw)
    except (TypeError, ValueError) as exc:
        raise DjangoValidationError(
            {"page_size": "Page size must be an integer."}
        ) from exc
    if not 1 <= size <= MAX_PAGE_SIZE:
        raise DjangoValidationError(
            {"page_size": "Page size must be between 1 and 200."}
        )
    return size


def validation_body(exc):
    if hasattr(exc, "error_dict"):
        return {
            field: [str(item.message) for item in errors]
            for field, errors in exc.error_dict.items()
        }
    return {"detail": [str(item.message) for item in exc.error_list]}


def api_exception_handler(exc, context):
    if isinstance(exc, VersionConflict):
        return Response(
            {"detail": "This record was updated. Reload and retry."},
            status=409,
        )
    if isinstance(exc, DjangoValidationError):
        return Response(validation_body(exc), status=422)
    if isinstance(exc, (DjangoPermissionDenied, DRFPermissionDenied)):
        return Response(
            {"detail": "You do not have access to this record."},
            status=403,
        )
    if isinstance(exc, Http404):
        return Response({"detail": "Not found."}, status=404)
    response = exception_handler(exc, context)
    if isinstance(exc, DRFValidationError) and response is not None:
        response.status_code = 422
    return response
