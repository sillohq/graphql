"""Subscriptions over ``graphql-transport-ws``.

The protocol in one paragraph: the client connects with the subprotocol
``graphql-transport-ws``, sends ``connection_init`` and waits for
``connection_ack``; then each operation is a ``subscribe`` carrying an id, the
server answers with ``next`` messages and ends with ``complete`` or ``error``;
either side may ``ping`` and must answer ``pong``; the client can ``complete``
an operation to unsubscribe.

Three rules do most of the work of keeping it well behaved:

* a connection that never sends ``connection_init`` is closed after
  ``init_timeout`` seconds, so an idle socket cannot be held open for free;
* an id already in use is a protocol error and closes the connection, because
  the alternative is two operations racing over one channel;
* every operation is cancelled when its socket closes, in a ``finally`` — a
  subscription that outlives its client is a leak that compounds.

``connection_init``'s payload is where authentication belongs. There are no
headers on a browser WebSocket handshake, so a token arrives here, and the
``@graph.on_connect`` hook is given it before any operation runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import json as jsonlib
import typing

from sillo_graphql.errors import GraphQLDenied, GraphQLError

if typing.TYPE_CHECKING:
    from sillo.websockets import WebSocketContext

    from sillo_graphql.graph import Graph

__all__ = ["PROTOCOL", "WebSocketTransport"]

#: The subprotocol this transport speaks.
PROTOCOL = "graphql-transport-ws"

#: The older protocol, named here only so a client asking for it is told
#: plainly rather than left waiting for messages that never come.
LEGACY_PROTOCOL = "graphql-ws"

# Close codes from the protocol.
CLOSE_BAD_MESSAGE = 4400
CLOSE_UNAUTHORIZED = 4401
CLOSE_INIT_TIMEOUT = 4408
CLOSE_ALREADY_INITIALISED = 4429
CLOSE_SUBSCRIBER_EXISTS = 4409


class WebSocketTransport:
    """Serves one :class:`~sillo_graphql.graph.Graph` over a WebSocket."""

    def __init__(
        self,
        graph: Graph,
        *,
        init_timeout: float = 10.0,
        keepalive: float | None = 30.0,
    ) -> None:
        self.graph = graph
        self.init_timeout = init_timeout
        self.keepalive = keepalive

    async def handle(self, ctx: WebSocketContext) -> None:
        """Run one connection to completion."""
        await ctx.accept(subprotocol=PROTOCOL)
        session = _Session(self, ctx)
        try:
            await session.run()
        finally:
            await session.shutdown()


class _Session:
    """One client connection, and the operations running on it."""

    def __init__(self, transport: WebSocketTransport, ctx: WebSocketContext) -> None:
        self.transport = transport
        self.graph = transport.graph
        self.ctx = ctx
        self.initialised = False
        self.connection_params: dict[str, typing.Any] = {}
        self.operations: dict[str, asyncio.Task] = {}
        self.extra: dict[str, typing.Any] = {}

    async def run(self) -> None:
        """Read messages until the client goes away or breaks the protocol."""
        try:
            await self._loop()
        except _Closed:
            # The client is gone. There is nothing left to send it and nothing
            # to report — every operation is torn down by `shutdown`.
            return

    async def _loop(self) -> None:
        """The message loop proper. Raises ``_Closed`` when the socket ends."""
        while True:
            raw = await self._receive()

            try:
                message = jsonlib.loads(raw)
                if not isinstance(message, dict):
                    raise ValueError("not an object")
            except ValueError:
                await self._close(CLOSE_BAD_MESSAGE, "Invalid message")
                return

            kind = str(message.get("type") or "")
            handler = {
                "connection_init": self._init,
                "subscribe": self._subscribe,
                "complete": self._complete,
                "ping": self._ping,
                "pong": self._pong,
            }.get(kind)

            if handler is None:
                await self._close(CLOSE_BAD_MESSAGE, f"Unknown message type {kind!r}")
                return
            if not await handler(message):
                return

    async def _receive(self) -> str:
        """The next text frame, subject to the init timeout.

        Before ``connection_init`` the wait is bounded: an unauthenticated
        socket that says nothing should not be able to occupy a connection
        slot indefinitely.
        """
        if not self.initialised and self.transport.init_timeout:
            try:
                return await asyncio.wait_for(
                    self._read(), timeout=self.transport.init_timeout
                )
            except asyncio.TimeoutError:
                await self._close(
                    CLOSE_INIT_TIMEOUT, "Connection initialisation timeout"
                )
                raise _Closed from None
        return await self._read()

    async def _read(self) -> str:
        try:
            return await self.ctx.receive_text()
        except Exception as exc:
            raise _Closed from exc

    async def _init(self, message: dict[str, typing.Any]) -> bool:
        if self.initialised:
            await self._close(
                CLOSE_ALREADY_INITIALISED, "Too many initialisation requests"
            )
            return False

        payload = message.get("payload")
        self.connection_params = payload if isinstance(payload, dict) else {}
        try:
            self.extra = await self.graph.connect(self.ctx, self.connection_params)
        except GraphQLDenied as denied:
            await self._close(CLOSE_UNAUTHORIZED, denied.message)
            return False

        self.initialised = True
        await self._send({"type": "connection_ack"})
        return True

    async def _subscribe(self, message: dict[str, typing.Any]) -> bool:
        if not self.initialised:
            await self._close(CLOSE_UNAUTHORIZED, "Unauthorized")
            return False

        operation_id = message.get("id")
        if not isinstance(operation_id, str):
            await self._close(CLOSE_BAD_MESSAGE, "`subscribe` needs a string id")
            return False
        if operation_id in self.operations:
            await self._close(
                CLOSE_SUBSCRIBER_EXISTS, f"Subscriber for {operation_id} already exists"
            )
            return False

        payload = message.get("payload")
        if not isinstance(payload, dict):
            await self._close(CLOSE_BAD_MESSAGE, "`subscribe` needs a payload object")
            return False

        task = asyncio.ensure_future(self._operation(operation_id, payload))
        self.operations[operation_id] = task
        return True

    async def _operation(
        self, operation_id: str, payload: dict[str, typing.Any]
    ) -> None:
        """Run one operation and stream its results under *operation_id*."""
        try:
            async for result in self.graph.stream(
                payload, socket=self.ctx, connection_params=self.connection_params
            ):
                await self._send(
                    {"type": "next", "id": operation_id, "payload": result.body()}
                )
        except asyncio.CancelledError:
            raise
        except GraphQLError as error:
            await self._send(
                {
                    "type": "error",
                    "id": operation_id,
                    "payload": [
                        {
                            "message": error.message,
                            "extensions": error.as_extensions(),
                        }
                    ],
                }
            )
        except _Closed:
            return
        else:
            await self._send({"type": "complete", "id": operation_id})
        finally:
            self.operations.pop(operation_id, None)

    async def _complete(self, message: dict[str, typing.Any]) -> bool:
        operation_id = message.get("id")
        task = (
            self.operations.pop(operation_id, None)
            if isinstance(operation_id, str)
            else None
        )
        if task is not None:
            task.cancel()
        return True

    async def _ping(self, message: dict[str, typing.Any]) -> bool:
        await self._send({"type": "pong", "payload": message.get("payload")})
        return True

    async def _pong(self, message: dict[str, typing.Any]) -> bool:
        """Nothing to do. Accepted so an unsolicited pong is not a protocol error."""
        return True

    async def _send(self, message: dict[str, typing.Any]) -> None:
        try:
            await self.ctx.send_text(jsonlib.dumps(message))
        except Exception as exc:
            raise _Closed from exc

    async def _close(self, code: int, reason: str) -> None:
        # An already-closed socket raises here, which is the state being
        # asked for.
        with contextlib.suppress(Exception):
            await self.ctx.close(code=code, reason=reason)

    async def shutdown(self) -> None:
        """Cancel every operation still running on this connection.

        In a ``finally``, and awaited: a subscription generator holding a
        database session must be given the chance to close it, and a task
        merely cancelled has not run its own ``finally`` yet.
        """
        tasks = list(self.operations.values())
        self.operations.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


class _Closed(Exception):
    """The socket is gone. Internal; never reaches a caller."""
