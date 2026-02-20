import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk
from gettext import gettext as _

from .volume_control import VolumeControl


class PlayerMenu(Gtk.PopoverMenu):
    def __init__(self, client):
        super().__init__()
        self._client=client
        self._volume_visible=False

        # volume
        self._volume_control=VolumeControl(client)
        self._volume_item=Gio.MenuItem()
        self._volume_item.set_attribute_value("custom", GLib.Variant("s", "volume"))

        # menu model
        self._volume_section=Gio.Menu()
        menu=Gio.Menu()
        menu.append(_("_Repeat Mode"), "app.repeat")
        menu.append(_("R_andom Mode"), "app.random")
        menu.append(_("_Single Mode"), "app.single")
        menu.append(_("_Pause After Song"), "app.single-oneshot")
        menu.append(_("_Consume Mode"), "app.consume")
        menu.append_section(None, self._volume_section)
        self.set_menu_model(menu)

        # connect
        self._client.emitter.connect("volume", self._on_volume_changed)
        self._client.emitter.connect("disconnected", self._on_disconnected)

    def _on_volume_changed(self, emitter, volume):
        if volume < 0 and self._volume_visible:
            self._volume_section.remove(0)
            self._volume_visible=False
        elif volume >= 0 and not self._volume_visible:
            self._volume_section.append_item(self._volume_item)
            self.add_child(self._volume_control, "volume")
            self._volume_visible=True

    def _on_disconnected(self, *args):
        if self._volume_visible:
            self._volume_section.remove(0)
            self._volume_visible=False