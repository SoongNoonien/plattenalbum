import itertools

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GObject
from gettext import gettext as _

from .browsersong import BrowserSongList, BrowserSongRow
from .artist_album import ArtistAlbumRow
from .artist import ArtistList
from .composer import ComposerList
from .composer_album import ComposerAlbumRow


class SearchView(Gtk.Stack):
	__gsignals__={
		"artist-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
		"composer-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
		"album-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,str,str,))
	}
	def __init__(self, client):
		super().__init__()
		self._client=client
		self._results=20  # TODO adjust number of results
		self._song_tags=("title", "artist", "composer", "album", "date")
		self._artist_tags=("albumartist", "albumartistsort")
		self._composer_tags=("composer", "composersort")
		self._album_tags=("album", "albumartist", "albumartistsort", "date")

		# artist list
		self._artist_list=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, tab_behavior=Gtk.ListTabBehavior.ITEM, valign=Gtk.Align.START)
		self._artist_list.add_css_class("boxed-list")

		# composer list
		self._composer_list=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, tab_behavior=Gtk.ListTabBehavior.ITEM, valign=Gtk.Align.START)
		self._composer_list.add_css_class("boxed-list")

		# album list
		self._album_list=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, tab_behavior=Gtk.ListTabBehavior.ITEM, valign=Gtk.Align.START)
		self._album_list.add_css_class("boxed-list")

		# song list
		self._song_list=BrowserSongList(client, show_album=True)
		self._song_list.add_css_class("boxed-list")

		# boxes
		self._artist_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
		self._artist_box.append(Gtk.Label(label=_("Artists"), xalign=0, css_classes=["heading"]))
		self._artist_box.append(self._artist_list)
		self._composer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
		self._composer_box.append(Gtk.Label(label=_("Composers"), xalign=0, css_classes=["heading"]))
		self._composer_box.append(self._composer_list)
		self._album_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
		self._album_box.append(Gtk.Label(label=_("Albums"), xalign=0, css_classes=["heading"]))
		self._album_box.append(self._album_list)
		self._song_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
		self._song_box.append(Gtk.Label(label=_("Songs"), xalign=0, css_classes=["heading"]))
		self._song_box.append(self._song_list)
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=30, margin_start=12, margin_end=12, margin_top=24, margin_bottom=24)
		box.append(self._artist_box)
		box.append(self._composer_box)
		box.append(self._album_box)
		box.append(self._song_box)

		# scroll
		scroll=Gtk.ScrolledWindow(child=Adw.Clamp(child=box))
		self._adj=scroll.get_vadjustment()

		# status page
		status_page=Adw.StatusPage(icon_name="edit-find-symbolic", title=_("No Results"), description=_("Try a different search"))

		# connect
		self._composer_list.connect("row-activated", self._on_composer_activate)
		self._composer_list.connect("keynav-failed", self._on_keynav_failed)
		self._artist_list.connect("row-activated", self._on_artist_activate)
		self._artist_list.connect("keynav-failed", self._on_keynav_failed)
		self._album_list.connect("row-activated", self._on_album_activate)
		self._album_list.connect("keynav-failed", self._on_keynav_failed)

		# packing
		self.add_named(status_page, "no-results")
		self.add_named(scroll, "results")

	def clear(self):
		self._composer_list.remove_all()
		self._artist_list.remove_all()
		self._album_list.remove_all()
		self._song_list.remove_all()
		self._adj.set_value(0.0)
		self.set_visible_child_name("no-results")

	def search(self, search_text):
		self.clear()
		if (keywords:=search_text.split()):
			self._client.restrict_tagtypes(*self._song_tags)
			songs=self._client.search(self._client.get_search_expression(self._song_tags, keywords), "window", f"0:{self._results}")
			self._client.tagtypes("all")
			for song in songs:
				row=BrowserSongRow(song, show_track=False)
				self._song_list.append(row)
			self._song_box.set_visible(self._song_list.get_first_child() is not None)
			albums=self._client.list("album", self._client.get_search_expression(self._album_tags, keywords), "group", "date", "group", "albumartist", "group", "composer")
			for album in itertools.islice(albums, self._results):
				# album_row=ArtistAlbumRow(album)
				album_row=ComposerAlbumRow(album)
				self._album_list.append(album_row)
			self._album_box.set_visible(self._album_list.get_first_child() is not None)
			artists=self._client.list("albumartist", self._client.get_search_expression(self._artist_tags, keywords))
			composers=self._client.list("composer", self._client.get_search_expression(self._composer_tags, keywords))

			for artist in itertools.islice(artists, self._results):
				row=Adw.ActionRow(title=artist["albumartist"], use_markup=False, activatable=True)
				row.add_suffix(Gtk.Image(icon_name="go-next-symbolic", accessible_role=Gtk.AccessibleRole.PRESENTATION))
				self._artist_list.append(row)

			for composer in itertools.islice(composers, self._results):
				row=Adw.ActionRow(title=composer["composer"], use_markup=False, activatable=True)
				row.add_suffix(Gtk.Image(icon_name="go-next-symbolic", accessible_role=Gtk.AccessibleRole.PRESENTATION))
				self._composer_list.append(row)

			self._artist_box.set_visible(self._artist_list.get_first_child() is not None)
			self._composer_box.set_visible(self._composer_list.get_first_child() is not None)
			if self._song_box.get_visible() or self._album_box.get_visible() or self._artist_box.get_visible():
				self.set_visible_child_name("results")

	def _on_composer_activate(self, list_box, row):
		self.emit("composer-selected", row.get_title())

	def _on_artist_activate(self, list_box, row):
		self.emit("artist-selected", row.get_title())

	def _on_album_activate(self, list_box, row):
		self.emit("album-selected", row.album, row.artist, row.date)

	def _on_keynav_failed(self, list_box, direction):
		if (root:=list_box.get_root()) is not None:
			if direction == Gtk.DirectionType.UP:
				root.child_focus(Gtk.DirectionType.TAB_BACKWARD)
			elif direction == Gtk.DirectionType.DOWN:
				root.child_focus(Gtk.DirectionType.TAB_FORWARD)