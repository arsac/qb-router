import argparse
import importlib
import logging
import os
import sys
from pathlib import Path

from qbrouter.utils.parser import EnvDefault

logger = logging.getLogger('qbrouter')

logging.basicConfig(
        stream=sys.stdout,
        level=logging.DEBUG if os.environ.get('DEBUG', None) else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%I:%M:%S %p",
    )

def get_parser():
    parser = argparse.ArgumentParser(description="qb-router")

    parser.add_argument(
        "-s",
        "--src",
        action=EnvDefault,
        envvar="SRC_PATH",
        help="qBittorrent server address",
        required=True,
    )

    parser.add_argument(
        "-d",
        "--dest",
        action=EnvDefault,
        envvar="DEST_PATH",
        help="qBittorrent server address",
        required=True,
    )

    parser.add_argument(
        "-q",
        "--src-url",
        action=EnvDefault,
        envvar="QB_SRC_URL",
        help="qBittorrent source url",
        required=True,
    )

    parser.add_argument(
        "--src-username",
        action=EnvDefault,
        envvar="QB_SRC_USERNAME",
        help="qBittorrent source username",
        required=False,
    )

    parser.add_argument(
        "--src-password",
        action=EnvDefault,
        envvar="QB_SRC_PASSWORD",
        help="qBittorrent source password",
        required=False,
    )


    parser.add_argument(
        "-Q",
        "--dest-url",
        action=EnvDefault,
        envvar="QB_DEST_URL",
        help="qBittorrent destination url",
        required=True,
    )

    parser.add_argument(
        "--dest-username",
        action=EnvDefault,
        envvar="QB_DEST_USERNAME",
        help="qBittorrent source username",
        required=False,
    )

    parser.add_argument(
        "--dest-password",
        action=EnvDefault,
        envvar="QB_DEST_PASSWORD",
        help="qBittorrent dest password",
        required=False,
    )

    parser.add_argument(
        "--min-space",
        action=EnvDefault,
        envvar="MIN_SPACE",
        help="qBittorrent source minimum space",
        required=False,
    )

    parser.add_argument(
        "--min-seeding-time",
        action=EnvDefault,
        envvar="MIN_SEEDING_TIME",
        help="qBittorrent minimum seeding time",
        required=False,
    )

    parser.add_argument(
        "--sleep",
        action=EnvDefault,
        envvar="SLEEP",
        help="sleep time between iterations",
        required=False,
    )

    return parser


def get_config():
    parser = get_parser()
    config = parser.parse_args()
    config.run = True
    config.src = Path(config.src)
    config.dest = Path(config.dest)
    config.min_space = int(config.min_space or 50)
    config.min_seeding_time = int(config.min_seeding_time or 3600)
    config.dry_run = getattr(config, 'dry_run', 'false') == "true"
    config.sleep = int(config.sleep or 30)

    return config


__all__ = [
    'logger', 'get_config'
]
