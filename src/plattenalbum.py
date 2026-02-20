#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Plattenalbum - MPD Client.
# Copyright (C) 2020-2026 Martin Wagner <martin.wagner.dev@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GObject, GLib

import sys
import signal
import locale
from gettext import gettext as _, ngettext, textdomain, bindtextdomain

try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error as e:
    print(e)
locale.bindtextdomain("de.wagnermartin.Plattenalbum", "/usr/local/share/locale")
locale.textdomain("de.wagnermartin.Plattenalbum")
bindtextdomain("de.wagnermartin.Plattenalbum", localedir="/usr/local/share/locale")
textdomain("de.wagnermartin.Plattenalbum")
Gio.Resource._register(Gio.resource_load(GLib.build_filenamev(["/usr/local/share/de.wagnermartin.Plattenalbum", "de.wagnermartin.Plattenalbum.gresource"])))

from plattenalbumlib.mpris import MPRISInterface
from plattenalbumlib.duration import Duration
from plattenalbumlib.client import Client
from plattenalbumlib.settings import Settings
from plattenalbumlib.dialogs import  ConnectDialog, ManualConnectDialog, PreferencesDialog, SetupDialog, ServerInfo
from plattenalbumlib.browser import Browser
from plattenalbumlib.player import Player
from plattenalbumlib.player_bar import PlayerBar

