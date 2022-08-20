"""Python Symetrix SymNet module."""

import asyncio
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

T = typing.TypeVar("T")
TDSPControl = typing.TypeVar("TDSPControl", bound="DSPControl")


class DSPControl(typing.Generic[T]):
    """A DSP control."""

    _connection: SymNetConnection

    _converter: SymNetConverter[T]
    _name: str
    _rcn: int
    _curr_value: T

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

        asyncio.ensure_future(
            self._connection.subscribe(rcn, self._rcn_updated)
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

    @property
    def value(self) -> T:
        """Get the current value."""
        return self._curr_value

    @value.setter
    def value(self, val: T) -> None:
        """Set the value."""
        old_value = self._curr_value

        self._curr_value = val

        try:
            self._connection.set_param(self._to_rcn())
        except Exception as err:
            # Restore value as the DSP didn't acknowledge the change.
            self._curr_value = old_value

            raise err

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

    _controls: dict[str, DSPControl]

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

        self._connection = SymNetConnection(host, port, mode)

    def add_control(
        self, name: str, rcn: int, converter: SymNetConverter[T] | None = None
    ) -> DSPControl:
        """Add a control property for the DSP."""
        if name in self._controls:
            return self._controls[name]

        control = DSPControl(self._connection, name, rcn, converter)

        self._controls[name] = control

        def get_ctrl(self) -> T:
            return control.value

        def set_ctrl(self, val: T) -> None:
            control.value = val

        def del_ctrl(self) -> None:
            control.destroy()

            del self._controls[name]

            delattr(self, name)

        setattr(self, name, property(get_ctrl, set_ctrl, del_ctrl))

    def remove_control(self, nameOrControl: str | DSPControl) -> None:
        """Remove a control property for the DSP."""
        if isinstance(nameOrControl, DSPControl):
            nameOrControl = nameOrControl.name

        delattr(self, nameOrControl)

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
