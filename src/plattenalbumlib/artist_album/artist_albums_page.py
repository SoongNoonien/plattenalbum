import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GObject, Gtk

from ..album import AlbumsPage
from ..artist_album import ArtistAlbum
from ..artist_album import ArtistAlbumListRow


class ArtistAlbumsPage(AlbumsPage):
    __gsignals__={"album-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,str,str,str,))}
    def __init__(self, client, settings):
        super().__init__(client, settings, ArtistAlbum, ArtistAlbumListRow, "Select an artist")

    def _get_albums(self, artist, role):
        albums=self._client.list("album", role, artist, "group", "date")
        for album in albums:
            yield ArtistAlbum(artist, role, album["album"], album["date"])

    def _on_activate(self, widget, pos):
        album=self._selection_model.get_item(pos)
        self.emit("album-selected", album.role, album.artist, album.name, album.date)