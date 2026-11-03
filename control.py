#!/usr/bin/env python3
"""Shell-independent user controls for Creation of Tux. Python standard library."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
APP = 'creation-of-tux'
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/APP
STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home()/'.local/state'))/APP
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', STATE/'runtime'))/APP
DEFAULTS = dict(columns=260, fps=30, period=9.0, tux_scale=0.65, output='')
PRESETS = {'eco': (180, 24), 'balanced': (260, 30), 'detailed': (360, 60)}


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(data, indent=2)+'\n')
    temp.replace(path)


def validate(data):
    if not isinstance(data, dict) or data.keys()-DEFAULTS.keys():
        raise ValueError('Unknown settings; use columns, fps, period, tux_scale and output')
    result = DEFAULTS | data
    for key, lower, upper, integer in [('columns',60,600,True), ('fps',1,120,True),
                                       ('period',2,120,False), ('tux_scale',0.1,1.5,False)]:
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int,float)) or not lower <= value <= upper:
            raise ValueError(f'{key} must be between {lower} and {upper}')
        if integer and not isinstance(value, int):
            raise ValueError(f'{key} must be an integer')
    output = result['output']
    if not isinstance(output, str) or len(output)>1024 or any(c.isspace() or ord(c)<32 for c in output):
        raise ValueError('Output must be an empty string (all) or comma-separated connector names')
    return result


def settings():
    try:
        return validate(json.loads((CONFIG/'settings.json').read_text()))
    except FileNotFoundError:
        return dict(DEFAULTS)


def renderer_args():
    cfg = settings()
    command = [str(ROOT/'build/creation-ascii')]
    for key in DEFAULTS:
        if cfg[key] != '':
            command += ['--'+key.replace('_','-'), str(cfg[key])]
    return command


def proc_start(pid):
    # /proc comm can contain spaces and parentheses. Field 22 follows the final ')'.
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]


def active_pid():
    try:
        record = json.loads((RUNTIME/'process.json').read_text())
        pid = int(record['pid'])
        if pid <= 1 or record['start'] != proc_start(pid):
            return None
        argv = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        if os.fsencode(str(ROOT/'control.py')) not in argv or b'_daemon' not in argv:
            return None
        return pid
    except (OSError,ValueError,KeyError,TypeError):
        return None


@contextmanager
def lock(name):
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (RUNTIME/name).open('a') as file:
        fcntl.flock(file, fcntl.LOCK_EX)
        yield file


def stop_unlocked():
    pid = active_pid()
    if pid is None:
        return
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic()+5
    while active_pid() is not None and time.monotonic()<deadline:
        time.sleep(.05)
    if active_pid() is not None:
        raise RuntimeError('Renderer did not stop; see '+str(STATE/'renderer.log'))


def start_unlocked():
    if active_pid() is not None:
        return
    renderer_args()  # Validate before creating a background process.
    if not os.environ.get('WAYLAND_DISPLAY'):
        raise RuntimeError('Start this from a Wayland desktop session')
    STATE.mkdir(parents=True, exist_ok=True)
    log_path = STATE/'renderer.log'
    if log_path.exists() and log_path.stat().st_size>2_000_000:
        log_path.replace(STATE/'renderer.previous.log')
    with log_path.open('a') as log:
        process = subprocess.Popen([sys.executable,str(ROOT/'control.py'),'_daemon'],
                                   stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    deadline = time.monotonic()+8
    while time.monotonic()<deadline:
        if process.poll() is not None:
            tail = '\n'.join(log_path.read_text(errors='replace').splitlines()[-5:])
            raise RuntimeError('Wallpaper failed to start:\n'+tail)
        if active_pid() is not None:
            return
        time.sleep(.05)
    process.terminate()
    raise RuntimeError('Startup timed out; see '+str(log_path))


def action(name):
    with lock('control.lock'):
        if name == 'toggle':
            name = 'stop' if active_pid() else 'start'
        if name in ('stop','restart'):
            stop_unlocked()
        if name in ('start','restart'):
            start_unlocked()
    return bool(active_pid())


def daemon():
    with lock('daemon.lock'):
        child = subprocess.Popen(renderer_args())
        stopping = False
        def stop(*_):
            nonlocal stopping
            stopping = True
            if child.poll() is None:
                child.terminate()
        def refresh(*_):
            if child.poll() is None:
                child.send_signal(signal.SIGUSR1)
        signal.signal(signal.SIGTERM,stop)
        signal.signal(signal.SIGINT,stop)
        signal.signal(signal.SIGUSR1,refresh)
        stream = None
        last_connect = -10.0
        pending = b''
        refresh_at = None
        try:
            # Give protocol/EGL failures a chance to surface before reporting success.
            try:
                code = child.wait(timeout=.7)
                return code or 1
            except subprocess.TimeoutExpired:
                pass
            atomic_json(RUNTIME/'process.json',dict(pid=os.getpid(),start=proc_start(os.getpid())))
            while child.poll() is None and not stopping:
                now = time.monotonic()
                signature = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE','')
                if stream is None and signature and now-last_connect>3:
                    last_connect = now
                    path = Path(os.environ.get('XDG_RUNTIME_DIR','/run/user/'+str(os.getuid())))/'hypr'/signature/'.socket2.sock'
                    try:
                        stream = socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
                        stream.connect(str(path));stream.setblocking(False)
                    except OSError:
                        if stream: stream.close()
                        stream = None
                if stream:
                    ready,_,_ = select.select([stream],[],[],.3)
                    if ready:
                        try: data = stream.recv(65536)
                        except OSError: data = b''
                        if not data:
                            stream.close();stream=None;pending=b''
                        else:
                            pending+=data
                            lines=pending.split(b'\n');pending=lines.pop()
                            for line in lines:
                                if line.startswith(b'openlayer>>') and b'creation-' not in line and any(word in line for word in (b'wallpaper',b'swaybg',b'swww')):
                                    refresh_at=time.monotonic()+.35
                else:
                    time.sleep(.3)
                if refresh_at is not None and time.monotonic()>=refresh_at:
                    refresh();refresh_at=None
        finally:
            if stream: stream.close()
            if child.poll() is None:
                child.terminate()
                try: child.wait(timeout=3)
                except subprocess.TimeoutExpired: child.kill();child.wait()
            (RUNTIME/'process.json').unlink(missing_ok=True)
        return 0 if stopping else child.returncode


def set_autostart(enabled):
    path = CONFIG.parent/'autostart'/f'{APP}.desktop'
    if enabled:
        path.parent.mkdir(parents=True,exist_ok=True)
        script = str(ROOT/'control.py')
        # Desktop Entry quoting is not shell quoting.
        def quote(value):
            return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')+'"'
        path.write_text('[Desktop Entry]\nType=Application\nName=Creation of Tux\n'
                        f'Exec={quote(sys.executable)} {quote(script)} start\n'
                        'Terminal=false\nX-GNOME-Autostart-enabled=true\n')
    else:
        path.unlink(missing_ok=True)


def diagnostics():
    print('Creation of Tux 0.1.0')
    print('Session:', os.environ.get('XDG_SESSION_TYPE','unknown'))
    print('Wayland socket:', os.environ.get('WAYLAND_DISPLAY','not set'))
    print('Configuration:', CONFIG/'settings.json')
    print('Log:', STATE/'renderer.log')
    print('Running:', bool(active_pid()))
    print('Noctalia: optional, never required')
    try:
        check = subprocess.run([str(ROOT/'build/creation-ascii'),'--list-outputs'],text=True,capture_output=True,timeout=8)
        print(check.stdout.strip() or check.stderr.strip())
        return check.returncode
    except (OSError,subprocess.TimeoutExpired) as error:
        print(error)
        return 1


def main(argv=None):
    parser=argparse.ArgumentParser(description='Animated ASCII wallpaper for Wayland. No desktop shell required.')
    parser.add_argument('command',nargs='?',default='settings',choices=['start','stop','toggle','restart','status','settings','run','doctor','autostart','configure','refresh','_daemon'])
    parser.add_argument('value',nargs='?')
    args=parser.parse_args(argv)
    try:
        if args.command=='_daemon': return daemon()
        if args.command in ('start','stop','toggle','restart'):
            print('Running' if action(args.command) else 'Stopped');return 0
        if args.command=='status':
            print('Running' if active_pid() else 'Stopped');return 0
        if args.command=='run':
            os.execv(renderer_args()[0],renderer_args())
        if args.command=='settings':
            from gui import show
            show();return 0
        if args.command=='doctor': return diagnostics()
        if args.command=='refresh':
            pid=active_pid()
            if pid: os.kill(pid,signal.SIGUSR1)
            return 0
        if args.command=='autostart':
            if args.value not in ('on','off'): parser.error('autostart needs on or off')
            set_autostart(args.value=='on');return 0
        if args.command=='configure':
            if args.value is None:
                print(json.dumps(settings(),indent=2));return 0
            if args.value in PRESETS:
                columns,fps=PRESETS[args.value]
                config=settings() | dict(columns=columns,fps=fps)
            else:
                config=validate(settings() | json.loads(args.value))
            atomic_json(CONFIG/'settings.json',config)
            if active_pid(): action('restart')
            return 0
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError,ImportError) as error:
        print('Creation of Tux:',error,file=sys.stderr);return 1
    return 0

if __name__=='__main__':
    sys.exit(main())
