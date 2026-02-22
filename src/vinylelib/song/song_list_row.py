import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GObject, Pango


class SongListRow(Gtk.Box):
    position=GObject.Property(type=int, default=-1)
    def __init__(self, show_track=True, **kwargs):
        # can_target=False is needed to use Gtk.Widget.pick() in Gtk.ListView
        super().__init__(can_target=False, **kwargs)

        # labels
        self._title=Gtk.Label(xalign=0, single_line_mode=True, ellipsize=Pango.EllipsizeMode.END)
        self._subtitle=Gtk.Label(xalign=0, single_line_mode=True, ellipsize=Pango.EllipsizeMode.END, css_classes=["dimmed", "caption"])
        self._length=Gtk.Label(xalign=1, single_line_mode=True, css_classes=["numeric", "dimmed"])

        # packing
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        box.append(self._title)
        box.append(self._subtitle)
        self.append(box)
        self.append(self._length)

    def set_song(self, song):
        subtitle=str(song["artist"])
        self._title.set_text(song["title"][0])
        self._subtitle.set_visible(bool(subtitle))
        self._subtitle.set_text(subtitle)
        self._length.set_text(str(song["duration"]))

    def unset_song(self):
        self._title.set_text("")
        self._subtitle.set_text("")
        self._length.set_text("")
