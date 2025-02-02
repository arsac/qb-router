import asyncio
import os
import signal
import time

import expiringdict
import requests

SYNCED_TAG = 'synced'
COMPLETED_STATES = ['stalledUP', 'pausedUP', 'uploading', 'queuedUP', 'forcedUP']


def has_synced_tag(torrent):
    return SYNCED_TAG in map(str.strip, torrent['tags'].split(','))


def is_completed(torrent):
    return torrent['state'] in COMPLETED_STATES


class QBManager:
    _run = True

    def __init__(self, source_url, source_username, source_password, dest_url, dest_username, dest_password, dest_path,
                 logger):

        self._torrent_files = expiringdict.ExpiringDict(max_len=2000, max_age_seconds=10)
        self._cache = expiringdict.ExpiringDict(max_len=100, max_age_seconds=60)

        self.qb = QB(
            source_url=source_url,
            source_username=source_username,
            source_password=source_password,
            dest_url=dest_url,
            dest_username=dest_username,
            dest_password=dest_password
        )
        self.dest_path = dest_path
        self.logger = logger

    # Method to fetch config from qbittorrent and cache for up to a minute
    def get_config(self, key):
        config = self._cache.get("config")
        if not config:
            config = self.qb.get_source_config()
            self._cache["config"] = config

        if key in config:
            return config[key]

        raise KeyError(f"Key {key} not found in config")

    def get_maindata(self, key):
        maindata = self._cache.get("maindata")
        if not maindata:
            maindata = self.qb.get_maindata()
            self._cache["maindata"] = maindata

        if key in maindata:
            return maindata[key]

        raise KeyError(f"Key {key} not found in maindata")

    # Method to fetch all torrents and cache for up to a minute
    def get_torrents(self, force=False):
        torrents = self._cache.get("torrents")
        if not torrents or force:
            torrents = self.qb.list_torrents()
            self._cache["torrents"] = torrents
        return torrents

    def get_completed_torrents(self):
        return [t for t in self.get_torrents() if is_completed(t)]

    # Method to fetch all files for a torrent and cache for up to a minute if a response is received, using the torrent hash as the key
    def get_torrent_files(self, torrent_hash):
        if self._torrent_files.get(torrent_hash):
            return self._torrent_files[torrent_hash]

        self.logger.debug("Cache expired, fetching torrent files...")
        self._torrent_files[torrent_hash] = self.qb.list_completed_files(torrent_hash)
        return self._torrent_files[torrent_hash]

    def handle_signal(self, signum, frame):
        self.logger.info(f"Received signal {signum}, shutting down...")
        self._run = False

    def is_synced(self, torrent):
        files = self.get_torrent_files(torrent['hash'])

        save_path = self.get_config('save_path')

        self.logger.debug(f"Tags: {torrent['tags']}")
        for file in files:
            content_file_path = os.path.join(torrent['save_path'], file['name'])
            relative_content_path = content_file_path[len(save_path) + 1:]
            dest_content_file_path = os.path.join(self.dest_path, relative_content_path)

            if not os.path.exists(dest_content_file_path):
                self.logger.debug(f"Torrent missing dest file: {dest_content_file_path}")
                return False

        return True

    def tag_synced_torrents(self):
        untagged_torrents = [t for t in self.get_completed_torrents() if not has_synced_tag(t)]

        if untagged_torrents:
            self.logger.info(f"Checking for synced torrents...")
            tagged = 0
            for torrent in untagged_torrents:
                if self.is_synced(torrent):
                    self.logger.info(f"Tagging synced torrent: {torrent['name']}...")
                    self.qb.tag_torrent(torrent['hash'], SYNCED_TAG)
                    tagged += 1

            if tagged > 0:
                self.logger.info(f"Tagged {tagged} torrents...")
                self.get_torrents(force=True)
        else:
            self.logger.info("No untagged torrents...")

    def move_torrents(self):
        server_state = self.get_maindata('server_state')

        # convert bytes to GB
        free_space_on_disk_gb = server_state['free_space_on_disk'] / 1073741824.0

        self.logger.info(f"{free_space_on_disk_gb} GB free on destination...")

        popularity_threshold = 0
        size_threshold = 21474836480 # 20GB
        seeding_time_threshold = 3600 * 2 # 2 hours

        if free_space_on_disk_gb < 10:
            self.logger.info(
                f"Extremely low disk space on destination ({int(free_space_on_disk_gb)}GB), using aggressive values...")
            popularity_threshold = 50
            size_threshold = 0
            seeding_time_threshold = 3600
        elif free_space_on_disk_gb < 20:
            self.logger.info(f"Low disk space on destination ({int(free_space_on_disk_gb)}GB), using aggressive values...")
            popularity_threshold = 0.5
            size_threshold = 10737418240 # 10GB
            seeding_time_threshold = 3600 # 1 hour

        # Get all stalled torrents that are not popular, are larger than 20GB and have been seeding for more than an hour
        torrents = [t for t in self.get_completed_torrents() if
                    has_synced_tag(t)
                    and t['popularity'] < popularity_threshold
                    and t['size'] > size_threshold
                    and t['seeding_time'] > seeding_time_threshold]

        if torrents:
            for torrent in torrents:
                self.logger.info(f"Processing: {torrent['name']}...")

                if not self.is_synced(torrent):
                    self.logger.info(f"Torrent not synced yet: {torrent['name']}")

                self.logger.info(f"Moving torrent: {torrent['name']}...")

                if self.qb.find_dest_torrent(torrent['hash']):
                    self.logger.info(f"Torrent already exists in destination, removing: {torrent['name']}")
                    self.qb.remove_torrent(torrent['hash'])
                    continue

                if torrent['state'] != 'stoppedUP':
                    self.logger.debug(f"Stopping torrent: {torrent['name']}#{torrent['hash']}")
                    self.qb.stop_torrent(torrent['hash'])
                    time.sleep(5)

                self.qb.move_torrent(torrent['hash'])

                # Add a timeout to avoid infinite loop`
                timeout = time.time() + 300  # 5 minutes from now
                while True:
                    dest_torrent = self.qb.find_dest_torrent(torrent['hash'])

                    if dest_torrent and not dest_torrent['state'].startswith('checking'):
                        break

                    if time.time() > timeout:
                        self.logger.info(f"Timeout reached while waiting for torrent to move: {torrent['name']}")
                        break

                    self.logger.info(
                        f"Waiting for torrent to move: {torrent['name']} [state: {dest_torrent['state']}]...")
                    time.sleep(1)

                self.qb.remove_torrent(torrent['hash'])
            self.get_torrents(force=True)
        else:
            self.logger.info("No torrents to move...")

    async def start(self):
        signal.signal(signal.SIGINT, self.handle_signal)
        while self._run:
            self.logger.debug("Running torrent tasks...")
            try:
                self.tag_synced_torrents()
                self.move_torrents()
            except Exception as e:
                self.logger.error(f"Error while processing torrents: {e}")
            finally:
                #  Only run every minute to avoid hammering the API and allow for sigint interrupts
                await asyncio.sleep(20)


