import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Graphene
from gettext import gettext as _

from .bitrate import BitRate
from .duration import Duration
from .progress import PlaylistProgress
from .playlist import PlaylistWindow
from .lyrics import LyricsWindow
from .media_buttons import MediaButtons
from .cover import FALLBACK_COVER

class PlaybackControls(Gtk.Box):
    def __init__(self, client, settings):
        super().__init__(hexpand=True, orientation=Gtk.Orientation.VERTICAL)
        self._client=client

        # labels
        self._elapsed=Gtk.Label(xalign=0, single_line_mode=True, valign=Gtk.Align.START, css_classes=["numeric"])
        self._rest=Gtk.Label(xalign=1, single_line_mode=True, valign=Gtk.Align.START, css_classes=["numeric"])

        # progress bar
        self._scale=Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, draw_value=False, hexpand=True)
        self._scale.set_increments(10, 10)
        self._scale.update_property([Gtk.AccessibleProperty.LABEL], [_("Progress bar")])
        self._adjustment=self._scale.get_adjustment()

        # popover
        self._popover=Gtk.Popover(autohide=False, has_arrow=False)
        self._time_label=Gtk.Label(single_line_mode=True, css_classes=["numeric"])
        self._popover.set_child(self._time_label)
        self._popover.set_parent(self)
        self._popover.set_position(Gtk.PositionType.TOP)

        # event controllers
        controller_motion=Gtk.EventControllerMotion()
        self._scale.add_controller(controller_motion)

        # connect
        self._scale.connect("change-value", self._on_change_value)
        controller_motion.connect("motion", self._on_pointer_motion)
        controller_motion.connect("leave", self._on_pointer_leave)
        self._client.emitter.connect("disconnected", self._disable)
        self._client.emitter.connect("state", self._on_state)
        self._client.emitter.connect("elapsed", self._refresh)
        self._client.emitter.connect("current-song", self._on_song_changed)

        # packing
        start_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.START)
        start_box.add_css_class("toolbar-text")
        start_box.append(self._elapsed)
        start_box.append(PlaylistProgress(client))
        end_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.START)
        end_box.add_css_class("toolbar-text")
        end_box.append(self._rest)
        end_box.append(BitRate(client, settings))
        center_box=Gtk.CenterBox(margin_start=6, margin_end=6)
        center_box.add_css_class("toolbar")
        center_box.set_center_widget(MediaButtons(client))
        center_box.set_start_widget(start_box)
        center_box.set_end_widget(end_box)
        self.append(self._scale)
        self.append(center_box)

    def _refresh(self, emitter, elapsed, duration):
        self._scale.set_visible(True)
        if duration > 0:
            if elapsed > duration:  # fix display error
    			elapsed=duration
			self._adjustment.set_upper(duration)
			self._scale.set_value(elapsed)
			self._elapsed.set_text(str(Duration(elapsed)))
			self._rest.set_text(str(Duration(duration-elapsed)))
		else:
			self._disable()
			self._elapsed.set_text(str(Duration(elapsed)))

	def _disable(self, *args):
		self._popover.popdown()
		self._scale.set_visible(False)
		self._scale.set_range(0, 0)
		self._elapsed.set_text("")
		self._rest.set_text("")

	def _on_change_value(self, range, scroll, value):  # value is inaccurate (can be above upper limit)
		duration=self._adjustment.get_upper()
		if value >= duration:
			pos=duration
			self._popover.popdown()
			if scroll == Gtk.ScrollType.JUMP:  # avoid endless skipping to the next song
				self._scale.set_sensitive(False)
				self._scale.set_sensitive(True)
		elif value <= 0:
			pos=0
			self._popover.popdown()
		else:
			pos=value
		try:
			self._client.seekcur(pos)
		except:
			pass

	def _on_pointer_motion(self, controller, x, y):
		range_rect=self._scale.get_range_rect()
		duration=self._adjustment.get_upper()
		if self._scale.get_direction() == Gtk.TextDirection.RTL:
			elapsed=int(((range_rect.width-x)/range_rect.width*duration))
		else:
			elapsed=int((x/range_rect.width*duration))
		if elapsed > duration:  # fix display error
			elapsed=int(duration)
		elif elapsed < 0:
			elapsed=0
		self._time_label.set_text(str(Duration(elapsed)))
		point=Graphene.Point.zero()
		point.x=x
		computed_point,point=self._scale.compute_point(self, point)
		if computed_point:
			rect=Gdk.Rectangle()
			rect.x,rect.y=point.x,0
			self._popover.set_pointing_to(rect)
			self._popover.popup()

	def _on_pointer_leave(self, *args):
		self._popover.popdown()

	def _on_state(self, emitter, state):
		if state == "stop":
			self._disable()

	def _on_song_changed(self, *args):
		self._popover.popdown()

