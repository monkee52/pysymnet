"""SymNet connection and related."""

import asyncio
import enum
import itertools
import logging
import typing

from .const import DEFAULT_PORT
from .protocol import SymNetProtocol
from .tasks import (
    SymNetBasicTask,
    SymNetMultiStringTask,
    SymNetMultiValueTask,
    SymNetStringTask,
    SymNetTask,
    SymNetValueTask,
)

LOGGER: logging.Logger = logging.getLogger(__name__)

T = typing.TypeVar("T")


class SymNetConnectionType(enum.Enum):
    """Connection modes to the DSP."""

    TCP = "tcp"
    UDP = "udp"


class SymNetConnection:
    """DSP connection interface."""

    _host: str
    _port: int
    _mode: SymNetConnectionType

    _version: typing.List[str]

    _subscriptions: dict[int, set[typing.Callable[[int, int], None]]]

    _protocol: SymNetProtocol | None
    _next_connect_tasks: typing.List[typing.Tuple[str, SymNetTask]]

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        mode: SymNetConnectionType = SymNetConnectionType.TCP,
    ):
        """Initialize the DSP connection."""
        self._host = host
        self._port = port
        self._mode = mode

        self._subscriptions = {}

        self._version = None
        self._protocol = None
        self._next_connect_tasks = []

    async def _get_connection(self) -> SymNetProtocol:
        if self._protocol is not None:
            return self._protocol

        loop = asyncio.get_running_loop()

        on_conn_made = loop.create_future()
        on_conn_lost = loop.create_future()

        on_conn_lost.add_done_callback(self._conn_lost)

        LOGGER.debug(f"Connection type is '{self._mode}'")

        match self._mode:
            case SymNetConnectionType.TCP:
                transport, protocol = await loop.create_connection(
                    lambda: SymNetProtocol(False, on_conn_made, on_conn_lost),
                    self._host,
                    self._port,
                )
            case SymNetConnectionType.UDP:
                transport, protocol = await loop.create_datagram_endpoint(
                    lambda: SymNetProtocol(True, on_conn_made, on_conn_lost),
                    remote_addr=(self._host, self._port),
                )
            case _:
                raise NotImplementedError(
                    f"'{self._mode}' is not a valid connection type."
                )

        protocol.update_callback = self._update_callback

        LOGGER.debug("Connecting...")

        await on_conn_made

        LOGGER.debug("Connected.")
        LOGGER.debug(f"Re-queuing {len(self._next_connect_tasks)} tasks.")

        for msg, task in self._next_connect_tasks:
            protocol.queue_task(msg, task)

        self._next_connect_tasks = []

        self._protocol = protocol

        return protocol

    def _conn_lost(self, fut: asyncio.Future[Exception | None]) -> None:
        self._next_connect_tasks = self._protocol.get_queue()
        self._protocol = None

    def _update_callback(self, rcn: int, val: int) -> None:
        self.publish(rcn, val)

    async def connect(self) -> None:
        """Connect to the DSP."""
        await self._get_connection()

    async def disconnect(self) -> None:
        """Disconnect from the DSP."""
        if self._protocol is None:
            return

        await self._protocol.disconnect()

    async def _do_task(self, msg: str, task: SymNetTask[T]) -> T:
        ctr: int = 0
        last_err: Exception | None = None

        while ctr < task.retry_limit:
            LOGGER.debug(f"'{msg}' attempt {ctr + 1} of {task.retry_limit}")

            try:
                conn = await self._get_connection()

                if ctr == 0:
                    conn.queue_task(msg, task)
                else:
                    conn.queue_task_immediate(msg, task)

                return await task
            except Exception as err:
                last_err = err

            ctr += 1

        if last_err is not None:
            raise last_err

    async def get_param(self, param: int) -> int:
        """Get value for DSP parameter."""
        return await self._do_task(
            f"GS {param}", SymNetValueTask(retry_limit=3)
        )

    async def set_param(self, param: int, value: int) -> None:
        """Set DSP parameter."""
        await self._do_task(f"CSQ {param} {value}", SymNetBasicTask())

    async def set_param_checked(self, param: int, value: int) -> None:
        """Set DSP parameter and ensure it exists."""
        await self._do_task(f"CS {param} {value}", SymNetBasicTask())

    async def change_param(self, param: int, amount: int) -> None:
        """Change DSP parameter by relative value."""
        dir = 1 if amount >= 0 else 0
        amount = abs(amount)

        await self._do_task(f"CC {param} {dir} {amount}", SymNetBasicTask())

    async def get_param_block(self, start: int, count: int) -> dict[int, int]:
        """Get multiple DSP parameters."""
        return await self._do_task(
            f"GDB {start} {count}", SymNetMultiValueTask(retry_limit=3)
        )

    async def get_preset(self) -> int:
        """Get the most recently loaded preset."""
        return await self._do_task("GPR", SymNetValueTask(retry_limit=3))

    async def load_preset(self, preset: int) -> None:
        """Load a preset."""
        await self._do_task(f"LP {preset}", SymNetBasicTask())

    async def flash(self, count: int = 8) -> None:
        """Flash the lights on the DSP to identify it."""
        await self._do_task(f"FU {count}", SymNetBasicTask(retry_limit=3))

    async def set_system_string(
        self,
        unit: int,
        resource: int,
        enum: int,
        card: int,
        channel: int,
        value: str,
    ) -> None:
        """Set a system string on the DSP."""
        await self._do_task(
            f"SSYSS {unit}.{resource}.{enum}.{card}.{channel}={value}",
            SymNetBasicTask(),
        )

    async def get_system_string(
        self, unit: int, resource: int, enum: int, card: int, channel: int
    ) -> str:
        """Get a system string from the DSP."""
        return await self._do_task(
            f"GSYSS {unit}.{resource}.{enum}.{card}.{channel}",
            SymNetStringTask(retry_limit=3),
        )

    async def get_ip(self) -> tuple[str, str]:
        """Get the connect IP and the self-reported DSP IP."""
        ip = await self._do_task("RI", SymNetStringTask(retry_limit=3))

        return (self._host, ip)

    async def get_version(self) -> str:
        """Get the version information from the DSP."""
        if self._version is None:
            self._version = await self._do_task(
                "$v V", SymNetMultiStringTask(retry_limit=3)
            )
        else:
            LOGGER.debug("Using cached version information.")

        return self._version

    async def subscribe(
        self, param: int, callback: typing.Callable[[int, int], None]
    ) -> None:
        """Subscribe to value changes for a parameter."""
        if param not in self._subscriptions:
            self._subscriptions[param] = {callback}

            await self._update_subscriptions()
        else:
            self._subscriptions[param].add(callback)

    async def unsubscribe(
        self, param: int, callback: typing.Callable[[int, int], None]
    ) -> None:
        """Unsubscribe from value changes for a parameter."""
        if param in self._subscriptions:
            subs = self._subscriptions[param]

            subs.discard(callback)

            if len(subs) == 0:
                del self._subscriptions[param]

                await self._update_subscriptions(param)

    async def _update_subscriptions(
        self, deleted_param: int | None = None
    ) -> None:
        if deleted_param is not None:
            self._do_task(
                f"PUD {deleted_param}", SymNetBasicTask(retry_limit=3)
            )

        # convert to ranges - https://stackoverflow.com/a/4629241
        params = sorted(param for param in self._subscriptions)
        ranges = []

        for key, group in itertools.groupby(
            enumerate(params), lambda t: t[1] - t[0]
        ):
            group = list(group)

            ranges.append((group[0][1], group[-1][1]))

        # subscribe
        subscribe_tasks = []

        for start, end in ranges:
            range_str = None

            if start == end:
                range_str = f"{start}"
            else:
                range_str = f"{start} {end}"

            subscribe_tasks.append(
                self._do_task(
                    f"PUE {range_str}", SymNetBasicTask(retry_limit=3)
                )
            )

        await asyncio.gather(*subscribe_tasks)

    def publish(self, param: int, value: int) -> None:
        """Trigger all callbacks that a parameter has changed."""
        if param in self._subscriptions:
            for callback in self._subscriptions[param]:
                try:
                    callback(param, value)
                except Exception as err:
                    LOGGER.debug(f"{param} update callback caused {err}")
