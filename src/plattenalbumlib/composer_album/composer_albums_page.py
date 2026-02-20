import gi
from gettext import gettext as _

gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GObject, Gtk

from ..albums_page import AlbumsPage
from ..models import SelectionModel
from ..composer_album import ComposerAlbum
from ..composer_album.composer_album_list_row import ComposerAlbumListRow


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