class VolumeControl(Gtk.Box):
	def __init__(self, client):
		super().__init__(orientation=Gtk.Orientation.HORIZONTAL, margin_start=12)
		self._client=client

		# adjustment
		scale=Gtk.Scale(hexpand=True)
		scale.update_property([Gtk.AccessibleProperty.LABEL], [_("Volume control")])
		self._adjustment=scale.get_adjustment()
		self._adjustment.configure(0, 0, 100, 5, 5, 0)

		# connect
		scale.connect("change-value", self._on_change_value)
		self._client.emitter.connect("volume", self._refresh)

		# packing
		self.append(Gtk.Image(icon_name="audio-speakers-symbolic", accessible_role=Gtk.AccessibleRole.PRESENTATION))
		self.append(scale)

	def _on_change_value(self, scale, scroll, value):
		self._client.setvol(str(int(max(min(value, 100), 0))))

	def _refresh(self, emitter, volume):
		self._adjustment.set_value(max(volume, 0))

class PlayerMenu(Gtk.PopoverMenu):
	def __init__(self, client):
		super().__init__()
		self._client=client
		self._volume_visible=False

		# volume
		self._volume_control=VolumeControl(client)
		self._volume_item=Gio.MenuItem()
		self._volume_item.set_attribute_value("custom", GLib.Variant("s", "volume"))

		# menu model
		self._volume_section=Gio.Menu()
		menu=Gio.Menu()
		menu.append(_("_Repeat Mode"), "app.repeat")
		menu.append(_("R_andom Mode"), "app.random")
		menu.append(_("_Single Mode"), "app.single")
		menu.append(_("_Pause After Song"), "app.single-oneshot")
		menu.append(_("_Consume Mode"), "app.consume")
		menu.append_section(None, self._volume_section)
		self.set_menu_model(menu)

		# connect
		self._client.emitter.connect("volume", self._on_volume_changed)
		self._client.emitter.connect("disconnected", self._on_disconnected)

	def _on_volume_changed(self, emitter, volume):
		if volume < 0 and self._volume_visible:
			self._volume_section.remove(0)
			self._volume_visible=False
		elif volume >= 0 and not self._volume_visible:
			self._volume_section.append_item(self._volume_item)
			self.add_child(self._volume_control, "volume")
			self._volume_visible=True

	def _on_disconnected(self, *args):
		if self._volume_visible:
			self._volume_section.remove(0)
			self._volume_visible=False

class Player(Adw.Bin):
	def __init__(self, client, settings):
		super().__init__(width_request=300, height_request=200)
		self._client=client

		# widgets
		self._cover=Gtk.Picture(css_classes=["cover"], accessible_role=Gtk.AccessibleRole.PRESENTATION,
			halign=Gtk.Align.CENTER, margin_start=12, margin_end=12, margin_bottom=6, visible=False)
		self._lyrics_window=LyricsWindow()
		playlist_window=PlaylistWindow(client)
		self._playback_controls=PlaybackControls(client, settings)
		self._playback_controls.set_visible(False)

		# box
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		box.append(Gtk.WindowHandle(child=self._cover))
		box.append(playlist_window)

		# stack
		self._stack=Adw.ViewStack(vhomogeneous=False, enable_transitions=True)
		self._stack.add_titled_with_icon(box, "playlist", _("Playlist"), "view-playlist-symbolic")
		self._stack.add_titled_with_icon(self._lyrics_window, "lyrics", _("Lyrics"), "view-lyrics-symbolic")

		# playlist page
		self._playlist_page=self._stack.get_page(box)

		# view switcher
		view_switcher=Adw.InlineViewSwitcher(stack=self._stack, display_mode=Adw.InlineViewSwitcherDisplayMode.ICONS)
		view_switcher.add_css_class("flat")

		# header bar
		header_bar=Adw.HeaderBar(show_title=False)
		header_bar.pack_start(view_switcher)
		header_bar.pack_end(Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text=_("Player Menu"), popover=PlayerMenu(client)))

		# connect
		self._stack.connect("notify::visible-child-name", self._on_visible_child_name)
		self._client.emitter.connect("current-song", self._on_song_changed)
		self._client.emitter.connect("playlist", self._on_playlist_changed)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)

		# packing
		toolbar_view=Adw.ToolbarView()
		toolbar_view.add_top_bar(header_bar)
		toolbar_view.set_content(self._stack)
		toolbar_view.add_bottom_bar(self._playback_controls)
		self.set_child(toolbar_view)

	def _on_visible_child_name(self, *args):
		if self._stack.get_visible_child_name() == "lyrics":
			self._lyrics_window.load()
		elif self._stack.get_visible_child_name() == "playlist":
			self._playlist_page.set_needs_attention(False)

	def _on_song_changed(self, emitter, song, songpos, songid, state):
		if song:
			self._cover.set_visible(True)
			self._lyrics_window.set_property("song", song)
			if self._stack.get_visible_child_name() == "lyrics":
				self._lyrics_window.load()
		else:
			self._cover.set_visible(False)
			self._lyrics_window.set_property("song", None)
		self._cover.set_paintable(self._client.current_cover.get_paintable())

	def _on_playlist_changed(self, emitter, version, length, songpos):
		self._playback_controls.set_visible(length > 0)
		if self._stack.get_visible_child_name() != "playlist":
			self._playlist_page.set_needs_attention(True)

	def _on_disconnected(self, *args):
		self._cover.set_paintable(FALLBACK_COVER)
		self._cover.set_visible(False)
		self._lyrics_window.set_property("song", None)
		self._stack.set_visible_child_name("playlist")

	def _on_connected(self, *args):
		self._stack.set_visible_child_name("playlist")