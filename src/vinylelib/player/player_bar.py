import gi


gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango
from gettext import gettext as _

from ..cover import FALLBACK_COVER
from ..media_buttons import MediaButtons


class ProgressBar(Gtk.ProgressBar):
    def __init__(self, client):
        super().__init__(valign=Gtk.Align.START, halign=Gtk.Align.FILL)
        self.add_css_class("osd")
        client.emitter.connect("state", self._on_state)
        client.emitter.connect("elapsed", self._on_elapsed)

    def _on_state(self, emitter, state):
        if state == "stop":
            self.set_visible(False)
            self.set_fraction(0.0)

    def _on_elapsed(self, emitter, elapsed, duration):
        if duration > 0:
            self.set_visible(True)
            self.set_fraction(elapsed/duration)
        else:
            self.set_visible(False)
            self.set_fraction(0.0)


class PlayerBar(Gtk.Overlay):
    def __init__(self, client):
        super().__init__()
        self._client=client

        # widgets
        self._cover=Gtk.Picture(css_classes=["cover"], accessible_role=Gtk.AccessibleRole.PRESENTATION, visible=False)
        progress_bar=ProgressBar(client)
        progress_bar.update_property([Gtk.AccessibleProperty.LABEL], [_("Progress bar")])
        self._title=Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self._subtitle=Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, css_classes=["dimmed", "caption"])

        # connect
        self._client.emitter.connect("current-song", self._on_song_changed)
        self._client.emitter.connect("disconnected", self._on_disconnected)

        # packing
        title_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        title_box.add_css_class("toolbar-text")
        title_box.append(self._title)
        title_box.append(self._subtitle)
        box=Gtk.Box()
        box.add_css_class("toolbar")
        box.append(Adw.Clamp(orientation=Gtk.Orientation.VERTICAL, unit=Adw.LengthUnit.PX, maximum_size=34, child=self._cover))
        box.append(title_box)
        box.append(MediaButtons(client))
        self.add_overlay(progress_bar)
        self.set_child(box)

    def _clear_title(self):
        self._title.set_text("")
        self._subtitle.set_text("")

    def _on_song_changed(self, emitter, song, songpos, songid, state):
        if song:
            self._cover.set_visible(True)
            self._title.set_text(song["title"][0])
            self._subtitle.set_text(str(song["artist"]))
        else:
            self._cover.set_visible(False)
            self._clear_title()
        self._cover.set_paintable(self._client.current_cover.get_paintable())

    def _on_disconnected(self, *args):
        self._clear_title()
        self._cover.set_paintable(FALLBACK_COVER)
        self._cover.set_visible(False)