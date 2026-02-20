import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw

from .view_preferences import ViewPreferences
from .behaviour_preferences import BehaviorPreferences


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, client, settings):
        super().__init__()
        page=Adw.PreferencesPage()
        page.add(ViewPreferences(settings))
        page.add(BehaviorPreferences(settings))
        self.add(page)