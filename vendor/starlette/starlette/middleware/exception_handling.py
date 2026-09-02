from __future__ import annotations

from typing import Any

from starlette._exception_handler import (
    RESPONSE_STARTED_KEY,
    find_exception_handler,
    send_handler_response,
    tracking_sender,
)
from starlette._utils import is_async_callable
from starlette.concurrency import run_in_threadpool
from starlette.middleware.errors import ServerErrorMiddleware
from starlette.middleware.exceptions import ExceptionMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp, ExceptionHandler, Receive, Scope, Send


class ExceptionHandlingMiddleware:
    """ServerErrorMiddleware and ExceptionMiddleware as one frame per request.

    Behaves exactly like ServerErrorMiddleware wrapping ExceptionMiddleware with nothing in
    between, which is the stack an application without user middleware gets.
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
        self.server_errors = ServerErrorMiddleware(app, handler=error_handler, debug=debug)
        self.exceptions = ExceptionMiddleware(app, handlers=exception_handlers, debug=debug)

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
        exceptions = self.exceptions
        scope["starlette.exception_handlers"] = (exceptions._exception_handlers, exceptions._status_handlers)

        try:
            try:
                await self.app(scope, receive, sender)
            except Exception as exc:
                handler = find_exception_handler(exc, scope)
                if handler is None:
                    raise
                if tracker[0]:
                    raise RuntimeError("Caught handled exception, but response already started.") from exc
                await send_handler_response(handler, exc, Request(scope, receive, send), scope, receive, sender)
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
