
from gettext import gettext as _
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk, GObject, Pango

from .album import Album
from .album_list_row import AlbumListRow
from .album_page import AlbumPage
from .browsersong import BrowserSongRow
from .duration import Duration
from .models import SelectionModel


class ArtistAlbum(Album):
	def __init__(self, artist, name, date):
		super().__init__(name, date)
		self.artist=artist


class ArtistAlbumListRow(AlbumListRow):
	def __init__(self, client):
		super().__init__(client)

	def set_album(self, album):
		super().set_album(album)
		if album.cover is None:
			self._client.tagtypes("clear")
			song=self._client.find("albumartist", album.artist, "album", album.name, "date", album.date, "window", "0:1")[0]
			self._client.tagtypes("all")
			album.cover=self._client.get_cover(song["file"]).get_paintable()
		self._cover.set_paintable(album.cover)


class ArtistAlbumRow(Adw.ActionRow):
	def __init__(self, album):
		super().__init__(use_markup=False, activatable=True, css_classes=["property"])
		self.album = album["album"]
		self.artist = album["albumartist"]
		self.date = album["date"]

		# fill
		self.set_title(self.artist)
		self.set_subtitle(self.album)
		date = Gtk.Label(xalign=1, single_line_mode=True, css_classes=["numeric", "dimmed"])
		date.set_text(self.date)

		# packing
		self.add_suffix(date)
		self.add_suffix(
			Gtk.Image(icon_name="go-next-symbolic", accessible_role=Gtk.AccessibleRole.PRESENTATION))


class ArtistAlbumsPage(Adw.NavigationPage):
	__gsignals__={"album-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,str,str,))}
	def __init__(self, client, settings):
		super().__init__(title=_("Albums"), tag="album_list")
		self._settings=settings
		self._client=client

		# grid view
		self.grid_view=Gtk.GridView(tab_behavior=Gtk.ListTabBehavior.ITEM, single_click_activate=True, vexpand=True, max_columns=2)
		self.grid_view.add_css_class("navigation-sidebar")
		self.grid_view.add_css_class("albums-view")
		self._selection_model=SelectionModel(ArtistAlbum)
		self.grid_view.set_model(self._selection_model)

		# factory
		def setup(factory, item):
			row=ArtistAlbumListRow(self._client)
			item.set_child(row)
		def bind(factory, item):
			row=item.get_child()
			row.set_album(item.get_item())
		factory=Gtk.SignalListItemFactory()
		factory.connect("setup", setup)
		factory.connect("bind", bind)
		self.grid_view.set_factory(factory)

		# breakpoint bin
		breakpoint_bin=Adw.BreakpointBin(width_request=320, height_request=200)
		for width, columns in ((500,3), (850,4), (1200,5), (1500,6)):
			break_point=Adw.Breakpoint()
			break_point.set_condition(Adw.BreakpointCondition.parse(f"min-width: {width}sp"))
			break_point.add_setter(self.grid_view, "max-columns", columns)
			breakpoint_bin.add_breakpoint(break_point)
		breakpoint_bin.set_child(Gtk.ScrolledWindow(child=self.grid_view, hscrollbar_policy=Gtk.PolicyType.NEVER))

		# status page
		status_page=Adw.StatusPage(icon_name="folder-music-symbolic", title=_("No Albums"), description=_("Select an artist"))

		# stack
		self._stack=Gtk.Stack()
		self._stack.add_named(breakpoint_bin, "albums")
		self._stack.add_named(status_page, "status-page")

		# connect
		self.grid_view.connect("activate", self._on_activate)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connection-error", self._on_connection_error)

		# packing
		toolbar_view=Adw.ToolbarView(content=self._stack)
		toolbar_view.add_top_bar(Adw.HeaderBar())
		self.set_child(toolbar_view)

	def clear(self, *args):
		self._selection_model.clear()
		self.set_title(_("Albums"))
		self._stack.set_visible_child_name("status-page")

	def _get_albums(self, artist):
		albums=self._client.list("album", "albumartist", artist, "group", "date")
		for album in albums:
			yield ArtistAlbum(artist, album["album"], album["date"])

	def display(self, artist):
		self._settings.set_property("cursor-watch", True)
		self._selection_model.clear()
		self.set_title(artist)
		self._stack.set_visible_child_name("albums")
		# ensure list is empty
		main=GLib.main_context_default()
		while main.pending():
			main.iteration()
		self.update_property([Gtk.AccessibleProperty.LABEL], [_("Albums of {artist}").format(artist=artist)])
		self._selection_model.append(sorted(self._get_albums(artist), key=lambda item: item.date))
		self._settings.set_property("cursor-watch", False)

	def _on_activate(self, widget, pos):
		album=self._selection_model.get_item(pos)
		self.emit("album-selected", album.artist, album.name, album.date)

	def _on_disconnected(self, *args):
		self._stack.set_visible_child_name("albums")

	def _on_connection_error(self, *args):
		self._stack.set_visible_child_name("albums")


class ArtistAlbumPage(AlbumPage):
	def __init__(self, client, albumartist, album, date):
		super().__init__(client, album, date)
		tag_filter=("albumartist", albumartist, "album", album, "date", date)

		self.play_button.connect("clicked", lambda *args: client.filter_to_playlist(tag_filter, "play"))
		self.append_button.connect("clicked", lambda *args: client.filter_to_playlist(tag_filter, "append"))

		self.suptitle.set_text(albumartist)
		self.length.set_text(str(Duration(client.count(*tag_filter)["playtime"])))
		client.restrict_tagtypes("track", "title", "artist")
		songs=client.find(*tag_filter)
		client.tagtypes("all")
		self.album_cover.set_paintable(client.get_cover(songs[0]["file"]).get_paintable())
		for song in songs:
			row=BrowserSongRow(song, hide_artist=albumartist)
			self.song_list.append(row)