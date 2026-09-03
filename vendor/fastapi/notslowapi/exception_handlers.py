from notslowapi.encoders import jsonable_encoder
from notslowapi.exceptions import (
    RequestValidationError,
    WebSocketRequestValidationError,
)
from notslowapi.starlette.exceptions import HTTPException
from notslowapi.starlette.requests import Request
from notslowapi.starlette.responses import JSONResponse, Response
from notslowapi.starlette.status import WS_1008_POLICY_VIOLATION
from notslowapi.utils import is_body_allowed_for_status_code
from notslowapi.websockets import WebSocket


async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    headers = getattr(exc, "headers", None)
    if not is_body_allowed_for_status_code(exc.status_code):
        return Response(status_code=exc.status_code, headers=headers)
    return JSONResponse(
        {"detail": exc.detail}, status_code=exc.status_code, headers=headers
    )


async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors())},
    )


async def websocket_request_validation_exception_handler(
    websocket: WebSocket, exc: WebSocketRequestValidationError
) -> None:
    await websocket.close(
        code=WS_1008_POLICY_VIOLATION, reason=jsonable_encoder(exc.errors())
    )
