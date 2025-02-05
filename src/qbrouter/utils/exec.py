import asyncio
import logging
from asyncio import create_subprocess_exec
from asyncio.subprocess import PIPE


async def _read_stream(stream, callback):
    while True:
        line = await stream.readline()
        if line:
            callback(line)
        else:
            break


async def execute(args: [str], logger: logging.Logger):
    process = await create_subprocess_exec(
        *args, stdout=PIPE, stderr=PIPE
    )
    await asyncio.gather(

            _read_stream(
                process.stdout,
                lambda x: logger.info(x.decode("UTF8")),
            ),
            _read_stream(
                process.stderr,
                lambda x: logger.error(x.decode("UTF8")),
            ),

    )
    await process.wait()
