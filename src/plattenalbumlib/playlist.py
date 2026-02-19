from .functions import lookup_icon
from .song import Song, SongList

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk
from gettext import gettext as _

class PlaylistMenu(Gtk.PopoverMenu):
    def __init__(self, client):
        super().__init__(has_arrow=False, halign=Gtk.Align.START)
        self.update_property([Gtk.AccessibleProperty.LABEL], [_("Context menu")])
        self._client=client
        self._file=None
        self._position=None

        # action group
        action_group=Gio.SimpleActionGroup()
        self._remove_action=Gio.SimpleAction.new("delete", None)
        self._remove_action.connect("activate", lambda *args: self._client.delete(self._position))
        action_group.add_action(self._remove_action)
        self._show_album_action=Gio.SimpleAction.new("show-album", None)
        self._show_album_action.connect("activate", lambda *args: self._client.show_album(self._file))
        action_group.add_action(self._show_album_action)
        self._show_file_action=Gio.SimpleAction.new("show-file", None)
        self._show_file_action.connect("activate", lambda *args: self._client.show_file(self._file))
        action_group.add_action(self._show_file_action)
        self.insert_action_group("menu", action_group)

        # menu model
        menu=Gio.Menu()
        menu.append(_("_Remove"), "menu.delete")
        menu.append(_("Show Al_bum"), "menu.show-album")
        menu.append(_("Show _File"), "menu.show-file")
        mpd_section=Gio.Menu()
        mpd_section.append(_("_Enqueue Album"), "app.enqueue")
        mpd_section.append(_("_Tidy"), "app.tidy")
        mpd_section.append(_("_Clear"), "app.clear")
        menu.append_section(None, mpd_section)
        self.set_menu_model(menu)

    def open(self, file, position, x, y):
        self._file=file
        self._position=position
        rect=Gdk.Rectangle()
        rect.x,rect.y=x,y
        self.set_pointing_to(rect)
        if file is None or position is None:
            self._remove_action.set_enabled(False)
            self._show_album_action.set_enabled(False)
            self._show_file_action.set_enabled(False)
        else:
            self._remove_action.set_enabled(True)
            self._show_album_action.set_enabled(self._client.can_show_album(file))
            self._show_file_action.set_enabled(self._client.can_show_file(file))
        self.popup()


