import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
from gettext import gettext as _

from ..playlist import PlaylistWindow
from ..lyrics import LyricsWindow
from ..cover import FALLBACK_COVER
from .playback_controls import PlaybackControls
from .player_menu import PlayerMenu
class Player(Adw.Bin):
    def __init__(self, client, settings):
        super().__init__(width_request=300, height_request=200)
        self._client=client

        # widgets
        self._cover=Gtk.Picture(css_classes=["cover"], accessible_role=Gtk.AccessibleRole.PRESENTATION,
            halign=Gtk.Align.CENTER, margin_start=12, margin_end=12, margin_bottom=6, visible=False)
        self._lyrics_window=LyricsWindow()
        playlist_window=PlaylistWindow(client)
        self._playback_controls=PlaybackControls(client, settings)
        self._playback_controls.set_visible(False)

        # box
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(Gtk.WindowHandle(child=self._cover))
        box.append(playlist_window)

        # stack
        self._stack=Adw.ViewStack(vhomogeneous=False, enable_transitions=True)
        self._stack.add_titled_with_icon(box, "playlist", _("Playlist"), "view-playlist-symbolic")
        self._stack.add_titled_with_icon(self._lyrics_window, "lyrics", _("Lyrics"), "view-lyrics-symbolic")

        # playlist page
        self._playlist_page=self._stack.get_page(box)

        # view switcher
        view_switcher=Adw.InlineViewSwitcher(stack=self._stack, display_mode=Adw.InlineViewSwitcherDisplayMode.ICONS)
        view_switcher.add_css_class("flat")

        # header bar
        header_bar=Adw.HeaderBar(show_title=False)
        header_bar.pack_start(view_switcher)
        header_bar.pack_end(Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text=_("Player Menu"), popover=PlayerMenu(client)))

        # connect
        self._stack.connect("notify::visible-child-name", self._on_visible_child_name)
        self._client.emitter.connect("current-song", self._on_song_changed)
        self._client.emitter.connect("playlist", self._on_playlist_changed)
        self._client.emitter.connect("disconnected", self._on_disconnected)
        self._client.emitter.connect("connected", self._on_connected)

        # packing
        toolbar_view=Adw.ToolbarView()
        toolbar_view.add_top_bar(header_bar)
        toolbar_view.set_content(self._stack)
        toolbar_view.add_bottom_bar(self._playback_controls)
        self.set_child(toolbar_view)

    def _on_visible_child_name(self, *args):
        if self._stack.get_visible_child_name() == "lyrics":
            self._lyrics_window.load()
        elif self._stack.get_visible_child_name() == "playlist":
            self._playlist_page.set_needs_attention(False)

    def _on_song_changed(self, emitter, song, songpos, songid, state):
        if song:
            self._cover.set_visible(True)
            self._lyrics_window.set_property("song", song)
            if self._stack.get_visible_child_name() == "lyrics":
                self._lyrics_window.load()
        else:
            self._cover.set_visible(False)
            self._lyrics_window.set_property("song", None)
        self._cover.set_paintable(self._client.current_cover.get_paintable())

    def _on_playlist_changed(self, emitter, version, length, songpos):
        self._playback_controls.set_visible(length > 0)
        if self._stack.get_visible_child_name() != "playlist":
            self._playlist_page.set_needs_attention(True)

    def _on_disconnected(self, *args):
        self._cover.set_paintable(FALLBACK_COVER)
        self._cover.set_visible(False)
        self._lyrics_window.set_property("song", None)
        self._stack.set_visible_child_name("playlist")

    def _on_connected(self, *args):
        self._stack.set_visible_child_name("playlist")