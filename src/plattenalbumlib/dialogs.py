import gi

from .duration import Duration

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, Pango, GLib
from gettext import gettext as _

class ViewPreferences(Adw.PreferencesGroup):
	def __init__(self, settings):
		super().__init__(title=_("View"))
		toggle_data=(
			(_("_Show Bit Rate"), "show-bit-rate", ""),
		)
		for title, key, subtitle in toggle_data:
			row=Adw.SwitchRow(title=title, subtitle=subtitle, use_underline=True)
			settings.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
			self.add(row)

class BehaviorPreferences(Adw.PreferencesGroup):
	def __init__(self, settings):
		super().__init__(title=_("Behavior"))
		toggle_data=(
			(_("Send _Notification on Title Change"), "send-notify", ""),
			(_("Stop _Playback on Quit"), "stop-on-quit", ""),
			(_("Support “_MPRIS”"), "mpris", _("Disable if “MPRIS” is supported by another client")),
		)
		for title, key, subtitle in toggle_data:
			row=Adw.SwitchRow(title=title, subtitle=subtitle, use_underline=True)
			settings.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
			self.add(row)

class PreferencesDialog(Adw.PreferencesDialog):
	def __init__(self, client, settings):
		super().__init__()
		page=Adw.PreferencesPage()
		page.add(ViewPreferences(settings))
		page.add(BehaviorPreferences(settings))
		self.add(page)

class ConnectDialog(Adw.Dialog):
	def __init__(self, title, target):
		super().__init__(title=title, width_request=360, follows_content_size=True)
		self._clamp=Adw.Clamp(margin_top=24, margin_bottom=24, margin_start=12, margin_end=12)
		connect_button=Gtk.Button(label=_("_Connect"), use_underline=True, action_name="app.connect", action_target=target)
		connect_button.set_css_classes(["suggested-action"])
		cancel_button=Gtk.Button(label=_("Ca_ncel"), use_underline=True)
		cancel_button.connect("clicked", lambda *args: self.close())
		scroll=Gtk.ScrolledWindow(child=self._clamp, propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
		header_bar=Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
		header_bar.pack_start(cancel_button)
		header_bar.pack_end(connect_button)
		toolbar_view=Adw.ToolbarView(content=scroll)
		toolbar_view.add_top_bar(header_bar)
		self._connection_toast=Adw.Toast(title=_("Connection failed"))
		self._toast_overlay=Adw.ToastOverlay(child=toolbar_view)
		self.set_child(self._toast_overlay)
		self.set_default_widget(connect_button)
		self.set_focus(connect_button)

	def set_content(self, widget):
		self._clamp.set_child(widget)

	def connection_error(self):
		self._toast_overlay.add_toast(self._connection_toast)

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

class CommandLabel(Gtk.Box):
	def __init__(self, text):
		super().__init__(css_classes=["card"])
		label=Gtk.Label(selectable=True, xalign=0, hexpand=True, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, css_classes=["monospace"])
		label.set_margin_start(12)
		label.set_margin_end(12)
		label.set_margin_top(9)
		label.set_margin_bottom(9)
		label.set_text(text)
		self.append(label)

class SetupDialog(ConnectDialog):
	def __init__(self):
		super().__init__(_("Setup"), GLib.Variant("b", False))
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
		box.append(Gtk.Label(label=_("To get started, install the Music Player Daemon (<tt>mpd</tt>) with your system package manager, and run the following commands"\
			" to configure and initialize a basic local instance. After that, Plattenalbum should be able to seamlessly connect to it."), use_markup=True, xalign=0, wrap=True))
		box.append(CommandLabel("mkdir ~/.mpd"))
		box.append(CommandLabel('cat << EOF > ~/.mpd/mpd.conf\ndb_file\t\t"~/.mpd/database"\nstate_file\t"~/.mpd/state"\n\n'\
			'audio_output {\n\ttype\t"pulse"\n\tname\t"Music"\n}\nEOF'))
		box.append(CommandLabel("systemctl --user enable --now mpd.socket"))
		self.set_content(box)

class ServerInfo(Adw.Dialog):
	def __init__(self, client, settings):
		super().__init__(title=_("Server Information"), width_request=360, follows_content_size=True)

		# list box
		list_box=Gtk.ListBox(valign=Gtk.Align.START)
		list_box.add_css_class("boxed-list")

		# populate
		display_str={
			"server": _("Server"),
			"protocol": _("Protocol"),
			"uptime": _("Uptime"),
			"playtime": _("Playtime"),
			"artists": _("Artists"),
			"albums": _("Albums"),
			"songs": _("Songs"),
			"db_playtime": _("Total Database Playtime"),
			"db_update": _("Last Database Update")
		}
		stats=client.stats()
		stats["server"]=client.server
		stats["protocol"]=str(client.mpd_version)
		for key in ("uptime","playtime","db_playtime"):
			stats[key]=str(Duration(stats[key]))
		stats["db_update"]=GLib.DateTime.new_from_unix_local(int(stats["db_update"])).format("%x, %X")
		for key in ("server","protocol","uptime","playtime","db_update","db_playtime","artists","albums","songs"):
			row=Adw.ActionRow(activatable=False, selectable=False, subtitle_selectable=True, title=display_str[key], subtitle=stats[key])
			row.add_css_class("property")
			list_box.append(row)

		# packing
		clamp=Adw.Clamp(child=list_box, margin_top=24, margin_bottom=24, margin_start=12, margin_end=12)
		scroll=Gtk.ScrolledWindow(child=clamp, propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
		toolbar_view=Adw.ToolbarView(content=scroll)
		toolbar_view.add_top_bar(Adw.HeaderBar())
		self.set_child(toolbar_view)