###############
# main window #
###############

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, client, settings, **kwargs):
        super().__init__(title="Plattenalbum", icon_name="de.wagnermartin.Plattenalbum", height_request=294, width_request=360, **kwargs)
        self.set_default_icon_name("de.wagnermartin.Plattenalbum")
        self._client=client
        self._settings=settings
        self._suspend_inhibit=0

        # MPRIS
        MPRISInterface(self, self._client, self._settings)

        # widgets
        self._browser=Browser(self._client, self._settings)
        player=Player(self._client, self._settings)
        self._updating_toast=Adw.Toast(title=_("Database is being updated"), timeout=0)
        self._updated_toast=Adw.Toast(title=_("Database updated"))
        self._a_b_loop_toast=Adw.Toast(priority=Adw.ToastPriority.HIGH)

        # actions
        simple_actions_data=("close", "search", "preferences", "manual-connect", "server-info")
        for name in simple_actions_data:
            action=Gio.SimpleAction.new(name, None)
            action.connect("activate", getattr(self, ("_on_"+name.replace("-","_"))))
            self.add_action(action)

        # sidebar layout
        overlay_split_view=Adw.OverlaySplitView(
            sidebar_position=Gtk.PackType.END, min_sidebar_width=300, max_sidebar_width=500, sidebar_width_fraction=0.30)
        overlay_split_view.set_content(Adw.LayoutSlot(id="browser"))
        overlay_split_view.set_sidebar(Adw.LayoutSlot(id="player"))
        sidebar_layout=Adw.Layout(content=overlay_split_view, name="sidebar")

        # bottom sheet layout
        content_bin=Adw.Bin(child=Adw.LayoutSlot(id="browser"))
        self._bottom_sheet=Adw.BottomSheet(content=content_bin, sheet=Adw.LayoutSlot(id="player"), bottom_bar=PlayerBar(client))
        self._bottom_sheet.bind_property("bottom-bar-height", content_bin, "margin-bottom", GObject.BindingFlags.DEFAULT)
        bottom_sheet_layout=Adw.Layout(content=self._bottom_sheet, name="bottom-sheet")

        # multi layout view
        multi_layout_view=Adw.MultiLayoutView()
        multi_layout_view.add_layout(sidebar_layout)
        multi_layout_view.add_layout(bottom_sheet_layout)
        multi_layout_view.set_child("browser", self._browser)
        multi_layout_view.set_child("player", player)
        multi_layout_view.set_layout_name("sidebar")

        # breakpoint
        break_point=Adw.Breakpoint()
        break_point.set_condition(Adw.BreakpointCondition.parse(f"max-width: 620sp"))
        break_point.add_setter(multi_layout_view, "layout-name", "bottom-sheet")
        self.add_breakpoint(break_point)

        # status page
        status_page=Adw.StatusPage(icon_name="de.wagnermartin.Plattenalbum", title=_("Connect to Your Music"))
        status_page.set_description(_("To use Plattenalbum, an instance of the Music Player Daemon "\
            "needs to be set up and running on this device or another one on the network"))
        connect_button=Gtk.Button(label=_("_Connect"), use_underline=True, action_name="app.connect", action_target=GLib.Variant("b", False))
        connect_button.set_css_classes(["suggested-action", "pill"])
        manual_connect_button=Gtk.Button(label=_("Connect _Manually"), use_underline=True, action_name="win.manual-connect")
        manual_connect_button.add_css_class("pill")
        button_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, spacing=12)
        button_box.append(connect_button)
        button_box.append(manual_connect_button)
        status_page.set_child(button_box)
        menu=Gio.Menu()
        menu.append(_("_Preferences"), "win.preferences")
        menu.append(_("_Keyboard Shortcuts"), "app.shortcuts")
        menu.append(_("_About Plattenalbum"), "app.about")
        menu_button=Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text=_("Main Menu"), primary=True, menu_model=menu)
        header_bar=Adw.HeaderBar()
        header_bar.pack_end(menu_button)
        status_page_toolbar_view=Adw.ToolbarView(content=status_page)
        status_page_toolbar_view.add_top_bar(header_bar)

        # stack
        self._status_page_stack=Gtk.Stack()
        self._status_page_stack.add_named(multi_layout_view, "content")
        self._status_page_stack.add_named(status_page_toolbar_view, "status-page")

        # event controller
        controller_focus=Gtk.EventControllerFocus()
        self._browser.search_entry.add_controller(controller_focus)

        # connect
        multi_layout_view.connect("notify::layout-name", self._on_layout_name)
        controller_focus.connect("enter", self._on_search_entry_focus_event, True)
        controller_focus.connect("leave", self._on_search_entry_focus_event, False)
        self._settings.connect_after("notify::cursor-watch", self._on_cursor_watch)
        self._client.emitter.connect("current-song", self._on_song_changed)
        self._client.emitter.connect("state", self._on_state)
        self._client.emitter.connect("connected", self._on_connected)
        self._client.emitter.connect("disconnected", self._on_disconnected)
        self._client.emitter.connect("connection_error", self._on_connection_error)
        self._client.emitter.connect("updating-db", self._on_updating_db)
        self._client.emitter.connect("updated-db", self._on_updated_db)
        self._client.emitter.connect("a-b-loop", self._on_a_b_loop)
        self._client.emitter.connect("show-album", lambda *args: self._bottom_sheet.set_open(False))

        # packing
        self._toast_overlay=Adw.ToastOverlay(child=self._status_page_stack)
        self.set_content(self._toast_overlay)

    def open(self):
        # bring player in consistent state
        self._client.emitter.emit("disconnected")
        self._client.emitter.emit("connecting")
        # set default window size
        self.set_default_size(self._settings.get_int("width"), self._settings.get_int("height"))
        self._settings.bind("width", self, "default-width", Gio.SettingsBindFlags.SET)
        self._settings.bind("height", self, "default-height", Gio.SettingsBindFlags.SET)
        if self._settings.get_boolean("maximize"):
            self.maximize()
        self.present()
        # ensure window is visible
        main=GLib.main_context_default()
        while main.pending():
            main.iteration()
        self._settings.bind("maximize", self, "maximized", Gio.SettingsBindFlags.SET)
        self._client.try_connect(self._settings.get_boolean("manual-connection"))

    def _clear_title(self):
        self.set_title("Plattenalbum")

    def _on_close(self, action, param):
        if (dialog:=self.get_visible_dialog()) is None:
            self.close()
        else:
            dialog.close()

    def _on_search(self, action, param):
        self._browser.search()

    def _on_preferences(self, action, param):
        if self.get_visible_dialog() is None:
            PreferencesDialog(self._client, self._settings).present(self)

    def _on_manual_connect(self, action, param):
        if self.get_visible_dialog() is None:
            ManualConnectDialog(self._settings).present(self)

    def _on_server_info(self, action, param):
        if self.get_visible_dialog() is None:
            ServerInfo(self._client, self._settings).present(self)

    def _on_search_entry_focus_event(self, controller, focus):
        if focus:
            self.get_application().set_accels_for_action("app.toggle-play", [])
            self.get_application().set_accels_for_action("app.a-b-loop", [])
        else:
            self.get_application().set_accels_for_action("app.toggle-play", ["space"])
            self.get_application().set_accels_for_action("app.a-b-loop", ["l"])

    def _on_song_changed(self, emitter, song, songpos, songid, state):
        if song:
            self.set_title(song["title"][0])
        else:
            self._clear_title()

    def _on_state(self, emitter, state):
        if state == "play":
            self._suspend_inhibit=self.get_application().inhibit(self, Gtk.ApplicationInhibitFlags.SUSPEND, _("Playing music"))
        elif self._suspend_inhibit:
            self.get_application().uninhibit(self._suspend_inhibit)
            self._suspend_inhibit=0

    def _on_connected(self, *args):
        if (dialog:=self.get_visible_dialog()) is not None:
            dialog.close()
        self._status_page_stack.set_visible_child_name("content")
        self.lookup_action("server-info").set_enabled(True)

    def _on_disconnected(self, *args):
        self._clear_title()
        self.lookup_action("server-info").set_enabled(False)
        self._updating_toast.dismiss()
        if self._suspend_inhibit:
            self.get_application().uninhibit(self._suspend_inhibit)
            self._suspend_inhibit=0

    def _on_connection_error(self, *args):
        if self._status_page_stack.get_visible_child_name() == "status-page":
            if (dialog:=self.get_visible_dialog()) is None:
                SetupDialog().present(self)
            elif isinstance(dialog, ConnectDialog):
                dialog.connection_error()
        else:
            self._status_page_stack.set_visible_child_name("status-page")

    def _on_updating_db(self, *args):
        self._toast_overlay.add_toast(self._updating_toast)

    def _on_updated_db(self, *args):
        self._updating_toast.dismiss()
        self._toast_overlay.add_toast(self._updated_toast)

    def _on_a_b_loop(self, emitter, first_mark, second_mark):
        if first_mark < 0.0:
            title=_("Cleared A‐B loop")
        else:
            if second_mark < 0.0:
                title=_("Started A‐B loop at {start}").format(start=Duration(first_mark))
            else:
                title=_("Activated A‐B loop from {start} to {end}").format(start=Duration(first_mark), end=Duration(second_mark))
        self._a_b_loop_toast.set_title(title)
        self._toast_overlay.add_toast(self._a_b_loop_toast)

    def _on_cursor_watch(self, obj, typestring):
        if obj.get_property("cursor-watch"):
            self.set_cursor_from_name("progress")
        else:
            self.set_cursor_from_name(None)

    def _on_layout_name(self, obj, *args):
        if obj.get_layout_name() == "bottom-sheet":
            self._bottom_sheet.set_open(False)

