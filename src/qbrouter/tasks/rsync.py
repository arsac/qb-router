import asyncio
import os
import time
from pathlib import Path

from qbrouter import get_task_logger
from qbrouter.utils.exec import execute
from qbrouter.utils.watcher import watch_path

# Create a task-specific logger
logger = get_task_logger("rsync")


async def run(config):
    queue = asyncio.Queue()

    if config.src == config.dest:
        logger.error("Source and destination directories are the same")
        return

    src = os.path.join(config.src, "")

    async def rsync():
        logger.info(f"Rsyncing {src} to {config.dest}")

        await execute(
            [
                "rsync",
                "--hard-links",
                "--times",
                "--whole-file",
                "--inplace",
                "--partial",
                "--verbose",
                "--progress",
                "--one-file-system",
                "--recursive",
                "--perms",
                "--group",
                "--owner",
                "--devices",
                "--specials",
                "--acls",
                "--xattrs",
                "--itemize-changes",
                src,
                config.dest,
            ],
            logger,
        )

    async def worker():
        while config.run or not queue.empty():
            batch = []
            # Accumulate events for at least 5 seconds
            start_time = time.time()
            while time.time() - start_time < 15:
                try:
                    batch.append(
                        await asyncio.wait_for(
                            queue.get(), timeout=5 - (time.time() - start_time)
                        )
                    )
                except asyncio.TimeoutError:
                    break

            if batch:
                for e in batch:
                    logger.debug(f"New file event for: {e.path}")

                if config.dry_run:
                    logger.info(f"Dry run: {len(batch)} events")
                else:
                    await rsync()
                    logger.info(f"Worker processed: {len(batch)} events")

    worker_task = asyncio.create_task(worker())

    logger.info("Initial sync...")
    await asyncio.create_task(rsync())

    logger.info("Starting rsync listener")

    async for event in watch_path(Path(config.src), logger):
        if not config.run:
            break
        queue.put_nowait(event)

    logger.info("Stopping rsync listener")
    await worker_task
