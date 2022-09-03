import asyncio
import inspect
import logging
from math import inf
import os
import sys
from time import time
import typing

logging.basicConfig(datefmt = "%H:%M:%S", format = "%(asctime)s.%(msecs)03d [%(threadName)s][%(name)s] %(msg)s", level = logging.DEBUG)

curr_dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parent_dir = os.path.dirname(curr_dir)

sys.path.insert(0, parent_dir)

import pysymnet
from pysymnet.connection import SymNetConnectionType


def counter(start: int = 0, step: int = 1, stop: int | None = None) -> typing.Generator[int, None, None]:
    i = start

    while stop is None or i < stop:
        yield i

        i += step

async def main():
    dsp = pysymnet.DSP("localhost", mode = SymNetConnectionType.UDP, timeout = 1)

    rcn = counter(101)

    await asyncio.gather(*[
        dsp.add_control("mic_1_muted", next(rcn), pysymnet.button_converter),
        dsp.add_control("mic_1_level", next(rcn), pysymnet.gain_pc_converter),
        dsp.add_control("mic_1_patch", 103),

        dsp.add_control("mic_2_muted", next(rcn), pysymnet.button_converter),
        dsp.add_control("mic_2_level", next(rcn), pysymnet.gain_pc_converter),
        dsp.add_control("mic_2_patch", next(rcn)),

        dsp.add_control("zone_1_announce_muted", next(rcn), pysymnet.button_converter),
        dsp.add_control("zone_2_announce_muted", next(rcn), pysymnet.button_converter),
        dsp.add_control("zone_3_announce_muted", next(rcn), pysymnet.button_converter),
        dsp.add_control("zone_4_announce_muted", next(rcn), pysymnet.button_converter),
        dsp.add_control("zone_5_announce_muted", next(rcn), pysymnet.button_converter),
        dsp.add_control("zone_6_announce_muted", next(rcn), pysymnet.button_converter),

        dsp.add_control("z1_bgm_muted", next(rcn), pysymnet.button_converter),
        dsp.add_control("z1_bgm_level", next(rcn), pysymnet.gain_pc_converter),
        dsp.add_control("z1_bgm_source", next(rcn)),

        dsp.add_control("z2_bgm_muted", next(rcn), pysymnet.button_converter),
        dsp.add_control("z2_bgm_level", next(rcn), pysymnet.gain_pc_converter),
        dsp.add_control("z2_bgm_source", next(rcn)),

        dsp.add_control("z3_bgm_muted", next(rcn), pysymnet.button_converter),
        dsp.add_control("z3_bgm_level", next(rcn), pysymnet.gain_pc_converter),
        dsp.add_control("z3_bgm_source", next(rcn)),

        dsp.add_control("z4_bgm_muted", next(rcn), pysymnet.button_converter),
        dsp.add_control("z4_bgm_level", next(rcn), pysymnet.gain_pc_converter),
        dsp.add_control("z4_bgm_source", next(rcn)),

        dsp.add_control("z5_bgm_muted", next(rcn), pysymnet.button_converter),
        dsp.add_control("z5_bgm_level", next(rcn), pysymnet.gain_pc_converter),
        dsp.add_control("z5_bgm_source", next(rcn)),

        dsp.add_control("z6_bgm_muted", next(rcn), pysymnet.button_converter),
        dsp.add_control("z6_bgm_level", next(rcn), pysymnet.gain_pc_converter),
        dsp.add_control("z6_bgm_source", next(rcn)),

        dsp.add_control("z12_combine", next(rcn), pysymnet.button_converter),
        dsp.add_control("z23_combine", next(rcn), pysymnet.button_converter),
        dsp.add_control("z34_combine", next(rcn), pysymnet.button_converter),
        dsp.add_control("z45_combine", next(rcn), pysymnet.button_converter),
        dsp.add_control("z56_combine", next(rcn), pysymnet.button_converter),
    ])

    def dsp_update(control: pysymnet.DSPControl, new_val: typing.Any) -> None:
        logging.info(f"{time()}: {control.name} = {new_val}")

    dsp.subscribe(None, dsp_update)

    while True:
        # await dsp.refresh_all()

        await asyncio.sleep(1)

asyncio.run(main())
