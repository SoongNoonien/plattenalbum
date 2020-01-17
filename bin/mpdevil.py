#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# mpdevil - MPD Client.
# Copyright 2020 Martin Wagner
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3 of the License.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307
# USA

import gi #python-gobject  dev-python/pygobject:3[${PYTHON_USEDEP}]
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gio, Gdk, GdkPixbuf, GObject, GLib
from mpd import MPDClient
import requests #dev-python/requests
from bs4 import BeautifulSoup, Comment #, NavigableString #dev-python/beautifulsoup
import threading, time
import locale
import gettext
import datetime
import os
import sys

DATADIR = '@datadir@'
NAME = 'mpdevil'
VERSION = '@version@'
PACKAGE = NAME.lower()

try:
	locale.setlocale(locale.LC_ALL, '')
	locale.bindtextdomain(PACKAGE, '@datadir@/locale')
	gettext.bindtextdomain(PACKAGE, '@datadir@/locale')
	gettext.textdomain(PACKAGE)
	gettext.install(PACKAGE, localedir='@datadir@/locale')
except locale.Error:
	print('  cannot use system locale.')
	locale.setlocale(locale.LC_ALL, 'C')
	gettext.textdomain(PACKAGE)
	gettext.install(PACKAGE, localedir='@datadir@/locale')

class IntEntry(Gtk.SpinButton):
	def __init__(self, default, lower, upper):
		Gtk.SpinButton.__init__(self)
		adj = Gtk.Adjustment(value=default, lower=lower, upper=upper, step_increment=1)
		self.set_adjustment(adj)

	def get_int(self):
		return int(self.get_value())

	def set_int(self, value):
		self.set_value(value)

class Cover(object):
	def __init__(self, client, lib_path, song_file):
		self.client=client
		self.lib_path=lib_path
		self.path=None
		if not song_file == None:
			head_tail=os.path.split(song_file)
			path=(self.lib_path+"/"+head_tail[0]+"/")
			if os.path.exists(path):
				filelist=[file for file in os.listdir(path) if file.endswith('.jpg') or file.endswith('.png') or file.endswith('.gif')]
				if not filelist == []:
					self.path=(path+filelist[0])

	def get_pixbuf(self, size):
		if self.path == None:
			self.path = Gtk.IconTheme.get_default().lookup_icon("mpdevil", size, Gtk.IconLookupFlags.FORCE_SVG).get_filename() #fallback cover
		return GdkPixbuf.Pixbuf.new_from_file_at_size(self.path, size, size)

class Client(MPDClient):
	def __init__(self):
		MPDClient.__init__(self)

	def connected(self):
		try:
			self.ping()
			return True
		except:
			return False

class AlbumDialog(Gtk.Dialog):
	def __init__(self, parent, client, album, artist, year):
		Gtk.Dialog.__init__(self, title=(artist+" - "+album+" ("+year+")"), transient_for=parent)
		self.add_buttons(Gtk.STOCK_ADD, Gtk.ResponseType.ACCEPT, Gtk.STOCK_MEDIA_PLAY, Gtk.ResponseType.YES, Gtk.STOCK_OK, Gtk.ResponseType.OK, Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
		self.set_default_size(800, 600)

		#adding vars
		self.client=client

		#scroll
		scroll=Gtk.ScrolledWindow()
		scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

		#Store
		#(track, title, artist, duration, file)
		self.store = Gtk.ListStore(str, str, str, str, str)

		#TreeView
		self.treeview = Gtk.TreeView(model=self.store)
		self.treeview.set_search_column(-1)
		self.treeview.columns_autosize()

		self.selection = self.treeview.get_selection()
		self.selection.set_mode(Gtk.SelectionMode.SINGLE)

		#Column
		renderer_text = Gtk.CellRendererText()

		self.column_track = Gtk.TreeViewColumn(_("No"), renderer_text, text=0)
		self.column_track.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_track.set_property("resizable", False)
		self.treeview.append_column(self.column_track)

		self.column_title = Gtk.TreeViewColumn(_("Title"), renderer_text, text=1)
		self.column_title.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_title.set_property("resizable", False)
		self.treeview.append_column(self.column_title)

		self.column_artist = Gtk.TreeViewColumn(_("Artist"), renderer_text, text=2)
		self.column_artist.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_artist.set_property("resizable", False)
		self.treeview.append_column(self.column_artist)

		self.column_time = Gtk.TreeViewColumn(_("Length"), renderer_text, text=3)
		self.column_time.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_time.set_property("resizable", False)
		self.treeview.append_column(self.column_time)

		self.populate_treeview(album, artist, year)

		#connect
		self.title_activated=self.treeview.connect("row-activated", self.on_row_activated)

		#packing
		scroll.add(self.treeview)
		self.vbox.pack_start(scroll, True, True, 0) #vbox default widget of dialogs
		self.show_all()

		#selection workaround
		self.selection.unselect_all()
		self.title_change=self.selection.connect("changed", self.on_selection_change)

	def on_row_activated(self, widget, path, view_column):
		treeiter=self.store.get_iter(path)
		selected_title=self.store.get_value(treeiter, 4)
		self.client.clear()
		self.client.add(selected_title)
		self.client.play(0)

	def on_selection_change(self, widget):
		treeiter=widget.get_selected()[1]
		if not treeiter == None:
			selected_title=self.store.get_value(treeiter, 4)
			self.client.add(selected_title)

	def populate_treeview(self, album, artist, year):
		songs=self.client.find("album", album, "date", year, "albumartist", artist)
		if not songs == []:
			for song in songs:
				try:
					title=song["title"]
				except:
					title=_("Unknown Title")
				try:
					artist=song["artist"]
				except:
					artist=_("Unknown Artist")
				try:
					track=song["track"].zfill(2)
				except:
					track="00"
				try:
					dura=float(song["duration"])
				except:
					dura=0.0
				duration=str(datetime.timedelta(seconds=int(dura)))
				self.store.append([track, title, artist, duration, song["file"]] )

class ArtistView(Gtk.ScrolledWindow):
	def __init__(self, client):
		Gtk.ScrolledWindow.__init__(self)
		self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

		#adding vars
		self.client=client
		self.albumartists=[]

		#artistStore
		#(name)
		self.store = Gtk.ListStore(str)
		self.store.set_sort_column_id(0, Gtk.SortType.ASCENDING)

		#TreeView
		self.treeview = Gtk.TreeView(model=self.store)
		self.treeview.set_search_column(-1)

		#artistSelection
		self.selection = self.treeview.get_selection()
		self.selection.set_mode(Gtk.SelectionMode.SINGLE)

		#Old Name Column
		renderer_text = Gtk.CellRendererText()
		self.column_name = Gtk.TreeViewColumn(_("Album Artist"), renderer_text, text=0)
		self.column_name.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_name.set_property("resizable", True)
		self.column_name.set_sort_column_id(0)
		self.treeview.append_column(self.column_name)

		self.refresh()

		self.add(self.treeview)

	def refresh(self): #returns True if refresh was actually performed
		if self.client.connected():
			if self.albumartists != self.client.list("albumartist"):
				self.store.clear()
				for artist in self.client.list("albumartist"):
					self.store.append([artist])
				self.albumartists=self.client.list("albumartist")
				return True
			else:
				return False
		else:
			self.store.clear()
			self.albumartists=[]
			return True

class AlbumView(Gtk.ScrolledWindow):
	def __init__(self, client, settings):
		Gtk.ScrolledWindow.__init__(self)
		self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

		#adding vars
		self.settings=settings
		self.client=client

		#cover, display_label, tooltip(titles), album, year
		self.store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str, str, str)
		self.store.set_sort_column_id(4, Gtk.SortType.ASCENDING)

		#iconview
		self.iconview = Gtk.IconView.new()
		self.iconview.set_model(self.store)
		self.iconview.set_pixbuf_column(0)
		self.iconview.set_text_column(1)
		self.iconview.set_tooltip_column(2)
		self.iconview.set_item_width(0)

		self.add(self.iconview)

	def gen_tooltip(self, album, artist, year):
		if self.settings.get_boolean("show-album-view-tooltips"):
			songs=self.client.find("album", album, "date", year, "albumartist", artist)
			length=float(0)
			for song in songs:
				try:
					dura=float(song["duration"])
				except:
					dura=0.0
				length=length+dura
				duration=str(datetime.timedelta(seconds=int(dura)))
			length_human_readable=str(datetime.timedelta(seconds=int(length)))
			tooltip=(_("%(total_tracks)i titles (%(total_length)s)") % {"total_tracks": len(songs), "total_length": length_human_readable})
			return tooltip
		else:
			return None

	def refresh(self, artist):
		self.store.clear()
		size=self.settings.get_int("album-cover")
		albums=[]
		for album in self.client.list("album", "albumartist", artist):
			albums.append({"album": album, "year": self.client.list("date", "album", album, "albumartist", artist)[0]})
		albums = sorted(albums, key=lambda k: k['year'])
		for album in albums:
			songs=self.client.find("album", album["album"], "date", album["year"], "albumartist", artist)
			if songs == []:
				song_file=None
			else:
				song_file=songs[0]["file"]
			cover=Cover(client=self.client, lib_path=self.settings.get_value("paths")[self.settings.get_int("active-profile")], song_file=song_file)
			img=cover.get_pixbuf(size)
			if album["year"] == "":
				self.store.append([img, album["album"], self.gen_tooltip(album["album"], artist, album["year"]), album["album"], album["year"]])
			else:
				self.store.append([img, album["album"]+" ("+album["year"]+")", self.gen_tooltip(album["album"], artist, album["year"]), album["album"], album["year"]])
			while Gtk.events_pending():
				Gtk.main_iteration_do(True)

