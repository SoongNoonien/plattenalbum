import itertools
import gi
from gettext import gettext as _

from ..sidebar_list_view import SidebarListView

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GObject, Pango, GLib


class ArtistList(SidebarListView):
    def __init__(self, client, SelectionModel):
        super().__init__(client, SelectionModel)

    def _refresh(self):
        artists=self._client.list("albumartistsort", "group", "albumartist")
        filtered_artists=[]
        for name, artist in itertools.groupby(((artist["albumartist"], artist["albumartistsort"]) for artist in artists), key=lambda x: x[0]):
            filtered_artists.append(next(artist))
            # ignore multiple albumartistsort values
            if next(artist, None) is not None:
                filtered_artists[-1]=(name, name)
        self.selection_model.set_list(filtered_artists)

    def _on_connected(self, emitter, database_is_empty):
        if not database_is_empty:
            self._refresh()
            if (song:=self._client.currentsong()):
                artist=song["albumartist"][0]
                self.select(artist)