import asyncio
import signal
import subprocess
import time

from asyncinotify import Inotify, Mask


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
            result = subprocess.run(['rsync', '--ignore-existing', '-razv', self.source, self.destination], check=True,
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

        with Inotify() as inotify:
            inotify.add_watch(self.source, Mask.CLOSE)

            async for event in inotify:
                if not self._run:
                    break
                self.queue.put_nowait(event)

            await worker_task
