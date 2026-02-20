import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GObject


class Artist(GObject.Object):
    def __init__(self, name):
        GObject.Object.__init__(self)
        self.name=name
