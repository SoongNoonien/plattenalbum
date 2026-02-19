from gettext import gettext as _
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk, GObject, Pango

from .models import SelectionModel


class AlbumsPage(Adw.NavigationPage):
    def __init__(self, client, settings):
        super().__init__(title=_("Albums"), tag="album_list")
        self._settings=settings
        self._client=client

        # grid view
        self.grid_view=Gtk.GridView(tab_behavior=Gtk.ListTabBehavior.ITEM, single_click_activate=True, vexpand=True, max_columns=2)
        self.grid_view.add_css_class("navigation-sidebar")
        self.grid_view.add_css_class("albums-view")

        self.factory = Gtk.SignalListItemFactory()
        def bind(factory, item):
            row=item.get_child()
            row.set_album(item.get_item())
        self.factory.connect("bind", bind)

        # breakpoint bin
        self.breakpoint_bin=Adw.BreakpointBin(width_request=320, height_request=200)
        for width, columns in ((500,3), (850,4), (1200,5), (1500,6)):
            break_point=Adw.Breakpoint()
            break_point.set_condition(Adw.BreakpointCondition.parse(f"min-width: {width}sp"))
            break_point.add_setter(self.grid_view, "max-columns", columns)
            self.breakpoint_bin.add_breakpoint(break_point)
        self.breakpoint_bin.set_child(Gtk.ScrolledWindow(child=self.grid_view, hscrollbar_policy=Gtk.PolicyType.NEVER))

        # stack
        self._stack=Gtk.Stack()

        # connect
        self.grid_view.connect("activate", self._on_activate)
        self._client.emitter.connect("disconnected", self._on_disconnected)
        self._client.emitter.connect("connection-error", self._on_connection_error)

        # packing
        self.toolbar_view=Adw.ToolbarView(content=self._stack)
        self.toolbar_view.add_top_bar(Adw.HeaderBar())

    def clear(self, *args):
        self._selection_model.clear()
        self.set_title(_("Albums"))
        self._stack.set_visible_child_name("status-page")

    def display(self, default):
        self._settings.set_property("cursor-watch", True)
        self._selection_model.clear()
        self.set_title(default)
        self._stack.set_visible_child_name("albums")
        # ensure list is empty
        main=GLib.main_context_default()
        while main.pending():
            main.iteration()

    def _on_activate(self, widget, pos):
        album=self._selection_model.get_item(pos)
        self.emit("album-selected", album.artist, album.name, album.date)

    def _on_disconnected(self, *args):
        self._stack.set_visible_child_name("albums")

    def _on_connection_error(self, *args):
        self._stack.set_visible_child_name("albums")
