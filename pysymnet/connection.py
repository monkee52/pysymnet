"""SymNet connection and related."""

import asyncio
import collections.abc
import enum
import itertools
import logging
import typing

from pysymnet.exceptions import SymNetException

from .const import DEFAULT_PORT, DEFAULT_TIMEOUT
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


def check_rcn(param: int):
    """Raise an exception if the RCN is not valid."""
    if param < 1 or param > 10_000:
        raise SymNetException("RCN must be between 0 and 10,000.")


class SymNetConnection:
    """DSP connection interface."""

    _host: str
    _port: int
    _mode: SymNetConnectionType
    _timeout: int

    _version: typing.List[str]

    _subscriptions: dict[int, set[typing.Callable[[int, int], None]]]

    _protocol_lock: asyncio.Lock
    _protocol: SymNetProtocol | None
    _next_connect_tasks: typing.List[typing.Tuple[str, SymNetTask]]

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        mode: SymNetConnectionType = SymNetConnectionType.TCP,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        """Initialize the DSP connection."""
        self._host = host
        self._port = port
        self._mode = mode
        self._timeout = timeout

        self._subscriptions = {}

        self._version = None
        self._protocol_lock = asyncio.Lock()
        self._protocol = None
        self._next_connect_tasks = []

    async def _get_connection(self) -> SymNetProtocol:
        async with self._protocol_lock:
            if self._protocol is not None:
                return self._protocol

            loop = asyncio.get_running_loop()

            on_conn_made = loop.create_future()
            on_conn_lost = loop.create_future()

            on_conn_lost.add_done_callback(self._conn_lost)

            LOGGER.debug(f"Connection type is '{self._mode}'")

            match self._mode:
                case SymNetConnectionType.TCP:
                    connect_task = loop.create_connection(
                        lambda: SymNetProtocol(
                            False, on_conn_made, on_conn_lost
                        ),
                        host=self._host,
                        port=self._port,
                    )

                    _, protocol = await asyncio.wait_for(
                        connect_task, self._timeout
                    )
                case SymNetConnectionType.UDP:
                    _, protocol = await loop.create_datagram_endpoint(
                        lambda: SymNetProtocol(
                            True, on_conn_made, on_conn_lost
                        ),
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
        if self._protocol is not None:
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

    async def _do_task(
        self,
        msg: str,
        task_factory: typing.Callable[[], SymNetTask[T]],
        retry_limit: int = 1,
    ) -> T:
        ctr: int = 0
        last_err: Exception | None = None

        while ctr < retry_limit:
            LOGGER.debug(f"'{msg}' attempt {ctr + 1} of {retry_limit}")

            task = task_factory()

            try:
                conn = await self._get_connection()

                if ctr == 0:
                    conn.queue_task(msg, task)
                else:
                    conn.queue_task_immediate(msg, task)

                return await asyncio.wait_for(task, self._timeout)
            except asyncio.CancelledError:
                # The task was cancelled, because it timed out.
                last_err = TimeoutError()
            except Exception as err:
                last_err = err

            ctr += 1

        if last_err is not None:
            raise last_err

    async def get_param(self, param: int) -> int:
        """Get value for DSP parameter."""
        return await self._do_task(
            f"GS {param}", lambda: SymNetValueTask(), retry_limit=3
        )

    async def set_param(self, param: int, value: int) -> None:
        """Set DSP parameter."""
        await self._do_task(f"CSQ {param} {value}", lambda: SymNetBasicTask())

    async def set_param_checked(self, param: int, value: int) -> None:
        """Set DSP parameter and ensure it exists."""
        await self._do_task(f"CS {param} {value}", lambda: SymNetBasicTask())

    async def change_param(self, param: int, amount: int) -> None:
        """Change DSP parameter by relative value."""
        dir = 1 if amount >= 0 else 0
        amount = abs(amount)

        await self._do_task(
            f"CC {param} {dir} {amount}", lambda: SymNetBasicTask()
        )

    async def get_param_block(self, start: int, count: int) -> dict[int, int]:
        """Get multiple DSP parameters."""
        return await self._do_task(
            f"GDB {start} {count}",
            lambda: SymNetMultiValueTask(),
            retry_limit=3,
        )

    async def get_preset(self) -> int:
        """Get the most recently loaded preset."""
        return await self._do_task(
            "GPR", lambda: SymNetValueTask(), retry_limit=3
        )

    async def load_preset(self, preset: int) -> None:
        """Load a preset."""
        await self._do_task(f"LP {preset}", lambda: SymNetBasicTask())

    async def flash(self, count: int = 8) -> None:
        """Flash the lights on the DSP to identify it."""
        await self._do_task(
            f"FU {count}", lambda: SymNetBasicTask(), retry_limit=3
        )

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
            lambda: SymNetBasicTask(),
        )

    async def get_system_string(
        self, unit: int, resource: int, enum: int, card: int, channel: int
    ) -> str:
        """Get a system string from the DSP."""
        return await self._do_task(
            f"GSYSS {unit}.{resource}.{enum}.{card}.{channel}",
            lambda: SymNetStringTask(),
            retry_limit=3,
        )

    async def get_ip(self) -> tuple[str, str]:
        """Get the connect IP and the self-reported DSP IP."""
        ip = await self._do_task(
            "RI", lambda: SymNetStringTask(), retry_limit=3
        )

        return (self._host, ip)

    async def get_version(self) -> str:
        """Get the version information from the DSP."""
        if self._version is None:
            self._version = await self._do_task(
                "$v V", lambda: SymNetMultiStringTask(), retry_limit=3
            )
        else:
            LOGGER.debug("Using cached version information.")

        return self._version

    async def reboot(self) -> None:
        """Reboot the DSP."""
        await self._do_task("R!", lambda: SymNetBasicTask())

    async def ping(self) -> None:
        """Ping the DSP."""
        await self._do_task("NOP", lambda: SymNetBasicTask())

    async def subscribe(
        self,
        params: int | collections.abc.Iterable[int] | None,
        callback: typing.Callable[[int, int], None],
    ) -> None:
        """Subscribe to value changes for a parameter."""
        try:
            params = iter(params)
        except TypeError:
            params = [params]

        for param in params:
            check_rcn(param)

            if param is None:
                param = -1

            if param not in self._subscriptions:
                self._subscriptions[param] = {callback}
            else:
                self._subscriptions[param].add(callback)

        await self._update_subscriptions()

    async def unsubscribe(
        self,
        params: int | collections.abc.Iterable[int] | None,
        callback: typing.Callable[[int, int], None],
    ) -> None:
        """Unsubscribe from value changes for a parameter."""
        try:
            params = iter(params)
        except TypeError:
            params = [params]

        remove_subs = []

        for param in params:
            check_rcn(param)

            if param is None:
                param = -1

            if param in self._subscriptions:
                subs = self._subscriptions[param]

                subs.discard(callback)

                if len(subs) == 0:
                    del self._subscriptions[param]

                    remove_subs.append(param)

        await self._update_subscriptions(remove_subs)

    async def _update_subscriptions(
        self, deleted_params: int | collections.abc.Iterable[int] | None = None
    ) -> None:
        subscribe_tasks = []

        if deleted_params is not None:
            try:
                deleted_params = iter(deleted_params)
            except TypeError:
                deleted_params = [deleted_params]

            for deleted_param in deleted_params:
                subscribe_tasks.append(
                    self._do_task(
                        f"PUD {deleted_param}",
                        lambda: SymNetBasicTask(),
                        retry_limit=3,
                    )
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
        for start, end in ranges:
            range_str = None

            if start == end:
                range_str = f"{start}"
            else:
                range_str = f"{start} {end}"

            subscribe_tasks.append(
                self._do_task(
                    f"PUE {range_str}",
                    lambda: SymNetBasicTask(),
                    retry_limit=3,
                )
            )

        await asyncio.gather(*subscribe_tasks)

    def _get_subscribers(
        self, param: int
    ) -> typing.Generator[typing.Callable[[int, int], None], None, None]:
        if -1 in self._subscriptions:
            for callback in self._subscriptions[-1]:
                yield callback

        for callback in self._subscriptions[param]:
            yield callback

    def publish(self, param: int, value: int) -> None:
        """Trigger all callbacks that a parameter has changed."""
        if param in self._subscriptions:
            for callback in self._get_subscribers(param):
                try:
                    callback(param, value)
                except Exception as err:
                    LOGGER.debug(f"{param} update callback caused {err}")