class TrackView(Gtk.Box):
	def __init__(self, client, settings):
		Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)
		self.settings = settings

		#adding vars
		self.client=client
		self.playlist=[]
		self.song_to_delete=""
		self.hovered_songpos=None
		self.song_file=None

		#Store
		#(track, title, artist, album, duration, file)
		self.store = Gtk.ListStore(str, str, str, str, str, str)

		#TreeView
		self.treeview = Gtk.TreeView(model=self.store)
		self.treeview.set_search_column(-1)
		self.treeview.columns_autosize()

		#selection
		self.selection = self.treeview.get_selection()
		self.selection.set_mode(Gtk.SelectionMode.SINGLE)

		#Column
		renderer_text = Gtk.CellRendererText()

		self.column_track = Gtk.TreeViewColumn(_("No"), renderer_text, text=0)
		self.column_track.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_track.set_property("resizable", True)
		self.treeview.append_column(self.column_track)

		self.column_title = Gtk.TreeViewColumn(_("Title"), renderer_text, text=1)
		self.column_title.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_title.set_property("resizable", True)
		self.treeview.append_column(self.column_title)

		self.column_artist = Gtk.TreeViewColumn(_("Artist"), renderer_text, text=2)
		self.column_artist.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_artist.set_property("resizable", True)
		self.treeview.append_column(self.column_artist)

		self.column_duration = Gtk.TreeViewColumn(_("Length"), renderer_text, text=4)
		self.column_duration.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_duration.set_property("resizable", True)
		self.treeview.append_column(self.column_duration)

		#scroll
		scroll=Gtk.ScrolledWindow()
		scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
		scroll.add(self.treeview)

		#cover
		self.cover=Gtk.Image.new()
		self.cover.set_from_pixbuf(Cover(client=self.client, lib_path=self.settings.get_value("paths")[self.settings.get_int("active-profile")], song_file=None).get_pixbuf(self.settings.get_int("track-cover"))) #set to fallback cover

		#audio infos
		audio=AudioType(self.client)

		#timeouts
		GLib.timeout_add(1000, self.update_cover)
		GLib.timeout_add(100, self.refresh)

		#connect
		self.title_change=self.selection.connect("changed", self.on_selection_change)
		self.treeview.connect("row-activated", self.on_row_activated)
		self.treeview.connect("motion-notify-event", self.on_move_event)
		self.treeview.connect("leave-notify-event", self.on_leave_event)
		self.key_press_event=self.treeview.connect("key-press-event", self.on_key_press_event)

		#packing
		self.pack_start(self.cover, False, False, 0)
		self.pack_start(scroll, True, True, 0)
		self.pack_end(audio, False, False, 0)

	def update_cover(self):
		try:
			song_file=self.client.currentsong()["file"]
		except:
			song_file=None
		if not song_file == self.song_file:
			self.cover.set_from_pixbuf(Cover(client=self.client, lib_path=self.settings.get_value("paths")[self.settings.get_int("active-profile")], song_file=song_file).get_pixbuf(self.settings.get_int("track-cover")))
			self.song_file=song_file
		return True

	def album_to_playlist(self, album, artist, year, append, force=False):
		if append:
			songs=self.client.find("album", album, "date", year, "albumartist", artist)
			if not songs == []:
				for song in songs:
					self.client.add(song["file"])
		else:
			if self.settings.get_boolean("add-album") and not force and not self.client.status()["state"] == "stop":
				self.selection.handler_block(self.title_change)
				status=self.client.status()
				self.client.moveid(status["songid"], 0)
				self.song_to_delete=self.client.playlistinfo()[0]["file"]
				self.selection.handler_unblock(self.title_change)
				try:
					self.client.delete((1,)) # delete all songs, but the first. #bad song index possible
				except:
					pass
				songs=self.client.find("album", album, "date", year, "albumartist", artist)
				if not songs == []:
					for song in songs:
						if not song["file"] == self.song_to_delete:
							self.client.add(song["file"])
						else:
							self.client.move(0, (len(self.client.playlist())-1))
							self.song_to_delete=""
			else:
				songs=self.client.find("album", album, "date", year, "albumartist", artist)
				if not songs == []:
					self.client.stop()
					self.client.clear()
					for song in songs:
						self.client.add(song["file"])
					self.client.play(0)

	def refresh(self):
		self.selection.handler_block(self.title_change)
		if self.client.connected():
			if self.client.playlist() != self.playlist:
				self.store.clear()
				songs=self.client.playlistinfo()
				if not songs == []:
					for song in songs:
						try:
							title=song["title"]
						except:
							title=_("Unknown Title")
						try:
							track=song["track"].zfill(2)
						except:
							track="00"
						try:
							artist=song["artist"]
						except:
							artist=_("Unknown Artist")
						try:
							album=song["album"]
						except:
							album=_("Unknown Album")
						try:
							dura=float(song["duration"])
						except:
							dura=0.0
						duration=str(datetime.timedelta(seconds=int(dura )))
						self.store.append([track, title, artist, album, duration, song["file"].replace("&", "")])
				self.playlist=self.client.playlist()
			else:
				if not self.song_to_delete == "":
					status=self.client.status()
					if not status["song"] == "0":
						if self.client.playlistinfo()[0]["file"] == self.song_to_delete:
							self.client.delete(0)
							self.playlist=self.client.playlist()
							self.store.remove(self.store.get_iter_first())
						self.song_to_delete=""
			try:
				song=self.client.status()["song"]
				path = Gtk.TreePath(int(song))
				self.selection.select_path(path)
			except:
				self.selection.select_path(Gtk.TreePath(0))
		else:
			self.store.clear()
			self.playlist=[]
		self.selection.handler_unblock(self.title_change)
		return True

	def on_key_press_event(self, widget, event):
		self.treeview.handler_block(self.key_press_event)
		if event.keyval == 65535: #entf
			if not self.hovered_songpos == None:
				self.selection.handler_block(self.title_change)
				try:
					self.client.delete(self.hovered_songpos) #bad song index possible
					self.playlist=self.client.playlist()
					self.store.remove(self.store.get_iter(self.hovered_songpos))
				except:
					self.hovered_songpos == None
				self.selection.handler_unblock(self.title_change)
		self.treeview.handler_unblock(self.key_press_event)

	def on_move_event(self, widget, event):
		self.treeview.grab_focus()
		return_tuple = self.treeview.get_path_at_pos(int(event.x), int(event.y))
		if not return_tuple == None:
			self.hovered_songpos=return_tuple[0]
		else:
			self.hovered_songpos=None

	def on_leave_event(self, widget, event):
		self.hovered_songpos=None

	def on_selection_change(self, widget):
		treeiter=widget.get_selected()[1]
		if not treeiter == None:
			selected_title=self.store.get_path(treeiter)
			self.client.play(selected_title)

	def on_row_activated(self, widget, path, view_column):
		treeiter=self.store.get_iter(path)
		selected_title=self.store.get_path(treeiter)
		self.client.play(selected_title)

