import asyncio
import logging
import os
from pathlib import Path

from qbittorrentapi import TorrentInfoList, Client, TorrentFilesList, TorrentFile, TorrentDictionary

from qbrouter import logger
from qbrouter.utils.wait import until
from qbrouter.utils.file import are_hardlinked

SYNCED_TAG = 'synced'


def has_synced_tag(torrent):
    logger.debug(f"Torrent {torrent.name} tags: {torrent['tags']}")
    return SYNCED_TAG in map(str.strip, torrent['tags'].split(','))


async def delete_torrent(client: Client, torrent_hash: str):
    return await asyncio.to_thread(client.torrents.delete, torrent_hash)


async def fetch_torrent(client: Client, torrent_hash: str) -> TorrentDictionary:
    return next(iter(await asyncio.to_thread(client.torrents.info, torrent_hashes=[torrent_hash]) or []), None)


async def fetch_completed_torrents(client: Client) -> TorrentInfoList:
    return await asyncio.to_thread(client.torrents.info.completed)


async def fetch_synced_torrents(client: Client) -> TorrentInfoList:
    return await asyncio.to_thread(client.torrents.info.completed, tags=SYNCED_TAG, sort='size', reverse=False)


async def fetch_save_path(client: Client) -> Path:
    return Path(await asyncio.to_thread(client.app_default_save_path))


async def fetch_maindata(client: Client):
    return await asyncio.to_thread(client.sync.maindata)


async def fetch_free_space_on_disk(client: Client):
    return (await asyncio.to_thread(client.sync.maindata))['server_state']['free_space_on_disk']


async def fetch_free_space_on_disk_in_gb(client: Client):
    return await fetch_free_space_on_disk(client) / 1073741824


async def fetch_torrent_files(client: Client, torrent_hash: str) -> TorrentFilesList:
    return await asyncio.to_thread(client.torrents.files, torrent_hash)


def torrent_file_path(torrent: TorrentDictionary, file: TorrentFile, dest_path: Path, save_path: Path) -> Path:
    content_file_path = os.path.join(torrent['save_path'], file['name'])
    relative_content_path = content_file_path[len(str(save_path)) + 1:]
    return Path(os.path.join(dest_path, relative_content_path))


async def are_torrent_files_synced(client: Client, torrent, dest_path: Path, save_path: Path,
                                   logger: logging.Logger) -> bool:
    for file in await fetch_torrent_files(client, torrent['hash']):
        dest_torrent_file_path = torrent_file_path(torrent, file, dest_path, save_path)

        if not dest_torrent_file_path.exists():
            logger.debug(f"Torrent missing dest file: {dest_torrent_file_path}")
            return False

    return True


def are_hardlinked_files(files, other_files):
    return all(any(are_hardlinked(file, other_file) for other_file in other_files) for file in files)


async def run(config):
    if config.src_url == config.dest_url:
        logger.error("Source and destination URLs are the same")
        return

    src_client = Client(host=config.src_url, username=config.src_username, password=config.src_password)
    dest_client = Client(host=config.dest_url, username=config.dest_username, password=config.dest_password)

    async def tag_synced_torrents():
        save_path = await fetch_save_path(src_client)
        torrents = [torrent for torrent in await fetch_completed_torrents(src_client) if
                    not has_synced_tag(torrent) and await are_torrent_files_synced(src_client, torrent, config.dest,
                                                                                   save_path, logger)]
        if torrents:
            for torrent in torrents:
                logger.info(f"Tagging torrent as synced: {torrent['name']}")
                if not config.dry_run:
                    torrent.addTags(SYNCED_TAG)
        else:
            logger.info("No torrents to tag as synced")

    async def move_torrent_to_cold(torrent):
        await asyncio.to_thread(torrent.stop)
        await until(lambda d: torrent.state_enum.is_stopped, lambda: asyncio.to_thread(torrent.sync_local), 30)

        existing_torrent = await fetch_torrent(dest_client, torrent.hash)

        if existing_torrent:
            logger.debug(f"Torrent already exists on destination: {torrent.name}")
            await asyncio.to_thread(existing_torrent.start)
            await asyncio.to_thread(torrent.delete, delete_files=True)
            return

        result = await asyncio.to_thread(dest_client.torrents.add,
                                         torrent_files=await asyncio.to_thread(torrent.export),
                                         save_path=torrent.save_path,
                                         category=torrent.category,
                                         tags=torrent.tags,
                                         use_auto_torrent_management=torrent.auto_tmm,
                                         )

        if result != 'Ok.':
            logger.error(f"Failed to add torrent {torrent.name}: {result}")
            await asyncio.to_thread(torrent.start)
            return

        dest_torrent = await until(lambda d: d is not None,
                                   lambda: fetch_torrent(dest_client, torrent.hash), 20)

        await until(lambda d: not dest_torrent.state_enum.is_uploading,
                    lambda: asyncio.to_thread(dest_torrent.sync_local), 300)
        await asyncio.to_thread(torrent.delete, delete_files=True)

    async def maybe_move_to_cold():

        if config.run and await fetch_free_space_on_disk_in_gb(src_client) < config.min_space:
            logger.info(f"Low disk space, attempting to move torrents to {config.dest_url}...")
            save_path = await fetch_save_path(src_client)
            torrents = await fetch_synced_torrents(src_client)

            torrent_files = {}
            torrent_dict = {}
            torrent_groups = []

            for torrent in torrents:
                torrent_dict[torrent['hash']] = torrent
                torrent_files[torrent['hash']] = await fetch_torrent_files(src_client, torrent['hash'])

            for torrent in torrents:
                if torrent['hash'] not in torrent_dict:
                    continue

                torrent_group = [torrent_dict.pop(torrent['hash'])]

                files = [torrent_file_path(torrent, f, config.src, save_path) for f in torrent_files[torrent['hash']]]

                for other_torrent in list(torrent_dict.values()):
                    other_files = [torrent_file_path(other_torrent, f, config.src, save_path) for f in
                                   torrent_files[other_torrent['hash']]]

                    if are_hardlinked_files(files, other_files):
                        logger.debug(f"Torrents are hardlinked: {torrent['name']} -> {other_torrent['name']}")
                        torrent_group.append(torrent_dict.pop(other_torrent['hash']))

                highest_popularity = max(torrent_group, key=lambda t: t['popularity'])['popularity']
                highest_size = max(torrent_group, key=lambda t: t['size'])['size']
                lowest_seeding_time = min(torrent_group, key=lambda t: t['seeding_time'])['seeding_time']

                torrent_groups.append({
                    'name': torrent.name,
                    'popularity': highest_popularity,
                    'size': highest_size,
                    'seeding_time': lowest_seeding_time,
                    'torrents': torrent_group
                })

            for torrent_group in sorted(torrent_groups, key=lambda x: (x['popularity'], -x['size'])):

                if torrent_group['seeding_time'] < config.min_seeding_time:
                    logger.info(
                        f"Skipping torrent group {torrent_group['name']} due to low seeding time of {torrent_group['seeding_time']}")
                    continue

                for torrent in torrent_group['torrents']:
                    if not config.dry_run:
                        await move_torrent_to_cold(torrent)

                if not config.run or await fetch_free_space_on_disk_in_gb(src_client) > config.min_space:
                    break

    while config.run:
        try:
            await tag_synced_torrents()
            await maybe_move_to_cold()
        except Exception as e:
            logger.error(f"Error: {e}")
        finally:
            await asyncio.sleep(config.sleep)
