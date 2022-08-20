from .exceptions import SymNetException
from .tasks import SymNetTask
import collections
import typing
import asyncio

class SymNetProtocol(asyncio.Protocol):
    _on_conn_made: asyncio.Future[bool] | None
    _on_conn_lost: asyncio.Future[Exception] | None
    _transport: asyncio.Transport | asyncio.DatagramTransport
    _is_datagram: bool

    _current_task: SymNetTask
    _queue: collections.deque[typing.Tuple[str, SymNetTask]]

    update_callback: typing.Callable[[int, int], None] | None

    def __init__(self, is_datagram: bool, on_conn_made: asyncio.Future[bool] | None, on_conn_lost: asyncio.Future[Exception] | None):
        self._on_conn_made = on_conn_made
        self._on_conn_lost = on_conn_lost

        self._transport = None

        self._is_datagram = is_datagram
        
        self.update_callback = None
    
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport

        if self._on_conn_made is not None:
            self._on_conn_made.set_result(True)
    
    def _process_line(self, line: str) -> None:
        task = self._current_task

        if (task is None or task.expects_update_format) and line[0] == "#":
            pos = line.index("=")

            rcn = int(line[1:pos])
            val = int(line[pos + 1:])

            if val == -1:
                pass # should never happen

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

            self._current_task = task

            task._future.add_done_callback(self._task_done)

            self._write(msg + "\r")
        except IndexError:
            pass
    
    def _task_done(self) -> None:
        self._queue.task_done()

        self._current_task = None

        self._try_process_tasks()
    
    def queue_task(self, msg: str, task: SymNetTask) -> None:
        self._queue.append((msg, task))

        self._try_process_tasks()
    
    def queue_task_immediate(self, msg: str, task: SymNetTask) -> None:
        self._queue.appendleft((msg, task))

        self._try_process_tasks()
    
    def get_queue(self) -> typing.List[typing.Tuple[str, SymNetTask]]:
        return list(self._queue)

    def data_received(self, data: bytes) -> None:
        for line in data.split(b"\r"):
            self._process_line(line.decode())
    
    def datagram_received(self, data: bytes, addr: typing.Tuple[str, int]) -> None:
        self.data_received(data)

    def _write(self, data: str) -> None:
        if self.is_datagram:
            self._transport.sendto(data.encode())
        else:
            self._transport.write(data.encode())
    
    def connection_lost(self, err: Exception | None) -> None:
        if self._on_conn_lost is not None:
            self._on_conn_lost.set_result(err)
    
    async def disconnect(self) -> None:
        self._transport.abort()

        await self._on_conn_lost
    
    @property
    def is_datagram(self):
        return self._is_datagram
