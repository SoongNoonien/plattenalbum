import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk
from gettext import gettext as _


class BitRate(Gtk.Label):
	def __init__(self, client, settings):
		super().__init__(xalign=1, single_line_mode=True, css_classes=["caption", "numeric", "dimmed"])
		self._client=client
		settings.bind("show-bit-rate", self, "visible", Gio.SettingsBindFlags.GET)
		self._mask=_("{bitrate} kb/s")

		# connect
		self._client.emitter.connect("bitrate", self._on_bitrate)
		self._client.emitter.connect("disconnected", self._on_disconnected)

	def _on_bitrate(self, emitter, bitrate):
		# handle unknown bitrates: https://github.com/MusicPlayerDaemon/MPD/issues/428#issuecomment-442430365
		if bitrate is None:
			self.set_text("")
		else:
			self.set_text(self._mask.format(bitrate=bitrate))

	def _on_disconnected(self, *args):
		self.set_text("")