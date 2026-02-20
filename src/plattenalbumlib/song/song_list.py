import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Graphene

from ..models import SelectionModel
from .song import Song
from .song_list_row import SongListRow

class SongList(Gtk.ListView):
    def __init__(self):
        super().__init__(tab_behavior=Gtk.ListTabBehavior.ITEM)
        self.set_model(SelectionModel(Song))

        # factory
        def setup(factory, item):
            item.set_child(SongListRow())
        def bind(factory, item):
            row=item.get_child()
            song=item.get_item()
            row.set_song(song)
            song.set_property("widget", row)
            row.set_property("position", item.get_position())
        def unbind(factory, item):
            row=item.get_child()
            song=item.get_item()
            row.unset_song()
            song.set_property("widget", None)
            row.set_property("position", -1)
        factory=Gtk.SignalListItemFactory()
        factory.connect("setup", setup)
        factory.connect("bind", bind)
        factory.connect("unbind", unbind)
        self.set_factory(factory)

    def _get_focus_row(self):
        return self.get_focus_child().get_first_child()

    def get_focus_popup_point(self):
        computed_point,point=self._get_focus_row().compute_point(self, Graphene.Point.zero())
        if computed_point:
            return (point.x, point.y)
        return (0, 0)

    def get_focus_position(self):
        return self._get_focus_row().get_property("position")

    def get_focus_song(self):
        return self.get_model().get_item(self.get_focus_position())

    def get_position(self, x, y):
        item=self.pick(x,y,Gtk.PickFlags.DEFAULT)
        if item is self or item is None:
            return None
        return item.get_first_child().get_property("position")

    def get_song(self, position):
        return self.get_model().get_item(position)