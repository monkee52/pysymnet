"""Python Symetrix SymNet module."""

import asyncio
import logging
import typing

from .connection import SymNetConnection, SymNetConnectionType
from .const import DEFAULT_PORT
from .converters import (
    DecibelConverter,
    PercentConverter,
    SelectorConverter,
    SymNetConverter,
    button_converter,
    inverted_button_converter,
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

        asyncio.ensure_future(self._async_init())

    async def _async_init(self):
        await asyncio.gather(
            self._connection.subscribe(self._rcn, self._rcn_updated),
            self.get_value(),
        )

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
            callback(self, old_value, self._curr_value)

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

    def destroy(self) -> None:
        """Destroy the control.

        Removes all update subscribers and notifies the control that
        we're no longer interested in it's updates.
        """
        self._subscribers.clear()

        asyncio.ensure_future(
            self._connection.unsubscribe(self._rcn, self._rcn_updated)
        )

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

    _connection: SymNetConnection

    _controls: dict[str, DSPControl] = {}

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        mode: SymNetConnectionType = SymNetConnectionType.TCP,
    ):
        """Initialize DSP host."""
        self._host = host
        self._port = port
        self._mode = mode

        self._controls = {}

        self._connection = SymNetConnection(host, port, mode)

    def add_control(
        self, name: str, rcn: int, converter: SymNetConverter[T] | None = None
    ) -> DSPControl:
        """Add a control property for the DSP."""
        if name in self._controls:
            return self._controls[name]

        control = DSPControl(self._connection, name, rcn, converter)

        self._controls[name] = control

        return control

    def remove_control(self, nameOrControl: str | DSPControl) -> None:
        """Remove a control property for the DSP."""
        if isinstance(nameOrControl, DSPControl):
            nameOrControl = nameOrControl.name

        delattr(self, nameOrControl)

    def get_control(self, nameOrControl: str | DSPControl[T]) -> DSPControl[T]:
        """Get a DSP control."""
        if not isinstance(nameOrControl, DSPControl):
            nameOrControl = self._controls[nameOrControl]

        return nameOrControl

    def __getattr__(self, name: str) -> typing.Any:
        """Get DSP control value, or pass up the chain."""
        if name in self._controls:
            return self._controls[name].value

        if name in self.__dict__:
            return self.__dict__[name]

        raise AttributeError(name)

    def __setattr__(self, name: str, value: T) -> None:
        """Set a DSP control value, or pass up the chain."""
        if name in self._controls:
            self._controls[name].value = value
        else:
            self.__dict__[name] = value

    def __delattr__(self, name: str) -> None:
        """Delete a DSP control, or pass up the chain."""
        if name in self._controls:
            self._controls[name].destroy()

            del self._controls[name]
        else:
            del self.__dict__[name]

    async def connect(self) -> None:
        """Connect to the DSP."""
        await self._connection.connect()

    def subscribe(
        self, name: str, callback: typing.Callable[[DSPControl[T], T, T], None]
    ) -> None:
        """Subscribe to a control update."""
        self._controls[name].subscribe(callback)

    def unsubscribe(
        self, name: str, callback: typing.Callable[[DSPControl[T], T, T], None]
    ) -> None:
        """Unsubscribe to a control update."""
        self._controls[name].unsubscribe(callback)

    @property
    def connection(self) -> SymNetConnection:
        """Get the SymNet connection."""
        return self._connection
