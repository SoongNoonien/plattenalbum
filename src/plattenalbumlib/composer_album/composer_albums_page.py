import gi
from gettext import gettext as _

gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GObject, Gtk

from ..album import AlbumsPage
from ..composer_album import ComposerAlbum
from ..composer_album import ComposerAlbumListRow


class ComposerAlbumsPage(AlbumsPage):
    __gsignals__={"album-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,str,str,))}
    def __init__(self, client, settings):
        super().__init__(client, settings, ComposerAlbum, ComposerAlbumListRow, "Select a composer")

    def _get_albums(self, composer):
        albums=self._client.list("album", "composer", composer, "group", "date")
        for album in albums:
            yield ComposerAlbum(composer, album["album"], album["date"])

    def _on_activate(self, widget, pos):
        album=self._selection_model.get_item(pos)
        self.emit("album-selected", album.composer, album.name, album.date)