import gi
import locale


gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GObject, Pango, GLib
from ..models import SelectionModel


class Composer(GObject.Object):
    def __init__(self, name):
        GObject.Object.__init__(self)
        self.name=name


class ComposerSelectionModel(SelectionModel):
    def __init__(self):
        super().__init__(Composer)

    def set_composers(self, composers):
        self.clear()
        self.append((Composer(item[0]) for item in sorted(composers, key=lambda item: locale.strxfrm(item[1]))))

    def select_composer(self, name):
        for i, composer in enumerate(self.data):
            if composer.name == name:
                self.select(i)
                return

    def get_composer(self, position):
        return self.get_item(position).name

    def get_selected_composer(self):
        if (selected:=self.get_selected()) is None:
            return None
        else:
            return self.get_composer(selected)