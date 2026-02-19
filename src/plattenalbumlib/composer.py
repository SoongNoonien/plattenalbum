import itertools
import gi
import locale
from gettext import gettext as _

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GObject, Pango, GLib
from .models import SelectionModel


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

class ComposerList(Gtk.ListView):
    def __init__(self, client):
        super().__init__(tab_behavior=Gtk.ListTabBehavior.ITEM, single_click_activate=True, css_classes=["navigation-sidebar"])
        self._client=client

        # factory
        def setup(factory, item):
            label=Gtk.Label(xalign=0, single_line_mode=True, ellipsize=Pango.EllipsizeMode.END)
            item.set_child(label)
        def bind(factory, item):
            label=item.get_child()
            if name:=item.get_item().name:
                label.set_text(name)
            else:
                label.set_markup(f'<i>{GLib.markup_escape_text(_("Unknown Composer"))}</i>')
        factory=Gtk.SignalListItemFactory()
        factory.connect("setup", setup)
        factory.connect("bind", bind)
        self.set_factory(factory)

        # header factory
        def header_setup(factory, item):
            label=Gtk.Label(xalign=0, single_line_mode=True)
            item.set_child(label)
        def header_bind(factory, item):
            label=item.get_child()
            label.set_text(item.get_item().section_name)
        header_factory=Gtk.SignalListItemFactory()
        header_factory.connect("setup", header_setup)
    	header_factory.connect("bind", header_bind)
		self.set_header_factory(header_factory)

		# model
		self.composer_selection_model=ComposerSelectionModel()
		self.set_model(self.composer_selection_model)

		# connect
		self.connect("activate", self._on_activate)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)
		self._client.emitter.connect("updated-db", self._on_updated_db)

	def select(self, name):
		self.composer_selection_model.select_composer(name)
		if (selected:=self.composer_selection_model.get_selected()) is None:
			self.composer_selection_model.select(0)
			self.scroll_to(0, Gtk.ListScrollFlags.FOCUS, None)
		else:
			self.scroll_to(selected, Gtk.ListScrollFlags.FOCUS, None)

	def _refresh(self):
		composers=self._client.list("composersort", "group", "composer")
		filtered_composers=[]
		for name, composer in itertools.groupby(((composer["composer"], composer["composersort"]) for composer in composers), key=lambda x: x[0]):
			if len(name) > 0:
				filtered_composers.append(next(composer))
				# ignore multiple albumcomposersort values
				if next(composer, None) is not None:
					filtered_composers[-1]=(name, name)
		self.composer_selection_model.set_composers(filtered_composers)

	def _on_activate(self, widget, pos):
		self.composer_selection_model.select(pos)

	def _on_disconnected(self, *args):
		self.composer_selection_model.clear()

	def _on_connected(self, emitter, database_is_empty):
		if not database_is_empty:
			self._refresh()
			if (song:=self._client.currentsong()):
				composer=song["albumcomposer"][0]
				self.select(composer)

	def _on_updated_db(self, emitter, database_is_empty):
		if database_is_empty:
			self.composer_selection_model.clear()
		else:
			if (composer:=self.composer_selection_model.get_selected_composer()) is None:
				self._refresh()
				self.composer_selection_model.select(0)
				self.scroll_to(0, Gtk.ListScrollFlags.FOCUS, None)
			else:
				self._refresh()
				self.select(composer)