class Browser(Gtk.Box):
	def __init__(self, client, settings, window):
		Gtk.Box.__init__(self, orientation=Gtk.Orientation.HORIZONTAL, spacing=3)

		#adding vars
		self.client=client
		self.settings=settings
		self.window=window

		#widgets
		self.artist_list=ArtistView(self.client)
		self.album_list=AlbumView(self.client, self.settings)
		self.title_list=TrackView(self.client, self.settings)

		#connect
		self.artist_change=self.artist_list.selection.connect("changed", self.on_artist_selection_change)
		self.album_change=self.album_list.iconview.connect("selection-changed", self.on_album_selection_change)
		self.album_item_activated=self.album_list.iconview.connect("item-activated", self.on_album_item_activated)
		self.album_list.iconview.connect("button-press-event", self.on_album_view_button_press_event)

		#timeouts
		GLib.timeout_add(1000, self.refresh)

		self.go_home(self, first_run=True)

		#packing
		self.paned1=Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
		self.paned2=Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
		self.paned1.pack1(self.artist_list, False, False)
		self.paned1.pack2(self.album_list, True, False)
		self.paned2.pack1(self.paned1, True, False)
		self.paned2.pack2(self.title_list, False, False)
		self.load_settings()
		self.pack_start(self.paned2, True, True, 0)

	def save_settings(self):
		self.settings.set_int("paned1", self.paned1.get_position())
		self.settings.set_int("paned2", self.paned2.get_position())

	def load_settings(self):
		self.paned1.set_position(self.settings.get_int("paned1"))
		self.paned2.set_position(self.settings.get_int("paned2"))

	def refresh(self):
		self.artist_list.selection.handler_block(self.artist_change)
		return_val=self.artist_list.refresh()
		self.artist_list.selection.handler_unblock(self.artist_change)
		if return_val:
			self.go_home(self, first_run=True)
		return True

	def go_home(self, widget, first_run=False): #TODO
		try:
			songid=self.client.status()["songid"]
			song=self.client.playlistid(songid)[0]

			row_num=len(self.artist_list.store)
			for i in range(0, row_num):
				path=Gtk.TreePath(i)
				treeiter = self.artist_list.store.get_iter(path)
				if self.artist_list.store.get_value(treeiter, 0) == song["albumartist"]:
					self.artist_list.selection.select_iter(treeiter)
					self.artist_list.treeview.scroll_to_cell(path)
					break
			if not self.settings.get_boolean("add-album") or first_run:
				self.album_list.iconview.handler_block(self.album_change)
			self.album_list.iconview.unselect_all()
			row_num=len(self.album_list.store)
			for i in range(0, row_num):
				path=Gtk.TreePath(i)
				treeiter = self.album_list.store.get_iter(path)
				if self.album_list.store.get_value(treeiter, 3) == song["album"]:
					self.album_list.iconview.select_path(path)
					self.album_list.iconview.scroll_to_path(path, True, 0, 0)
					break
			if not self.settings.get_boolean("add-album") or first_run:
				self.album_list.iconview.handler_unblock(self.album_change)
		except:
			self.artist_list.selection.unselect_all()
			self.album_list.store.clear()
		treeview, treeiter=self.title_list.selection.get_selected()
		if not treeiter == None:
			path=treeview.get_path(treeiter)
			self.title_list.treeview.scroll_to_cell(path) #TODO multiple home-button presses needed

	def on_album_view_button_press_event(self, widget, event):
		path = widget.get_path_at_pos(int(event.x), int(event.y))
		if not path == None:
			if not event.button == 1:
				treeiter=self.album_list.store.get_iter(path)
				selected_album=self.album_list.store.get_value(treeiter, 3)
				selected_album_year=self.album_list.store.get_value(treeiter, 4)
				treeiter=self.artist_list.selection.get_selected()[1]
				selected_artist=self.artist_list.store.get_value(treeiter, 0)
			if event.button == 2:
				self.title_list.album_to_playlist(selected_album, selected_artist, selected_album_year, True)
			elif event.button == 3:
				if self.client.connected():
					album = AlbumDialog(self.window, self.client, selected_album, selected_artist, selected_album_year)
					response = album.run()
					if response == Gtk.ResponseType.OK:
						self.title_list.album_to_playlist(selected_album, selected_artist, selected_album_year, False)
					elif response == Gtk.ResponseType.ACCEPT:
						self.title_list.album_to_playlist(selected_album, selected_artist, selected_album_year, True)
					elif response == Gtk.ResponseType.YES:
						self.title_list.album_to_playlist(selected_album, selected_artist, selected_album_year, False, True)
					album.destroy()


	def on_album_selection_change(self, widget):
		paths=widget.get_selected_items()
		if not len(paths) == 0:
			treeiter=self.album_list.store.get_iter(paths[0])
			selected_album=self.album_list.store.get_value(treeiter, 3)
			selected_album_year=self.album_list.store.get_value(treeiter, 4)
			treeiter=self.artist_list.selection.get_selected()[1]
			selected_artist=self.artist_list.store.get_value(treeiter, 0)
			self.title_list.album_to_playlist(selected_album, selected_artist, selected_album_year, False)

	def on_album_item_activated(self, widget, path):
		treeiter=self.album_list.store.get_iter(path)
		selected_album=self.album_list.store.get_value(treeiter, 3)
		selected_album_year=self.album_list.store.get_value(treeiter, 4)
		treeiter=self.artist_list.selection.get_selected()[1]
		selected_artist=self.artist_list.store.get_value(treeiter, 0)
		self.title_list.album_to_playlist(selected_album, selected_artist, selected_album_year, False, True)

	def on_artist_selection_change(self, widget):
		treeiter=widget.get_selected()[1]
		if not treeiter == None:
			def test(*args):
				return False
			selected_artist=self.artist_list.store.get_value(treeiter, 0)
			self.artist_list.selection.handler_block(self.artist_change)
			self.artist_list.selection.set_select_function(test)
			self.album_list.refresh(selected_artist)
			self.artist_list.selection.set_select_function(None)
			self.artist_list.selection.select_iter(treeiter)
			self.artist_list.selection.handler_unblock(self.artist_change)
		else:
			self.album_list.refresh(None)

