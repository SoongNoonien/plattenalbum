import collections

import gi

from .duration import Duration
from .models import SelectionModel
from .multitag import MultiTag
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gdk, Gtk, Gio, GObject, Pango, Graphene
from gettext import gettext as _


class SongMetaclass(type(GObject.Object), type(collections.UserDict)): pass

class Song(collections.UserDict, GObject.Object, metaclass=SongMetaclass):
	widget=GObject.Property(type=Gtk.Widget, default=None)  # current widget representing the song in the UI
	def __init__(self, data):
		collections.UserDict.__init__(self, data)
		GObject.Object.__init__(self)
	def __setitem__(self, key, value):
		if key == "time":  # time is deprecated https://mpd.readthedocs.io/en/latest/protocol.html#other-metadata
			pass
		elif key == "duration":
			super().__setitem__(key, Duration(value))
		elif key in ("range", "file", "pos", "id", "format", "last-modified"):
			super().__setitem__(key, value)
		else:
			if isinstance(value, list):
				super().__setitem__(key, MultiTag(value))
			else:
				super().__setitem__(key, MultiTag([value]))

	def __missing__(self, key):
		if self.data:
			if key == "albumartist":
				return self["artist"]
			elif key == "albumartistsort":
				return self["albumartist"]
			elif key == "artistsort":
				return self["artist"]
			elif key == "title":
				return MultiTag([GLib.path_get_basename(self.data["file"])])
			elif key == "duration":
				return Duration()
			else:
				return MultiTag([""])
		else:
			return None

class SongListRow(Gtk.Box):
	position=GObject.Property(type=int, default=-1)
	def __init__(self, show_track=True, **kwargs):
		# can_target=False is needed to use Gtk.Widget.pick() in Gtk.ListView
		super().__init__(can_target=False, **kwargs)

		# labels
		self._title=Gtk.Label(xalign=0, single_line_mode=True, ellipsize=Pango.EllipsizeMode.END)
		self._subtitle=Gtk.Label(xalign=0, single_line_mode=True, ellipsize=Pango.EllipsizeMode.END, css_classes=["dimmed", "caption"])
		self._length=Gtk.Label(xalign=1, single_line_mode=True, css_classes=["numeric", "dimmed"])

		# packing
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
		box.append(self._title)
		box.append(self._subtitle)
		self.append(box)
		self.append(self._length)

	def set_song(self, song):
		subtitle=str(song["artist"])
		self._title.set_text(song["title"][0])
		self._subtitle.set_visible(bool(subtitle))
		self._subtitle.set_text(subtitle)
		self._length.set_text(str(song["duration"]))

	def unset_song(self):
		self._title.set_text("")
		self._subtitle.set_text("")
		self._length.set_text("")

class SongMenu(Gtk.PopoverMenu):
	def __init__(self, client, show_album=False):
		super().__init__(has_arrow=False, halign=Gtk.Align.START)
		self.update_property([Gtk.AccessibleProperty.LABEL], [_("Context menu")])
		self._client=client
		self._file=None

		# action group
		action_group=Gio.SimpleActionGroup()
		action=Gio.SimpleAction.new("append", None)
		action.connect("activate", lambda *args: self._client.file_to_playlist(self._file, "append"))
		action_group.add_action(action)
		action=Gio.SimpleAction.new("as-next", None)
		action.connect("activate", lambda *args: self._client.file_to_playlist(self._file, "as-next"))
		action_group.add_action(action)
		if show_album:
			action=Gio.SimpleAction.new("show-album", None)
			action.connect("activate", lambda *args: self._client.show_album(self._file))
			action_group.add_action(action)
		self._show_file_action=Gio.SimpleAction.new("show-file", None)
		self._show_file_action.connect("activate", lambda *args: self._client.show_file(self._file))
		action_group.add_action(self._show_file_action)
		self.insert_action_group("menu", action_group)

		# menu model
		menu=Gio.Menu()
		menu.append(_("_Append"), "menu.append")
		menu.append(_("As _Next"), "menu.as-next")
		subsection=Gio.Menu()
		if show_album:
			subsection.append(_("Show Al_bum"), "menu.show-album")
		subsection.append(_("Show _File"), "menu.show-file")
		menu.append_section(None, subsection)
		self.set_menu_model(menu)

	def open(self, file, x, y):
		self._file=file
		rect=Gdk.Rectangle()
		rect.x,rect.y=x,y
		self.set_pointing_to(rect)
		self._show_file_action.set_enabled(self._client.can_show_file(file))
		self.popup()


class SongList(Gtk.ListView):
	def __init__(self):
		super().__init__(tab_behavior=Gtk.ListTabBehavior.ITEM)
		self.set_model(SelectionModel(Song))

		# factory
		def setup(factory, item):
			item.set_child(SongListRow())
		def bind(factory, item):
			row=item.get_child()
			song=item.get_item()
			row.set_song(song)
			song.set_property("widget", row)
			row.set_property("position", item.get_position())
		def unbind(factory, item):
			row=item.get_child()
			song=item.get_item()
			row.unset_song()
			song.set_property("widget", None)
			row.set_property("position", -1)
		factory=Gtk.SignalListItemFactory()
		factory.connect("setup", setup)
		factory.connect("bind", bind)
		factory.connect("unbind", unbind)
		self.set_factory(factory)

	def _get_focus_row(self):
		return self.get_focus_child().get_first_child()

	def get_focus_popup_point(self):
		computed_point,point=self._get_focus_row().compute_point(self, Graphene.Point.zero())
		if computed_point:
			return (point.x, point.y)
		return (0, 0)

	def get_focus_position(self):
		return self._get_focus_row().get_property("position")

	def get_focus_song(self):
		return self.get_model().get_item(self.get_focus_position())

	def get_position(self, x, y):
		item=self.pick(x,y,Gtk.PickFlags.DEFAULT)
		if item is self or item is None:
			return None
		return item.get_first_child().get_property("position")

	def get_song(self, position):
		return self.get_model().get_item(position)