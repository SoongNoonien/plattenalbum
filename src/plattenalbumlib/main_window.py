import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GObject, GLib
from gettext import gettext as _

from .mpris import MPRISInterface
from .duration import Duration
from .dialogs import ConnectDialog, ManualConnectDialog, PreferencesDialog, SetupDialog, ServerInfo
from .browser import Browser
from .player import Player, PlayerBar


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