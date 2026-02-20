import collections
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk, GObject

from ..duration import Duration
from ..multitag import MultiTag

class SongMetaclass(type(GObject.Object), type(collections.UserDict)):
    pass


class Song(collections.UserDict, GObject.Object, metaclass=SongMetaclass):
    widget=GObject.Property(type=Gtk.Widget, default=None)  # current widget representing the song in the UI
    def __init__(self, data):
        collections.UserDict.__init__(self, data)
        GObject.Object.__init__(self)
    def __setitem__(self, key, value):
        if key == "time":  # time is deprecated https://mpd.readthedocs.io/en/latest/protocol.html#other-metadata
            pass
        elif key == "duration":
            super().__setitem__(key, Duration(value))
        elif key in ("range", "file", "pos", "id", "format", "last-modified"):
            super().__setitem__(key, value)
        else:
            if isinstance(value, list):
                super().__setitem__(key, MultiTag(value))
            else:
                super().__setitem__(key, MultiTag([value]))

    def __missing__(self, key):
        if self.data:
            if key == "albumartist":
                return self["artist"]
            elif key == "albumartistsort":
                return self["albumartist"]
            elif key == "artistsort":
                return self["artist"]
            elif key == "title":
                return MultiTag([GLib.path_get_basename(self.data["file"])])
            elif key == "duration":
                return Duration()
            else:
                return MultiTag([""])
        else:
            return None
