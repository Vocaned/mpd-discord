from pathlib import Path
import os
import sys
import subprocess

p = Path(os.environ.get('XDG_CONFIG_HOME', '~/.config') + '/systemd/user/mpd-discord.service').expanduser().resolve()

if p.exists():
    print('Service file exists, do you want to remove it?')
    if input('[y/N] ').lower().strip() == 'y':
        subprocess.run(['systemctl', '--user', 'disable', '--now', 'mpd-discord'])
        p.unlink()
        print('Service file removed')
        sys.exit(0)

service = f'''[Unit]
Description=mpd-discord
Documentation=https://github.com/Vocaned/mpd-discord
After=mpd.service
Requires=mpd.service

[Service]
Type=simple
ExecStart=python {Path(os.getcwd() + '/main.py').resolve()}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=mpd.service
'''

print(f'Do you want to install a service file at {p}?')
if input('[y/N] ').lower().strip() == 'y': 
    with open(p, 'w') as f:
        f.write(service)
    print('Service file written.')
    subprocess.run(['systemctl', '--user', 'enable', '--now', 'mpd-discord'])
    print('Service started.')
