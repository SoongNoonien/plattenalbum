
from gettext import gettext as _
import gi

from .duration import Duration
from .models import SelectionModel
from .browsersong import BrowserSongRow
from .browsersong import BrowserSongList
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk, GObject, Pango


class Album(GObject.Object):
	def __init__(self, artist, name, date):
		GObject.Object.__init__(self)
		self.artist=artist
		self.name=name
		self.date=date
		self.cover=None


class AlbumCover(Gtk.Widget):
	def __init__(self, **kwargs):
		super().__init__(hexpand=True, **kwargs)
		self._picture=Gtk.Picture(css_classes=["cover"], accessible_role=Gtk.AccessibleRole.PRESENTATION)
		self._picture.set_parent(self)
		self.connect("destroy", lambda *args: self._picture.unparent())

	def do_get_request_mode(self):
		return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

	def do_size_allocate(self, width, height, baseline):
		self._picture.allocate(width, height, baseline, None)

	def do_measure(self, orientation, for_size):
		return (for_size, for_size, -1, -1)

	def set_paintable(self, paintable):
		if paintable.get_intrinsic_width()/paintable.get_intrinsic_height() >= 1:
			self._picture.set_halign(Gtk.Align.FILL)
			self._picture.set_valign(Gtk.Align.CENTER)
		else:
			self._picture.set_halign(Gtk.Align.CENTER)
			self._picture.set_valign(Gtk.Align.FILL)
		self._picture.set_paintable(paintable)

	def set_alternative_text(self, alt_text):
		self._picture.set_alternative_text(alt_text)


class AlbumListRow(Gtk.Box):
	def __init__(self, client):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)
		self._client=client
		self._cover=AlbumCover()
		self._title=Gtk.Label(single_line_mode=True, ellipsize=Pango.EllipsizeMode.END, margin_top=3)
		self._date=Gtk.Label(single_line_mode=True, css_classes=["dimmed", "caption"])
		self.append(self._cover)
		self.append(self._title)
		self.append(self._date)

	def set_album(self, album):
		if album.name:
			self._title.set_text(album.name)
			self._cover.set_alternative_text(_("Album cover of {album}").format(album=album.name))
		else:
			self._title.set_markup(f'<i>{GLib.markup_escape_text(_("Unknown Album"))}</i>')
			self._cover.set_alternative_text(_("Album cover of an unknown album"))
		self._date.set_text(album.date)
		if album.cover is None:
			self._client.tagtypes("clear")
			song=self._client.find("albumartist", album.artist, "album", album.name, "date", album.date, "window", "0:1")[0]
			self._client.tagtypes("all")
			album.cover=self._client.get_cover(song["file"]).get_paintable()
		self._cover.set_paintable(album.cover)

class AlbumRow(Adw.ActionRow):
	def __init__(self, album):
		super().__init__(use_markup=False, activatable=True, css_classes=["property"])
		self.album = album["album"]
		self.artist = album["albumartist"]
		self.date = album["date"]

		# fill
		self.set_title(self.artist)
		self.set_subtitle(self.album)
		date = Gtk.Label(xalign=1, single_line_mode=True, css_classes=["numeric", "dimmed"])
		date.set_text(self.date)

		# packing
		self.add_suffix(date)
		self.add_suffix(
			Gtk.Image(icon_name="go-next-symbolic", accessible_role=Gtk.AccessibleRole.PRESENTATION))

