from ..song import Song
from .playlist_view import PlaylistView
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk
from gettext import gettext as _


class PlaylistWindow(Gtk.Stack):
    def __init__(self, client):
        super().__init__(vhomogeneous=False, vexpand=True)
        self._client=client

        # widgets
        self._playlist_view=PlaylistView(self._client)
        self.scroll=Gtk.ScrolledWindow(child=self._playlist_view, propagate_natural_height=True)
        self._adj=self.scroll.get_vadjustment()
        status_page=Adw.StatusPage(icon_name="view-playlist-symbolic", title=_("Playlist is Empty"))
        status_page.add_css_class("compact")
        status_page.add_css_class("no-drop-highlight")

        # scroll button
        overlay=Gtk.Overlay(child=self.scroll)
        self._scroll_button=Gtk.Button(css_classes=["osd", "circular"], tooltip_text=_("Scroll to Current Song"),
            margin_bottom=12, margin_top=12, halign=Gtk.Align.CENTER, visible=False)
        overlay.add_overlay(self._scroll_button)

        # event controller
        drop_target=Gtk.DropTarget()
        drop_target.set_actions(Gdk.DragAction.COPY)
        drop_target.set_gtypes((Song,))
        status_page.add_controller(drop_target)

        # connect
        drop_target.connect("drop", self._on_drop)
        self._scroll_button.connect("clicked", self._on_scroll_button_clicked)
        self._adj.connect("value-changed", self._update_scroll_button_visibility)
        self._playlist_view.get_model().connect("selection-changed", self._update_scroll_button_visibility)
        self._client.emitter.connect("playlist", self._on_playlist_changed)
        self._client.emitter.connect("disconnected", self._on_disconnected)
        self._client.emitter.connect("connection-error", self._on_connection_error)

        # packing
        self.add_named(overlay, "playlist")
        self.add_named(status_page, "empty-playlist")

    def _on_drop(self, drop_target, value, x, y):
        if isinstance(value, Song):
            self._client.add(value["file"])
            return True
        return False

    def _on_playlist_changed(self, emitter, version, length, songpos):
        if length:
            self.set_visible_child_name("playlist")
        else:
            self.set_visible_child_name("empty-playlist")

    def _on_scroll_button_clicked(self, *args):
        if (selected:=self._playlist_view.get_model().get_selected()) is not None:
            self._playlist_view.scroll_to(selected, Gtk.ListScrollFlags.FOCUS, None)
        self._scroll_button.set_visible(False)

    def _update_scroll_button_visibility(self, *args):
        if (selected:=self._playlist_view.get_model().get_selected()) is None:
            self._scroll_button.set_visible(False)
        else:
            row_height=self._adj.get_upper()/self._playlist_view.get_model().get_n_items()
            value=self._adj.get_upper()*selected/self._playlist_view.get_model().get_n_items()+1/2*row_height
            if self._adj.get_value() > value:
                self._scroll_button.set_icon_name("go-up-symbolic")
                self._scroll_button.set_valign(Gtk.Align.START)
                self._scroll_button.set_visible(True)
            elif self._adj.get_value() < value-self.scroll.get_height():
                self._scroll_button.set_icon_name("go-down-symbolic")
                self._scroll_button.set_valign(Gtk.Align.END)
                self._scroll_button.set_visible(True)
            else:
                self._scroll_button.set_visible(False)

    def _on_disconnected(self, *args):
        self.set_visible_child_name("playlist")

    def _on_connection_error(self, *args):
        self.set_visible_child_name("playlist")