###############
# application #
###############

class Plattenalbum(Adw.Application):
    def __init__(self):
        super().__init__(application_id="de.wagnermartin.Plattenalbum", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option("debug", ord("d"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE, _("Debug mode"), None)
        self._settings=Settings()
        self._client=Client(self._settings)
        self._window=None

        # actions
        action=Gio.SimpleAction.new("about", None)
        action.connect("activate", self._on_about)
        self.add_action(action)
        action=Gio.SimpleAction.new("quit", None)
        action.connect("activate", self._on_quit)
        self.add_action(action)

        # mpd actions
        self._disable_on_stop_data=["next","previous","seek-forward","seek-backward","a-b-loop"]
        self._disable_no_song_data=["tidy","enqueue"]
        self._enable_disable_on_playlist_data=["toggle-play","clear"]
        self._enable_on_reconnect_data=["stop","update","disconnect"]
        self._data=self._disable_on_stop_data+self._disable_no_song_data+self._enable_on_reconnect_data+self._enable_disable_on_playlist_data
        for name in self._data:
            action=Gio.SimpleAction.new(name, None)
            action.connect("activate", getattr(self, ("_on_"+name.replace("-","_"))))
            self.add_action(action)
        playback_data=["repeat","random","single","single-oneshot","consume"]
        self._enable_on_reconnect_data+=playback_data
        self._data+=playback_data
        for name in playback_data:
            action=Gio.SimpleAction.new_stateful(name , None, GLib.Variant("b", False))
            handler=action.connect("notify::state", self._on_mode_change, name)
            self.add_action(action)
            self._client.emitter.connect(name, self._update_action, action, handler)
        self._connect_action=Gio.SimpleAction.new("connect", GLib.VariantType.new("b"))
        self._connect_action.connect("activate", self._on_connect)
        self.add_action(self._connect_action)

        # accelerators
        action_accels=(
            ("app.quit", ["<Ctrl>q"]),("win.close", ["<Ctrl>w"]),("win.preferences", ["<Ctrl>comma"]),("win.search", ["<Ctrl>f"]),
            ("win.server-info", ["<Ctrl>i"]),("app.disconnect", ["<Ctrl>d"]),("app.update", ["F5"]),("app.clear", ["<Shift>Delete"]),
            ("app.toggle-play", ["space"]),("app.stop", ["<Ctrl>space"]),("app.next", ["<Ctrl>k"]),("app.previous", ["<Shift><Ctrl>k"]),
            ("app.repeat", ["<Ctrl>r"]),("app.random", ["<Ctrl>n"]),("app.single", ["<Ctrl>s"]),("app.consume", ["<Ctrl>o"]),
            ("app.single-oneshot", ["<Ctrl>p"]),("app.seek-forward", ["<Ctrl>plus"]),("app.seek-backward", ["<Ctrl>minus"]),
            ("app.a-b-loop", ["l"]),("app.enqueue", ["<Ctrl>e"]),("app.tidy", ["<Ctrl>t"]),("menu.delete", ["Delete"])
        )
        for action, accels in action_accels:
            self.set_accels_for_action(action, accels)

        # connect
        self._client.emitter.connect("state", self._on_state)
        self._client.emitter.connect("current-song", self._on_song_changed)
        self._client.emitter.connect("playlist", self._on_playlist_changed)
        self._client.emitter.connect("disconnected", self._on_disconnected)
        self._client.emitter.connect("connected", self._on_connected)

    def do_activate(self):
        if self._window is None:
            self._window=MainWindow(self._client, self._settings, application=self)
            self._window.connect("close-request", self._on_quit)
            self._window.open()
        else:
            self._window.present()

    def do_shutdown(self):
        Adw.Application.do_shutdown(self)
        if self._settings.get_boolean("stop-on-quit") and self._client.connected():
            self._client.stop()
        self.withdraw_notification("title-change")

    def do_command_line(self, command_line):
        # convert GVariantDict -> GVariant -> dict
        options=command_line.get_options_dict().end().unpack()
        if "debug" in options:
            import logging
            logging.basicConfig(level=logging.DEBUG)
        self.activate()
        return 0

    def _on_about(self, *args):
        dialog=Adw.AboutDialog.new_from_appdata("/de/wagnermartin/Plattenalbum/de.wagnermartin.Plattenalbum.metainfo.xml")
        dialog.set_copyright("© 2020-2026 Martin Wagner")
        dialog.set_developers(["Martin Wagner <martin.wagner.dev@gmail.com>"])
        dialog.set_translator_credits(_("translator-credits"))
        dialog.present(self._window)

    def _on_quit(self, *args):
        self.quit()

    def _on_toggle_play(self, action, param):
        self._client.toggle_play()

    def _on_stop(self, action, param):
        self._client.stop()

    def _on_next(self, action, param):
        self._client.next()

    def _on_previous(self, action, param):
        self._client.previous()

    def _on_seek_forward(self, action, param):
        self._client.seekcur("+10")

    def _on_seek_backward(self, action, param):
        self._client.seekcur("-10")

    def _on_a_b_loop(self, action, param):
        self._client.a_b_loop()

    def _on_tidy(self, action, param):
        self._client.tidy_playlist()

    def _on_enqueue(self, action, param):
        song=self._client.currentsong()
        self._client.album_to_playlist(song["albumartist"][0], song["album"][0], song["date"][0], "enqueue")

    def _on_clear(self, action, param):
        self._client.clear()

    def _on_update(self, action, param):
        self._client.update()

    def _update_action(self, emitter, value, action, handler):
        action.handler_block(handler)
        action.set_state(GLib.Variant("b", value))
        action.handler_unblock(handler)

    def _on_mode_change(self, action, typestring, name):
        if name == "single-oneshot":
            self._client.single("oneshot" if action.get_state() else "0")
        else:
            getattr(self._client, name)("1" if action.get_state() else "0")

    def _on_disconnect(self, action, param):
        self._client.disconnect()

    def _on_connect(self, action, param):
        self._client.try_connect(param.get_boolean())

    def _on_state(self, emitter, state):
        state_dict={"play": True, "pause": True, "stop": False}
        for action in self._disable_on_stop_data:
            self.lookup_action(action).set_enabled(state_dict[state])

    def _on_song_changed(self, emitter, song, songpos, songid, state):
        for action in self._disable_no_song_data:
            self.lookup_action(action).set_enabled(songpos is not None)
        if song:
            if self._settings.get_boolean("send-notify") and not self._window.is_active() and state == "play":
                notify=Gio.Notification()
                notify.set_title(_("Next Title is Playing"))
                if artist:=song["artist"]:
                    body=_("Now playing “{title}” by “{artist}”").format(title=song["title"][0], artist=str(artist))
                else:
                    body=_("Now playing “{title}”").format(title=song["title"][0])
                notify.set_body(body)
                notify.add_button(_("Skip"), "app.next")
                self.send_notification("title-change", notify)
            else:
                self.withdraw_notification("title-change")
        else:
            if self._settings.get_boolean("send-notify") and not self._window.is_active():
                notify=Gio.Notification()
                notify.set_title(_("Playback Finished"))
                notify.set_body(_("The playlist is over"))
                self.send_notification("title-change", notify)
            else:
                self.withdraw_notification("title-change")

    def _on_playlist_changed(self, emitter, version, length, songpos):
        for action in self._enable_disable_on_playlist_data:
            self.lookup_action(action).set_enabled(length > 0)

    def _on_disconnected(self, *args):
        self._connect_action.set_enabled(True)
        for action in self._data:
            self.lookup_action(action).set_enabled(False)

    def _on_connected(self, *args):
        self._connect_action.set_enabled(False)
        for action in self._enable_on_reconnect_data:
            self.lookup_action(action).set_enabled(True)

if __name__ == "__main__":
    app=Plattenalbum()
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # allow using ctrl-c to terminate
    app.run(sys.argv)

