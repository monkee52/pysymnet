import abc
import asyncio
import typing

from . import SymNetException

T = typing.TypeVar("T")

class SymNetTask(typing.Generic[T], metaclass = abc.ABCMeta):
    expects_update_format: bool = False
    retry_limit: int = 0

    _future: asyncio.Future[T]

    def __init__(self, retry_limit: int = 0):
        loop = asyncio.get_running_loop()

        self._future = loop.create_future()

        self._retry_limit = retry_limit

    def __await__(self) -> typing.Generator[typing.Any, None, T]:
        return self._future.__await__()

    @abc.abstractmethod
    async def handle_line(self, line: str) -> None:
        raise NotImplementedError()

    def error(self, err: Exception) -> None:
        self._future.set_exception(err)

class SymNetBasicTask(SymNetTask[None]):
    def __init__(self, retry_limit: int = 0):
        super().__init__(retry_limit)
    
    async def handle_line(self, line: str) -> None:
        if line == "ACK":
            self._future.set_result()
        else:
            self.error(SymNetException(f"Unexpected value: '{line}'"))

class SymNetStringTask(SymNetTask[str]):
    def __init__(self, retry_limit: int = 0) :
        super().__init__(retry_limit)
    
    async def handle_line(self, line: str) -> None:
        self._future.set_result(line)

class SymNetMultiStringTask(SymNetTask[typing.List[str]]):
    _strs: typing.List[str]

    def __init__(self, retry_limit: int = 0):
        super().__init__(retry_limit)

        self._strs = []
    
    async def handle_line(self, line: str) -> None:
        if line == ">":
            self._future.set_result(self._strs)
        else:
            self._strs.append(line)

class SymNetValueTask(SymNetTask[int]):
    def __init__(self, retry_limit: int = 0):
        super().__init__(retry_limit)
    
    async def handle_line(self, line: str) -> None:
        try:
            val: int = int(line)

            self._future.set_result(val)
        except Exception as err:
            self.error(err)

class SymNetMultiValueTask(SymNetTask[dict[int, int]]):
    start_control: int
    control_count: int

    _values: dict[int, int]
    _line_counter: int

    def __init__(self, retry_limit: int = 0, start_control: int = 0, control_count: int = 1):
        super().__init__(retry_limit)

        self.start_control = start_control
        self.control_count = control_count

        self._values = {}
        self._line_counter = 0
    
    async def handle_line(self, line: str) -> None:
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

