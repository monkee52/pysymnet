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


async def main():
    dsp = pysymnet.DSP("10.67.1.168")

    #await asyncio.gather(*[
    #    dsp.add_control("mute_b1t", 501, pysymnet.button_converter)
    #])

    def dsp_update(control: pysymnet.DSPControl, new_val: typing.Any) -> None:
        logging.info(f"{time()}: {control.name} = {new_val}")

    dsp.subscribe(None, dsp_update)

    print("\r\n".join(await dsp.connection.get_version()))
    print(await dsp.connection.get_ip())

    while True:
        # await dsp.refresh_all()

        await asyncio.sleep(1)

asyncio.run(main())
