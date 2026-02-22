import itertools
import gi
from gettext import gettext as _

from ..sidebar_list_view import SidebarListView

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GObject, Pango, GLib


class ArtistList(SidebarListView):
    def __init__(self, client, SelectionModel, artist_role):
        super().__init__(client, SelectionModel)
        self.artist_role = artist_role

    def _refresh(self):
        if self.artist_role == 'conductor':
            artists = self._client.list("conductor")
            artist_iterator = itertools.groupby(((artist["conductor"], artist["conductor"]) for artist in artists),
                                                key=lambda x: x[0])
        elif self.artist_role == 'composer':
            artists = self._client.list("composer")
            artist_iterator = itertools.groupby(((artist["composer"], artist["composer"]) for artist in artists),
                                                key=lambda x: x[0])
        else:
            artists=self._client.list("albumartistsort", "group", "albumartist")
            artist_iterator = itertools.groupby(((artist["albumartist"], artist["albumartistsort"]) for artist in artists),
                                                key=lambda x: x[0])
        filtered_artists=[]
        for name, artist in artist_iterator:
            if name == "":
                next(artist)
                continue
            artist_with_role=list(next(artist))
            artist_with_role.append(self.artist_role)
            filtered_artists.append(artist_with_role)
            # ignore multiple albumartistsort values
            if next(artist, None) is not None:
                filtered_artists[-1]=(name, name, self.artist_role)
        self.selection_model.set_list(filtered_artists)

    def _on_connected(self, emitter, database_is_empty):
        if not database_is_empty:
            self._refresh()
            if (song:=self._client.currentsong()):
                if self.artist_role == 'conductor':
                    artist=song["conductor"][0]
                elif self.artist_role == 'composer':
                    artist=song["composer"][0]
                else:
                    artist=song["artist"][0]
                self.select(artist)