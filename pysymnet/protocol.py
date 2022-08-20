"""SymNet TCP/UDP protocol."""

import asyncio
import collections
import logging
import typing

from .exceptions import SymNetException
from .tasks import SymNetTask

LOGGER = logging.getLogger(__name__)


class SymNetProtocol(asyncio.Protocol, asyncio.DatagramProtocol):
    """SymNet TCP/UDP protocol."""

    _on_conn_made: asyncio.Future[bool] | None
    _on_conn_lost: asyncio.Future[Exception] | None
    _transport: asyncio.Transport | asyncio.DatagramTransport
    _is_datagram: bool

    _current_msg: str | None
    _current_task: SymNetTask | None
    _queue: collections.deque[typing.Tuple[str, SymNetTask]]

    update_callback: typing.Callable[[int, int], None] | None

    def __init__(
        self,
        is_datagram: bool,
        on_conn_made: asyncio.Future[bool] | None,
        on_conn_lost: asyncio.Future[Exception] | None,
    ):
        """Initialize SymNet protocol."""
        self._on_conn_made = on_conn_made
        self._on_conn_lost = on_conn_lost

        self._transport = None

        self._is_datagram = is_datagram

        self._current_msg = None
        self._current_task = None
        self._queue = collections.deque()

        self.update_callback = None

    def connection_made(
        self, transport: asyncio.Transport | asyncio.DatagramTransport
    ) -> None:
        """Notify a connection has been established."""
        LOGGER.debug("Connection with DSP established.")

        self._transport = transport

        if self._on_conn_made is not None:
            self._on_conn_made.set_result(True)

    def _process_line(self, line: str) -> None:
        LOGGER.debug(f"Processing line '{line}'")

        task = self._current_task

        if (task is None or not task.expects_update_format) and line[0] == "#":
            pos = line.index("=")
            after_equal = pos + 1

            rcn = int(line[1:pos])
            val = int(line[after_equal:])

            if val == -1:
                pass  # should never happen

            if self.update_callback is not None:
                self.update_callback(rcn, val)
        else:
            if line.upper() == "NAK":
                task.error(SymNetException("NAK received from DSP."))
            else:
                task.handle_line(line)

    def _try_process_tasks(self) -> None:
        if self._current_task is not None:
            return

        try:
            msg: str
            task: SymNetTask

            msg, task = self._queue.popleft()

            self._current_msg = msg
            self._current_task = task

            task._future.add_done_callback(self._task_done)

            LOGGER.debug(f"Sending '{msg}'")

            self._write(msg + "\r")
        except IndexError:
            pass

    def _task_done(self, fut: asyncio.Future) -> None:
        try:
            result = fut.result()

            LOGGER.debug(f"Task completed with result {result}")
        except Exception as err:
            LOGGER.debug(f"Task completed with exception {err}")

        self._current_task = None

        self._try_process_tasks()

    def queue_task(self, msg: str, task: SymNetTask) -> None:
        """Add a task to the end of the queue."""
        LOGGER.debug(f"Queued {msg}.")

        self._queue.append((msg, task))

        self._try_process_tasks()

    def queue_task_immediate(self, msg: str, task: SymNetTask) -> None:
        """Add a task to the front of the queue."""
        LOGGER.debug(f"Queued immediate {msg}")

        self._queue.appendleft((msg, task))

        self._try_process_tasks()

    def get_queue(self) -> typing.List[typing.Tuple[str, SymNetTask]]:
        """Get all tasks in the queue."""
        tasks = list(self._queue)

        if (
            self._current_task is not None
            and not self._current_task._future.done()
        ):
            tasks = [(self._current_msg, self._current_task)] + tasks

            self._current_msg = None
            self._current_task = None

        return tasks

    def data_received(self, data: bytes) -> None:
        """Notify that TCP data has been received."""
        for line in data.split(b"\r")[:-1]:
            self._process_line(line.decode())

    def datagram_received(
        self, data: bytes, addr: typing.Tuple[str, int]
    ) -> None:
        """Notify that UDP data has been received."""
        self.data_received(data)

    def _write(self, data: str) -> None:
        if self.is_datagram:
            self._transport.sendto(data.encode())
        else:
            self._transport.write(data.encode())

    def connection_lost(self, err: Exception | None) -> None:
        """Notify that the connection has been disconnected."""
        LOGGER.debug("Connection lost.")

        if self._on_conn_lost is not None:
            self._on_conn_lost.set_result(err)

    async def disconnect(self) -> None:
        """Disconnect the connection."""
        LOGGER.debug("User initiated disconnect.")

        self._transport.abort()

        await self._on_conn_lost

    @property
    def is_datagram(self):
        """Determine if the protocol is operating in UDP mode."""
        return self._is_datagram
