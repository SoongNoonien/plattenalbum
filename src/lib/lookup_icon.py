import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

def lookup_icon(icon_name, size, scale=1):
	return Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).lookup_icon(
			icon_name, None, size, scale, Gtk.TextDirection.NONE, Gtk.IconLookupFlags.FORCE_REGULAR)
