import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GObject


class Album(GObject.Object):
	def __init__(self, name, date):
		GObject.Object.__init__(self)
		self.name=name
		self.date=date
		self.cover=None