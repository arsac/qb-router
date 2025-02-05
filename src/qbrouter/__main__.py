import asyncio
import signal

from qbrouter import logger, get_config
from qbrouter.tasks import get_tasks


async def main():
    config = get_config()
    loop = asyncio.get_running_loop()

    def handle_signal():
        logger.info("Received signal, shutting down...")
        config.run = False

    loop.add_signal_handler(signal.SIGINT, handle_signal)
    loop.add_signal_handler(signal.SIGTERM, handle_signal)

    logger.info("Starting qb-router in dry-run mode" if config.dry_run else "Starting qb-router")

    await asyncio.gather(*[task.run(config) for task in get_tasks()])


if __name__ == "__main__":
    asyncio.run(main())
