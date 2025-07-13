import os
import sys
import socket
import struct
import json
import time
import subprocess
from uuid import uuid4

CLIENT_ID = '1031137720317263873'

class IPC(socket.socket):
    IPC_PATH = f'/run/user/{os.getuid()}/discord-ipc-0'

    def __init__(self, client_id: str) -> None:
        self.CLIENT_ID = client_id
        super().__init__(socket.AF_UNIX, socket.SOCK_STREAM)
        self.connect(self.IPC_PATH)

    def ipc_connect(self) -> dict:
        self.ipc_write(0, {'v': 1, 'client_id': self.CLIENT_ID})
        _, data = self.ipc_read()
        if not data or 'cmd' not in data or data['cmd'] != 'DISPATCH':
            print(data)
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

    def close(self) -> None:
        self.ipc_write(2, {'v': 1, 'client_id': self.CLIENT_ID})
        op, data = self.ipc_read()
        print(op, data)
        super().close()

    def ipc_activity(self, activity: dict) -> tuple[int, dict]:
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

def main():
    s = IPC(CLIENT_ID)
    try:
        s.ipc_connect()

        while True:
            status = json.loads(subprocess.run(['rmpc', 'status'], encoding='utf-8', capture_output=True).stdout)
            song = json.loads(subprocess.run(['rmpc', 'song'], encoding='utf-8', capture_output=True).stdout)

            if status['state'] != 'Play':
                time.sleep(5)
                continue

            time_start = int(time.time()) - int(status['elapsed']['secs'])
            time_end = time_start + int(status['duration']['secs'])

            _, data = s.ipc_activity({
                'status_display_type': 1,
                'type': 2,
                'state': song['metadata']['albumartist'] or song['metadata']['artist'],
                'state_url': f"https://musicbrainz.org/artist/{song['metadata']['musicbrainz_albumartistid']}",
                'details': song['metadata']['title'],
                'details_url': f"https://musicbrainz.org/track/{song['metadata']['musicbrainz_trackid']}",
                'timestamps': {
                    'start': time_start * 1000,
                    'end': time_end * 1000
                },
                'assets': {
                    'large_image': f"https://coverartarchive.org/release/{song['metadata']['musicbrainz_albumid']}/front",
                    'large_text': song['metadata']['album'],
                    'large_url': f"https://musicbrainz.org/release/{song['metadata']['musicbrainz_albumid']}"
                },
            })

            print(data)

            time.sleep(5)
    except KeyboardInterrupt:
        s.close()


if __name__ == '__main__':
    main()
