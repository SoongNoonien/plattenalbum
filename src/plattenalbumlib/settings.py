import gi
from gi.overrides.GObject import GObject

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GObject

class Settings(Gio.Settings):
    BASE_KEY="de.wagnermartin.Plattenalbum"
    # temp settings
    cursor_watch=GObject.Property(type=bool, default=False)
    def __init__(self):
        super().__init__(schema=self.BASE_KEY)