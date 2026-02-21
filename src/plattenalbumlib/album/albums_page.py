from gettext import gettext as _
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk, GObject, Pango
from ..models import SelectionModel


class AlbumsPage(Adw.NavigationPage):
    def __init__(self, client, settings, AlbumType, ListRow, prompt_string):
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

        # factory
        def setup(factory, item):
            row = ListRow(self._client)
            item.set_child(row)

        self.factory.connect("setup", setup)
        self.grid_view.set_factory(self.factory)
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

        self._selection_model = SelectionModel(AlbumType)
        self.grid_view.set_model(self._selection_model)
        status_page = Adw.StatusPage(icon_name="folder-music-symbolic", title=_("No Albums"),
                                     description=_(prompt_string))
        self._stack.add_named(self.breakpoint_bin, "albums")
        self._stack.add_named(status_page, "status-page")
        self.set_child(self.toolbar_view)

    def clear(self, *args):
        self._selection_model.clear()
        self.set_title(_("Albums"))
        self._stack.set_visible_child_name("status-page")

    def display(self, item, role):
        self._settings.set_property("cursor-watch", True)
        self._selection_model.clear()
        self.set_title(item)
        self._stack.set_visible_child_name("albums")
        # ensure list is empty
        main=GLib.main_context_default()
        while main.pending():
            main.iteration()
        self.update_property([Gtk.AccessibleProperty.LABEL], [_("Albums of {item}").format(item=item)])
        self._selection_model.append(sorted(self._get_albums(item, role), key=lambda item: item.date))
        self._settings.set_property("cursor-watch", False)

    def _on_activate(self, widget, pos):
        album=self._selection_model.get_item(pos)
        self.emit("album-selected", album.artist, album.role, album.name, album.date)

    def _on_disconnected(self, *args):
        self._stack.set_visible_child_name("albums")

    def _on_connection_error(self, *args):
        self._stack.set_visible_child_name("albums")