def _login(url, username, password):
    session = requests.Session()
    login_data = {'username': username, 'password': password}
    response = session.post(f'{url}/api/v2/auth/login', data=login_data)
    response.raise_for_status()
    return session


class QB:
    def __init__(self, source_url, source_username, source_password, dest_url, dest_username, dest_password):
        self.source_url = source_url
        self.source_session = _login(source_url, source_username, source_password)
        self.dest_url = dest_url
        self.dest_session = _login(dest_url, dest_username, dest_password)

    def tag_torrent(self, torrent_hash, tag):
        response = self.source_session.post(f'{self.source_url}/api/v2/torrents/addTags',
                                            data={'hashes': torrent_hash, 'tags': tag})
        response.raise_for_status()

    # Method to retrieve qbittorrent configuration
    def get_source_config(self):
        response = self.source_session.get(f'{self.source_url}/api/v2/app/preferences')
        response.raise_for_status()
        return response.json()

    def list_stalled_up(self):
        response = self.source_session.get(f'{self.source_url}/api/v2/torrents/info?filter=stalledUp')
        response.raise_for_status()
        return response.json()

    def list_torrents(self):
        response = self.source_session.get(f'{self.source_url}/api/v2/torrents/info')
        response.raise_for_status()
        return response.json()

    def find_dest_torrent(self, torrent_hash):
        response = self.dest_session.get(f'{self.dest_url}/api/v2/torrents/info?hashes={torrent_hash}')
        response.raise_for_status()
        return next(iter(response.json() or []), None)

    def stop_torrent(self, torrent_hash):
        response = self.source_session.post(f'{self.source_url}/api/v2/torrents/stop',
                                            data={'hashes': torrent_hash})
        response.raise_for_status()

    def remove_torrent(self, torrent_hash):
        response = self.source_session.post(f'{self.source_url}/api/v2/torrents/delete',
                                            data={'hashes': torrent_hash, 'deleteFiles': 'true'})
        response.raise_for_status()

    def move_torrent(self, torrent_hash):
        # Get torrent info from source
        response = self.source_session.get(f'{self.source_url}/api/v2/torrents/info?hashes={torrent_hash}')
        response.raise_for_status()
        torrent_info = response.json()[0]

        # Get torrent file
        response = self.source_session.get(f'{self.source_url}/api/v2/torrents/export?hash={torrent_hash}')
        response.raise_for_status()

        torrent_file = response.content

        # Add torrent to destination
        files = {'torrents': ('torrent', torrent_file)}
        data = {
            'savepath': torrent_info['save_path'],
            'category': torrent_info['category'],
            'tags': torrent_info['tags'],
            'autoTMM': torrent_info['auto_tmm'],
            'paused': 'true'
        }
        response = self.dest_session.post(f'{self.dest_url}/api/v2/torrents/add', files=files, data=data)
        response.raise_for_status()

    def list_completed_files(self, torrent_hash):
        response = self.source_session.get(f'{self.source_url}/api/v2/torrents/files?hash={torrent_hash}')
        response.raise_for_status()
        return response.json()

    def get_maindata(self):
        response = self.source_session.get(f'{self.source_url}/api/v2/sync/maindata')
        response.raise_for_status()
        return response.json()