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


class PercentConverter(SymNetConverter[float]):
    """DSP percentage converter."""

    def from_rcn(self, val: int) -> float:
        """Convert a DSP value to the percentage equivalent."""
        return val / 65535.0 * 100.0

    def to_rcn(self, val: float) -> int:
        """Convert a percentage value to the DSP equivalent."""
        return val * 65535.0 / 100.0


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

    _valid_counts: list[int] = [2, 4, 6, 8, 12, 16]
    _options: list[str]
    _count: int
    _real_count: int

    def __init__(self, options: list[str], count: int | None = None):
        """Initialize enum converter."""
        self._count = len(options)
        self._options = options.copy()

        if count is None:
            ctr = 0

            while self._count > self._valid_counts[ctr] and ctr < len(
                self._valid_counts
            ):
                ctr += 1

            self._real_count = self._valid_counts[ctr]
        elif count in self._valid_counts:
            self._real_count = count
        else:
            raise ValueError(
                f"{count} is not a valid selector. Valid selectors:"
                " 2, 4, 6, 8, 12, 16"
            )

    @property
    def count(self):
        """Get the count of values for the selector."""
        return self._count

    @property
    def selector_count(self):
        """Get the underlying selector count."""
        return self._real_count

    def from_rcn(self, val: int) -> int:
        """Convert a DSP value to the selector number."""
        # TODO: RCN to selector number converter.
        return int(val * (self._real_count - 1) / 65535.0)

    def to_rcn(self, val: int) -> int:
        """Convert a selector value to the DSP equivalent."""
        return int(float(val) * 65535.0 / float(self._real_count - 1))


button_converter = ButtonConverter()
inverted_button_converter = ButtonConverter(inverted=True)

gain_converter = DecibelConverter()
trim_converter = DecibelConverter(-24.0, +24.0)
percent_converter = PercentConverter()
