import gi


gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango, GLib
from gettext import gettext as _

from .connect_dialog import ConnectDialog


class CommandLabel(Gtk.Box):
    def __init__(self, text):
        super().__init__(css_classes=["card"])
        label=Gtk.Label(selectable=True, xalign=0, hexpand=True, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, css_classes=["monospace"])
        label.set_margin_start(12)
        label.set_margin_end(12)
        label.set_margin_top(9)
        label.set_margin_bottom(9)
        label.set_text(text)
        self.append(label)


class SetupDialog(ConnectDialog):
    def __init__(self):
        super().__init__(_("Setup"), GLib.Variant("b", False))
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(Gtk.Label(label=_("To get started, install the Music Player Daemon (<tt>mpd</tt>) with your system package manager, and run the following commands"\
            " to configure and initialize a basic local instance. After that, Plattenalbum should be able to seamlessly connect to it."), use_markup=True, xalign=0, wrap=True))
        box.append(CommandLabel("mkdir ~/.mpd"))
        box.append(CommandLabel('cat << EOF > ~/.mpd/mpd.conf\ndb_file\t\t"~/.mpd/database"\nstate_file\t"~/.mpd/state"\n\n'\
            'audio_output {\n\ttype\t"pulse"\n\tname\t"Music"\n}\nEOF'))
        box.append(CommandLabel("systemctl --user enable --now mpd.socket"))
        self.set_content(box)