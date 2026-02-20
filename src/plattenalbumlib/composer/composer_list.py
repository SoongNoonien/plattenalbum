import itertools
import gi

from ..sidebar_list_view import SidebarListView

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GObject, Pango, GLib


class ComposerList(SidebarListView):
    def __init__(self, client, SelectionModel):
        super().__init__(client, SelectionModel)

    def _refresh(self):
        composers=self._client.list("composersort", "group", "composer")
        filtered_composers=[]
        for name, composer in itertools.groupby(((composer["composer"], composer["composersort"]) for composer in composers), key=lambda x: x[0]):
            if len(name) > 0:
                filtered_composers.append(next(composer))
                # ignore multiple albumcomposersort values
                if next(composer, None) is not None:
                    filtered_composers[-1]=(name, name)
        self.selection_model.set_list(filtered_composers)

    def _on_connected(self, emitter, database_is_empty):
        if not database_is_empty:
            self._refresh()
            if (song:=self._client.currentsong()):
                composer=song["albumcomposer"][0]
                self.select(composer)