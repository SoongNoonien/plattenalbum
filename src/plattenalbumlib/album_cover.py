import gi

gi.require_version("Gtk", "4.0")
from gi.repository import  Gtk


class AlbumCover(Gtk.Widget):
    def __init__(self, **kwargs):
        super().__init__(hexpand=True, **kwargs)
        self._picture=Gtk.Picture(css_classes=["cover"], accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self._picture.set_parent(self)
        self.connect("destroy", lambda *args: self._picture.unparent())

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_size_allocate(self, width, height, baseline):
        self._picture.allocate(width, height, baseline, None)

    def do_measure(self, orientation, for_size):
        return (for_size, for_size, -1, -1)

    def set_paintable(self, paintable):
        if paintable.get_intrinsic_width()/paintable.get_intrinsic_height() >= 1:
            self._picture.set_halign(Gtk.Align.FILL)
            self._picture.set_valign(Gtk.Align.CENTER)
        else:
            self._picture.set_halign(Gtk.Align.CENTER)
            self._picture.set_valign(Gtk.Align.FILL)
        self._picture.set_paintable(paintable)

    def set_alternative_text(self, alt_text):
        self._picture.set_alternative_text(alt_text)