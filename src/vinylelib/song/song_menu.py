import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk, Gio
from gettext import gettext as _


class SongMenu(Gtk.PopoverMenu):
    def __init__(self, client, show_album=False):
        super().__init__(has_arrow=False, halign=Gtk.Align.START)
        self.update_property([Gtk.AccessibleProperty.LABEL], [_("Context menu")])
        self._client=client
        self._file=None

        # action group
        action_group=Gio.SimpleActionGroup()
        action=Gio.SimpleAction.new("append", None)
        action.connect("activate", lambda *args: self._client.file_to_playlist(self._file, "append"))
        action_group.add_action(action)
        action=Gio.SimpleAction.new("as-next", None)
        action.connect("activate", lambda *args: self._client.file_to_playlist(self._file, "as-next"))
        action_group.add_action(action)
        if show_album:
            action=Gio.SimpleAction.new("show-album", None)
            action.connect("activate", lambda *args: self._client.show_album(self._file))
            action_group.add_action(action)
        self._show_file_action=Gio.SimpleAction.new("show-file", None)
        self._show_file_action.connect("activate", lambda *args: self._client.show_file(self._file))
        action_group.add_action(self._show_file_action)
        self.insert_action_group("menu", action_group)

        # menu model
        menu=Gio.Menu()
        menu.append(_("_Append"), "menu.append")
        menu.append(_("As _Next"), "menu.as-next")
        subsection=Gio.Menu()
        if show_album:
            subsection.append(_("Show Al_bum"), "menu.show-album")
        subsection.append(_("Show _File"), "menu.show-file")
        menu.append_section(None, subsection)
        self.set_menu_model(menu)

    def open(self, file, x, y):
        self._file=file
        rect=Gdk.Rectangle()
        rect.x,rect.y=x,y
        self.set_pointing_to(rect)
        self._show_file_action.set_enabled(self._client.can_show_file(file))
        self.popup()