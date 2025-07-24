import asyncio
from asyncio import Event as AsyncioEvent
from logging import Logger
from pathlib import Path
from typing import Generator, AsyncGenerator, TYPE_CHECKING
from unittest.mock import Mock

try:
    from asyncinotify import Mask, Event, Inotify
except AttributeError as e:
    print(f"Error importing asyncinotify: {e}")
    Mask = Mock()
    Event = Mock()
    Inotify = Mock()

    # Ensure the Mask mock responds to types CREATE and MOVE
    Mask.CREATE = 1
    Mask.MOVE = 2
    Mask.MOVED_FROM = 3
    Mask.MOVED_TO = 4
    Mask.DELETE_SELF = 5
    Mask.IGNORED = 6

    # Ensure the Mask mock supports bitwise operations
    Mask.__or__ = lambda self, other: self
    Mask.__and__ = lambda self, other: self
    Mask.__contains__ = lambda self, item: item in [
        Mask.CREATE,
        Mask.MOVE,
        Mask.MOVED_FROM,
        Mask.MOVED_TO,
        Mask.DELETE_SELF,
        Mask.IGNORED,
    ]
    Mask.__eq__ = lambda self, other: str(self) == str(other)
    Mask.__str__ = lambda self: "Mask"

    # Define an async generator method for Inotify mock
    async def mock_inotify_iter():
        while True:
            await asyncio.sleep(10)
            yield Event()

    Inotify.__aiter__ = lambda self: mock_inotify_iter()
    Inotify.__enter__ = lambda self: self
    Inotify.__exit__ = lambda self, exc_type, exc_val, exc_tb: None

    def add_watch(path, mask):
        Event.path = path
        return None

    Inotify.add_watch = add_watch
    Inotify.return_value = Inotify

    # Define an async generator method for Event mock
    async def mock_event_iter():
        while True:
            await asyncio.sleep(1)
            yield Event()

    Event.__aiter__ = lambda self: mock_event_iter()
    Event.mask = Mask
    Event.path = Path("./tmp")
    Event.return_value = Event


def get_directories_recursive(path: Path) -> Generator[Path, None, None]:
    if path.is_dir():
        yield path
        for child in path.iterdir():
            yield from get_directories_recursive(child)


async def watch_path(path: Path, logger: Logger) -> AsyncGenerator[Event, None]:
    mask = Mask.CREATE | Mask.MOVE
    with Inotify() as inotify:
        for directory in get_directories_recursive(path):
            logger.debug(f"init watching {directory}")
            inotify.add_watch(
                directory,
                mask
                | Mask.MOVED_FROM
                | Mask.MOVED_TO
                | Mask.CREATE
                | Mask.DELETE_SELF
                | Mask.IGNORED,
            )

        async for event in inotify:

            # Add subdirectories to watch if a new directory is added.  We do
            # this recursively here before processing events to make sure we
            # have complete coverage of existing and newly-created directories
            # by watching before recursing and adding, since we know
            # get_directories_recursive is depth-first and yields every
            # directory before iterating their children, we know we won't miss
            # anything.
            if (
                Mask.CREATE in event.mask
                and event.path is not None
                and event.path.is_dir()
            ):
                for directory in get_directories_recursive(event.path):
                    logger.debug(f"add watching {directory}")
                    inotify.add_watch(
                        directory,
                        mask
                        | Mask.MOVED_FROM
                        | Mask.MOVED_TO
                        | Mask.CREATE
                        | Mask.DELETE_SELF
                        | Mask.IGNORED,
                    )

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
                logger.debug(f"unyielded event: {event}")
                # inotify.rm_watch(event.watch)
