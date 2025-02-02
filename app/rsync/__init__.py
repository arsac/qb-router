import asyncio
import signal
import subprocess
import time
from pathlib import Path
from typing import Generator, AsyncGenerator

from asyncinotify import Inotify, Mask, Event


def get_directories_recursive(path: Path) -> Generator[Path, None, None]:
    """Recursively list all directories under path, including path itself, if
    it's a directory.

    The path itself is always yielded before its children are iterated, so you
    can pre-process a path (by watching it with inotify) before you get the
    directory listing.

    Passing a non-directory won't raise an error or anything, it'll just yield
    nothing.
    """

    if path.is_dir():
        yield path
        for child in path.iterdir():
            yield from get_directories_recursive(child)


async def watch_recursive(path: Path, mask: Mask) -> AsyncGenerator[Event, None]:
    with Inotify() as inotify:
        for directory in get_directories_recursive(path):
            print(f'INIT: watching {directory}')
            inotify.add_watch(directory,
                              mask | Mask.MOVED_FROM | Mask.MOVED_TO | Mask.CREATE | Mask.DELETE_SELF | Mask.IGNORED)

        # Things that can throw this off:
        #
        # * Moving a watched directory out of the watch tree (will still
        #   generate events even when outside of directory tree)
        #
        # * Doing two changes on a directory or something before the program
        #   has a time to handle it (this will also throw off a lot of inotify
        #   code, though)
        #
        # * Moving a watched directory within a watched directory will get the
        #   wrong path.  This needs to use the cookie system to link events
        #   together and complete the move properly, which can still make some
        #   events get the wrong path if you get file events during the move or
        #   something silly like that, since MOVED_FROM and MOVED_TO aren't
        #   guaranteed to be contiguous.  That exercise is left up to the
        #   reader.
        #
        # * Trying to watch a path that doesn't exist won't automatically
        #   create it or anything of the sort.
        #
        # * Deleting and recreating or moving the watched directory won't do
        #   anything special, but it probably should.
        async for event in inotify:

            # Add subdirectories to watch if a new directory is added.  We do
            # this recursively here before processing events to make sure we
            # have complete coverage of existing and newly-created directories
            # by watching before recursing and adding, since we know
            # get_directories_recursive is depth-first and yields every
            # directory before iterating their children, we know we won't miss
            # anything.
            if Mask.CREATE in event.mask and event.path is not None and event.path.is_dir():
                for directory in get_directories_recursive(event.path):
                    print(f'EVENT: watching {directory}')
                    inotify.add_watch(directory,
                                      mask | Mask.MOVED_FROM | Mask.MOVED_TO | Mask.CREATE | Mask.DELETE_SELF | Mask.IGNORED)

            # If there is at least some overlap, assume the user wants this event.
            if event.mask & mask:
                yield event
            else:
                # Note that these events are needed for cleanup purposes.
                # We'll always get IGNORED events so the watch can be removed
                # from the inotify.  We don't need to do anything with the
                # events, but they do need to be generated for cleanup.
                # We don't need to pass IGNORED events up, because the end-user
                # doesn't have the inotify instance anyway, and IGNORED is just
                # used for management purposes.
                print(f'UNYIELDED EVENT: {event}')


class RSyncListen:
    queue = asyncio.Queue()

    _run = True

    def __init__(self, source, destination, logger):
        self.source = source
        self.destination = destination
        self.logger = logger
        signal.signal(signal.SIGINT, self.handle_signal)

    def handle_signal(self, signum, frame):
        self.logger.info(f"Received signal {signum}, shutting down rsync...")
        self._run = False

    def rsync(self):
        """
        Executes the rsync command to copy files recursively from the source to the destination.
        """
        try:
            result = subprocess.run(['rsync', '-H', '--ignore-existing', '-razv', self.source, self.destination],
                                    check=True,
                                    capture_output=True,
                                    text=True)
            self.logger.info(result.stdout)
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error during rsync: {e.stderr}")

    async def worker(self):
        while self._run or not self.queue.empty():
            batch = []

            # Accumulate events for at least 5 seconds
            start_time = time.time()
            while time.time() - start_time < 5:
                try:
                    event = await asyncio.wait_for(self.queue.get(), timeout=5 - (time.time() - start_time))
                    batch.append(event)
                except asyncio.TimeoutError:
                    break

            if batch:
                for e in batch:
                    self.logger.debug(f"Event: {e.path}")

                self.rsync()
                self.logger.info(f'Worker processed: {len(batch)} events')

    async def start(self):
        worker_task = asyncio.create_task(self.worker())

        self.logger.info('Starting rsync listener')

        async for event in watch_recursive(Path(self.source), Mask.CREATE | Mask.MOVE):
            if not self._run:
                break
            self.queue.put_nowait(event)

        await worker_task
