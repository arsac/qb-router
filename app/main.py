import asyncio
import logging
import os
import sys

from qb import QBManager
from rsync import RSyncListen

logger = logging.getLogger(__name__)

SRC_PATH = os.environ.get('SRC_PATH')
DEST_PATH = os.environ.get('DEST_PATH')

if not SRC_PATH or not DEST_PATH:
    raise ValueError("SRC_PATH and DEST_PATH environment variables must be set")

QB_SRC_URL = os.environ.get('QB_SRC_URL', None)
QB_DEST_URL = os.environ.get('QB_DEST_URL', None)

if not QB_SRC_URL or not QB_DEST_URL:
    raise ValueError("QB_SRC_URL and QB_DEST_URL environment variables must be set")

async def main():
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.DEBUG if os.environ.get('DEBUG', None) else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%I:%M:%S %p",
    )

    logging.info(f"SRC_PATH: {SRC_PATH}")
    logging.info(f"DEST_PATH: {DEST_PATH}")
    logging.info(f"QB_SRC_URL: {QB_SRC_URL}")
    logging.info(f"QB_DEST_URL: {QB_DEST_URL}")

    listener = RSyncListen(SRC_PATH, DEST_PATH, logger)
    qb_manager = QBManager(QB_SRC_URL, '', '', QB_DEST_URL, '', '', DEST_PATH, logger)

    await asyncio.gather(
        listener.start(),
        qb_manager.start()
    )

if __name__ == "__main__":
    asyncio.run(main())
