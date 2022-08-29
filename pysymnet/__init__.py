"""Python Symetrix SymNet module."""

import asyncio
import logging
import typing
from xml.dom.minidom import Attr

from .connection import SymNetConnection, SymNetConnectionType
from .const import DEFAULT_PORT, DEFAULT_TIMEOUT
from .converters import (
    DecibelConverter,
    PercentConverter,
    SelectorConverter,
    SymNetConverter,
    button_converter,
    gain_converter,
    gain_pc_converter,
    inverted_button_converter,
    trim_converter,
    trim_pc_converter,
)
from .exceptions import SymNetException

T = typing.TypeVar("T")
TDSPControl = typing.TypeVar("TDSPControl", bound="DSPControl")

LOGGER = logging.getLogger(__name__)


class DSPControl(typing.Generic[T]):
    """A DSP control."""

    _connection: SymNetConnection

    _converter: SymNetConverter[T]
    _name: str
    _rcn: int
    _curr_value: T | None
    _last_set_failed: bool

    _subscribers: set[typing.Callable[[TDSPControl, T, T], None]]

    _init_lock: asyncio.Lock
    _initialized: bool

    def __init__(
        self,
        connection: SymNetConnection,
        name: str,
        rcn: int,
        converter: SymNetConverter[T] | None,
    ):
        """Initialize DSP control."""
        self._connection = connection
        self._name = name
        self._rcn = rcn
        self._converter = converter

        self._subscribers = set()

        self._curr_value = None
        self._last_set_failed = False

        self._init_lock = asyncio.Lock()
        self._initialized = False

        asyncio.ensure_future(self.async_init())

    async def async_init(self):
        """Initialize subscriptions for the control."""
        async with self._init_lock:
            if self._initialized:
                return

            await asyncio.gather(
                self._connection.subscribe(self._rcn, self._rcn_updated),
                self.get_value(),
            )

            self._initialized = True

    def _from_rcn(self, val: int) -> None:
        if self._converter is not None:
            self._curr_value = self._converter.from_rcn(val)
        else:
            self._curr_value = val

    def _to_rcn(self) -> int:
        if self._converter is not None:
            return self._converter.to_rcn(self._curr_value)
        else:
            return self._curr_value

    def _rcn_updated(self, rcn: int, val: int) -> None:
        if rcn != self._rcn:
            return

        old_value = self._curr_value

        self._from_rcn(val)

        for callback in self._subscribers:
            callback(self, self._curr_value, old_value)

    def subscribe(
        self, callback: typing.Callable[[TDSPControl, T, T], None]
    ) -> None:
        """Register for update notifications."""
        self._subscribers.add(callback)

    def unsubscribe(
        self, callback: typing.Callable[[TDSPControl, T, T], None]
    ) -> None:
        """Deregister for update notifications."""
        self._subscribers.discard(callback)

    async def destroy(self) -> None:
        """Destroy the control.

        Removes all update subscribers and notifies the control that
        we're no longer interested in it's updates.
        """
        async with self._init_lock:
            if not self._initialized:
                return

            self._subscribers.clear()

            await self._connection.unsubscribe(self._rcn, self._rcn_updated)

            self._initialized = False

    async def get_value(self) -> T:
        """Get the current value."""
        val = await self._connection.get_param(self._rcn)

        self._rcn_updated(self._rcn, val)

        return self.value

    async def set_value(self, val: T, force: bool = False) -> None:
        """Set the value."""
        old_value = self._curr_value

        if not force and not self._last_set_failed and val == old_value:
            return

        self._curr_value = val

        try:
            await self._connection.set_param(self._rcn, self._to_rcn())
        except Exception as err:
            try:
                # Try to determine if the call actually succeeded.
                curr_value = await self.get_value()

                if val == curr_value:
                    self._last_set_failed = False

                    return
            except SymNetException:
                self._curr_value = old_value
                self._last_set_failed = True

                LOGGER.warning(
                    (
                        f"Failed to verify that {self.name} was set. Restoring"
                        f" previous value {old_value} for future checks."
                    )
                )

            raise err

        self._last_set_failed = False

    @property
    def value(self) -> T:
        """Get the current value."""
        return self._curr_value

    @value.setter
    def value(self, val: T) -> None:
        """Set the value."""
        asyncio.ensure_future(self.set_value(val))

    @property
    def control_number(self) -> int:
        """Get the control number."""
        return self._rcn

    @property
    def name(self) -> str:
        """Get the name of the control."""
        return self._name


