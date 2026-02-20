from gettext import gettext as _
import gi


gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GObject, Gtk

from src.plattenalbumlib.album import Album
from src.plattenalbumlib.album_list_row import AlbumListRow
from src.plattenalbumlib.album_page import AlbumPage
from src.plattenalbumlib.albums_page import AlbumsPage
from src.plattenalbumlib.browsersong import BrowserSongRow
from src.plattenalbumlib.duration import Duration
from src.plattenalbumlib.models import SelectionModel


class ComposerAlbum(Album):
    def __init__(self, composer, name, date):
        super().__init__(name, date)
        self.composer=composer


class ComposerAlbumListRow(AlbumListRow):
    def __init__(self, client):
        super().__init__(client)

    def set_album(self, album):
        super().set_album(album)
        if album.cover is None:
            self._client.tagtypes("clear")
            song=self._client.find("composer", album.composer, "album", album.name, "date", album.date, "window", "0:1")[0]
            self._client.tagtypes("all")
            album.cover=self._client.get_cover(song["file"]).get_paintable()
        self._cover.set_paintable(album.cover)


class ComposerAlbumRow(Adw.ActionRow):
    def __init__(self, album):
        super().__init__(use_markup=False, activatable=True, css_classes=["property"])
        self.album = album["album"]
        self.composer = album["composer"]
        self.date = album["date"]

        # fill
        self.set_title(self.composer)
        self.set_subtitle(self.album)
        date = Gtk.Label(xalign=1, single_line_mode=True, css_classes=["numeric", "dimmed"])
        date.set_text(self.date)

        # packing
        self.add_suffix(date)
        self.add_suffix(
            Gtk.Image(icon_name="go-next-symbolic", accessible_role=Gtk.AccessibleRole.PRESENTATION))


class ComposerAlbumsPage(AlbumsPage):
    __gsignals__={"album-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,str,str,))}
    def __init__(self, client, settings):
        super().__init__(client, settings)

        self._selection_model=SelectionModel(ComposerAlbum)
        self.grid_view.set_model(self._selection_model)

        # factory
        def setup(factory, item):
            row=ComposerAlbumListRow(self._client)
            item.set_child(row)
        self.factory.connect("setup", setup)
        self.grid_view.set_factory(self.factory)

        status_page=Adw.StatusPage(icon_name="folder-music-symbolic", title=_("No Albums"), description=_("Select a composer"))
        self._stack.add_named(self.breakpoint_bin, "albums")
        self._stack.add_named(status_page, "status-page")
        self.set_child(self.toolbar_view)

    def _get_albums(self, composer):
        albums=self._client.list("album", "composer", composer, "group", "date")
        for album in albums:
            yield ComposerAlbum(composer, album["album"], album["date"])

    def display(self, composer):
        super().display(composer)
        self.set_title(composer)
        self.update_property([Gtk.AccessibleProperty.LABEL], [_("Albums of {composer}").format(composer=composer)])
        self._selection_model.append(sorted(self._get_albums(composer), key=lambda item: item.date))
        self._settings.set_property("cursor-watch", False)

    def _on_activate(self, widget, pos):
        album=self._selection_model.get_item(pos)
        self.emit("album-selected", album.composer, album.name, album.date)


class ComposerAlbumPage(AlbumPage):
    def __init__(self, client, albumcomposer, album, date):
        super().__init__(client, album, date)
        tag_filter = ("composer", albumcomposer, "album", album, "date", date)

        self.play_button.connect("clicked", lambda *args: client.filter_to_playlist(tag_filter, "play"))
        self.append_button.connect("clicked", lambda *args: client.filter_to_playlist(tag_filter, "append"))

        self.suptitle.set_text(albumcomposer)
        self.length.set_text(str(Duration(client.count(*tag_filter)["playtime"])))
        client.restrict_tagtypes("track", "title", "composer")
        songs = client.find(*tag_filter)
        client.tagtypes("all")
        self.album_cover.set_paintable(client.get_cover(songs[0]["file"]).get_paintable())
        for song in songs:
            row = BrowserSongRow(song, hide_composer=albumcomposer)
            self.song_list.append(row)
