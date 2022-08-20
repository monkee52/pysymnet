"""SymNet converters."""

import abc
import typing

from .const import DEFAULT_FADER_MAX, DEFAULT_FADER_MIN

T = typing.TypeVar("T")

NEGATIVE_INFINITY = float("-inf")


class SymNetConverter(typing.Generic[T], metaclass=abc.ABCMeta):
    """Base converter for RCN values."""

    @abc.abstractmethod
    def from_rcn(self, val: int) -> T:
        """Convert a DSP value to the T equivalent."""
        raise NotImplementedError()

    @abc.abstractmethod
    def to_rcn(self, val: T) -> int:
        """Convert a T value to the DSP equivalent."""
        raise NotImplementedError()


class DecibelConverter(SymNetConverter[float]):
    """DSP decibel fader value converter."""

    _min: float
    _max: float
    _delta: float

    def __init__(
        self, min: float = DEFAULT_FADER_MIN, max: float = DEFAULT_FADER_MAX
    ):
        """Initialize the fader value converter."""
        self._min = min
        self._max = max

        self._delta = max - min

    @property
    def min(self) -> float:
        """Get the minimum value of the fader."""
        return self._min

    @property
    def max(self) -> float:
        """Get the maximum value of the fader."""
        return self._max

    def from_rcn(self, val: int) -> float:
        """Convert a DSP value to the decibel equivalent."""
        if val == 0:
            return NEGATIVE_INFINITY

        return self.min + self._delta * float(val) / 65535.0

    def to_rcn(self, val: float) -> int:
        """Convert a decibel value to the DSP equivalent."""
        if val == NEGATIVE_INFINITY:
            return 0

        rcn_val = int((val - self.min) * 65535.0 / self._delta)

        return max(0, min(65535, rcn_val))


class PercentConverter(DecibelConverter):
    """DSP percentage converter."""

    def from_rcn(self, val: int) -> float:
        """Convert a DSP value to the percentage equivalent."""
        db = super().from_rcn(val)

        return db - self.min / self._delta * 100.0

    def to_rcn(self, val: float) -> int:
        """Convert a percentage value to the DSP equivalent."""
        db = val / 100.0 * self._delta + self.min

        return super().to_rcn(db)


class ButtonConverter(SymNetConverter[bool]):
    """DSP button converter."""

    _inverted: bool

    def __init__(self, inverted: bool = False):
        """Initialize button converter."""
        self._inverted = inverted

    @property
    def inverted(self) -> bool:
        """Get the conversion inversion."""
        return self._inverted

    def from_rcn(self, val: int) -> bool:
        """Convert a DSP value to the boolean equivalent."""
        return (val > 32767) ^ self.inverted

    def to_rcn(self, val: bool) -> int:
        """Convert a boolean value to the DSP equivalent."""
        return 65535 if (val ^ self.inverted) else 0


class SelectorConverter(SymNetConverter[int]):
    """DSP selector converter."""

    _count: int

    def __init__(self, count: int):
        """Initialize enum converter."""
        self._count = count

    @property
    def count(self):
        """Get the count of values for the selector."""
        return self._count

    def from_rcn(self, val: int) -> int:
        """Convert a DSP value to the selector number."""
        # TODO: RCN to selector number converter.
        raise NotImplementedError()

    def to_rcn(self, val: int) -> int:
        """Convert a selector value to the DSP equivalent."""
        return int(float(val) * 65535.0 / float(self.count - 1))


button_converter = ButtonConverter()
inverted_button_converter = ButtonConverter(inverted=True)

default_decibel_converter = DecibelConverter()
