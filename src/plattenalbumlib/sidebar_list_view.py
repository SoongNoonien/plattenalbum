import itertools
import gi
from gettext import gettext as _


gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GObject, Pango, GLib


class SidebarListView(Gtk.ListView):
    def __init__(self, client, SelectionModel):
        super().__init__(tab_behavior=Gtk.ListTabBehavior.ITEM, single_click_activate=True, css_classes=["navigation-sidebar"])
        self._client=client

        # factory
        def setup(factory, item):
            label=Gtk.Label(xalign=0, single_line_mode=True, ellipsize=Pango.EllipsizeMode.END)
            item.set_child(label)
        def bind(factory, item):
            label=item.get_child()
            if name:=item.get_item().name:
                label.set_text(name)
            else:
                label.set_markup(f'<i>{GLib.markup_escape_text(_("Unknown Artist"))}</i>')
        factory=Gtk.SignalListItemFactory()
        factory.connect("setup", setup)
        factory.connect("bind", bind)
        self.set_factory(factory)

        # header factory
        def header_setup(factory, item):
            label=Gtk.Label(xalign=0, single_line_mode=True)
            item.set_child(label)
        def header_bind(factory, item):
            label=item.get_child()
            label.set_text(item.get_item().section_name)
        header_factory=Gtk.SignalListItemFactory()
        header_factory.connect("setup", header_setup)
        header_factory.connect("bind", header_bind)
        self.set_header_factory(header_factory)

        # model
        self.selection_model=SelectionModel()
        self.set_model(self.selection_model)

        # connect
        self.connect("activate", self._on_activate)
        self._client.emitter.connect("disconnected", self._on_disconnected)
        self._client.emitter.connect("connected", self._on_connected)
        self._client.emitter.connect("updated-db", self._on_updated_db)

    def select(self, name):
        self.selection_model.select_item(name)
        if (selected:=self.selection_model.get_selected()) is None:
            self.selection_model.select(0)
            self.scroll_to(0, Gtk.ListScrollFlags.FOCUS, None)
        else:
            self.scroll_to(selected, Gtk.ListScrollFlags.FOCUS, None)

    def _refresh(self):
        artists=self._client.list("albumartistsort", "group", "albumartist")
        filtered_artists=[]
        for name, artist in itertools.groupby(((artist["albumartist"], artist["albumartistsort"]) for artist in artists), key=lambda x: x[0]):
            filtered_artists.append(next(artist))
            # ignore multiple albumartistsort values
            if next(artist, None) is not None:
                filtered_artists[-1]=(name, name)
        self.selection_model.set_list(filtered_artists)

    def _on_activate(self, widget, pos):
        self.selection_model.select(pos)

    def _on_disconnected(self, *args):
        self.selection_model.clear()

    def _on_connected(self, emitter, database_is_empty):
        if not database_is_empty:
            self._refresh()
            if (song:=self._client.currentsong()):
                artist=song["albumartist"][0]
                self.select(artist)

    def _on_updated_db(self, emitter, database_is_empty):
        if database_is_empty:
            self.selection_model.clear()
        else:
            if (item:=self.selection_model.get_selected_item()) is None:
                self._refresh()
                self.selection_model.select(0)
                self.scroll_to(0, Gtk.ListScrollFlags.FOCUS, None)
            else:
                self._refresh()
                self.select(item)