"""Python Symetrix SymNet module."""

import asyncio
import enum
import collections
from concurrent.futures.thread import ThreadPoolExecutor
import typing

from .tasks import *
from .exceptions import SymNetException

DEFAULT_PORT: int = 48631

class SymNetConnectionType(enum.Enum):
    TCP = "tcp"
    UDP = "udp"

def fader_converter(min: float, max: float) -> typing.Tuple[typing.Callable[[int], float], typing.Callable[[float], int]]:
    delta: float = max - min

    def to_db(val: int) -> float:
        if val == 0:
            return 0.0
        
        return min + delta * float(val) / 65535.0
    
    def from_db(val: float) -> int:
        if val == 0.0:
            return 0
        
        return (val - min) * 65535.0 / delta
    
    return to_db, from_db

class SymNetConnection:
    _host: str
    _port: int
    _mode: SymNetConnectionType

    _current_task: SymNetTask
    _queue: collections.deque[typing.Tuple[str, SymNetTask]]

    _connect_future: asyncio.Future

    _reader: asyncio.StreamReader
    _writer: asyncio.StreamWriter

    _version: typing.List[str]

    _subscriptions: dict[int, set[typing.Callable[[int, int], None]]]

    def __init__(self, host: str, port: int = DEFAULT_PORT, mode: SymNetConnectionType = SymNetConnectionType.TCP):
        self._host = host
        self._port = port
        self._mode = mode

        self._current_task = None
        self._queue = collections.deque()
        self._subscriptions = set()

        self._reader = None
        self._writer = None

        loop = asyncio.get_running_loop()

        self._connect_future = loop.create_future()

        self._version = None
    
    async def _get_connection(self) -> None:
        if self._reader is not None:
            return
        
        if self._mode == SymNetConnectionType.TCP:
            reader, writer = await asyncio.open_connection(self._host, self._port)

            self._reader = reader
            self._writer = writer
        elif self._mode == SymNetConnectionType.UDP:
            raise NotImplementedError()
        else:
            raise NotImplementedError()
    
    async def _symnet_loop(self) -> None:
        try:
            await self._get_connection()
        except Exception as err:
            self._connect_future.set_exception(err)

        self._connect_future.set_result(None)

        while True:
            line = await self._reader.readuntil(b"\r")
            task = self._current_task

            # check if it's an update
            if (task is None or not task.expects_update_format) and line[0] == "#":
                pos = line.index("=")

                rcn = int(line[1:pos])
                val = int(line[pos + 1:])

                if val == -1:
                    # Should never happen
                    pass
            elif task is not None:
                if line == "NAK":
                    task.error(SymNetException("NAK received from DSP."))
                else:
                    await task.handle_line(line)
    
    def _try_exec_tasks(self) -> None:
        if self._current_task is not None:
            return
        
        try:
            msg: str
            task: SymNetTask[T]
            
            msg, task = self._queue.popleft(False)

            self._current_task = task

            task._future.add_done_callback(self._task_done)

            self._get_connection()

            self._writer.write(msg.encode() + b"\r")
        except IndexError:
            return
    
    def _task_done(self, _fut: asyncio.Future):
        self._queue.task_done()

        self._current_task = None

        self._try_exec_tasks()

    async def _do_task(self, msg: str, task: SymNetTask[T]) -> T:
        ctr: int = 0
        last_err: Exception = None

        while ctr < task.retry_limit:
            if ctr == 0:
                self._queue.append((msg, task))
            else:
                self._queue.appendleft((msg, task))
            
            ctr += 1

            self._try_exec_tasks()

            try:
                return await task
            except Exception as err:
                last_err = err
        
        if last_err is not None:
            task.error(last_err)

    async def get_param(self, param: int) -> int:
        return await self._do_task(f"GS {param}", SymNetValueTask(retry_limit = 3))
    
    async def set_param(self, param: int, value: int) -> None:
        await self._do_task(f"CSQ {param} {value}", SymNetBasicTask())
    
    async def set_param_checked(self, param: int, value: int) -> None:
        await self._do_task(f"CS {param} {value}", SymNetBasicTask())

    async def change_param(self, param: int, amount: int) -> None:
        dir = 1 if amount >= 0 else 0
        amount = abs(amount)

        await self._do_task(f"CC {param} {dir} {amount}", SymNetBasicTask())
    
    async def get_param_block(self, start: int, count: int) -> dict[int, int]:
        return await self._do_task(f"GDB {start} {count}", SymNetMultiValueTask(retry_limit = 3))
    
    async def get_preset(self) -> int:
        return await self._do_task(f"GPR", SymNetValueTask(retry_limit = 3))
    
    async def load_preset(self, preset: int) -> None:
        await self._do_task(f"LP {preset}", SymNetBasicTask())
    
    async def flash(self, count: int = 8) -> None:
        await self._do_task(f"FU {count}", SymNetBasicTask(retry_limit = 3))
    
    async def set_system_string(self, unit: int, resource: int, enum: int, card: int, channel: int, value: str) -> None:
        await self._do_task(f"SSYSS {unit}.{resource}.{enum}.{card}.{channel}={value}", SymNetBasicTask())
    
    async def get_system_string(self, unit: int, resource: int, enum: int, card: int, channel: int) -> str:
        return await self._do_task(f"GSYSS {unit}.{resource}.{enum}.{card}.{channel}", SymNetStringTask(retry_limit = 3))
    
    async def get_ip(self) -> tuple[str, str]:
        return (self._host, await self._do_task(f"RI", SymNetStringTask(retry_limit = 3)))
    
    async def get_version(self) -> str:
        if self._version is None:
            self._version = await self._do_task(f"$v V", SymNetMultiStringTask(retry_limit = 3))
        
        return self._version
    
    def subscribe(self, param: int, callback: typing.Callable[[int, int], None]) -> None:
        if not param in self._subscriptions:
            self._subscriptions[param] = { callback }

            self._update_subscriptions()
        else:
            self._subscriptions[param].add(callback)
    
    def unsubscribe(self, param: int, callback: typing.Callable[[int, int], None]) -> None:
        if param in self._subscriptions:
            subs = self._subscriptions[param]

            subs.discard(callback)

            if len(subs) == 0:
                del self._subscriptions[param]

                self._update_subscriptions()
    
    def _update_subscriptions(self):
        pass
    
    def publish(self, param: int, value: int) -> None:
        if param in self._subscriptions:
            for callback in self._subscriptions[param]:
                try:
                    callback(param, value)
                except:
                    pass
    
    async def connect(self) -> None:
        #loop = asyncio.get_running_loop()

        #executor = ThreadPoolExecutor(max_workers=4)

        asyncio.ensure_future(self._symnet_loop())

        await self._connect_future