class DSP:
    """A SymNet compatible DSP."""

    _host: str
    _port: int
    _mode: SymNetConnectionType
    _timeout: int

    _connection: SymNetConnection

    _controls: dict[str, DSPControl]
    _subscriptions: set[DSPControl]

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        mode: SymNetConnectionType = SymNetConnectionType.TCP,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        """Initialize DSP host."""
        self._host = host
        self._port = port
        self._mode = mode
        self._timeout = timeout

        self._controls = {}
        self._subscriptions = set()

        self._connection = SymNetConnection(host, port, mode, timeout)

    async def add_control(
        self, name: str, rcn: int, converter: SymNetConverter[T] | None = None
    ) -> DSPControl:
        """Add a control property for the DSP."""
        if name in self._controls:
            return self._controls[name]

        control = DSPControl(self._connection, name, rcn, converter)

        await control.async_init()

        self._controls[name] = control

        control.subscribe(self._control_updated)

        return control

    async def remove_control(self, nameOrControl: str | DSPControl) -> None:
        """Remove a control property for the DSP."""
        # Ensure it's a control
        nameOrControl = self.get_control(nameOrControl)

        nameOrControl.unsubscribe(self._control_updated)

        await nameOrControl.destroy()

        # Change back to name
        nameOrControl = nameOrControl.name

        delattr(self, nameOrControl)

    def get_control(self, nameOrControl: str | DSPControl[T]) -> DSPControl[T]:
        """Get a DSP control."""
        if not isinstance(nameOrControl, DSPControl):
            nameOrControl = self._controls[nameOrControl]

        return nameOrControl

    def __getattr__(self, name: str) -> typing.Any:
        """Get DSP control value, or pass up the chain."""
        if "_controls" in self.__dict__ and name in self.__dict__["_controls"]:
            return self.__dict__["_controls"]

    def __setattr__(self, name: str, value: T) -> None:
        """Set a DSP control value, or pass up the chain."""
        if name == "_controls":
            self.__dict__[name] = value

            return

        if "_controls" in self.__dict__ and name in self.__dict__["_controls"]:
            self._controls[name].value = value
        else:
            self.__dict__[name] = value

    def __delattr__(self, name: str) -> None:
        """Delete a DSP control, or pass up the chain."""
        if name in self._controls:
            asyncio.ensure_future(self._controls[name].destroy())

            del self._controls[name]
        else:
            del self.__dict__[name]

    async def refresh_all(self) -> None:
        """Refresh all DSP controls."""
        await asyncio.gather(
            *[
                self._controls[control].get_value()
                for control in self._controls
            ]
        )

    async def connect(self) -> None:
        """Connect to the DSP."""
        await self._connection.connect()

    def _control_updated(
        self, control: DSPControl[T], val: T, old_val: T
    ) -> None:
        for callback in self._subscriptions:
            callback(control, val)

    def subscribe(
        self,
        name: str | None,
        callback: typing.Callable[[DSPControl[T], T, T], None],
    ) -> None:
        """Subscribe to a control update."""
        if name is None:
            self._subscriptions.add(callback)

            return

        self._controls[name].subscribe(callback)

    def unsubscribe(
        self,
        name: str | None,
        callback: typing.Callable[[DSPControl[T], T, T], None],
    ) -> None:
        """Unsubscribe to a control update."""
        if name is None:
            self._subscriptions.discard(callback)

            return

        self._controls[name].unsubscribe(callback)

    @property
    def connection(self) -> SymNetConnection:
        """Get the SymNet connection."""
        return self._connection
