"""Temporary-home integration tests: never touch an installed wallpaper."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

SOURCE=Path(__file__).resolve().parents[1]

class Controls(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='tux-controls-')
        self.root=Path(self.temp.name)
        self.app=self.root/'app with spaces'
        (self.app/'build').mkdir(parents=True)
        shutil.copy2(SOURCE/'control.py',self.app/'control.py')
        self.env=dict(os.environ, HOME=str(self.root),XDG_CONFIG_HOME=str(self.root/'config'),
            XDG_STATE_HOME=str(self.root/'state'),XDG_RUNTIME_DIR=str(self.root/'runtime'),WAYLAND_DISPLAY='fake-0')
        self.env.pop('HYPRLAND_INSTANCE_SIGNATURE',None)
        fake=self.app/'build/creation-ascii'
        fake.write_text('#!'+sys.executable+'''\nimport os,signal,time,json,sys
from pathlib import Path
root=Path(os.environ['HOME'])
(root/'args.json').write_text(json.dumps(sys.argv[1:]))
signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))
signal.signal(signal.SIGUSR1,lambda *_:(root/'refreshed').touch())
while True:time.sleep(.03)
''')
        fake.chmod(0o755)
    def cli(self,*args,check=True):
        result=subprocess.run([sys.executable,str(self.app/'control.py'),*args],env=self.env,
                              text=True,capture_output=True,timeout=15)
        if check:self.assertEqual(result.returncode,0,result.stderr)
        return result
    def tearDown(self):
        self.cli('stop',check=False)
        self.temp.cleanup()
    def test_start_idempotent_stop(self):
        self.cli('start')
        record=self.root/'runtime/creation-of-tux/process.json'
        first=json.loads(record.read_text())
        self.cli('start')
        self.assertEqual(first,json.loads(record.read_text()))
        self.assertEqual(self.cli('status').stdout.strip(),'Running')
        self.cli('stop')
        self.assertEqual(self.cli('status').stdout.strip(),'Stopped')
        self.assertFalse(record.exists())
    def test_output_and_restart(self):
        self.cli('configure','{"output":"DP-3,eDP-1","fps":24}')
        self.cli('start')
        args=json.loads((self.root/'args.json').read_text())
        self.assertIn('DP-3,eDP-1',args)
        self.assertEqual(args[args.index('--fps')+1],'24')
        self.cli('configure','detailed')
        args=json.loads((self.root/'args.json').read_text())
        self.assertEqual(args[args.index('--fps')+1],'60')
        self.assertIn('DP-3,eDP-1',args)
    def test_invalid_settings_do_not_start(self):
        self.assertNotEqual(self.cli('configure','{"fps":0}',check=False).returncode,0)
        self.assertNotEqual(self.cli('configure','{"fps":true}',check=False).returncode,0)
        self.assertNotEqual(self.cli('configure','{"period":NaN}',check=False).returncode,0)
        self.assertNotEqual(self.cli('configure','{"unknown":42}',check=False).returncode,0)
        self.assertFalse((self.root/'args.json').exists())
    def test_bad_config_is_preserved(self):
        path=self.root/'config/creation-of-tux/settings.json';path.parent.mkdir(parents=True)
        path.write_text('{broken')
        self.assertNotEqual(self.cli('start',check=False).returncode,0)
        self.assertEqual(path.read_text(),'{broken')
    def test_no_wayland_clear_error(self):
        self.env.pop('WAYLAND_DISPLAY')
        result=self.cli('start',check=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Wayland',result.stderr)
    def test_renderer_failure_visible(self):
        (self.app/'build/creation-ascii').write_text('#!/bin/sh\necho "No layer-shell" >&2\nexit 1\n')
        result=self.cli('start',check=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('No layer-shell',result.stderr)
    def test_stale_pid_does_not_kill_unrelated_process(self):
        other=subprocess.Popen(['sleep','20'])
        try:
            runtime=self.root/'runtime/creation-of-tux';runtime.mkdir(parents=True)
            stat=Path(f'/proc/{other.pid}/stat').read_text().rsplit(')',1)[1].split()[19]
            (runtime/'process.json').write_text(json.dumps(dict(pid=other.pid,start=stat)))
            self.cli('stop')
            self.assertIsNone(other.poll())
        finally:other.terminate();other.wait()
    def test_autostart_paths_with_spaces(self):
        self.cli('autostart','on')
        path=self.root/'config/autostart/creation-of-tux.desktop'
        text=path.read_text()
        self.assertIn('"'+str(self.app/'control.py')+'" start',text)
        self.cli('autostart','off')
        self.assertFalse(path.exists())
    def test_refresh(self):
        self.cli('start');self.cli('refresh')
        deadline=time.monotonic()+2
        while not (self.root/'refreshed').exists() and time.monotonic()<deadline:time.sleep(.03)
        self.assertTrue((self.root/'refreshed').exists())

class Installation(unittest.TestCase):
    def test_install_update_uninstall_keeps_other_files(self):
        with tempfile.TemporaryDirectory(prefix='tux-install-') as temporary:
            root=Path(temporary);prefix=root/'prefix with spaces'
            env=dict(os.environ,HOME=str(root),XDG_CONFIG_HOME=str(root/'config'),
                XDG_STATE_HOME=str(root/'state'),XDG_RUNTIME_DIR=str(root/'runtime'))
            command=[sys.executable,str(SOURCE/'install.py'),'--prefix',str(prefix)]
            def run(cmd):
                result=subprocess.run(cmd,env=env,text=True,capture_output=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr)
            run(command)
            launcher=prefix/'bin/creation-of-tux'
            run([str(launcher),'status'])
            self.assertFalse((root/'config/autostart/creation-of-tux.desktop').exists())
            keep=prefix/'share/unrelated.txt';keep.write_text('keep')
            run(command)
            run(command+['--uninstall'])
            self.assertFalse(launcher.exists())
            self.assertFalse((prefix/'share/creation-of-tux').exists())
            self.assertEqual(keep.read_text(),'keep')
    def test_refuse_unmanaged_destination(self):
        with tempfile.TemporaryDirectory(prefix='tux-unmanaged-') as temporary:
            prefix=Path(temporary)
            dest=prefix/'share/creation-of-tux';dest.mkdir(parents=True)
            sentinel=dest/'important';sentinel.write_text('keep')
            result=subprocess.run([sys.executable,str(SOURCE/'install.py'),'--prefix',str(prefix)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(sentinel.read_text(),'keep')

if __name__=='__main__':unittest.main()
