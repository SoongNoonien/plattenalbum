import gi
import locale

from ..models import SelectionModel

gi.require_version("Gtk", "4.0")
from gi.repository import GObject


class Artist(GObject.Object):
    def __init__(self, name):
        GObject.Object.__init__(self)
        self.name=name


class ArtistSelectionModel(SelectionModel):
    def __init__(self):
        super().__init__(Artist)

    def set_artists(self, artists):
        self.clear()
        self.append((Artist(item[0]) for item in sorted(artists, key=lambda item: locale.strxfrm(item[1]))))

    def select_artist(self, name):
        for i, artist in enumerate(self.data):
            if artist.name == name:
                self.select(i)
                return

    def get_artist(self, position):
        return self.get_item(position).name

    def get_selected_artist(self):
        if (selected:=self.get_selected()) is None:
            return None
        else:
            return self.get_artist(selected)
