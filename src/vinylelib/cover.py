import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib

FALLBACK_COVER=Gdk.Paintable.new_empty(1, 1)

class FallbackCover():
    def get_paintable(self):
        return FALLBACK_COVER

class BinaryCover(bytes):
    def get_paintable(self):
        try:
            paintable=Gdk.Texture.new_from_bytes(GLib.Bytes.new(self))
        except gi.repository.GLib.Error:  # load fallback if cover can't be loaded
            paintable=FALLBACK_COVER
        return paintable

class FileCover(str):
    def get_paintable(self):
        try:
            paintable=Gdk.Texture.new_from_filename(self)
        except gi.repository.GLib.Error:  # load fallback if cover can't be loaded
            paintable=FALLBACK_COVER
        return paintable
