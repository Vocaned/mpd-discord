import os
import sys
import socket
import struct
import json
import time
import subprocess
from pathlib import Path
from uuid import uuid4

CLIENT_ID = '1031137720317263873'

class IPC(socket.socket):
    def __init__(self, socket_path: str, client_id: str) -> None:
        self.CLIENT_ID = client_id
        super().__init__(socket.AF_UNIX, socket.SOCK_STREAM)
        self.connect(socket_path)

    def ipc_connect(self) -> dict:
        self.ipc_write(0, {'v': 1, 'client_id': self.CLIENT_ID})
        _, data = self.ipc_read()
        if not data or 'cmd' not in data or data['cmd'] != 'DISPATCH':
            print(data, file=sys.stderr)
            sys.exit()
        return data

    def ipc_read(self) -> tuple[int, dict]:
        header = self.recv(8)
        op, length = struct.unpack('<II', header)
        return (op, json.loads(self.recv(length)))

    def ipc_write(self, op: int, payload: dict) -> None:
        s = json.dumps(payload)
        header = struct.pack('<II', op, len(s))
        self.send(header + s.encode('utf-8'))

    def ipc_close(self) -> None:
        self.ipc_write(2, {'v': 1, 'client_id': self.CLIENT_ID})
        op, data = self.ipc_read()
        print(op, data)
        self.close()

    def ipc_activity(self, activity: dict | None) -> tuple[int, dict]:
        payload = {
            'cmd': 'SET_ACTIVITY',
            'args': {
                'pid': os.getpid(),
                'activity': activity
            },
            'nonce': str(uuid4())
        }
        self.ipc_write(1, payload)
        return self.ipc_read()

def clean_dict(d):
    if isinstance(d, dict):
        return {k: clean_dict(v) for k, v in d.items() if v is not None}
    return d

def run(*cmd: str) -> dict | None:
    ret = subprocess.run(cmd, encoding='utf-8', capture_output=True).stdout
    if not ret.strip():
        return None # cmd returned nothing
    return json.loads(ret)

SOCKET_DIRS = (
    '.',
    'app/com.discordapp.Discord/',
    'snap.discord-canary/',
    'snap.discord/'
)

def get_socket() -> IPC:
    while True:
        try:
            p = Path(os.getenv('XDG_RUNTIME_DIR', '/tmp'))
            for subdir in SOCKET_DIRS:
                for socket in p.joinpath(subdir).glob('discord-ipc-*'):
                    return IPC(str(socket), CLIENT_ID)

            raise RuntimeError
        except ConnectionRefusedError or RuntimeError:
            print('Discord socket not running, trying again in 30 seconds', file=sys.stderr)
            time.sleep(30)

def main():
    while True:
        s = get_socket()
        try:
            s.ipc_connect()

            while True:
                status = run('rmpc', 'status')
                song = run('rmpc', 'song')
                if not status or not song or status.get('state') != 'Play' or not song.get('metadata'):
                    s.ipc_activity(None)
                    time.sleep(5)
                    continue

                metadata = song['metadata']

                time_start = int(time.time()) - int(status['elapsed']['secs'])
                time_end = time_start + int(status['duration']['secs'])

                meta = {
                    'artist': metadata.get('albumartist') or metadata.get('artist'),
                    'artistid': metadata.get('musicbrainz_albumartistid') or metadata.get('musicbrainz_artistid'),
                    'track': metadata.get('title'),
                    'trackid': metadata.get('musicbrainz_trackid'),
                    'album': metadata.get('album'),
                    'albumid': metadata.get('musicbrainz_albumid'),
                }

                # Filter metadata to only use the first tag in case multiple are present
                meta = {k: (lambda x: x[0] if isinstance(x, list) else x)(v) for k, v in meta.items()}

                _, data = s.ipc_activity(clean_dict({
                    'status_display_type': 1,
                    'type': 2,
                    'flags': 1,
                    'state': meta['artist'],
                    'state_url': f'https://musicbrainz.org/artist/{meta["artistid"]}' if meta['artistid'] else None,
                    'details': meta['track'],
                    'details_url': f'https://musicbrainz.org/track/{meta["trackid"]}' if meta['trackid'] else None,
                    'timestamps': {
                        'start': time_start * 1000,
                        'end': time_end * 1000
                    },
                    'assets': {
                        'large_image': f'https://coverartarchive.org/release/{meta["albumid"]}/front' if meta['albumid'] else None,
                        'large_text': meta['album'],
                        'large_url': f'https://musicbrainz.org/release/{meta["albumid"]}' if meta['albumid'] else None
                    }
                }))

                if 'code' in data['data']:
                    print(data, file=sys.stderr)

                time.sleep(5)
        except KeyboardInterrupt:
            s.ipc_close()
            sys.exit(0)
        except BrokenPipeError:
            # Restart the main loop
            s.close()



if __name__ == '__main__':
    main()