class PlaylistView(SongList):
    def __init__(self, client):
        super().__init__()
        self._client=client
        self._playlist_version=None
        self._activate_on_release=False
        self._autoscroll=True
        self._highlighted_widget=None
        self.add_css_class("playlist")
        self.add_css_class("no-drop-highlight")

        # menu
        self._menu=PlaylistMenu(client)
        self._menu.set_parent(self)

        # action group
        action_group=Gio.SimpleActionGroup()
        action=Gio.SimpleAction.new("menu", None)
        action.connect("activate", self._on_menu)
        action_group.add_action(action)
        action=Gio.SimpleAction.new("delete", None)
        action.connect("activate", self._on_delete)
        action_group.add_action(action)
        self.insert_action_group("view", action_group)

        # shortcuts
        self.add_shortcut(Gtk.Shortcut.new(Gtk.KeyvalTrigger.new(Gdk.KEY_Menu, 0), Gtk.NamedAction.new("view.menu")))
        self.add_shortcut(Gtk.Shortcut.new(Gtk.KeyvalTrigger.new(Gdk.KEY_F10, Gdk.ModifierType.SHIFT_MASK), Gtk.NamedAction.new("view.menu")))
        self.add_shortcut(Gtk.Shortcut.new(Gtk.KeyvalTrigger.new(Gdk.KEY_Delete, 0), Gtk.NamedAction.new("view.delete")))

        # event controller
        button_controller=Gtk.GestureClick(button=0)
        self.add_controller(button_controller)
        long_press_controller=Gtk.GestureLongPress()
        self.add_controller(long_press_controller)
        drag_source=Gtk.DragSource()
        drag_source.set_icon(lookup_icon("audio-x-generic", 32, self.get_scale_factor()), 0, 0)
        drag_source.set_actions(Gdk.DragAction.MOVE)
        self.add_controller(drag_source)
        drop_target=Gtk.DropTarget()
        drop_target.set_actions(Gdk.DragAction.COPY|Gdk.DragAction.MOVE)
        drop_target.set_gtypes((int,Song,))
        self.add_controller(drop_target)
        drop_motion=Gtk.DropControllerMotion()
        self.add_controller(drop_motion)

        # connect
        self.connect("activate", self._on_activate)
        button_controller.connect("pressed", self._on_button_pressed)
        button_controller.connect("stopped", self._on_button_stopped)
        button_controller.connect("released", self._on_button_released)
        long_press_controller.connect("pressed", self._on_long_pressed)
        drag_source.connect("prepare", self._on_drag_prepare)
        drop_target.connect("drop", self._on_drop)
        drop_motion.connect("motion", self._on_drop_motion)
        drop_motion.connect("leave", self._on_drop_leave)
        self._client.emitter.connect("playlist", self._on_playlist_changed)
        self._client.emitter.connect("current-song", self._on_song_changed)
        self._client.emitter.connect("disconnected", self._on_disconnected)

    def _clear(self, *args):
        self._menu.popdown()
        self._playlist_version=None
        self.get_model().clear()

    def _refresh_selection(self, song):
        if song is None:
            self.get_model().unselect()
        else:
            self.get_model().select(int(song))

    def _on_button_pressed(self, controller, n_press, x, y):
        if (position:=self.get_position(x,y)) is None:
            if controller.get_current_button() == 3 and n_press == 1:
                self._menu.open(None, None, x, y)
        else:
            if controller.get_current_button() == 1 and n_press == 1:
                self._activate_on_release=True
            elif controller.get_current_button() == 2 and n_press == 1:
                self._client.delete(position)
            elif controller.get_current_button() == 3 and n_press == 1:
                self._menu.open(self.get_song(position)["file"], position, x, y)

    def _on_button_stopped(self, controller):
        self._activate_on_release=False

    def _on_button_released(self, controller, n_press, x, y):
        if self._activate_on_release and (position:=self.get_position(x,y)) is not None:
            self._autoscroll=False
            self._client.play(position)
        self._activate_on_release=False

    def _on_long_pressed(self, controller, x, y):
        if (position:=self.get_position(x,y)) is None:
            self._menu.open(None, None, x, y)
        else:
            self._menu.open(self.get_song(position)["file"], position, x, y)

    def _on_activate(self, listview, pos):
        self._autoscroll=False
        self._client.play(pos)

    def _on_playlist_changed(self, emitter, version, length, songpos):
        self._menu.popdown()
        self._client.restrict_tagtypes("track", "title", "artist", "composer", "album", "date")
        if self._playlist_version is not None:
            songs=self._client.plchanges(self._playlist_version)
        else:
            songs=self._client.playlistinfo()
        self._client.tagtypes("all")
        for song in songs:
            self.get_model().set(int(song["pos"]), song)
        self.get_model().clear(length)
        self._refresh_selection(songpos)
        if self._playlist_version is None and (selected:=self.get_model().get_selected()) is not None:  # always scroll to song on startup
            self.scroll_to(selected, Gtk.ListScrollFlags.FOCUS, None)
        self._playlist_version=version

    def _on_song_changed(self, emitter, song, songpos, songid, state):
        self._refresh_selection(songpos)
        if self._autoscroll:
            if (selected:=self.get_model().get_selected()) is not None and state == "play":
                self.scroll_to(selected, Gtk.ListScrollFlags.FOCUS, None)
                adj=self.get_vadjustment()
                value=adj.get_upper()*selected/self.get_model().get_n_items()-self.get_parent().get_height()*0.3
                if value >= adj.get_value():
                    adj.set_value(value)
        else:
            self._autoscroll=True

    def _on_menu(self, action, state):
        self._menu.open(self.get_focus_song()["file"], self.get_focus_position(), *self.get_focus_popup_point())

    def _on_delete(self, action, state):
        self._client.delete(self.get_focus_position())

    def _on_drag_prepare(self, drag_source, x, y):
        if (position:=self.get_position(x,y)) is not None:
            return Gdk.ContentProvider.new_for_value(position)

    def _on_drop(self, drop_target, value, x, y):
        self._remove_highlight()
        item=self.pick(x,y,Gtk.PickFlags.DEFAULT)
        if isinstance(value, int):
            if item is self:
                position=self.get_model().get_n_items()-1
            else:
                position=item.get_first_child().get_property("position")
            if value != position:
                self._client.move(value, position)
                return True
        elif isinstance(value, Song):
            if item is self:
                position=self.get_model().get_n_items()
            else:
                position=item.get_first_child().get_property("position")
            self._client.add(value["file"], position)
            return True
        return False

    def _remove_highlight(self):
        if self._highlighted_widget is not None:
            self._highlighted_widget.remove_css_class("drop-row")
        self._highlighted_widget=None

    def _on_drop_motion(self, drop_motion, x, y):
        self._remove_highlight()
        item=self.pick(x,y,Gtk.PickFlags.DEFAULT)
        if item is not self:
            item.add_css_class("drop-row")
            self._highlighted_widget=item

    def _on_drop_leave(self, drop_target):
        self._remove_highlight()

    def _on_disconnected(self, *args):
        self._clear()


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