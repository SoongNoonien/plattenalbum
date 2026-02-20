import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk, Graphene
from gettext import gettext as _

from ..bitrate import BitRate
from ..duration import Duration
from ..progress import PlaylistProgress
from ..media_buttons import MediaButtons


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