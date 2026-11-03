#!/usr/bin/env python3
"""Optional Noctalia v5 picker adapter. Never imported by standalone controls."""
import argparse
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import control

THUMB=control.CONFIG/'Tux - live ASCII wallpaper.png'
STATE=control.STATE/'noctalia.json'

def run(*args):
    return subprocess.check_output(args,text=True,timeout=10).strip()

def load():
    try:return json.loads(STATE.read_text())
    except FileNotFoundError:return {'fallbacks':{},'outputs':[]}

def snapshot():
    monitors=run(str(control.ROOT/'build/creation-ascii'),'--list-outputs').splitlines()
    return {name:run('noctalia','msg','wallpaper-get',name) for name in monitors}

def selected(path):
    return not path.startswith('color:') and Path(path).expanduser().resolve()==THUMB.resolve()

def sync():
    STATE.parent.mkdir(parents=True,exist_ok=True)
    with (STATE.parent/"noctalia-sync.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        _sync()

def _sync():
    paths=snapshot();state=load()
    for name,path in paths.items():
        if path and not selected(path):state['fallbacks'][name]=path
    wanted=sorted(name for name,path in paths.items() if selected(path))
    before=state.get('outputs',[])
    if wanted:
        cfg=control.settings()
        state.setdefault('manual_output',cfg['output'])
        cfg['output']=','.join(wanted)
        control.atomic_json(control.CONFIG/'settings.json',cfg)
        control.action('restart' if control.active_pid() and before!=wanted else 'start')
    elif before:
        control.action('stop')
        cfg=control.settings();cfg['output']=state.pop('manual_output','')
        control.atomic_json(control.CONFIG/'settings.json',cfg)
    state['outputs']=wanted
    control.atomic_json(STATE,state)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','sync','select','restore','disable'])
    args=parser.parse_args()
    if args.command=='prepare':
        import shutil
        control.CONFIG.mkdir(parents=True,exist_ok=True)
        shutil.copy2(control.ROOT/'docs/preview.png',THUMB)
        print('Add this folder to Noctalia wallpaper directories:',THUMB.parent)
        print('Optional hooks (merge with any existing commands; see README):')
        cmd=json.dumps(sys.executable+' '+__import__('shlex').quote(str(Path(__file__).resolve()))+' sync')
        print('[hooks]\nwallpaper_changed = '+cmd+'\nstarted = '+cmd)
    elif args.command=='sync':sync()
    elif args.command=='select':
        if not THUMB.exists():raise RuntimeError('Run noctalia.py prepare first')
        state=load()
        for name,path in snapshot().items():
            if path and not selected(path):state['fallbacks'][name]=path
        control.atomic_json(STATE,state)
        run('noctalia','msg','wallpaper-set',str(THUMB));sync()
    elif args.command in ('restore','disable'):
        state=load()
        if args.command=='restore':
            for name,path in snapshot().items():
                if selected(path):
                    previous=state['fallbacks'].get(name)
                    if not previous:raise RuntimeError('Previous wallpaper is unknown for '+name)
                    run('noctalia','msg','wallpaper-set',name,previous)
            sync()
        else:
            # Hooks are installed manually, so never rewrite unrelated shell settings.
            hook=control.CONFIG.parent/'noctalia/zz-creation-of-tux.toml'
            if hook.exists() and str(control.ROOT/'noctalia.py') in hook.read_text():hook.unlink()
            print('Remove any manually added Noctalia hooks pointing to',Path(__file__))
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print('Noctalia adapter:',error,file=sys.stderr);sys.exit(1)
