import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib
from gettext import gettext as _

from .client import Client
from .settings import Settings
from .main_window import MainWindow


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