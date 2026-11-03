#!/usr/bin/env python3
"""Unprivileged, per-user installation. Never edits compositor/shell settings."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent
FILES=('control.py','gui.py','install.py','noctalia.py','README.md','LICENSE','THIRD_PARTY.md','VERSION')
DIRS=('assets','docs','LICENSES')
MARKER='.creation-of-tux-install.json'


def desktop_quote(value):
    return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('$','\\$').replace('`','\\`').replace('%','%%')+'"'


def main(argv=None):
    parser=argparse.ArgumentParser(description='Install or remove Creation of Tux for this user; no sudo.')
    parser.add_argument('--prefix',type=Path,default=None,help='Default: ~/.local, respecting XDG_DATA_HOME')
    parser.add_argument('--uninstall',action='store_true')
    args=parser.parse_args(argv)
    prefix=(args.prefix or Path.home()/'.local').expanduser().resolve()
    data=prefix/'share' if args.prefix else Path(os.environ.get('XDG_DATA_HOME',prefix/'share')).expanduser().resolve()
    dest=data/'creation-of-tux'
    launcher=prefix/'bin/creation-of-tux'
    desktop=data/'applications/io.github.creationoftux.Controls.desktop'
    config=Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config')).expanduser().resolve()
    autostart=config/'autostart/creation-of-tux.desktop'
    if dest.exists() and not (dest/MARKER).is_file():
        raise RuntimeError(f'{dest} exists and is not an installation managed by this installer')
    if args.uninstall:
        if not dest.exists():
            print('Not installed in',dest);return 0
        record=json.loads((dest/MARKER).read_text())
        if record.get('destination')!=str(dest) or record.get('launcher')!=str(launcher):
            raise RuntimeError('Installation manifest does not match this prefix')
        subprocess.run([sys.executable,str(dest/'control.py'),'stop'],check=True)
        if (config/'noctalia/zz-creation-of-tux.toml').exists():
            subprocess.run([sys.executable,str(dest/'noctalia.py'),'disable'],check=True)
        for path in (launcher,desktop):
            if path.is_symlink() and path.resolve().is_relative_to(dest):path.unlink()
        if autostart.exists() and str(dest/'control.py') in autostart.read_text():autostart.unlink()
        shutil.rmtree(dest)
        print('Uninstalled. Preferences and logs retained in XDG config/state directories.')
        return 0
    binary=ROOT/'build/creation-ascii'
    sources=[ROOT/'main.cpp',ROOT/'build.sh',*(ROOT/'protocol').glob('*.xml')]
    needs_build=not binary.is_file() or any(p.exists() and p.stat().st_mtime_ns>binary.stat().st_mtime_ns for p in sources)
    if needs_build:
        if not (ROOT/'build.sh').is_file():raise RuntimeError('Renderer is missing. Download the complete source archive.')
        subprocess.run(['bash',str(ROOT/'build.sh')],check=True)
    for path in (launcher,desktop):
        if path.exists() or path.is_symlink():
            if not (path.is_symlink() and path.resolve().is_relative_to(dest)):
                raise RuntimeError(f'Refusing to overwrite an unrelated file: {path}')
    if dest==ROOT:
        raise RuntimeError('Run the installer from the downloaded source directory')
    dest.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.creation-of-tux-',dir=dest.parent) as temporary:
        stage=Path(temporary)/'payload';stage.mkdir()
        for name in FILES:shutil.copy2(ROOT/name,stage/name)
        for name in DIRS:shutil.copytree(ROOT/name,stage/name)
        (stage/'build').mkdir();shutil.copy2(ROOT/'build/creation-ascii',stage/'build/creation-ascii')
        script=stage/'creation-of-tux'
        script.write_text('#!/bin/sh\nexec '+__import__('shlex').quote(sys.executable)+' '+__import__('shlex').quote(str(dest/'control.py'))+' "$@"\n')
        script.chmod(0o755)
        desk=stage/'controls.desktop'
        desk.write_text('[Desktop Entry]\nType=Application\nName=Creation of Tux\nComment=Animated ASCII wallpaper and settings\n'
            f'Exec={desktop_quote(sys.executable)} {desktop_quote(dest/"control.py")} settings\n'
            f'Icon={dest/"docs/icon.png"}\nTerminal=false\nCategories=Settings;DesktopSettings;\n'
            'Actions=Start;Stop;\n\n[Desktop Action Start]\nName=Start wallpaper\n'
            f'Exec={desktop_quote(sys.executable)} {desktop_quote(dest/"control.py")} start\n\n'
            '[Desktop Action Stop]\nName=Stop wallpaper\n'
            f'Exec={desktop_quote(sys.executable)} {desktop_quote(dest/"control.py")} stop\n')
        (stage/MARKER).write_text(json.dumps(dict(version='0.1.0',destination=str(dest),launcher=str(launcher)),indent=2)+'\n')
        backup=None
        if dest.exists():
            subprocess.run([sys.executable,str(dest/'control.py'),'stop'],check=True)
            backup=Path(temporary)/'previous';dest.rename(backup)
        try:
            stage.rename(dest)
            for path,target in ((launcher,dest/'creation-of-tux'),(desktop,dest/'controls.desktop')):
                path.parent.mkdir(parents=True,exist_ok=True)
                if path.is_symlink():path.unlink()
                path.symlink_to(target)
        except Exception:
            if dest.exists():shutil.rmtree(dest)
            if backup:backup.rename(dest)
            raise
    print('Installed:',dest)
    print('Open “Creation of Tux” in your app launcher, or run:',launcher,'start')
    print('Autostart is off until you enable it. Nothing in your desktop configuration was changed.')
    print('Uninstall:',sys.executable,str(dest/'install.py'),'--uninstall',*( ['--prefix',str(prefix)] if args.prefix else []))
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,RuntimeError,ValueError,subprocess.SubprocessError) as error:
        print('Installer:',error,file=sys.stderr);sys.exit(1)
