"""Optional native GTK4 controls. CLI and wallpaper do not depend on GTK."""
import threading
import control


def show():
    try:
        import gi
        gi.require_version('Gtk','4.0')
        from gi.repository import Gtk, GLib
    except ImportError as error:
        raise RuntimeError('Install GTK4 + PyGObject for the settings window, or use: creation-of-tux start') from error
    class App(Gtk.Application):
        def __init__(self):
            super().__init__(application_id='io.github.creationoftux.Controls')
        def do_activate(self):
            if self.get_active_window():
                self.get_active_window().present();return
            cfg=control.settings()
            window=Gtk.ApplicationWindow(application=self,title='Creation of Tux')
            window.set_default_size(460,600)
            box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=16)
            for method in ('set_margin_top','set_margin_bottom','set_margin_start','set_margin_end'):
                getattr(box,method)(24)
            window.set_child(box)
            picture=Gtk.Picture.new_for_filename(str(control.ROOT/'docs/preview.png'))
            picture.set_can_shrink(True);picture.set_size_request(400,180)
            box.append(picture)
            title=Gtk.Label(label='Creation of Tux',xalign=0)
            title.add_css_class('title-1');box.append(title)
            box.append(Gtk.Label(label='Live ASCII · Wayland · by Ch3L1k',xalign=0))
            status=Gtk.Label(xalign=0,wrap=True)
            box.append(status)
            def row(label,widget):
                line=Gtk.Box(spacing=12)
                text=Gtk.Label(label=label,xalign=0);text.set_hexpand(True)
                line.append(text);line.append(widget);box.append(line)
                return widget
            columns=row('ASCII columns',Gtk.SpinButton.new_with_range(60,600,10));columns.set_value(cfg['columns'])
            fps=row('Frames per second',Gtk.SpinButton.new_with_range(1,120,1));fps.set_value(cfg['fps'])
            period=row('Seconds per rotation',Gtk.SpinButton.new_with_range(2,120,1));period.set_value(cfg['period'])
            scale=row('Tux size',Gtk.SpinButton.new_with_range(.1,1.5,.05));scale.set_digits(2);scale.set_value(cfg['tux_scale'])
            output=row('Monitors',Gtk.Entry())
            output.set_placeholder_text('All, or DP-1,eDP-1');output.set_text(cfg['output'])
            auto=row('Start when I sign in',Gtk.Switch())
            auto.set_active((control.CONFIG.parent/'autostart/creation-of-tux.desktop').exists())
            hint=Gtk.Label(label='Some compositors require adding an autostart command. See README.',xalign=0,wrap=True)
            hint.add_css_class('dim-label');box.append(hint)
            buttons=Gtk.Box(spacing=8)
            start=Gtk.Button(label='Start');start.add_css_class('suggested-action')
            stop=Gtk.Button(label='Stop')
            apply=Gtk.Button(label='Apply settings')
            for button in (start,stop,apply): buttons.append(button)
            box.append(buttons)
            busy=False
            def update():
                if not busy:
                    status.set_text('● Running' if control.active_pid() else '○ Stopped')
                return True
            def execute(name):
                nonlocal busy
                if busy:return
                try:
                    values=control.validate(dict(columns=columns.get_value_as_int(),fps=fps.get_value_as_int(),
                        period=period.get_value(),tux_scale=scale.get_value(),output=output.get_text().strip()))
                except ValueError as error:
                    status.set_text(str(error));return
                enabled=auto.get_active()
                busy=True;status.set_text('Applying…')
                for button in (start,stop,apply):button.set_sensitive(False)
                def work():
                    error=None
                    try:
                        if name!='stop':
                            control.atomic_json(control.CONFIG/'settings.json',values)
                            control.set_autostart(enabled)
                        if name=='apply':
                            if control.active_pid():control.action('restart')
                        else:control.action(name)
                    except Exception as problem:error=str(problem)
                    def done():
                        nonlocal busy
                        busy=False
                        for button in (start,stop,apply):button.set_sensitive(True)
                        if error:status.set_text(error)
                        else:update()
                        return False
                    GLib.idle_add(done)
                threading.Thread(target=work,daemon=True).start()
            start.connect('clicked',lambda *_:execute('start'))
            stop.connect('clicked',lambda *_:execute('stop'))
            apply.connect('clicked',lambda *_:execute('apply'))
            update()
            timer=GLib.timeout_add_seconds(2,update)
            window.connect('destroy',lambda *_:GLib.source_remove(timer))
            window.present()
    App().run([])
