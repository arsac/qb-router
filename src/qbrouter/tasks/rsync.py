import asyncio
import os
import tempfile
import time
from pathlib import Path

from qbrouter import get_task_logger
from qbrouter.utils.exec import execute
from qbrouter.utils.watcher import watch_path

# Create a task-specific logger
logger = get_task_logger("rsync")


async def run(config):
    queue = asyncio.Queue()
    initial_sync_done = asyncio.Event()

    if config.src == config.dest:
        logger.error("Source and destination directories are the same")
        return

    src = os.path.join(config.src, "")

    async def rsync(reason="sync", files=None):
        logger.info(f"Rsyncing {src} to {config.dest} ({reason})")

        cmd = [
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
        ]

        if files:
            # Create temporary file with list of files to sync
            with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
                for file_path in files:
                    # Check if file still exists before adding to sync list
                    if os.path.exists(file_path):
                        # Make path relative to source directory
                        rel_path = os.path.relpath(file_path, config.src)
                        f.write(f"{rel_path}\n")
                    else:
                        logger.debug(f"Skipping missing file: {file_path}")
                files_from = f.name

            cmd.extend(["--files-from", files_from])
            cmd.extend([src, config.dest])

            try:
                await execute(cmd, logger)
            except Exception:
                # Re-raise the exception after cleanup
                raise
            finally:
                # Ensure cleanup happens regardless of success/failure
                try:
                    os.unlink(files_from)
                except FileNotFoundError:
                    # File already deleted, ignore
                    pass
                except OSError as e:
                    logger.warning(
                        f"Failed to cleanup temporary file {files_from}: {e}"
                    )
        else:
            cmd.extend([src, config.dest])
            await execute(cmd, logger)

    async def initial_sync():
        """Perform initial sync"""
        logger.info("Starting initial sync...")
        if config.dry_run:
            logger.info("Dry run: initial sync")
        else:
            await rsync("initial sync")
            logger.info("Initial sync completed")
        initial_sync_done.set()

    async def process_events():
        """Process file system events in batches"""
        # Wait for initial sync to complete before processing events
        await initial_sync_done.wait()

        while config.run or not queue.empty():
            batch = []
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
                # Extract unique file paths from events
                changed_files = list(set(str(event.path) for event in batch))

                for event in batch:
                    logger.debug(f"New file event for: {event.path}")

                if config.dry_run:
                    logger.info(
                        f"Dry run: {len(batch)} events for files: {changed_files}"
                    )
                else:
                    await rsync("file changes", files=changed_files)
                    logger.info(f"Processed {len(batch)} file events")

    async def watch_and_queue():
        """Watch for file changes and queue them"""
        async for event in watch_path(Path(config.src), logger):
            if not config.run:
                break
            queue.put_nowait(event)

    logger.info("Starting rsync listener")

    # Run all tasks concurrently
    await asyncio.gather(
        initial_sync(), process_events(), watch_and_queue(), return_exceptions=True
    )

    logger.info("Stopping rsync listener")
