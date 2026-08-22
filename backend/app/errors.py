from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas.common import error_payload

_STATUS_CODES = {
    400: "validation_error",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
}


def unprocessable(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)


def not_found(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)


def _message_from_detail(detail: object) -> str:
    if isinstance(detail, str):
        return detail
    return str(detail)


def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    code = _STATUS_CODES.get(exc.status_code, "internal_error" if exc.status_code >= 500 else "request_error")
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(code, _message_from_detail(exc.detail)),
    )


def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    field: str | None = None
    message = "Invalid request"
    if errors:
        location = errors[0].get("loc") or ()
        if len(location) > 1:
            field = str(location[-1])
        message = str(errors[0].get("msg") or message)
    return JSONResponse(status_code=422, content=error_payload("validation_error", message, field))


def unhandled_exception_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=error_payload("internal_error", "An unexpected error occurred"),
    )