class ProfileSettings(Gtk.Grid):
	def __init__(self, parent, settings):
		Gtk.Grid.__init__(self)
		self.set_row_spacing(3)
		self.set_column_spacing(3)
		self.set_property("border-width", 3)

		#adding vars
		self.settings = settings

		#widgets
		self.profiles_combo=Gtk.ComboBoxText()
		self.profiles_combo.set_entry_text_column(0)

		add_button=Gtk.Button(label=None, image=Gtk.Image(stock=Gtk.STOCK_ADD))
		delete_button=Gtk.Button(label=None, image=Gtk.Image(stock=Gtk.STOCK_DELETE))

		self.profile_entry=Gtk.Entry()
		self.host_entry=Gtk.Entry()
		self.port_entry=IntEntry(0, 0, 65535)
		self.path_select_button=Gtk.Button(label=_("Select"), image=Gtk.Image(stock=Gtk.STOCK_OPEN))

		profiles_label=Gtk.Label(label=_("Profile:"))
		profiles_label.set_xalign(1)
		profile_label=Gtk.Label(label=_("Name:"))
		profile_label.set_xalign(1)
		host_label=Gtk.Label(label=_("Host:"))
		host_label.set_xalign(1)
		port_label=Gtk.Label(label=_("Port:"))
		port_label.set_xalign(1)
		path_label=Gtk.Label(label=_("Music lib:"))
		path_label.set_xalign(1)

		#connect
		self.profile_entry_changed=self.profile_entry.connect("activate", self.on_profile_entry_changed)
		self.host_entry_changed=self.host_entry.connect("activate", self.on_host_entry_changed)
		self.port_entry_changed=self.port_entry.connect("value-changed", self.on_port_entry_changed)
		self.path_select_button.connect("clicked", self.on_path_select_button_clicked, parent)
		add_button.connect("clicked", self.on_add_button_clicked)
		delete_button.connect("clicked", self.on_delete_button_clicked)
		self.profiles_combo_changed=self.profiles_combo.connect("changed", self.on_profiles_changed)

		self.profiles_combo_reload()
		self.profiles_combo.set_active(0)

		#packing
		self.add(profiles_label)
		self.attach_next_to(profile_label, profiles_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(host_label, profile_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(port_label, host_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(path_label, port_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(self.profiles_combo, profiles_label, Gtk.PositionType.RIGHT, 1, 1)
		self.attach_next_to(add_button, self.profiles_combo, Gtk.PositionType.RIGHT, 1, 1)
		self.attach_next_to(delete_button, add_button, Gtk.PositionType.RIGHT, 1, 1)
		self.attach_next_to(self.profile_entry, profile_label, Gtk.PositionType.RIGHT, 1, 1)
		self.attach_next_to(self.host_entry, host_label, Gtk.PositionType.RIGHT, 1, 1)
		self.attach_next_to(self.port_entry, port_label, Gtk.PositionType.RIGHT, 1, 1)
		self.attach_next_to(self.path_select_button, path_label, Gtk.PositionType.RIGHT, 1, 1)

	def settings_array_append(self, vtype, key, value): #append to Gio.Settings (self.settings) array
		array=self.settings.get_value(key).unpack()
		array.append(value)
		self.settings.set_value(key, GLib.Variant(vtype, array))

	def settings_array_delete(self, vtype, key, pos): #delete entry of Gio.Settings (self.settings) array
		array=self.settings.get_value(key).unpack()
		array.pop(pos)
		self.settings.set_value(key, GLib.Variant(vtype, array))

	def settings_array_modify(self, vtype, key, pos, value): #modify entry of Gio.Settings (self.settings) array
		array=self.settings.get_value(key).unpack()
		array[pos]=value
		self.settings.set_value(key, GLib.Variant(vtype, array))

	def profiles_combo_reload(self, *args):
		self.profiles_combo.handler_block(self.profiles_combo_changed)
		self.profile_entry.handler_block(self.profile_entry_changed)
		self.host_entry.handler_block(self.host_entry_changed)
		self.port_entry.handler_block(self.port_entry_changed)

		self.profiles_combo.remove_all()
		for profile in self.settings.get_value("profiles"):
			self.profiles_combo.append_text(profile)

		self.profiles_combo.handler_unblock(self.profiles_combo_changed)
		self.profile_entry.handler_unblock(self.profile_entry_changed)
		self.host_entry.handler_unblock(self.host_entry_changed)
		self.port_entry.handler_unblock(self.port_entry_changed)

	def on_add_button_clicked(self, *args):
		pos=self.profiles_combo.get_active()
		self.settings_array_append('as', "profiles", "new profile")
		self.settings_array_append('as', "hosts", "localhost")
		self.settings_array_append('ai', "ports", 6600)
		self.settings_array_append('as', "paths", "")
		self.profiles_combo_reload()
		self.profiles_combo.set_active(pos)

	def on_delete_button_clicked(self, *args):
		pos=self.profiles_combo.get_active()
		self.settings_array_delete('as', "profiles", pos)
		self.settings_array_delete('as', "hosts", pos)
		self.settings_array_delete('ai', "ports", pos)
		self.settings_array_delete('as', "paths", pos)
		self.profiles_combo_reload()
		self.profiles_combo.set_active(0)	

	def on_profile_entry_changed(self, *args):
		pos=self.profiles_combo.get_active()
		self.settings_array_modify('as', "profiles", pos, self.profile_entry.get_text())
		self.profiles_combo_reload()
		self.profiles_combo.set_active(pos)

	def on_host_entry_changed(self, *args):
		self.settings_array_modify('as', "hosts", self.profiles_combo.get_active(), self.host_entry.get_text())

	def on_port_entry_changed(self, *args):
		self.settings_array_modify('ai', "ports", self.profiles_combo.get_active(), self.port_entry.get_int())

	def on_path_select_button_clicked(self, widget, parent):
		dialog = Gtk.FileChooserDialog(title=_("Choose directory"), transient_for=parent, action=Gtk.FileChooserAction.SELECT_FOLDER)
		dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
		dialog.add_buttons(Gtk.STOCK_OK, Gtk.ResponseType.OK)
		dialog.set_default_size(800, 400)
		dialog.set_current_folder(self.settings.get_value("paths")[self.profiles_combo.get_active()])
		response = dialog.run()
		if response == Gtk.ResponseType.OK:
			self.settings_array_modify('as', "paths", self.profiles_combo.get_active(), dialog.get_filename())
		dialog.destroy()

	def on_profiles_changed(self, *args):
		active=self.profiles_combo.get_active()
		self.profile_entry.handler_block(self.profile_entry_changed)
		self.host_entry.handler_block(self.host_entry_changed)
		self.port_entry.handler_block(self.port_entry_changed)

		self.profile_entry.set_text(self.settings.get_value("profiles")[active])
		self.host_entry.set_text(self.settings.get_value("hosts")[active])
		self.port_entry.set_int(self.settings.get_value("ports")[active])
		self.path_select_button.set_tooltip_text(self.settings.get_value("paths")[active])

		self.profile_entry.handler_unblock(self.profile_entry_changed)
		self.host_entry.handler_unblock(self.host_entry_changed)
		self.port_entry.handler_unblock(self.port_entry_changed)

class GeneralSettings(Gtk.Grid):
	def __init__(self, settings):
		Gtk.Grid.__init__(self)
		self.set_row_spacing(3)
		self.set_column_spacing(3)
		self.set_property("border-width", 3)

		#adding vars
		self.settings = settings

		#widgets
		track_cover_label=Gtk.Label(label=_("Main cover size:"))
		track_cover_label.set_xalign(1)
		album_cover_label=Gtk.Label(label=_("Album-view cover size:"))
		album_cover_label.set_xalign(1)

		track_cover_size=IntEntry(self.settings.get_int("track-cover"), 100, 1200)
		album_cover_size=IntEntry(self.settings.get_int("album-cover"), 50, 600)

		show_stop=Gtk.CheckButton(label=_("Show stop button"))
		show_stop.set_active(self.settings.get_boolean("show-stop"))

		show_album_view_tooltips=Gtk.CheckButton(label=_("Show tooltips in album view"))
		show_album_view_tooltips.set_active(self.settings.get_boolean("show-album-view-tooltips"))

		send_notify=Gtk.CheckButton(label=_("Send notification on title change"))
		send_notify.set_active(self.settings.get_boolean("send-notify"))

		stop_on_quit=Gtk.CheckButton(label=_("Stop playback on quit"))
		stop_on_quit.set_active(self.settings.get_boolean("stop-on-quit"))

		add_album=Gtk.CheckButton(label=_("Play selected album after current title"))
		add_album.set_active(self.settings.get_boolean("add-album"))

		#connect
		track_cover_size.connect("value-changed", self.on_int_changed, "track-cover")
		album_cover_size.connect("value-changed", self.on_int_changed, "album-cover")
		show_stop.connect("toggled", self.on_toggled, "show-stop")
		show_album_view_tooltips.connect("toggled", self.on_toggled, "show-album-view-tooltips")
		send_notify.connect("toggled", self.on_toggled, "send-notify")
		stop_on_quit.connect("toggled", self.on_toggled, "stop-on-quit")
		add_album.connect("toggled", self.on_toggled, "add-album")

		#packing
		self.add(track_cover_label)
		self.attach_next_to(album_cover_label, track_cover_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(track_cover_size, track_cover_label, Gtk.PositionType.RIGHT, 1, 1)
		self.attach_next_to(album_cover_size, album_cover_label, Gtk.PositionType.RIGHT, 1, 1)
		self.attach_next_to(show_stop, album_cover_label, Gtk.PositionType.BOTTOM, 2, 1)
		self.attach_next_to(show_album_view_tooltips, show_stop, Gtk.PositionType.BOTTOM, 2, 1)
		self.attach_next_to(send_notify, show_album_view_tooltips, Gtk.PositionType.BOTTOM, 2, 1)
		self.attach_next_to(add_album, send_notify, Gtk.PositionType.BOTTOM, 2, 1)
		self.attach_next_to(stop_on_quit, add_album, Gtk.PositionType.BOTTOM, 2, 1)

	def on_int_changed(self, widget, key):
		self.settings.set_int(key, widget.get_int())

	def on_toggled(self, widget, key):
		self.settings.set_boolean(key, widget.get_active())

class SettingsDialog(Gtk.Dialog):
	def __init__(self, parent, settings):
		Gtk.Dialog.__init__(self, title=_("Settings"), transient_for=parent)
		self.add_button(Gtk.STOCK_OK, Gtk.ResponseType.OK)
		self.set_default_size(500, 400)

		#adding vars
		self.settings = settings

		#widgets
		general=GeneralSettings(self.settings)
		profiles=ProfileSettings(parent, self.settings)

		#packing
		tabs = Gtk.Notebook()
		tabs.append_page(general, Gtk.Label(label=_("General")))
		tabs.append_page(profiles, Gtk.Label(label=_("Profiles")))
		self.vbox.pack_start(tabs, True, True, 0) #vbox default widget of dialogs

		self.show_all()

class ClientControl(Gtk.ButtonBox):
	def __init__(self, client, settings):
		Gtk.ButtonBox.__init__(self, spacing=3)

		#adding vars
		self.client=client
		self.settings=settings

		#widgets
		self.play_button = Gtk.Button(image=Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.DND))
		self.stop_button = Gtk.Button(image=Gtk.Image.new_from_icon_name("media-playback-stop-symbolic", Gtk.IconSize.DND))
		self.prev_button = Gtk.Button(image=Gtk.Image.new_from_icon_name("media-skip-backward-symbolic", Gtk.IconSize.DND))
		self.next_button = Gtk.Button(image=Gtk.Image.new_from_icon_name("media-skip-forward-symbolic", Gtk.IconSize.DND))

		#connect
		self.play_button.connect("clicked", self.on_play_clicked)
		self.stop_button.connect("clicked", self.on_stop_clicked)
		self.prev_button.connect("clicked", self.on_prev_clicked)
		self.next_button.connect("clicked", self.on_next_clicked)
		self.settings.connect("changed::show-stop", self.on_settings_changed)

		#timeouts
		GLib.timeout_add(1000, self.update)

		#packing
		self.pack_start(self.prev_button, True, True, 0)
		self.pack_start(self.play_button, True, True, 0)
		if self.settings.get_boolean("show-stop"):
			self.pack_start(self.stop_button, True, True, 0)
		self.pack_start(self.next_button, True, True, 0)

	def update(self):
		if self.client.connected():
			status=self.client.status()
			if status["state"] == "play":
				self.play_button.set_image(Gtk.Image.new_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.DND))
				self.prev_button.set_sensitive(True)
				self.next_button.set_sensitive(True)
			elif status["state"] == "pause":
				self.play_button.set_image(Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.DND))
				self.prev_button.set_sensitive(True)
				self.next_button.set_sensitive(True)
			else:
				self.play_button.set_image(Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.DND))
				self.prev_button.set_sensitive(False)
				self.next_button.set_sensitive(False)
		return True

	def on_play_clicked(self, widget):
		if self.client.connected():
			status=self.client.status()
			if status["state"] == "play":
				self.client.pause(1)
			elif status["state"] == "pause":
				self.client.pause(0)
			else:
				try:
					self.client.play(status["song"])
				except:
					try:
						self.client.play(0) #bad song index possible
					except:
						pass
			self.update()

	def on_stop_clicked(self, widget):
		if self.client.connected():
			self.client.stop()
			self.update()

	def on_prev_clicked(self, widget):
		if self.client.connected():
			self.client.previous()

	def on_next_clicked(self, widget):
		if self.client.connected():
			self.client.next()

	def on_settings_changed(self, *args):
		if self.settings.get_boolean("show-stop"):
			self.pack_start(self.stop_button, True, True, 0)
			self.reorder_child(self.stop_button, 2)
			self.stop_button.show()
		else:
			self.remove(self.stop_button)

class SeekBar(Gtk.Box):
	def __init__(self, client):
		Gtk.Box.__init__(self)

		#adding vars
		self.client=client

		#widgets
		self.elapsed=Gtk.Label()
		self.rest=Gtk.Label()
		self.scale=Gtk.Scale.new_with_range(orientation=Gtk.Orientation.HORIZONTAL, min=0, max=100, step=0.001)
		self.scale.set_draw_value(False)

		#connect
		self.scale.connect("change-value", self.seek)

		#timeouts
		GLib.timeout_add(100, self.update)

		#packing
		self.pack_start(self.elapsed, False, False, 0)
		self.pack_start(self.scale, True, True, 0)
		self.pack_end(self.rest, False, False, 0)

	def seek(self, range, scroll, value):
		status=self.client.status()
		duration=float(status["duration"])
		factor=(value/100)
		pos=(duration*factor)
		self.client.seekcur(pos)

	def update(self):
		try:
			status=self.client.status()
			duration=float(status["duration"])
			elapsed=float(status["elapsed"])
			fraction=(elapsed/duration)*100
			self.scale.set_value(fraction)
			self.elapsed.set_text(str(datetime.timedelta(seconds=int(elapsed))))
			self.rest.set_text("-"+str(datetime.timedelta(seconds=int(duration-elapsed))))
			self.scale.set_sensitive(True)
		except:
			self.scale.set_value(0.0)
			self.elapsed.set_text("0:00:00")
			self.rest.set_text("-0:00:00")
			self.scale.set_sensitive(False)
		return True

class PlaybackOptions(Gtk.Box):
	def __init__(self, client):
		Gtk.Box.__init__(self)

		#adding vars
		self.client=client

		#widgets
		self.random=Gtk.ToggleButton(image=Gtk.Image.new_from_icon_name("media-playlist-shuffle-symbolic", Gtk.IconSize.DND))
		self.random.set_tooltip_text(_("Random mode"))
		self.repeat=Gtk.ToggleButton(image=Gtk.Image.new_from_icon_name("media-playlist-repeat-symbolic", Gtk.IconSize.DND))
		self.repeat.set_tooltip_text(_("Repeat mode"))
		self.single=Gtk.ToggleButton(image=Gtk.Image.new_from_icon_name("zoom-original-symbolic", Gtk.IconSize.DND))
		self.single.set_tooltip_text(_("Single mode"))
		self.consume=Gtk.ToggleButton(image=Gtk.Image.new_from_icon_name("edit-cut-symbolic", Gtk.IconSize.DND))
		self.consume.set_tooltip_text(_("Consume mode"))
		self.volume=Gtk.VolumeButton()

		#connect
		self.random_toggled=self.random.connect("toggled", self.set_random)
		self.repeat_toggled=self.repeat.connect("toggled", self.set_repeat)
		self.single_toggled=self.single.connect("toggled", self.set_single)
		self.consume_toggled=self.consume.connect("toggled", self.set_consume)
		self.volume_changed=self.volume.connect("value-changed", self.set_volume)

		#timeouts
		GLib.timeout_add(100, self.update)

		#packing
		ButtonBox=Gtk.ButtonBox()
		ButtonBox.set_property("layout-style", Gtk.ButtonBoxStyle.EXPAND)
		ButtonBox.pack_start(self.repeat, True, True, 0)
		ButtonBox.pack_start(self.random, True, True, 0)
		ButtonBox.pack_start(self.single, True, True, 0)
		ButtonBox.pack_start(self.consume, True, True, 0)
		self.pack_start(ButtonBox, True, True, 0)
		self.pack_start(self.volume, True, True, 0)

	def set_random(self, widget):
		if widget.get_active():
			self.client.random("1")
		else:
			self.client.random("0")

	def set_repeat(self, widget):
		if widget.get_active():
			self.client.repeat("1")
		else:
			self.client.repeat("0")

	def set_single(self, widget):
		if widget.get_active():
			self.client.single("1")
		else:
			self.client.single("0")

	def set_consume(self, widget):
		if widget.get_active():
			self.client.consume("1")
		else:
			self.client.consume("0")

	def set_volume(self, widget, value):
		self.client.setvol(str(int(value*100)))

	def update(self):
		self.repeat.handler_block(self.repeat_toggled)
		self.random.handler_block(self.random_toggled)
		self.single.handler_block(self.single_toggled)
		self.consume.handler_block(self.consume_toggled)
		self.volume.handler_block(self.volume_changed)
		if self.client.connected():
			status=self.client.status()
			if status["repeat"] == "0":
				self.repeat.set_active(False)
			else:
				self.repeat.set_active(True)
			if status["random"] == "0":
				self.random.set_active(False)
			else:
				self.random.set_active(True)
			if status["single"] == "0":
				self.single.set_active(False)
			else:
				self.single.set_active(True)
			if status["consume"] == "0":
				self.consume.set_active(False)
			else:
				self.consume.set_active(True)
			try:
				self.volume.set_value((int(status["volume"])/100))
			except:
				self.volume.set_value(0)
		else:
			self.repeat.set_active(False)
			self.random.set_active(False)
			self.single.set_active(False)
			self.consume.set_active(False)
			self.volume.set_value(0)
		self.repeat.handler_unblock(self.repeat_toggled)
		self.random.handler_unblock(self.random_toggled)
		self.single.handler_unblock(self.single_toggled)
		self.consume.handler_unblock(self.consume_toggled)
		self.volume.handler_unblock(self.volume_changed)
		return True

class AudioType(Gtk.EventBox):
	def __init__(self, client):
		Gtk.EventBox.__init__(self)
		self.set_tooltip_text(_("Right click to show additional information"))

		#adding vars
		self.client=client

		#widgets
		self.label=Gtk.Label()
		self.label.set_xalign(1)
		self.popover=Gtk.Popover()

		#Store
		#(tag, value)
		self.store = Gtk.ListStore(str, str)

		#TreeView
		self.treeview = Gtk.TreeView(model=self.store)
		self.treeview.set_search_column(-1)
		sel = self.treeview.get_selection()
		sel.set_mode(Gtk.SelectionMode.NONE)

		#Column
		renderer_text = Gtk.CellRendererText()

		self.column_tag = Gtk.TreeViewColumn(_("MPD-Tag"), renderer_text, text=0)
		self.treeview.append_column(self.column_tag)

		self.column_value = Gtk.TreeViewColumn(_("Value"), renderer_text, text=1)
		self.treeview.append_column(self.column_value)

		self.popover.add(self.treeview)

		#timeouts
		GLib.timeout_add(1000, self.update)

		#connect
		self.connect("button-press-event", self.on_button_press_event)

		self.add(self.label)

	def update(self):
		if self.client.connected():
			status=self.client.status()
			try:
				file_type=self.client.playlistinfo(status["song"])[0]["file"].split('.')[-1]
				freq, res, chan = status["audio"].split(':')
				freq=str(float(freq)/1000)
				brate = status["bitrate"]
				string=_("%(bitrate)s kb/s, %(frequency)s kHz, %(resolution)s bit, %(channels)s channels, %(file_type)s") % {"bitrate": brate, "frequency": freq, "resolution": res, "channels": chan, "file_type": file_type}
				self.label.set_text(string)
			except:
				self.label.set_text("-")
		else:
			self.label.set_text("-")
		return True

	def on_button_press_event(self, widget, event):
		if event.button == 3:
			self.popover.remove(self.treeview) #workaround
			self.store.clear()
			self.popover.add(self.treeview) #workaround
			try:
				song=self.client.status()["song"]
				tags=self.client.playlistinfo(song)[0]
				for key in tags:
					if key == "time":
						self.store.append([key, str(datetime.timedelta(seconds=int(tags[key])))])
					else:
						self.store.append([key, tags[key]])
				self.popover.set_relative_to(self)
				self.popover.show_all()
				self.popover.popup()
			except:
				pass

class ProfileSelect(Gtk.ComboBoxText):
	def __init__(self, client, settings):
		Gtk.ComboBoxText.__init__(self)

		#adding vars
		self.client=client
		self.settings=settings

		self.changed=self.connect("changed", self.on_changed)

		self.reload()
		self.set_active(self.settings.get_int("active-profile"))

		self.settings.connect("changed::profiles", self.on_settings_changed)
		self.settings.connect("changed::hosts", self.on_settings_changed)
		self.settings.connect("changed::ports", self.on_settings_changed)
		self.settings.connect("changed::paths", self.on_settings_changed)

	def reload(self, *args):
		self.handler_block(self.changed)
		self.remove_all()
		for profile in self.settings.get_value("profiles"):
			self.append_text(profile)
		self.handler_unblock(self.changed)

	def on_settings_changed(self, *args):
		self.reload()

	def on_changed(self, *args):
		active=self.get_active()
		self.settings.set_int("active-profile", active)
		try:
			self.client.disconnect()
			self.client.connect(self.settings.get_value("hosts")[active], self.settings.get_value("ports")[active])
		except:
			pass

class ServerStats(Gtk.Dialog):
	def __init__(self, parent, client):
		Gtk.Dialog.__init__(self, title=_("Stats"), transient_for=parent)

		#adding vars
		self.client=client

		#Store
		#(tag, value)
		self.store = Gtk.ListStore(str, str)

		#TreeView
		self.treeview = Gtk.TreeView(model=self.store)
		self.treeview.set_search_column(-1)
		sel = self.treeview.get_selection()
		sel.set_mode(Gtk.SelectionMode.NONE)

		#Column
		renderer_text = Gtk.CellRendererText()

		self.column_tag = Gtk.TreeViewColumn(_("Tag"), renderer_text, text=0)
		self.treeview.append_column(self.column_tag)

		self.column_value = Gtk.TreeViewColumn(_("Value"), renderer_text, text=1)
		self.treeview.append_column(self.column_value)

		stats=self.client.stats()
		for key in stats:
			if key == "uptime" or key == "playtime" or key == "db_playtime":
				self.store.append([key, str(datetime.timedelta(seconds=int(stats[key])))])
			elif key == "db_update":
				self.store.append([key, str(datetime.datetime.fromtimestamp(int(stats[key])))])
			else:
				self.store.append([key, stats[key]])

		self.vbox.pack_start(self.treeview, True, True, 0)
		self.show_all()

class Search(Gtk.Dialog):
	def __init__(self, parent, client):
		Gtk.Dialog.__init__(self, title=_("Search"), transient_for=parent)
		self.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
		self.set_default_size(800, 600)

		#adding vars
		self.client=client

		#scroll
		scroll=Gtk.ScrolledWindow()
		scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

		#search entry
		self.search_entry=Gtk.SearchEntry()

		#label
		self.label=Gtk.Label()
		self.label.set_xalign(1)

		#Store
		#(track, title, artist, album, duration, file)
		self.store = Gtk.ListStore(str, str, str, str, str, str)

		#TreeView
		self.treeview = Gtk.TreeView(model=self.store)
		self.treeview.set_search_column(-1)
		self.treeview.columns_autosize()

		self.selection = self.treeview.get_selection()
		self.selection.set_mode(Gtk.SelectionMode.SINGLE)

		#Column
		renderer_text = Gtk.CellRendererText()

		self.column_track = Gtk.TreeViewColumn(_("No"), renderer_text, text=0)
		self.column_track.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_track.set_property("resizable", False)
		self.treeview.append_column(self.column_track)

		self.column_title = Gtk.TreeViewColumn(_("Title"), renderer_text, text=1)
		self.column_title.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_title.set_property("resizable", False)
		self.treeview.append_column(self.column_title)

		self.column_artist = Gtk.TreeViewColumn(_("Artist"), renderer_text, text=2)
		self.column_artist.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_artist.set_property("resizable", False)
		self.treeview.append_column(self.column_artist)

		self.column_album = Gtk.TreeViewColumn(_("Album"), renderer_text, text=3)
		self.column_album.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_album.set_property("resizable", False)
		self.treeview.append_column(self.column_album)

		self.column_time = Gtk.TreeViewColumn(_("Length"), renderer_text, text=4)
		self.column_time.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_time.set_property("resizable", False)
		self.treeview.append_column(self.column_time)

		#connect
		self.title_activated=self.treeview.connect("row-activated", self.on_row_activated)
		self.title_change=self.selection.connect("changed", self.on_selection_change)
		self.search_entry.connect("search-changed", self.on_search_changed)

		#packing
		scroll.add(self.treeview)
		self.vbox.pack_start(self.search_entry, False, False, 0) #vbox default widget of dialogs
		self.vbox.pack_start(scroll, True, True, 0)
		self.vbox.pack_start(self.label, False, False, 0)
		self.show_all()

	def on_row_activated(self, widget, path, view_column):
		treeiter=self.store.get_iter(path)
		selected_title=self.store.get_value(treeiter, 5)
		self.client.clear()
		self.client.add(selected_title)
		self.client.play(0)

	def on_selection_change(self, widget):
		treeiter=widget.get_selected()[1]
		if not treeiter == None:
			selected_title=self.store.get_value(treeiter, 5)
			self.client.add(selected_title)

	def on_search_changed(self, widget):
		self.store.clear()
		for song in self.client.search("title", self.search_entry.get_text()):
			try:
				title=song["title"]
			except:
				title=_("Unknown Title")
			try:
				track=song["track"].zfill(2)
			except:
				track="00"
			try:
				artist=song["artist"]
			except:
				artist=_("Unknown Artist")
			try:
				album=song["album"]
			except:
				album=_("Unknown Album")
			try:
				dura=float(song["duration"])
			except:
				dura=0.0
			duration=str(datetime.timedelta(seconds=int(dura)))
			self.store.append([track, title, artist, album, duration, song["file"].replace("&", "")] )
		self.label.set_text(_("Hits: %i") % (len(self.store)))

class LyricsWindow(Gtk.Window): #Lyrics view with own client because MPDClient isn't threadsafe
	def __init__(self, settings):
		Gtk.Window.__init__(self, title=_("Lyrics"))
		self.set_icon_name("mpdevil")
		self.set_default_size(450, 800)

		#adding vars
		self.client=Client()
		self.settings=settings

		#connect client
		active=self.settings.get_int("active-profile")
		try:
			self.client.connect(self.settings.get_value("hosts")[active], self.settings.get_value("ports")[active])
		except:
			pass
		self.current_song={}

		#widgets
		self.scroll=Gtk.ScrolledWindow()
		self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
		self.label=Gtk.Label()
		self.label.set_yalign(0)
		self.label.set_xalign(0)

		#connect
		self.settings.connect("changed::active-profile", self.on_settings_changed)
		self.connect("destroy", self.quit)

		#packing
		self.scroll.add(self.label)
		self.add(self.scroll)

		self.show_all()

		#update loop in extra thread
		def update_label(text):
			self.label.set_text(text)
			return False

		def update_loop():
			while not self.stop:
				try:
					cs=self.client.currentsong()
					cs.pop("pos") #avoid unnecessary reloads caused by position change of current title
					if cs != self.current_song:
						GLib.idle_add(update_label, _("searching..."))
						try:
							text=self.getLyrics(cs["artist"],cs["title"])
						except:
							text=_("not found")
						GLib.idle_add(update_label, text)
						self.current_song=cs
				except:
					self.current_song={}
					GLib.idle_add(update_label, _("not connected"))
				time.sleep(1)

		self.stop=False
		update_thread=threading.Thread(target=update_loop, daemon=True)
		update_thread.start()

	def quit(self, *args):
		self.stop=True
		self.client.disconnect()

	def getLyrics(self, singer, song): #partially copied from PyLyrics 1.1.0
		#Replace spaces with _
		singer = singer.replace(' ', '_')
		song = song.replace(' ', '_')
		r = requests.get('http://lyrics.wikia.com/{0}:{1}'.format(singer,song))
		s = BeautifulSoup(r.text)
		#Get main lyrics holder
		lyrics = s.find("div",{'class':'lyricbox'})
		if lyrics is None:
			raise ValueError("Song or Singer does not exist or the API does not have Lyrics")
			return None
		#Remove Scripts
		[s.extract() for s in lyrics('script')]
		#Remove Comments
		comments = lyrics.findAll(text=lambda text:isinstance(text, Comment))
		[comment.extract() for comment in comments]
		#Remove span tag (Needed for instrumantal)
		if not lyrics.span == None:
			lyrics.span.extract()
		#Remove unecessary tags
		for tag in ['div','i','b','a']:
			for match in lyrics.findAll(tag):
				match.replaceWithChildren()
		#Get output as a string and remove non unicode characters and replace <br> with newlines
		output = str(lyrics).encode('utf-8', errors='replace')[22:-6:].decode("utf-8").replace('\n','').replace('<br/>','\n')
		try:
			return output
		except:
			return output.encode('utf-8')

	def on_settings_changed(self, *args):
		active=self.settings.get_int("active-profile")
		try:
			self.client.disconnect()
			self.client.connect(self.settings.get_value("hosts")[active], self.settings.get_value("ports")[active])
		except:
			pass

class MainWindow(Gtk.ApplicationWindow):
	def __init__(self, app, client, settings):
		Gtk.ApplicationWindow.__init__(self, title=("mpdevil"), application=app)
		self.set_icon_name("mpdevil")
		self.settings = settings
		self.set_default_size(self.settings.get_int("width"), self.settings.get_int("height"))

		#adding vars
		self.client=client
		self.songid_playing=None

		#actions
		save_action = Gio.SimpleAction.new("save", None)
		save_action.connect("activate", self.on_save)
		self.add_action(save_action)

		settings_action = Gio.SimpleAction.new("settings", None)
		settings_action.connect("activate", self.on_settings)
		self.add_action(settings_action)

		stats_action = Gio.SimpleAction.new("stats", None)
		stats_action.connect("activate", self.on_stats)
		self.add_action(stats_action)

		update_action = Gio.SimpleAction.new("update", None)
		update_action.connect("activate", self.on_update)
		self.add_action(update_action)

		#widgets
		self.browser=Browser(self.client, self.settings, self)
		self.profiles=ProfileSelect(self.client, self.settings)
		self.profiles.set_tooltip_text(_("Select profile"))
		self.control=ClientControl(self.client, self.settings)
		self.progress=SeekBar(self.client)
		self.go_home_button=Gtk.Button(image=Gtk.Image.new_from_icon_name("go-home-symbolic", Gtk.IconSize.DND))
		self.go_home_button.set_tooltip_text(_("Return to album of current title"))
		self.search_button=Gtk.Button(image=Gtk.Image.new_from_icon_name("system-search-symbolic", Gtk.IconSize.DND))
		self.search_button.set_tooltip_text(_("Title search"))
		self.lyrics_button=Gtk.ToggleButton(image=Gtk.Image.new_from_icon_name("media-view-subtitles-symbolic", Gtk.IconSize.DND))
		self.lyrics_button.set_tooltip_text(_("Show lyrics"))
		self.play_opts=PlaybackOptions(self.client)

		#info bar
		self.info_bar=Gtk.InfoBar.new()
		self.info_bar.set_revealed(False)
		self.info_bar.add_button(Gtk.STOCK_OK, Gtk.ResponseType.OK)
		self.info_bar.get_content_area().pack_start(Gtk.Label(label=_("Not connected to MPD-server. Reconnect?")), False, False, 0)

		#menu
		menu = Gio.Menu()
		menu.append(_("Save window size"), "win.save")
		menu.append(_("Settings"), "win.settings")
		menu.append(_("Update database"), "win.update")
		menu.append(_("Server stats"), "win.stats")
		menu.append(_("About"), "app.about")
		menu.append(_("Quit"), "app.quit")

		menu_button = Gtk.MenuButton.new()
		menu_popover = Gtk.Popover.new_from_model(menu_button, menu)
		menu_button.set_popover(menu_popover)
		menu_button.set_tooltip_text(_("Main menu"))

		#connect
		self.go_home_button.connect("clicked", self.browser.go_home)
		self.search_button.connect("clicked", self.on_search_clicked)
		self.lyrics_button.connect("toggled", self.on_lyrics_toggled)
		self.info_bar.connect("response", self.on_info_bar_response)
		#unmap space
		binding_set=Gtk.binding_set_find('GtkTreeView')
		Gtk.binding_entry_remove(binding_set, 32, Gdk.ModifierType.MOD2_MASK)
		#map space play/pause
		self.connect("key-press-event", self.on_key_press_event)

		#timeouts
		GLib.timeout_add(1000, self.update, app)

		#packing
		self.vbox=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
		self.hbox=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
		self.vbox.pack_start(self.info_bar, False, False, 0)
		self.vbox.pack_start(self.browser, True, True, 0)
		self.vbox.pack_start(self.hbox, False, False, 0)
		self.hbox.pack_start(self.control, False, False, 0)
		self.hbox.pack_start(self.progress, True, True, 10)
		self.hbox.pack_start(self.go_home_button, False, False, 0)
		self.hbox.pack_start(self.search_button, False, False, 0)
		self.hbox.pack_start(self.lyrics_button, False, False, 0)
		self.hbox.pack_start(self.profiles, False, False, 0)
		self.hbox.pack_start(self.play_opts, False, False, 0)
		self.hbox.pack_end(menu_button, False, False, 0)

		self.add(self.vbox)

	def update(self, app): #update title and send notify
		if self.client.connected():
			self.info_bar.set_revealed(False)
			self.progress.set_sensitive(True)
			self.control.set_sensitive(True)
			self.play_opts.set_sensitive(True)
			self.go_home_button.set_sensitive(True)
			self.search_button.set_sensitive(True)
			self.lyrics_button.set_sensitive(True)
			try:
				songid=self.client.status()["songid"]
				if not songid == self.songid_playing:
					if songid == None:
						self.set_title("mpdevil")
					else:
						song=self.client.playlistid(songid)[0]
						self.set_title(song["artist"]+" - "+song["title"]+" - "+song["album"])
						if not self.is_active() and self.settings.get_boolean("send-notify"):
							notify=Gio.Notification.new(title=song["title"])
							notify.set_body(song["artist"]+"\n"+song["album"])
							app.send_notification(None, notify)
					self.songid_playing=songid
			except:
				self.set_title("mpdevil")
		else:
			self.set_title("mpdevil (not connected)")
			self.songid_playing=None
			self.info_bar.set_revealed(True)
			self.progress.set_sensitive(False)
			self.control.set_sensitive(False)
			self.play_opts.set_sensitive(False)
			self.go_home_button.set_sensitive(False)
			self.search_button.set_sensitive(False)
			self.lyrics_button.set_sensitive(False)
		return True

	def on_info_bar_response(self, info_bar, response_id):
		if response_id == Gtk.ResponseType.OK:
			active=self.settings.get_int("active-profile")
			try:
				self.client.connect(self.settings.get_value("hosts")[active], self.settings.get_value("ports")[active])
			except:
				pass
			info_bar.set_revealed(False)

	def on_search_clicked(self, widget):
		if self.client.connected():
			search = Search(self, self.client)
			search.run()
			search.destroy()

	def on_lyrics_toggled(self, widget):
		if widget.get_active():
			if self.client.connected():
				def set_active(*args):
					self.lyrics_button.set_active(False)
				self.lyrics_win = LyricsWindow(self.settings)
				self.lyrics_win.connect("destroy", set_active)
		else:
			self.lyrics_win.destroy()

	def on_key_press_event(self, widget, event):
		if event.keyval == 32:
			self.control.play_button.grab_focus()

	def on_save(self, action, param):
		size=self.get_size()
		self.settings.set_int("width", size[0])
		self.settings.set_int("height", size[1])
		self.browser.save_settings()

	def on_settings(self, action, param):
		settings = SettingsDialog(self, self.settings)
		settings.run()
		settings.destroy()

	def on_stats(self, action, param):
		if self.client.connected():
			stats = ServerStats(self, self.client)
			stats.run()
			stats.destroy()

	def on_update(self, action, param):
		if self.client.connected():
			self.client.update()

class mpdevil(Gtk.Application):
	BASE_KEY = "org.mpdevil"
	def __init__(self, *args, **kwargs):
		super().__init__(*args, application_id="org.mpdevil", flags=Gio.ApplicationFlags.FLAGS_NONE, **kwargs)
		#Gtk.window_set_default_icon_name("mpdevil")
		self.client=Client()
		self.settings = Gio.Settings.new(self.BASE_KEY)
		self.window=None

	def do_activate(self):
		self.window = MainWindow(self, self.client, self.settings)
		self.window.connect("delete-event", self.on_delete_event)
		self.window.show_all()

	def do_startup(self):
		Gtk.Application.do_startup(self)

		action = Gio.SimpleAction.new("about", None)
		action.connect("activate", self.on_about)
		self.add_action(action)

		action = Gio.SimpleAction.new("quit", None)
		action.connect("activate", self.on_quit)
		self.add_action(action)

	def on_delete_event(self, *args):
		if self.settings.get_boolean("stop-on-quit") and self.client.connected():
			self.client.stop()
		self.quit()

	def on_about(self, action, param):
		dialog=Gtk.AboutDialog(transient_for=self.window, modal=True)
		dialog.set_program_name(NAME)
		dialog.set_version(VERSION)
		dialog.set_comments(_("A small MPD client written in python"))
		dialog.set_authors(["Martin Wagner"])
		dialog.set_website("https://github.com/SoongNoonien/mpdevil")
		dialog.set_logo_icon_name(PACKAGE)
		dialog.run()
		dialog.destroy()

	def on_quit(self, action, param):
		if self.settings.get_boolean("stop-on-quit") and self.client.connected():
			self.client.stop()
		self.quit()

if __name__ == '__main__':
	app = mpdevil()
	app.run(sys.argv)

