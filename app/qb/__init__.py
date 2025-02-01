import os
import signal
import time

import requests


class QBManager:
    _run = True

    def __init__(self, source_url, source_username, source_password, dest_url, dest_username, dest_password, dest_path, logger):
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

    def handle_signal(self, signum, frame):
        self.logger.info(f"Received signal {signum}, shutting down...")
        self._run = False

    def move_torrents(self):
        config = self.qb.get_source_config()

        config_save_path = config['save_path']

        # Get all stalled torrents that are not popular, are larger than 20GB and have been seeding for more than an hour
        torrents = [t for t in self.qb.list_stalled_up() if
                    t['popularity'] == 0
                    and t['size'] > 21474836480
                    and t['seeding_time'] > 3600]

        if torrents:
            for torrent in torrents:
                self.logger.info(f"Processing: {torrent['name']}...")
                files = self.qb.list_completed_files(torrent['hash'])
                save_path = torrent['save_path']

                existing_file_count = 0

                for file in files:
                    content_file_path = os.path.join(save_path, file['name'])
                    relative_content_path = content_file_path[len(config_save_path) + 1:]
                    dest_content_file_path = os.path.join(self.dest_path, relative_content_path)

                    if os.path.exists(dest_content_file_path):
                        existing_file_count += 1

                if existing_file_count != len(files):
                    self.logger.info(f"Not all files are present on destination: {torrent['name']}...")
                    continue

                self.logger.info(f"Moving torrent: {torrent['name']}...")

                dest_torrent = self.qb.find_dest_torrent(torrent['hash'])

                if dest_torrent:
                    self.logger.info(f"Torrent already exists in destination, removing: {torrent['name']}")
                    self.qb.remove_torrent(torrent['hash'])
                    print(dest_torrent)
                    continue

                if torrent['state'] != 'stoppedUP':
                    print(f"Stopping torrent: {torrent['name']}#{torrent['hash']}")
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

                    self.logger.info(f"Waiting for torrent to move: {torrent['name']} [state: {dest_torrent['state']}]...")
                    time.sleep(1)

                self.qb.remove_torrent(torrent['hash'])

        else:
            self.logger.info("No torrents to move...")

    async def start(self):
        signal.signal(signal.SIGINT, self.handle_signal)
        while self._run:
            self.logger.info("Checking for torrents that can be moved...")
            try:
                self.move_torrents()
            except Exception as e:
                self.logger.error(f"Error moving torrents: {e}")
            finally:
                #  Only run every minute to avoid hammering the API and allow for sigint interrupts
                time.sleep(60)


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
                                            data={'hashes': torrent_hash, 'deleteFiles': 'false'})
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
