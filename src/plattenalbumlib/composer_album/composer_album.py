from gettext import gettext as _
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GObject, Gtk

from ..album import Album


class ComposerAlbum(Album):
    def __init__(self, composer, name, date):
        super().__init__(name, date)
        self.composer=composer


