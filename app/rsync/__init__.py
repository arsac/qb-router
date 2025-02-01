import asyncio
import signal
import subprocess
import time

from asyncinotify import Inotify, Mask


class RSync:
    def __init__(self, source, destination):
        """
        Initializes the RsyncWrapper with source and destination directories.

        Args:
            source (str): The source directory to copy from.
            destination (str): The destination directory to copy to.
        """
        self.source = source
        self.destination = destination

    def run(self):
        """
        Executes the rsync command to copy files recursively from the source to the destination.
        """
        try:
            result = subprocess.run(['rsync', '--ignore-existing', '-razv', self.source, self.destination], check=True,
                                    capture_output=True,
                                    text=True)
            print(result.stdout)
        except subprocess.CalledProcessError as e:
            print(f"Error during rsync: {e.stderr}")


class RSyncListen:
    queue = asyncio.Queue()

    _run = True

    def __init__(self, source, destination):
        self.source = source
        self.destination = destination
        self.rsync = RSync(source, destination)
        signal.signal(signal.SIGINT, self.handle_signal)

    def handle_signal(self, signum, frame):
        print(f"Received signal {signum}, shutting down...")
        self._run = False

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
                    print(f"Event: {e.path}")

                self.rsync.run()
                print(f'Worker processed: {len(batch)} events')

    async def start(self):
        worker_task = asyncio.create_task(self.worker())

        with Inotify() as inotify:
            inotify.add_watch(self.source, Mask.CLOSE)

            async for event in inotify:
                if not self._run:
                    break
                self.queue.put_nowait(event)

            await worker_task
