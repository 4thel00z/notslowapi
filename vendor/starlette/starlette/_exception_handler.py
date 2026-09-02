from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from starlette._utils import is_async_callable
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.types import ASGIApp, ExceptionHandler, Message, Receive, Scope, Send
from starlette.websockets import WebSocket

ExceptionHandlers = dict[Any, ExceptionHandler]
StatusHandlers = dict[int, ExceptionHandler]

RESPONSE_STARTED_KEY = "starlette.response_started"


def tracking_sender(send: Send, tracker: list[bool]) -> Send:
    """Wrap send so tracker[0] becomes True once http.response.start has been sent."""

    def sender(message: Message) -> Awaitable[None]:
        if message["type"] == "http.response.start":
            tracker[0] = True
        return send(message)

    return sender


def _lookup_exception_handler(exc_handlers: ExceptionHandlers, exc: Exception) -> ExceptionHandler | None:
    for cls in type(exc).__mro__:
        if cls in exc_handlers:
            return exc_handlers[cls]
    return None


async def run_handling_exceptions(
    app: ASGIApp,
    conn: Request | WebSocket | None,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    """Run app; on an exception with a registered handler, respond with the handler's response.

    conn is the connection object handed to the handler; None builds one from the scope on demand.
    """
    tracker: list[bool] | None = scope.get(RESPONSE_STARTED_KEY)
    if tracker is None:
        tracker = [False]
        scope[RESPONSE_STARTED_KEY] = tracker
        sender = tracking_sender(send, tracker)
    else:
        sender = send

    try:
        await app(scope, receive, sender)
    except Exception as exc:
        handler = find_exception_handler(exc, scope)
        if handler is None:
            raise exc
        if tracker[0]:
            raise RuntimeError("Caught handled exception, but response already started.") from exc
        if conn is None:
            conn = Request(scope, receive, send) if scope["type"] == "http" else WebSocket(scope, receive, send)
        await send_handler_response(handler, exc, conn, scope, receive, sender)


def find_exception_handler(exc: Exception, scope: Scope) -> ExceptionHandler | None:
    """The handler registered in the scope for exc's status code or class, if any."""
    exception_handlers: ExceptionHandlers
    status_handlers: StatusHandlers
    try:
        exception_handlers, status_handlers = scope["starlette.exception_handlers"]
    except KeyError:
        exception_handlers, status_handlers = {}, {}
    if isinstance(exc, HTTPException):
        handler = status_handlers.get(exc.status_code)
        if handler is not None:
            return handler
    return _lookup_exception_handler(exception_handlers, exc)


async def send_handler_response(
    handler: ExceptionHandler,
    exc: Exception,
    conn: Request | WebSocket,
    scope: Scope,
    receive: Receive,
    sender: Send,
) -> None:
    """Call handler for exc and send the response it returns, if any."""
    if is_async_callable(handler):
        response = await handler(conn, exc)  # type: ignore[arg-type]
    else:
        response = await run_in_threadpool(handler, conn, exc)  # type: ignore[arg-type]
    if response is not None:
        await response(scope, receive, sender)


def wrap_app_handling_exceptions(app: ASGIApp, conn: Request | WebSocket) -> ASGIApp:
    async def wrapped_app(scope: Scope, receive: Receive, send: Send) -> None:
        await run_handling_exceptions(app, conn, scope, receive, send)

    return wrapped_app
