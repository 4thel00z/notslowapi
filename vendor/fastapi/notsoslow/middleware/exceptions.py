"""One ASGI layer doing the work of ServerErrorMiddleware plus ExceptionMiddleware."""

from typing import Any

from starlette._exception_handler import (
    RESPONSE_STARTED_KEY,
    _lookup_exception_handler,
    tracking_sender,
)
from starlette._utils import is_async_callable
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.middleware.errors import ServerErrorMiddleware
from starlette.middleware.exceptions import ExceptionMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp, ExceptionHandler, Receive, Scope, Send


class ExceptionHandlingMiddleware:
    """Handles registered exceptions and server errors in one frame per request.

    Behaves exactly like ServerErrorMiddleware wrapping ExceptionMiddleware with
    nothing in between, which is the stack an app without user middleware gets.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        error_handler: ExceptionHandler | None,
        exception_handlers: dict[Any, ExceptionHandler],
        debug: bool,
    ) -> None:
        self.app = app
        self.server_errors = ServerErrorMiddleware(
            app, handler=error_handler, debug=debug
        )
        self.exceptions = ExceptionMiddleware(
            app, handlers=exception_handlers, debug=debug
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope["type"]
        if scope_type != "http":
            if scope_type == "websocket":
                await self.exceptions(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        tracker = [False]
        scope[RESPONSE_STARTED_KEY] = tracker
        sender = tracking_sender(send, tracker)
        exception_handlers = self.exceptions._exception_handlers
        status_handlers = self.exceptions._status_handlers
        scope["starlette.exception_handlers"] = (exception_handlers, status_handlers)

        try:
            try:
                await self.app(scope, receive, sender)
            except Exception as exc:
                handler = None
                if isinstance(exc, HTTPException):
                    handler = status_handlers.get(exc.status_code)
                if handler is None:
                    handler = _lookup_exception_handler(exception_handlers, exc)
                if handler is None:
                    raise
                if tracker[0]:
                    raise RuntimeError(
                        "Caught handled exception, but response already started."
                    ) from exc
                conn = Request(scope, receive, send)
                if is_async_callable(handler):
                    response = await handler(conn, exc)  # type: ignore[arg-type]
                else:
                    response = await run_in_threadpool(handler, conn, exc)  # type: ignore[arg-type]
                if response is not None:
                    await response(scope, receive, sender)
        except Exception as exc:
            server_errors = self.server_errors
            request = Request(scope)
            if server_errors.debug:
                response = server_errors.debug_response(request, exc)
            elif server_errors.handler is None:
                response = server_errors.error_response(request, exc)
            elif is_async_callable(server_errors.handler):
                response = await server_errors.handler(request, exc)  # type: ignore[arg-type,assignment]
            else:
                response = await run_in_threadpool(server_errors.handler, request, exc)  # type: ignore[arg-type]
            if not tracker[0]:
                await response(scope, receive, send)
            raise exc