class AlbumsPage(Adw.NavigationPage):
	__gsignals__={"album-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,str,str,))}
	def __init__(self, client, settings):
		super().__init__(title=_("Albums"), tag="album_list")
		self._settings=settings
		self._client=client

		# grid view
		self.grid_view=Gtk.GridView(tab_behavior=Gtk.ListTabBehavior.ITEM, single_click_activate=True, vexpand=True, max_columns=2)
		self.grid_view.add_css_class("navigation-sidebar")
		self.grid_view.add_css_class("albums-view")
		self._selection_model=SelectionModel(Album)
		self.grid_view.set_model(self._selection_model)

		# factory
		def setup(factory, item):
			row=AlbumListRow(self._client)
			item.set_child(row)
		def bind(factory, item):
			row=item.get_child()
			row.set_album(item.get_item())
		factory=Gtk.SignalListItemFactory()
		factory.connect("setup", setup)
		factory.connect("bind", bind)
		self.grid_view.set_factory(factory)

		# breakpoint bin
		breakpoint_bin=Adw.BreakpointBin(width_request=320, height_request=200)
		for width, columns in ((500,3), (850,4), (1200,5), (1500,6)):
			break_point=Adw.Breakpoint()
			break_point.set_condition(Adw.BreakpointCondition.parse(f"min-width: {width}sp"))
			break_point.add_setter(self.grid_view, "max-columns", columns)
			breakpoint_bin.add_breakpoint(break_point)
		breakpoint_bin.set_child(Gtk.ScrolledWindow(child=self.grid_view, hscrollbar_policy=Gtk.PolicyType.NEVER))

		# status page
		status_page=Adw.StatusPage(icon_name="folder-music-symbolic", title=_("No Albums"), description=_("Select an artist"))

		# stack
		self._stack=Gtk.Stack()
		self._stack.add_named(breakpoint_bin, "albums")
		self._stack.add_named(status_page, "status-page")

		# connect
		self.grid_view.connect("activate", self._on_activate)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connection-error", self._on_connection_error)

		# packing
		toolbar_view=Adw.ToolbarView(content=self._stack)
		toolbar_view.add_top_bar(Adw.HeaderBar())
		self.set_child(toolbar_view)

	def clear(self, *args):
		self._selection_model.clear()
		self.set_title(_("Albums"))
		self._stack.set_visible_child_name("status-page")

	def _get_albums(self, artist):
		albums=self._client.list("album", "albumartist", artist, "group", "date")
		for album in albums:
			yield Album(artist, album["album"], album["date"])

	def display(self, artist):
		self._settings.set_property("cursor-watch", True)
		self._selection_model.clear()
		self.set_title(artist)
		self._stack.set_visible_child_name("albums")
		# ensure list is empty
		main=GLib.main_context_default()
		while main.pending():
			main.iteration()
		self.update_property([Gtk.AccessibleProperty.LABEL], [_("Albums of {artist}").format(artist=artist)])
		self._selection_model.append(sorted(self._get_albums(artist), key=lambda item: item.date))
		self._settings.set_property("cursor-watch", False)

	def _on_activate(self, widget, pos):
		album=self._selection_model.get_item(pos)
		self.emit("album-selected", album.artist, album.name, album.date)

	def _on_disconnected(self, *args):
		self._stack.set_visible_child_name("albums")

	def _on_connection_error(self, *args):
		self._stack.set_visible_child_name("albums")



class AlbumPage(Adw.NavigationPage):
	def __init__(self, client, albumartist, album, date):
		super().__init__()
		tag_filter=("albumartist", albumartist, "album", album, "date", date)

		# songs list
		song_list=BrowserSongList(client)
		song_list.add_css_class("boxed-list")

		# buttons
		self.play_button=Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text=_("Play"))
		self.play_button.connect("clicked", lambda *args: client.filter_to_playlist(tag_filter, "play"))
		append_button=Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Append"))
		append_button.connect("clicked", lambda *args: client.filter_to_playlist(tag_filter, "append"))

		# header bar
		header_bar=Adw.HeaderBar(show_title=False)
		header_bar.pack_end(self.play_button)
		header_bar.pack_end(append_button)

		# labels
		suptitle=Gtk.Label(single_line_mode=True, ellipsize=Pango.EllipsizeMode.END, css_classes=["dimmed", "caption"])
		title=Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, css_classes=["title-4"])
		subtitle=Gtk.Label(single_line_mode=True, ellipsize=Pango.EllipsizeMode.END, visible=bool(date))
		length=Gtk.Label(single_line_mode=True, css_classes=["numeric", "dimmed", "caption"])

		# label box
		label_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, margin_top=9, margin_bottom=18)
		label_box.append(suptitle)
		label_box.append(title)
		label_box.append(subtitle)
		label_box.append(length)

		# cover
		album_cover=AlbumCover()

		# packing
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=12, margin_end=12, margin_top=6, margin_bottom=24)
		box.append(Adw.Clamp(child=album_cover, maximum_size=200))
		box.append(label_box)
		box.append(Adw.Clamp(child=song_list))
		self._scroll=Gtk.ScrolledWindow(child=box)
		self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
		toolbar_view=Adw.ToolbarView(content=self._scroll)
		toolbar_view.add_top_bar(header_bar)
		self.set_child(toolbar_view)

		# populate
		if album:
			self.set_title(album)
			title.set_text(album)
		else:
			self.set_title(_("Unknown Album"))
			title.set_text(_("Unknown Album"))
		suptitle.set_text(albumartist)
		subtitle.set_text(date)
		length.set_text(str(Duration(client.count(*tag_filter)["playtime"])))
		client.restrict_tagtypes("track", "title", "artist")
		songs=client.find(*tag_filter)
		client.tagtypes("all")
		album_cover.set_paintable(client.get_cover(songs[0]["file"]).get_paintable())
		for song in songs:
			row=BrowserSongRow(song, hide_artist=albumartist)
			song_list.append(row)