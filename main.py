import os
import sys
import socket
import struct
import json
import time
from pathlib import Path
from uuid import uuid4

CLIENT_ID = '1031137720317263873'
MPD_SOCKET = '$XDG_RUNTIME_DIR/mpd.sock'

class Discord(socket.socket):
    def __init__(self, socket_path: str, client_id: str) -> None:
        self.CLIENT_ID = client_id
        super().__init__(socket.AF_UNIX, socket.SOCK_STREAM)
        self.settimeout(5) # Timeout socket after 5 seconds
        self.connect(socket_path)

    def ipc_connect(self) -> dict:
        self.ipc_write(0, {'v': 1, 'client_id': self.CLIENT_ID})
        _, data = self.ipc_read()
        if not data or 'cmd' not in data or data['cmd'] != 'DISPATCH':
            raise ValueError(f'Encountered unexpected data when logging in, no clue what to do: {data}')
        return data

    def ipc_read(self) -> tuple[int, dict]:
        header = self.recv(8)
        op, length = struct.unpack('<II', header)
        d = json.loads(self.recv(length))

        if 'code' in d and d['code'] == 1000:
            # Unknown error (typically user logout), assume connection is closed and reset socket
            raise RuntimeError(str(d))

        return (op, d)

    def ipc_write(self, op: int, payload: dict) -> None:
        s = json.dumps(payload)
        header = struct.pack('<II', op, len(s))
        self.sendall(header + s.encode('utf-8'))

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

class MPD(socket.socket):
    def __init__(self, socket_path: str) -> None:
        # TODO: support tcp sockets
        super().__init__(socket.AF_UNIX, socket.SOCK_STREAM)
        self.settimeout(5)
        self.connect(socket_path)
        self.versionstring = self.recv_until(b'\n')

    def recv_until(self, terminator: bytes) -> bytes:
        buffer = b''
        while True:
            data = self.recv(4096)
            if not data:
                # Socket closed?
                raise RuntimeError
            buffer += data
            if buffer.endswith(terminator) or b'\nACK' in buffer:
                return buffer

    def query_command(self, command: str) -> dict:
        out = {}

        self.sendall(command.encode() + b'\n')
        for line in self.recv_until(b'OK\n').decode().splitlines():
            if ':' in line:
                k,v = line.split(':', maxsplit=1)
                out[k.strip().lower()] = v.strip()
        return out

def clean_dict(d):
    if isinstance(d, dict):
        return {k: clean_dict(v) for k, v in d.items() if v is not None}
    return d

SOCKET_DIRS = (
    '.',
    'app/com.discordapp.Discord/',
    'snap.discord-canary/',
    'snap.discord/'
)

def get_discord() -> Discord:
    try:
        p = Path(os.getenv('XDG_RUNTIME_DIR', '/tmp'))
        for subdir in SOCKET_DIRS:
            for socket in p.joinpath(subdir).glob('discord-ipc-*'):
                return Discord(str(socket), CLIENT_ID)

        raise FileNotFoundError('Discord socket not found')
    except (FileNotFoundError, ConnectionRefusedError, TimeoutError) as e:
        print('Could not connect to Discord socket, trying again in 30 seconds', file=sys.stderr)
        time.sleep(30)
        raise e

def get_mpd() -> MPD:
    try:
        return MPD(os.path.expandvars(MPD_SOCKET))
    except (FileNotFoundError, ConnectionRefusedError, TimeoutError) as e:
        print(f'Could not connect to mpd socket, trying again in 30 seconds', file=sys.stderr)
        time.sleep(30)
        raise e

def main():
    while True:
        d = get_discord()
        mpd = get_mpd()
        try:
            d.ipc_connect()

            while True:
                status = mpd.query_command('status')
                song = mpd.query_command('currentsong')
                if not status or not song or status.get('state') != 'play' or not song:
                    d.ipc_activity(None)
                    time.sleep(5)
                    continue

                time_start = time.time() - float(status['elapsed'])
                time_end = time_start + float(status['duration'])

                meta = {
                    'artist': song.get('artistsort') or song.get('artist'),
                    'artistid': song.get('musicbrainz_albumartistid') or song.get('musicbrainz_artistid'),
                    'track': song.get('title'),
                    'trackid': song.get('musicbrainz_trackid'),
                    'album': song.get('album'),
                    'albumid': song.get('musicbrainz_albumid'),
                }

                # Filter metadata to only use the first tag in case multiple are present
                meta = {k: (lambda x: x[0] if isinstance(x, list) else x)(v) for k, v in meta.items()}

                d.ipc_activity(clean_dict({
                    'status_display_type': 1,
                    'type': 2,
                    'flags': 1,
                    'state': meta['artist'],
                    'state_url': f'https://musicbrainz.org/artist/{meta["artistid"]}' if meta['artistid'] else None,
                    'details': meta['track'],
                    'details_url': f'https://musicbrainz.org/track/{meta["trackid"]}' if meta['trackid'] else None,
                    'timestamps': {
                        'start': int(time_start) * 1000,
                        'end': int(time_end) * 1000
                    },
                    'assets': {
                        'large_image': f'https://coverartarchive.org/release/{meta["albumid"]}/front' if meta['albumid'] else None,
                        'large_text': meta['album'],
                        'large_url': f'https://musicbrainz.org/release/{meta["albumid"]}' if meta['albumid'] else None
                    }
                }))
                time.sleep(5)
        except KeyboardInterrupt:
            d.ipc_close()
            sys.exit(0)
        except Exception as e:
            print(f'Received {type(e).__name__}, closing socket and restarting', file=sys.stderr)
            print(e, file=sys.stderr)
            try:
                d.close()
            except:
                pass


if __name__ == '__main__':
    main()

