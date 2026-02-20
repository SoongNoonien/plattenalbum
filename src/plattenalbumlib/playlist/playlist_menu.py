import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk
from gettext import gettext as _

class PlaylistMenu(Gtk.PopoverMenu):
    def __init__(self, client):
        super().__init__(has_arrow=False, halign=Gtk.Align.START)
        self.update_property([Gtk.AccessibleProperty.LABEL], [_("Context menu")])
        self._client=client
        self._file=None
        self._position=None

        # action group
        action_group=Gio.SimpleActionGroup()
        self._remove_action=Gio.SimpleAction.new("delete", None)
        self._remove_action.connect("activate", lambda *args: self._client.delete(self._position))
        action_group.add_action(self._remove_action)
        self._show_album_action=Gio.SimpleAction.new("show-album", None)
        self._show_album_action.connect("activate", lambda *args: self._client.show_album(self._file))
        action_group.add_action(self._show_album_action)
        self._show_file_action=Gio.SimpleAction.new("show-file", None)
        self._show_file_action.connect("activate", lambda *args: self._client.show_file(self._file))
        action_group.add_action(self._show_file_action)
        self.insert_action_group("menu", action_group)

        # menu model
        menu=Gio.Menu()
        menu.append(_("_Remove"), "menu.delete")
        menu.append(_("Show Al_bum"), "menu.show-album")
        menu.append(_("Show _File"), "menu.show-file")
        mpd_section=Gio.Menu()
        mpd_section.append(_("_Enqueue Album"), "app.enqueue")
        mpd_section.append(_("_Tidy"), "app.tidy")
        mpd_section.append(_("_Clear"), "app.clear")
        menu.append_section(None, mpd_section)
        self.set_menu_model(menu)

    def open(self, file, position, x, y):
        self._file=file
        self._position=position
        rect=Gdk.Rectangle()
        rect.x,rect.y=x,y
        self.set_pointing_to(rect)
        if file is None or position is None:
            self._remove_action.set_enabled(False)
            self._show_album_action.set_enabled(False)
            self._show_file_action.set_enabled(False)
        else:
            self._remove_action.set_enabled(True)
            self._show_album_action.set_enabled(self._client.can_show_album(file))
            self._show_file_action.set_enabled(self._client.can_show_file(file))
        self.popup()





