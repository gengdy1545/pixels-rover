from typing import Any

from app.request_id import get_request_id


def api_success(data: Any = None, message: str = "success") -> dict[str, Any]:
    return {
        "code": 200,
        "message": message,
        "data": data,
        "requestId": get_request_id(),
        "apiVersion": "v1",
    }


def api_error(code: int, message: str, error_code: str | None = None) -> dict[str, Any]:
    payload = {
        "code": code,
        "message": message,
        "requestId": get_request_id(),
        "apiVersion": "v1",
    }
    if error_code:
        payload["errorCode"] = error_code
    return payload
