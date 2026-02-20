import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
from gettext import gettext as _


class VolumeControl(Gtk.Box):
    def __init__(self, client):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, margin_start=12)
        self._client=client

        # adjustment
        scale=Gtk.Scale(hexpand=True)
        scale.update_property([Gtk.AccessibleProperty.LABEL], [_("Volume control")])
        self._adjustment=scale.get_adjustment()
        self._adjustment.configure(0, 0, 100, 5, 5, 0)

        # connect
        scale.connect("change-value", self._on_change_value)
        self._client.emitter.connect("volume", self._refresh)

        # packing
        self.append(Gtk.Image(icon_name="audio-speakers-symbolic", accessible_role=Gtk.AccessibleRole.PRESENTATION))
        self.append(scale)

    def _on_change_value(self, scale, scroll, value):
        self._client.setvol(str(int(max(min(value, 100), 0))))

    def _refresh(self, emitter, volume):
        self._adjustment.set_value(max(volume, 0))