import asyncio
import os
import tempfile

from qb import QB, QBManager
# from rsync import RSyncListen

SRC_PATH = os.environ.get('SRC_PATH')
DEST_PATH = os.environ.get('DEST_PATH')

if not SRC_PATH or not DEST_PATH:
    raise ValueError("SRC_PATH and DEST_PATH environment variables must be set")

QB_SRC_URL = os.environ.get('QB_SRC_URL', None)
QB_DEST_URL = os.environ.get('QB_DEST_URL', None)

if not QB_SRC_URL or not QB_DEST_URL:
    raise ValueError("QB_SRC_URL and QB_DEST_URL environment variables must be set")

print(f"SRC_PATH: {SRC_PATH}")
print(f"DEST_PATH: {DEST_PATH}")
print(f"QB_SRC_URL: {QB_SRC_URL}")
print(f"QB_DEST_URL: {QB_DEST_URL}")

async def main():
    # listener = RSyncListen(SRC_PATH, DEST_PATH)
    qb_manager = QBManager(QB_SRC_URL, '', '', QB_DEST_URL, '', '', DEST_PATH)

    await asyncio.gather(
        # listener.start(),
        qb_manager.start()
    )


if __name__ == "__main__":
    asyncio.run(main())
