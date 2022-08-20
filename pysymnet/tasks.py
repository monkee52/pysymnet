"""SymNet tasks."""

import abc
import asyncio
import typing

from .exceptions import SymNetException

T = typing.TypeVar("T")


class SymNetTask(typing.Generic[T], metaclass=abc.ABCMeta):
    """Base SymNet task."""

    expects_update_format: bool = False
    retry_limit: int = 0

    _future: asyncio.Future[T]

    def __init__(self, retry_limit: int = 0):
        """Initialize task."""
        loop = asyncio.get_running_loop()

        self._future = loop.create_future()

        self._retry_limit = retry_limit

    def __await__(self) -> typing.Generator[typing.Any, None, T]:
        """Allow task to be awaited."""
        return self._future.__await__()

    @abc.abstractmethod
    async def handle_line(self, line: str) -> None:
        """Process a line of text returned from the DSP."""
        raise NotImplementedError()

    def error(self, err: Exception) -> None:
        """Raise an exception."""
        self._future.set_exception(err)


class SymNetBasicTask(SymNetTask[None]):
    """SymNet task that returns ACK/NAK."""

    def __init__(self, retry_limit: int = 0):
        """Initialize task."""
        super().__init__(retry_limit)

    async def handle_line(self, line: str) -> None:
        """Process a line of text returned from the DSP."""
        if line == "ACK":
            self._future.set_result()
        else:
            self.error(SymNetException(f"Unexpected value: '{line}'"))


class SymNetStringTask(SymNetTask[str]):
    """SymNet task that returns a single string."""

    def __init__(self, retry_limit: int = 0):
        """Initialize task."""
        super().__init__(retry_limit)

    async def handle_line(self, line: str) -> None:
        """Process a line of text returned from the DSP."""
        self._future.set_result(line)


class SymNetMultiStringTask(SymNetTask[typing.List[str]]):
    """SymNet task that returns multiple strings."""

    _strs: typing.List[str]

    def __init__(self, retry_limit: int = 0):
        """Initialize task."""
        super().__init__(retry_limit)

        self._strs = []

    async def handle_line(self, line: str) -> None:
        """Process a line of text returned from the DSP."""
        if line == ">":
            self._future.set_result(self._strs)
        else:
            self._strs.append(line)


class SymNetValueTask(SymNetTask[int]):
    """SymNet task that returns an integer."""

    def __init__(self, retry_limit: int = 0):
        """Initialize task."""
        super().__init__(retry_limit)

    async def handle_line(self, line: str) -> None:
        """Process a line of text returned from the DSP."""
        try:
            val: int = int(line)

            self._future.set_result(val)
        except Exception as err:
            self.error(err)


class SymNetMultiValueTask(SymNetTask[dict[int, int]]):
    """SymNet task that returns multiple integers."""

    start_control: int
    control_count: int

    _values: dict[int, int]
    _line_counter: int

    def __init__(
        self,
        retry_limit: int = 0,
        start_control: int = 0,
        control_count: int = 1,
    ):
        """Initialize task."""
        super().__init__(retry_limit)

        self.start_control = start_control
        self.control_count = control_count

        self._values = {}
        self._line_counter = 0

    async def handle_line(self, line: str) -> None:
        """Process a line of text returned from the DSP."""
        try:
            val: int = int(line)
            control: int = self.start_control + self._line_counter

            self._line_counter += 1

            if val == -1:
                return

            self._values[control] = val

            if self._line_counter == self.control_count:
                self._future.set_result(self._values)
        except Exception as err:
            self.error(err)
