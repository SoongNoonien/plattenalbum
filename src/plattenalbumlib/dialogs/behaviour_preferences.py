import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio
from gettext import gettext as _


class BehaviorPreferences(Adw.PreferencesGroup):
    def __init__(self, settings):
        super().__init__(title=_("Behavior"))
        toggle_data=(
            (_("Send _Notification on Title Change"), "send-notify", ""),
            (_("Stop _Playback on Quit"), "stop-on-quit", ""),
            (_("Support “_MPRIS”"), "mpris", _("Disable if “MPRIS” is supported by another client")),
            (_("Browse by composer, (requires to restart the app)"), "composer", _("Choose sidebar navigation")),
        )
        for title, key, subtitle in toggle_data:
            row=Adw.SwitchRow(title=title, subtitle=subtitle, use_underline=True)
            settings.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
            self.add(row)