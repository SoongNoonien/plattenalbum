import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib
from gettext import gettext as _
from ..duration import Duration

class ServerInfo(Adw.Dialog):
    def __init__(self, client, settings):
        super().__init__(title=_("Server Information"), width_request=360, follows_content_size=True)

        # list box
        list_box=Gtk.ListBox(valign=Gtk.Align.START)
        list_box.add_css_class("boxed-list")

        # populate
        display_str={
            "server": _("Server"),
            "protocol": _("Protocol"),
            "uptime": _("Uptime"),
            "playtime": _("Playtime"),
            "artists": _("Artists"),
            "albums": _("Albums"),
            "songs": _("Songs"),
            "db_playtime": _("Total Database Playtime"),
            "db_update": _("Last Database Update")
        }
        stats=client.stats()
        stats["server"]=client.server
        stats["protocol"]=str(client.mpd_version)
        for key in ("uptime","playtime","db_playtime"):
            stats[key]=str(Duration(stats[key]))
        stats["db_update"]=GLib.DateTime.new_from_unix_local(int(stats["db_update"])).format("%x, %X")
        for key in ("server","protocol","uptime","playtime","db_update","db_playtime","artists","albums","songs"):
            row=Adw.ActionRow(activatable=False, selectable=False, subtitle_selectable=True, title=display_str[key], subtitle=stats[key])
            row.add_css_class("property")
            list_box.append(row)

        # packing
        clamp=Adw.Clamp(child=list_box, margin_top=24, margin_bottom=24, margin_start=12, margin_end=12)
        scroll=Gtk.ScrolledWindow(child=clamp, propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        toolbar_view=Adw.ToolbarView(content=scroll)
        toolbar_view.add_top_bar(Adw.HeaderBar())
        self.set_child(toolbar_view)