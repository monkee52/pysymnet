"""SymNet tasks."""

import abc
import asyncio
import typing

from .exceptions import SymNetException

T = typing.TypeVar("T")


class SymNetTask(typing.Generic[T], asyncio.Future[T], metaclass=abc.ABCMeta):
    """Base SymNet task."""

    expects_update_format: bool = False

    def __init__(self):
        """Initialize task."""
        super().__init__()

    @abc.abstractmethod
    def handle_line(self, line: str) -> None:
        """Process a line of text returned from the DSP."""
        raise NotImplementedError()


class SymNetBasicTask(SymNetTask[bool]):
    """SymNet task that returns ACK/NAK."""

    def __init__(self):
        """Initialize task."""
        super().__init__()

    def handle_line(self, line: str) -> None:
        """Process a line of text returned from the DSP."""
        if line.upper() == "ACK":
            self.set_result(True)
        else:
            self.set_exception(SymNetException(f"Unexpected value: '{line}'"))


class SymNetStringTask(SymNetTask[str]):
    """SymNet task that returns a single string."""

    def __init__(self):
        """Initialize task."""
        super().__init__()

    def handle_line(self, line: str) -> None:
        """Process a line of text returned from the DSP."""
        self.set_result(line)


class SymNetMultiStringTask(SymNetTask[typing.List[str]]):
    """SymNet task that returns multiple strings."""

    _strs: typing.List[str]

    def __init__(self):
        """Initialize task."""
        super().__init__()

        self._strs = []

    def handle_line(self, line: str) -> None:
        """Process a line of text returned from the DSP."""
        if line == ">":
            self.set_result(self._strs)
        else:
            self._strs.append(line)


class SymNetValueTask(SymNetTask[int]):
    """SymNet task that returns an integer."""

    def __init__(self):
        """Initialize task."""
        super().__init__()

    def handle_line(self, line: str) -> None:
        """Process a line of text returned from the DSP."""
        try:
            val: int = int(line)

            self.set_result(val)
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
        start_control: int = 0,
        control_count: int = 1,
    ):
        """Initialize task."""
        super().__init__()

        self.start_control = start_control
        self.control_count = control_count

        self._values = {}
        self._line_counter = 0

    def handle_line(self, line: str) -> None:
        """Process a line of text returned from the DSP."""
        try:
            val: int = int(line)
            control: int = self.start_control + self._line_counter

            self._line_counter += 1

            if val == -1:
                return

            self._values[control] = val

            if self._line_counter == self.control_count:
                self.set_result(self._values)
        except Exception as err:
            self.error(err)
