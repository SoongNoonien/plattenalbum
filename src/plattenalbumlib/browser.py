import gi

from.artist.artist import ArtistSelectionModel
from .composer.composer import ComposerSelectionModel

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GObject, Pango, GLib
from gettext import gettext as _

from .artist import ArtistList
from .artist_album import ArtistAlbumsPage, ArtistAlbumPage
from .composer import ComposerList
from .composer_album import ComposerAlbumsPage, ComposerAlbumPage
from .search import SearchView


class MainMenuButton(Gtk.MenuButton):
    def __init__(self):
        super().__init__(icon_name="open-menu-symbolic", tooltip_text=_("Main Menu"), primary=True)
        app_section=Gio.Menu()
        app_section.append(_("_Preferences"), "win.preferences")
        app_section.append(_("_Keyboard Shortcuts"), "app.shortcuts")
        app_section.append(_("_About Plattenalbum"), "app.about")
        menu=Gio.Menu()
        menu.append(_("_Disconnect"), "app.disconnect")
        menu.append(_("_Update Database"), "app.update")
        menu.append(_("_Server Information"), "win.server-info")
        menu.append_section(None, app_section)
        self.set_menu_model(menu)


class Browser(Gtk.Stack):
    def __init__(self, client, settings):
        super().__init__()
        self._client=client
        self.browse_by_composer = settings['composer']
        # search
        self._search_view=SearchView(client, settings)
        self.search_entry=Gtk.SearchEntry(placeholder_text=_("Search collection"), max_width_chars=25)
        self.search_entry.update_property([Gtk.AccessibleProperty.LABEL], [_("Search collection")])
        search_toolbar_view=Adw.ToolbarView(content=self._search_view)
        search_header_bar=Adw.HeaderBar(title_widget=self.search_entry)
        search_toolbar_view.add_top_bar(search_header_bar)
        search_toolbar_view.add_css_class("content-pane")

        # album list
        if self.browse_by_composer:
            composer_page = self._composer_list_setup(client)
            self._albums_page = ComposerAlbumsPage(client, settings)
        else:
            artist_page = self._artist_list_setup(client)
            self._albums_page = ArtistAlbumsPage(client, settings)

        # navigation view
        self._album_navigation_view=Adw.NavigationView()
        self._album_navigation_view.add(self._albums_page)
        album_navigation_view_page=Adw.NavigationPage(child=self._album_navigation_view, title=_("Albums"), tag="albums")

        # split view
        if self.browse_by_composer:
            self._navigation_split_view=Adw.NavigationSplitView(sidebar=composer_page, content=album_navigation_view_page)
        else:
            self._navigation_split_view=Adw.NavigationSplitView(sidebar=artist_page, content=album_navigation_view_page)

        # breakpoint bin
        breakpoint_bin=Adw.BreakpointBin(width_request=320, height_request=200)
        break_point=Adw.Breakpoint()
        break_point.set_condition(Adw.BreakpointCondition.parse(f"max-width: 550sp"))
        break_point.add_setter(self._navigation_split_view, "collapsed", True)
        break_point.connect("apply", lambda *args: self._navigation_split_view.add_css_class("content-pane"))
        break_point.connect("unapply", lambda *args: self._navigation_split_view.remove_css_class("content-pane"))
        breakpoint_bin.add_breakpoint(break_point)
        breakpoint_bin.set_child(self._navigation_split_view)

        # status page
        status_page=Adw.StatusPage(icon_name="folder-music-symbolic", title=_("Collection is Empty"))
        status_page_header_bar=Adw.HeaderBar(show_title=False)
        status_page_header_bar.pack_end(MainMenuButton())
        status_page_toolbar_view=Adw.ToolbarView(content=status_page)
        status_page_toolbar_view.add_top_bar(status_page_header_bar)

        # navigation view
        self._navigation_view=Adw.NavigationView()
        self._navigation_view.add(Adw.NavigationPage(child=breakpoint_bin, title=_("Collection"), tag="collection"))
        self._navigation_view.add(Adw.NavigationPage(child=search_toolbar_view, title=_("Search"), tag="search"))

        # connect
        self._albums_page.connect("album-selected", self._on_album_selected)
        if self.browse_by_composer:
            self._composer_list_connect()
        else:
            self._artist_list_connect()
        self._search_view.connect("album-selected", lambda widget, *args: self._show_album(*args))
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("stop-search", self._on_search_stopped)
        client.emitter.connect("disconnected", self._on_disconnected)
        client.emitter.connect("connection-error", self._on_connection_error)
        client.emitter.connect("connected", self._on_connected_or_updated_db)
        client.emitter.connect("updated-db", self._on_connected_or_updated_db)
        client.emitter.connect("show-album", lambda widget, *args: self._show_album(*args))

        # packing
        self.add_named(self._navigation_view, "browser")
        self.add_named(status_page_toolbar_view, "empty-collection")

    def _composer_list_connect(self):
        self._composer_list.selection_model.connect("selected", self._on_composer_selected)
        self._composer_list.selection_model.connect("reselected", self._on_composer_reselected)
        self._composer_list.selection_model.connect("clear", self._albums_page.clear)
        self._search_view.connect("composer-selected", self._on_search_composer_selected)

    def _composer_list_setup(self, client):
        # composer list
        self._composer_list = ComposerList(client, ComposerSelectionModel)
        composer_window = Gtk.ScrolledWindow(child=self._composer_list)
        composer_header_bar = Adw.HeaderBar()
        search_button = Gtk.Button(icon_name="system-search-symbolic", tooltip_text=_("Search"))
        search_button.connect("clicked", lambda *args: self.search())
        composer_header_bar.pack_start(search_button)
        composer_header_bar.pack_end(MainMenuButton())
        composer_toolbar_view = Adw.ToolbarView(content=composer_window)
        composer_toolbar_view.add_top_bar(composer_header_bar)
        composer_page = Adw.NavigationPage(child=composer_toolbar_view, title=_("Composers"), tag="composers")
        return composer_page

    def _artist_list_connect(self):
        self._artist_list.selection_model.connect("selected", self._on_artist_selected)
        self._artist_list.selection_model.connect("reselected", self._on_artist_reselected)
        self._artist_list.selection_model.connect("clear", self._albums_page.clear)
        self._search_view.connect("artist-selected", self._on_search_artist_selected)

    def _artist_list_setup(self, client):
        # artist list
        self._artist_list = ArtistList(client, ArtistSelectionModel)
        artist_window = Gtk.ScrolledWindow(child=self._artist_list)
        artist_header_bar = Adw.HeaderBar()
        search_button = Gtk.Button(icon_name="system-search-symbolic", tooltip_text=_("Search"))
        search_button.connect("clicked", lambda *args: self.search())
        artist_header_bar.pack_start(search_button)
        artist_header_bar.pack_end(MainMenuButton())
        artist_toolbar_view = Adw.ToolbarView(content=artist_window)
        artist_toolbar_view.add_top_bar(artist_header_bar)
        artist_page = Adw.NavigationPage(child=artist_toolbar_view, title=_("Artists"), tag="artists")
        return artist_page

    def search(self):
        if self._navigation_view.get_visible_page_tag() != "search":
            self._navigation_view.push_by_tag("search")
        self.search_entry.select_region(0, -1)
        self.search_entry.grab_focus()

    def _on_search_changed(self, entry):
        if (search_text:=self.search_entry.get_text()):
            self._search_view.search(search_text)
        else:
            self._search_view.clear()

    def _on_search_stopped(self, widget):
        self._navigation_view.pop_to_tag("collection")

    def _on_composer_selected(self, model, position):
        self._navigation_split_view.set_show_content(True)
        self._album_navigation_view.replace_with_tags(["album_list"])
        self._albums_page.display(model.get_composer(position))

    def _on_composer_reselected(self, model):
        self._navigation_split_view.set_show_content(True)
        self._album_navigation_view.pop_to_tag("album_list")

    def _on_artist_selected(self, model, position):
        self._navigation_split_view.set_show_content(True)
        self._album_navigation_view.replace_with_tags(["album_list"])
        self._albums_page.display(model.get_artist(position))

    def _on_artist_reselected(self, model):
        self._navigation_split_view.set_show_content(True)
        self._album_navigation_view.pop_to_tag("album_list")

    def _on_album_selected(self, widget, *tags):
        if self.browse_by_composer:
            album_page = ComposerAlbumPage(self._client, *tags)
        else:
            album_page = ArtistAlbumPage(self._client, *tags)
        self._album_navigation_view.push(album_page)
        album_page.play_button.grab_focus()

    def _on_search_composer_selected(self, widget, composer):
        self._composer_list.select(composer)
        self.search_entry.emit("stop-search")
        self._albums_page.grid_view.grab_focus()

    def _on_search_artist_selected(self, widget, artist):
        self._artist_list.select(artist)
        self.search_entry.emit("stop-search")
        self._albums_page.grid_view.grab_focus()

    def _show_album(self, album, artist, date):
        if self.browse_by_composer:
            self._composer_list.select(artist)
            album_page = ComposerAlbumPage(self._client, artist, album, date)
        else:
            self._artist_list.select(artist)
            album_page = ArtistAlbumPage(self._client, artist, album, date)

        self._album_navigation_view.replace([self._albums_page, album_page])
        self.search_entry.emit("stop-search")
        album_page.play_button.grab_focus()

    def _on_disconnected(self, *args):
        self._album_navigation_view.pop_to_tag("album_list")
        self.set_visible_child_name("browser")
        self._navigation_split_view.set_show_content(False)
        self.search_entry.emit("stop-search")

    def _on_connection_error(self, *args):
        self.set_visible_child_name("empty-collection")

    def _on_connected_or_updated_db(self, emitter, database_is_empty):
        self.search_entry.emit("stop-search")
        self.search_entry.set_text("")
        if database_is_empty:
            self.set_visible_child_name("empty-collection")
        else:
            self.set_visible_child_name("browser")