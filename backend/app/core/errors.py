"""Consistent API errors: {"error": {"code", "message", "details"}} with proper status codes."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return {"error": body}


def not_found(entity: str, ident: Any) -> ApiError:
    return ApiError(404, "not_found", f"{entity} '{ident}' was not found.")


def forbidden(message: str, details: Any = None) -> ApiError:
    return ApiError(403, "forbidden", message, details)


def bad_request(message: str, details: Any = None) -> ApiError:
    return ApiError(400, "bad_request", message, details)


def conflict(message: str, details: Any = None) -> ApiError:
    return ApiError(409, "conflict", message, details)


def unprocessable(message: str, details: Any = None) -> ApiError:
    return ApiError(422, "validation_error", message, details)
