import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GObject


class Artist(GObject.Object):
    ROLES=('artist', 'composer', 'conductor')
    def __init__(self, name, role):
        GObject.Object.__init__(self)
        self.name=name
        self.role=role
