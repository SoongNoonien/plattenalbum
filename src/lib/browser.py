import itertools

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GObject, Pango, GLib
from gettext import gettext as _

from .browsersong import BrowserSongList, BrowserSongRow
from .album import AlbumRow, AlbumsPage, AlbumPage
from .artist import ArtistList


class SearchView(Gtk.Stack):
	__gsignals__={"artist-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
			"album-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,str,str,))}
	def __init__(self, client):
		super().__init__()
		self._client=client
		self._results=20  # TODO adjust number of results
		self._song_tags=("title", "artist", "album", "date")
		self._artist_tags=("albumartist", "albumartistsort")
		self._album_tags=("album", "albumartist", "albumartistsort", "date")

		# artist list
		self._artist_list=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, tab_behavior=Gtk.ListTabBehavior.ITEM, valign=Gtk.Align.START)
		self._artist_list.add_css_class("boxed-list")

		# album list
		self._album_list=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, tab_behavior=Gtk.ListTabBehavior.ITEM, valign=Gtk.Align.START)
		self._album_list.add_css_class("boxed-list")

		# song list
		self._song_list=BrowserSongList(client, show_album=True)
		self._song_list.add_css_class("boxed-list")

		# boxes
		self._artist_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
		self._artist_box.append(Gtk.Label(label=_("Artists"), xalign=0, css_classes=["heading"]))
		self._artist_box.append(self._artist_list)
		self._album_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
		self._album_box.append(Gtk.Label(label=_("Albums"), xalign=0, css_classes=["heading"]))
		self._album_box.append(self._album_list)
		self._song_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
		self._song_box.append(Gtk.Label(label=_("Songs"), xalign=0, css_classes=["heading"]))
		self._song_box.append(self._song_list)
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=30, margin_start=12, margin_end=12, margin_top=24, margin_bottom=24)
		box.append(self._artist_box)
		box.append(self._album_box)
		box.append(self._song_box)

		# scroll
		scroll=Gtk.ScrolledWindow(child=Adw.Clamp(child=box))
		self._adj=scroll.get_vadjustment()

		# status page
		status_page=Adw.StatusPage(icon_name="edit-find-symbolic", title=_("No Results"), description=_("Try a different search"))

		# connect
		self._artist_list.connect("row-activated", self._on_artist_activate)
		self._artist_list.connect("keynav-failed", self._on_keynav_failed)
		self._album_list.connect("row-activated", self._on_album_activate)
		self._album_list.connect("keynav-failed", self._on_keynav_failed)

		# packing
		self.add_named(status_page, "no-results")
		self.add_named(scroll, "results")

	def clear(self):
		self._artist_list.remove_all()
		self._album_list.remove_all()
		self._song_list.remove_all()
		self._adj.set_value(0.0)
		self.set_visible_child_name("no-results")

	def search(self, search_text):
		self.clear()
		if (keywords:=search_text.split()):
			self._client.restrict_tagtypes(*self._song_tags)
			songs=self._client.search(self._client.get_search_expression(self._song_tags, keywords), "window", f"0:{self._results}")
			self._client.tagtypes("all")
			for song in songs:
				row=BrowserSongRow(song, show_track=False)
				self._song_list.append(row)
			self._song_box.set_visible(self._song_list.get_first_child() is not None)
			albums=self._client.list("album", self._client.get_search_expression(self._album_tags, keywords), "group", "date", "group", "albumartist")
			for album in itertools.islice(albums, self._results):
				album_row=AlbumRow(album)
				self._album_list.append(album_row)
			self._album_box.set_visible(self._album_list.get_first_child() is not None)
			artists=self._client.list("albumartist", self._client.get_search_expression(self._artist_tags, keywords))
			for artist in itertools.islice(artists, self._results):
				row=Adw.ActionRow(title=artist["albumartist"], use_markup=False, activatable=True)
				row.add_suffix(Gtk.Image(icon_name="go-next-symbolic", accessible_role=Gtk.AccessibleRole.PRESENTATION))
				self._artist_list.append(row)
			self._artist_box.set_visible(self._artist_list.get_first_child() is not None)
			if self._song_box.get_visible() or self._album_box.get_visible() or self._artist_box.get_visible():
				self.set_visible_child_name("results")

	def _on_artist_activate(self, list_box, row):
		self.emit("artist-selected", row.get_title())

	def _on_album_activate(self, list_box, row):
		self.emit("album-selected", row.album, row.artist, row.date)

	def _on_keynav_failed(self, list_box, direction):
		if (root:=list_box.get_root()) is not None:
			if direction == Gtk.DirectionType.UP:
				root.child_focus(Gtk.DirectionType.TAB_BACKWARD)
			elif direction == Gtk.DirectionType.DOWN:
				root.child_focus(Gtk.DirectionType.TAB_FORWARD)


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

		# search
		self._search_view=SearchView(client)
		self.search_entry=Gtk.SearchEntry(placeholder_text=_("Search collection"), max_width_chars=25)
		self.search_entry.update_property([Gtk.AccessibleProperty.LABEL], [_("Search collection")])
		search_toolbar_view=Adw.ToolbarView(content=self._search_view)
		search_header_bar=Adw.HeaderBar(title_widget=self.search_entry)
		search_toolbar_view.add_top_bar(search_header_bar)
		search_toolbar_view.add_css_class("content-pane")

		# artist list
		self._artist_list=ArtistList(client)
		artist_window=Gtk.ScrolledWindow(child=self._artist_list)
		artist_header_bar=Adw.HeaderBar()
		search_button=Gtk.Button(icon_name="system-search-symbolic", tooltip_text=_("Search"))
		search_button.connect("clicked", lambda *args: self.search())
		artist_header_bar.pack_start(search_button)
		artist_header_bar.pack_end(MainMenuButton())
		artist_toolbar_view=Adw.ToolbarView(content=artist_window)
		artist_toolbar_view.add_top_bar(artist_header_bar)
		artist_page=Adw.NavigationPage(child=artist_toolbar_view, title=_("Artists"), tag="artists")

		# album list
		self._albums_page=AlbumsPage(client, settings)

		# navigation view
		self._album_navigation_view=Adw.NavigationView()
		self._album_navigation_view.add(self._albums_page)
		album_navigation_view_page=Adw.NavigationPage(child=self._album_navigation_view, title=_("Albums"), tag="albums")

		# split view
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
		self._artist_list.artist_selection_model.connect("selected", self._on_artist_selected)
		self._artist_list.artist_selection_model.connect("reselected", self._on_artist_reselected)
		self._artist_list.artist_selection_model.connect("clear", self._albums_page.clear)
		self._search_view.connect("artist-selected", self._on_search_artist_selected)
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

	def _on_artist_selected(self, model, position):
		self._navigation_split_view.set_show_content(True)
		self._album_navigation_view.replace_with_tags(["album_list"])
		self._albums_page.display(model.get_artist(position))

	def _on_artist_reselected(self, model):
		self._navigation_split_view.set_show_content(True)
		self._album_navigation_view.pop_to_tag("album_list")

	def _on_album_selected(self, widget, *tags):
		album_page=AlbumPage(self._client, *tags)
		self._album_navigation_view.push(album_page)
		album_page.play_button.grab_focus()

	def _on_search_artist_selected(self, widget, artist):
		self._artist_list.select(artist)
		self.search_entry.emit("stop-search")
		self._albums_page.grid_view.grab_focus()

	def _show_album(self, album, artist, date):
		self._artist_list.select(artist)
		album_page=AlbumPage(self._client, artist, album, date)
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