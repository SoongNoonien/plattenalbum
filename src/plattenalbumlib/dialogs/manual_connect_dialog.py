import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Gio, GLib
from gettext import gettext as _

from .connect_dialog import ConnectDialog


class ManualConnectDialog(ConnectDialog):
    def __init__(self, settings):
        super().__init__(_("Manual Connection"), GLib.Variant("b", True))
        list_box=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        list_box.add_css_class("boxed-list")
        hostname_row=Adw.EntryRow(title=_("Host"))
        settings.bind("host", hostname_row, "text", Gio.SettingsBindFlags.DEFAULT)
        list_box.append(hostname_row)
        port_row=Adw.SpinRow.new_with_range(0, 65535, 1)
        port_row.set_title(_("Port"))
        settings.bind("port", port_row, "value", Gio.SettingsBindFlags.DEFAULT)
        list_box.append(port_row)
        password_row=Adw.PasswordEntryRow(title=_("Password (optional)"))
        settings.bind("password", password_row, "text", Gio.SettingsBindFlags.DEFAULT)
        list_box.append(password_row)
        self.set_content(list_box)