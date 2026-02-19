from gettext import gettext as _
import gi


gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GObject, Gtk

from .album import Album
from .album_list_row import AlbumListRow
from .album_page import AlbumPage
from .albums_page import AlbumsPage
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


class ArtistAlbumsPage(AlbumsPage):
	__gsignals__={"album-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,str,str,))}
	def __init__(self, client, settings):
		super().__init__(client, settings)

		self._selection_model=SelectionModel(ArtistAlbum)
		self.grid_view.set_model(self._selection_model)

		# factory
		def setup(factory, item):
			row=ArtistAlbumListRow(self._client)
			item.set_child(row)
		self.factory.connect("setup", setup)
		self.grid_view.set_factory(self.factory)

		status_page=Adw.StatusPage(icon_name="folder-music-symbolic", title=_("No Albums"), description=_("Select an artist"))
		self._stack.add_named(self.breakpoint_bin, "albums")
		self._stack.add_named(status_page, "status-page")
		self.set_child(self.toolbar_view)

	def _get_albums(self, artist):
		albums=self._client.list("album", "albumartist", artist, "group", "date")
		for album in albums:
			yield ArtistAlbum(artist, album["album"], album["date"])

	def display(self, artist):
		super().display(artist)
		self.set_title(artist)
		self.update_property([Gtk.AccessibleProperty.LABEL], [_("Albums of {artist}").format(artist=artist)])
		self._selection_model.append(sorted(self._get_albums(artist), key=lambda item: item.date))
		self._settings.set_property("cursor-watch", False)

	def _on_activate(self, widget, pos):
		album=self._selection_model.get_item(pos)
		self.emit("album-selected", album.artist, album.name, album.date)


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