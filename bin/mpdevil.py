#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# mpdevil - MPD Client.
# Copyright 2020 Martin Wagner <martin.wagner.dev@gmail.com>
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

# MPRIS interface based on 'mpDris2' (master 19.03.2020) by Jean-Philippe Braun <eon@patapon.info>, Mantas Mikulėnas <grawity@gmail.com>

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Notify', '0.7')
from gi.repository import Gtk, Gio, Gdk, GdkPixbuf, Pango, GObject, GLib, Notify
from mpd import MPDClient
import requests
from bs4 import BeautifulSoup, Comment
import threading
import locale
import gettext
import datetime
import os
import sys
import re

# MPRIS modules
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
import base64

DATADIR='@datadir@'
NAME='mpdevil'
VERSION='@version@'
PACKAGE=NAME.lower()

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
	def __init__(self, default, lower, upper, step):
		Gtk.SpinButton.__init__(self)
		adj=Gtk.Adjustment(value=default, lower=lower, upper=upper, step_increment=step)
		self.set_adjustment(adj)

	def get_int(self):
		return int(self.get_value())

	def set_int(self, value):
		self.set_value(value)

class PixelSizedIcon(Gtk.Image):
	def __init__(self, icon_name, pixel_size):
		Gtk.Image.__init__(self)
		self.set_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
		if pixel_size > 0:
			self.set_pixel_size(pixel_size)

class FocusFrame(Gtk.Overlay):
	def __init__(self):
		Gtk.Overlay.__init__(self)

		self.frame=Gtk.Frame()
		self.frame.set_no_show_all(True)
		self.style_context=self.frame.get_style_context()
		self.provider=Gtk.CssProvider()
		css=b"""* {border-color: @theme_selected_bg_color; border-width: 2px;}"""
		self.provider.load_from_data(css)
		self.style_context.add_provider(self.provider, 800)

		self.add_overlay(self.frame)
		self.set_overlay_pass_through(self.frame, True)

	def set_widget(self, widget):
		widget.connect("focus-in-event", self.on_focus_in_event)
		widget.connect("focus-out-event", self.on_focus_out_event)

	def on_focus_in_event(self, *args):
		self.frame.show()

	def on_focus_out_event(self, *args):
		self.frame.hide()

class Cover(object):
	regex=re.compile(r'^\.?(album|cover|folder|front).*\.(gif|jpeg|jpg|png)$', flags=re.IGNORECASE)
	def __init__(self, lib_path, song_file):
		self.lib_path=lib_path or ""
		self.path=None
		if not song_file == None:
			head, tail=os.path.split(song_file)
			song_dir=os.path.join(self.lib_path, head)
			if os.path.exists(song_dir):
				for f in os.listdir(song_dir):
					if self.regex.match(f):
						self.path=os.path.join(song_dir, f)
						break

	def get_pixbuf(self, size):
		if self.path == None:
			self.path=Gtk.IconTheme.get_default().lookup_icon("mpdevil", size, Gtk.IconLookupFlags.FORCE_SVG).get_filename()  # fallback cover
		return GdkPixbuf.Pixbuf.new_from_file_at_size(self.path, size, size)

class MpdEventEmitter(GObject.Object):
	__gsignals__={
		'database': (GObject.SignalFlags.RUN_FIRST, None, ()),
		'update': (GObject.SignalFlags.RUN_FIRST, None, ()),
		'stored_playlist': (GObject.SignalFlags.RUN_FIRST, None, ()),
		'playlist': (GObject.SignalFlags.RUN_FIRST, None, ()),
		'player': (GObject.SignalFlags.RUN_FIRST, None, ()),
		'mixer': (GObject.SignalFlags.RUN_FIRST, None, ()),
		'output': (GObject.SignalFlags.RUN_FIRST, None, ()),
		'options': (GObject.SignalFlags.RUN_FIRST, None, ()),
		'sticker': (GObject.SignalFlags.RUN_FIRST, None, ()),
		'subscription': (GObject.SignalFlags.RUN_FIRST, None, ()),
		'message': (GObject.SignalFlags.RUN_FIRST, None, ()),
		'disconnected': (GObject.SignalFlags.RUN_FIRST, None, ()),
		'reconnected': (GObject.SignalFlags.RUN_FIRST, None, ()),
		'playing_file_changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
		'periodic_signal': (GObject.SignalFlags.RUN_FIRST, None, ())
	}

	def __init__(self):
		super().__init__()

	# mpd signals
	def do_database(self):
		pass

	def do_update(self):
		pass

	def do_stored_playlist(self):
		pass

	def do_playlist(self):
		pass

	def do_player(self):
		pass

	def do_mixer(self):
		pass

	def do_output(self):
		pass

	def do_options(self):
		pass

	def do_sticker(self):
		pass

	def do_subscription(self):
		pass

	def do_message(self):
		pass

	# custom signals
	def do_disconnected(self):
		pass

	def do_reconnected(self):
		pass

	def do_playing_file_changed(self):
		pass

	def do_periodic_signal(self):
		pass

class ClientHelper():
	def song_to_str_dict(song):  # converts tags with multiple values to comma separated strings
		return_song=song
		for tag, value in return_song.items():
			if type(value) == list:
				return_song[tag]=(', '.join(value))
		return return_song

	def song_to_first_str_dict(song):  # extracts the first value of multiple value tags
		return_song=song
		for tag, value in return_song.items():
			if type(value) == list:
				return_song[tag]=value[0]
		return return_song

	def extend_song_for_display(song):
		base_song={"title": _("Unknown Title"), "track": "0", "disc": "", "artist": _("Unknown Artist"), "album": _("Unknown Album"), "duration": "0.0", "date": "", "genre": ""}
		base_song.update(song)
		base_song["human_duration"]=str(datetime.timedelta(seconds=int(float(base_song["duration"])))).lstrip("0").lstrip(":")
		return base_song

	def calc_display_length(songs):
		length=float(0)
		for song in songs:
			try:
				dura=float(song["duration"])
			except:
				dura=0.0
			length=length+dura
		return str(datetime.timedelta(seconds=int(length))).lstrip("0").lstrip(":")

class Client(MPDClient):
	def __init__(self, settings):
		MPDClient.__init__(self)
		self.settings=settings
		self.settings.connect("changed::active-profile", self.on_settings_changed)

		# idle client
		self.idle_client=MPDClient()

		# adding vars
		self.settings=settings
		self.emitter=MpdEventEmitter()

		self.current_file=None

	def start(self):
		if self.disconnected_loop():
			self.disconnected_timeout_id=GLib.timeout_add(1000, self.disconnected_loop)

	def connected(self):
		try:
			self.ping()
			return True
		except:
			return False

	def on_settings_changed(self, *args):
		self.disconnect()
		self.idle_client.disconnect()

	def files_to_playlist(self, files, append, force=False):
		if append:
			for f in files:
				self.add(f)
		else:
			if self.settings.get_boolean("force-mode") or force or self.status()["state"] == "stop":
				if not files == []:
					self.clear()
					for f in files:
						self.add(f)
					self.play()
			else:
				status=self.status()
				self.moveid(status["songid"], 0)
				current_song_file=self.playlistinfo()[0]["file"]
				try:
					self.delete((1,))  # delete all songs, but the first. bad song index possible
				except:
					pass
				for f in files:
					if not f == current_song_file:
						self.add(f)
					else:
						self.move(0, (len(self.playlistinfo())-1))

	def album_to_playlist(self, album, artist, year, append, force=False):
		songs=self.find("album", album, "date", year, self.settings.get_artist_type(), artist)
		self.files_to_playlist([song['file'] for song in songs], append, force)

	def comp_list(self, *args):  # simulates listing behavior of python-mpd2 1.0
		if "group" in args:
			raise ValueError("'group' is not supported")
		native_list=self.list(*args)
		if len(native_list) > 0:
			if type(native_list[0]) == dict:
				return ([l[args[0]] for l in native_list])
			else:
				return native_list
		else:
			return([])

	def loop(self, *args):
		# idle
		try:
			try:
				idle_return=self.idle_client.noidle()
				for i in idle_return:
					self.emitter.emit(i)
				if "player" in idle_return:
					current_song=self.idle_client.currentsong()
					if not current_song == {}:
						if not current_song['file'] == self.current_file:
							self.emitter.emit("playing_file_changed")
							self.current_file=current_song['file']
					else:
						self.emitter.emit("playing_file_changed")
						self.current_file=None
			except:
				pass
			self.idle_client.send_idle()
			# heartbeat
			status=self.status()
			if status['state'] == "stop" or status['state'] == "pause":
				self.ping()
			else:
				self.emitter.emit("periodic_signal")
		except:
			try:
				self.idle_client.disconnect()
			except:
				pass
			try:
				self.disconnect()
			except:
				pass
			self.emitter.emit("disconnected")
			if self.disconnected_loop():
				self.disconnected_timeout_id=GLib.timeout_add(1000, self.disconnected_loop)
			return False
		return True

	def disconnected_loop(self, *args):
		self.current_file=None
		active=self.settings.get_int("active-profile")
		try:
			self.connect(self.settings.get_value("hosts")[active], self.settings.get_value("ports")[active])
			if self.settings.get_value("passwords")[active] != "":
				self.password(self.settings.get_value("passwords")[active])
		except:
			print("connect failed")
			return True
		try:
			self.idle_client.connect(self.settings.get_value("hosts")[active], self.settings.get_value("ports")[active])
			if self.settings.get_value("passwords")[active] != "":
				self.idle_client.password(self.settings.get_value("passwords")[active])
		except:
			print("connect failed")
			print("max clients could be too small")
			self.diconnect()
			return True
		# connect successful
		self.main_timeout_id=GLib.timeout_add(100, self.loop)
		self.emitter.emit("periodic_signal")
		self.emitter.emit("playlist")
		self.emitter.emit("player")
		self.emitter.emit("playing_file_changed")
		self.emitter.emit("options")
		self.emitter.emit("mixer")
		self.emitter.emit("update")
		self.emitter.emit("reconnected")
		return False

class MPRISInterface(dbus.service.Object):  # TODO emit Seeked if needed
	__introspect_interface="org.freedesktop.DBus.Introspectable"
	__prop_interface=dbus.PROPERTIES_IFACE

	# python dbus bindings don't include annotations and properties
	MPRIS2_INTROSPECTION="""<node name="/org/mpris/MediaPlayer2">
	  <interface name="org.freedesktop.DBus.Introspectable">
	    <method name="Introspect">
	      <arg direction="out" name="xml_data" type="s"/>
	    </method>
	  </interface>
	  <interface name="org.freedesktop.DBus.Properties">
	    <method name="Get">
	      <arg direction="in" name="interface_name" type="s"/>
	      <arg direction="in" name="property_name" type="s"/>
	      <arg direction="out" name="value" type="v"/>
	    </method>
	    <method name="GetAll">
	      <arg direction="in" name="interface_name" type="s"/>
	      <arg direction="out" name="properties" type="a{sv}"/>
	    </method>
	    <method name="Set">
	      <arg direction="in" name="interface_name" type="s"/>
	      <arg direction="in" name="property_name" type="s"/>
	      <arg direction="in" name="value" type="v"/>
	    </method>
	    <signal name="PropertiesChanged">
	      <arg name="interface_name" type="s"/>
	      <arg name="changed_properties" type="a{sv}"/>
	      <arg name="invalidated_properties" type="as"/>
	    </signal>
	  </interface>
	  <interface name="org.mpris.MediaPlayer2">
	    <method name="Raise"/>
	    <method name="Quit"/>
	    <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>
	    <property name="CanQuit" type="b" access="read"/>
	    <property name="CanRaise" type="b" access="read"/>
	    <property name="HasTrackList" type="b" access="read"/>
	    <property name="Identity" type="s" access="read"/>
	    <property name="DesktopEntry" type="s" access="read"/>
	    <property name="SupportedUriSchemes" type="as" access="read"/>
	    <property name="SupportedMimeTypes" type="as" access="read"/>
	  </interface>
	  <interface name="org.mpris.MediaPlayer2.Player">
	    <method name="Next"/>
	    <method name="Previous"/>
	    <method name="Pause"/>
	    <method name="PlayPause"/>
	    <method name="Stop"/>
	    <method name="Play"/>
	    <method name="Seek">
	      <arg direction="in" name="Offset" type="x"/>
	    </method>
	    <method name="SetPosition">
	      <arg direction="in" name="TrackId" type="o"/>
	      <arg direction="in" name="Position" type="x"/>
	    </method>
	    <method name="OpenUri">
	      <arg direction="in" name="Uri" type="s"/>
	    </method>
	    <signal name="Seeked">
	      <arg name="Position" type="x"/>
	    </signal>
	    <property name="PlaybackStatus" type="s" access="read">
	      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
	    </property>
	    <property name="LoopStatus" type="s" access="readwrite">
	      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
	    </property>
	    <property name="Rate" type="d" access="readwrite">
	      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
	    </property>
	    <property name="Shuffle" type="b" access="readwrite">
	      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
	    </property>
	    <property name="Metadata" type="a{sv}" access="read">
	      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
	    </property>
	    <property name="Volume" type="d" access="readwrite">
	      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>
	    </property>
	    <property name="Position" type="x" access="read">
	      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>
	    </property>
	    <property name="MinimumRate" type="d" access="read">
	      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
	    </property>
	    <property name="MaximumRate" type="d" access="read">
	      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
	    </property>
	    <property name="CanGoNext" type="b" access="read">
	      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
	    </property>
	    <property name="CanGoPrevious" type="b" access="read">
	      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
	    </property>
	    <property name="CanPlay" type="b" access="read">
	      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
	    </property>
	    <property name="CanPause" type="b" access="read">
	      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
	    </property>
	    <property name="CanSeek" type="b" access="read">
	      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
	    </property>
	    <property name="CanControl" type="b" access="read">
	      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>
	    </property>
	  </interface>
	</node>"""

	# MPRIS allowed metadata tags
	allowed_tags={
		'mpris:trackid': dbus.ObjectPath,
		'mpris:length': dbus.Int64,
		'mpris:artUrl': str,
		'xesam:album': str,
		'xesam:albumArtist': list,
		'xesam:artist': list,
		'xesam:asText': str,
		'xesam:audioBPM': int,
		'xesam:comment': list,
		'xesam:composer': list,
		'xesam:contentCreated': str,
		'xesam:discNumber': int,
		'xesam:firstUsed': str,
		'xesam:genre': list,
		'xesam:lastUsed': str,
		'xesam:lyricist': str,
		'xesam:title': str,
		'xesam:trackNumber': int,
		'xesam:url': str,
		'xesam:useCount': int,
		'xesam:userRating': float,
	}

	def __init__(self, window, client, settings):
		dbus.service.Object.__init__(self, dbus.SessionBus(), "/org/mpris/MediaPlayer2")
		self._name="org.mpris.MediaPlayer2.mpdevil"

		self._bus=dbus.SessionBus()
		self._uname=self._bus.get_unique_name()
		self._dbus_obj=self._bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus")
		self._dbus_obj.connect_to_signal("NameOwnerChanged", self._name_owner_changed_callback, arg0=self._name)

		self.window=window
		self.client=client
		self.settings=settings
		self.metadata={}

		# connect
		self.client.emitter.connect("player", self.on_player_changed)
		self.client.emitter.connect("playing_file_changed", self.on_file_changed)
		self.client.emitter.connect("mixer", self.on_volume_changed)
		self.client.emitter.connect("options", self.on_options_changed)

	def on_player_changed(self, *args):
		self.update_property('org.mpris.MediaPlayer2.Player', 'PlaybackStatus')
		self.update_property('org.mpris.MediaPlayer2.Player', 'CanGoNext')
		self.update_property('org.mpris.MediaPlayer2.Player', 'CanGoPrevious')

	def on_file_changed(self, *args):
		self.update_metadata()
		self.update_property('org.mpris.MediaPlayer2.Player', 'Metadata')

	def on_volume_changed(self, *args):
		self.update_property('org.mpris.MediaPlayer2.Player', 'Volume')

	def on_options_changed(self, *args):
		self.update_property('org.mpris.MediaPlayer2.Player', 'LoopStatus')
		self.update_property('org.mpris.MediaPlayer2.Player', 'Shuffle')

	def update_metadata(self):  # TODO
		"""
		Translate metadata returned by MPD to the MPRIS v2 syntax.
		http://www.freedesktop.org/wiki/Specifications/mpris-spec/metadata
		"""

		mpd_meta=self.client.currentsong()
		self.metadata={}

		for tag in ('album', 'title'):
			if tag in mpd_meta:
				self.metadata['xesam:%s' % tag]=mpd_meta[tag]

		if 'id' in mpd_meta:
			self.metadata['mpris:trackid']="/org/mpris/MediaPlayer2/Track/%s" % mpd_meta['id']

		if 'time' in mpd_meta:
			self.metadata['mpris:length']=int(mpd_meta['time']) * 1000000

		if 'date' in mpd_meta:
			self.metadata['xesam:contentCreated']=mpd_meta['date'][0:4]

		if 'track' in mpd_meta:
			# TODO: Is it even *possible* for mpd_meta['track'] to be a list?
			if type(mpd_meta['track']) == list and len(mpd_meta['track']) > 0:
				track=str(mpd_meta['track'][0])
			else:
				track=str(mpd_meta['track'])

			m=re.match('^([0-9]+)', track)
			if m:
				self.metadata['xesam:trackNumber']=int(m.group(1))
				# Ensure the integer is signed 32bit
				if self.metadata['xesam:trackNumber'] & 0x80000000:
					self.metadata['xesam:trackNumber'] += -0x100000000
			else:
				self.metadata['xesam:trackNumber']=0

		if 'disc' in mpd_meta:
			# TODO: Same as above. When is it a list?
			if type(mpd_meta['disc']) == list and len(mpd_meta['disc']) > 0:
				disc=str(mpd_meta['disc'][0])
			else:
				disc=str(mpd_meta['disc'])

			m=re.match('^([0-9]+)', disc)
			if m:
				self.metadata['xesam:discNumber']=int(m.group(1))

		if 'artist' in mpd_meta:
			if type(mpd_meta['artist']) == list:
				self.metadata['xesam:artist']=mpd_meta['artist']
			else:
				self.metadata['xesam:artist']=[mpd_meta['artist']]

		if 'composer' in mpd_meta:
			if type(mpd_meta['composer']) == list:
				self.metadata['xesam:composer']=mpd_meta['composer']
			else:
				self.metadata['xesam:composer']=[mpd_meta['composer']]

		# Stream: populate some missings tags with stream's name
		if 'name' in mpd_meta:
			if 'xesam:title' not in self.metadata:
				self.metadata['xesam:title']=mpd_meta['name']
			elif 'xesam:album' not in self.metadata:
				self.metadata['xesam:album']=mpd_meta['name']

		if 'file' in mpd_meta:
			song_file=mpd_meta['file']
			self.metadata['xesam:url']="file://"+os.path.join(self.settings.get_value("paths")[self.settings.get_int("active-profile")], song_file)
			cover=Cover(lib_path=self.settings.get_value("paths")[self.settings.get_int("active-profile")], song_file=song_file)
			if not cover.path == None:
				self.metadata['mpris:artUrl']="file://"+cover.path
			else:
				self.metadata['mpris:artUrl']=None

		# Cast self.metadata to the correct type, or discard it
		for key, value in self.metadata.items():
			try:
				self.metadata[key]=self.allowed_tags[key](value)
			except ValueError:
				del self.metadata[key]

	def _name_owner_changed_callback(self, name, old_owner, new_owner):
		if name == self._name and old_owner == self._uname and new_owner != "":
			try:
				pid=self._dbus_obj.GetConnectionUnixProcessID(new_owner)
			except:
				pid=None
			loop.quit()

	def acquire_name(self):
		self._bus_name=dbus.service.BusName(self._name, bus=self._bus, allow_replacement=True, replace_existing=True)

	def release_name(self):
		if hasattr(self, "_bus_name"):
			del self._bus_name

	__root_interface="org.mpris.MediaPlayer2"
	__root_props={
		"CanQuit": (False, None),
		"CanRaise": (True, None),
		"DesktopEntry": ("mpdevil", None),
		"HasTrackList": (False, None),
		"Identity": ("mpdevil", None),
		"SupportedUriSchemes": (dbus.Array(signature="s"), None),
		"SupportedMimeTypes": (dbus.Array(signature="s"), None)
	}

	def __get_playback_status(self):
		status=self.client.status()
		return {'play': 'Playing', 'pause': 'Paused', 'stop': 'Stopped'}[status['state']]

	def __set_loop_status(self, value):
		if value == "Playlist":
			self.client.repeat(1)
			self.client.single(0)
		elif value == "Track":
			self.client.repeat(1)
			self.client.single(1)
		elif value == "None":
			self.client.repeat(0)
			self.client.single(0)
		else:
			raise dbus.exceptions.DBusException("Loop mode %r not supported" % value)
		return

	def __get_loop_status(self):
		status=self.client.status()
		if int(status['repeat']) == 1:
			if int(status.get('single', 0)) == 1:
				return "Track"
			else:
				return "Playlist"
		else:
			return "None"

	def __set_shuffle(self, value):
		self.client.random(value)
		return

	def __get_shuffle(self):
		if int(self.client.status()['random']) == 1:
			return True
		else:
			return False

	def __get_metadata(self):
		return dbus.Dictionary(self.metadata, signature='sv')

	def __get_volume(self):
		vol=float(self.client.status().get('volume', 0))
		if vol > 0:
			return vol / 100.0
		else:
			return 0.0

	def __set_volume(self, value):
		if value >= 0 and value <= 1:
			self.client.setvol(int(value * 100))
		return

	def __get_position(self):
		status=self.client.status()
		if 'time' in status:
			current, end=status['time'].split(':')
			return dbus.Int64((int(current) * 1000000))
		else:
			return dbus.Int64(0)

	def __get_can_next_prev(self):
		status=self.client.status()
		if status['state'] == "stop":
			return False
		else:
			return True

	__player_interface="org.mpris.MediaPlayer2.Player"
	__player_props={
		"PlaybackStatus": (__get_playback_status, None),
		"LoopStatus": (__get_loop_status, __set_loop_status),
		"Rate": (1.0, None),
		"Shuffle": (__get_shuffle, __set_shuffle),
		"Metadata": (__get_metadata, None),
		"Volume": (__get_volume, __set_volume),
		"Position": (__get_position, None),
		"MinimumRate": (1.0, None),
		"MaximumRate": (1.0, None),
		"CanGoNext": (__get_can_next_prev, None),
		"CanGoPrevious": (__get_can_next_prev, None),
		"CanPlay": (True, None),
		"CanPause": (True, None),
		"CanSeek": (True, None),
		"CanControl": (True, None),
	}

	__prop_mapping={
		__player_interface: __player_props,
		__root_interface: __root_props,
	}

	@dbus.service.method(__introspect_interface)
	def Introspect(self):
		return self.MPRIS2_INTROSPECTION

	@dbus.service.signal(__prop_interface, signature="sa{sv}as")
	def PropertiesChanged(self, interface, changed_properties, invalidated_properties):
		pass

	@dbus.service.method(__prop_interface, in_signature="ss", out_signature="v")
	def Get(self, interface, prop):
		getter, setter=self.__prop_mapping[interface][prop]
		if callable(getter):
			return getter(self)
		return getter

	@dbus.service.method(__prop_interface, in_signature="ssv", out_signature="")
	def Set(self, interface, prop, value):
		getter, setter=self.__prop_mapping[interface][prop]
		if setter is not None:
			setter(self, value)

	@dbus.service.method(__prop_interface, in_signature="s", out_signature="a{sv}")
	def GetAll(self, interface):
		read_props={}
		props=self.__prop_mapping[interface]
		for key, (getter, setter) in props.items():
			if callable(getter):
				getter=getter(self)
			read_props[key]=getter
		return read_props

	def update_property(self, interface, prop):
		getter, setter=self.__prop_mapping[interface][prop]
		if callable(getter):
			value=getter(self)
		else:
			value=getter
		self.PropertiesChanged(interface, {prop: value}, [])
		return value

	# Root methods
	@dbus.service.method(__root_interface, in_signature='', out_signature='')
	def Raise(self):
		self.window.present()
		return

	@dbus.service.method(__root_interface, in_signature='', out_signature='')
	def Quit(self):
		return

	# Player methods
	@dbus.service.method(__player_interface, in_signature='', out_signature='')
	def Next(self):
		self.client.next()
		return

	@dbus.service.method(__player_interface, in_signature='', out_signature='')
	def Previous(self):
		self.client.previous()
		return

	@dbus.service.method(__player_interface, in_signature='', out_signature='')
	def Pause(self):
		self.client.pause(1)
		return

	@dbus.service.method(__player_interface, in_signature='', out_signature='')
	def PlayPause(self):
		status=self.client.status()
		if status['state'] == 'play':
			self.client.pause(1)
		else:
			self.client.play()
		return

	@dbus.service.method(__player_interface, in_signature='', out_signature='')
	def Stop(self):
		self.client.stop()
		return

	@dbus.service.method(__player_interface, in_signature='', out_signature='')
	def Play(self):
		self.client.play()
		return

	@dbus.service.method(__player_interface, in_signature='x', out_signature='')
	def Seek(self, offset):  # TODO
		status=self.client.status()
		current, end=status['time'].split(':')
		current=int(current)
		end=int(end)
		offset=int(offset) / 1000000
		if current + offset <= end:
			position=current + offset
			if position < 0:
				position=0
			self.client.seekid(int(status['songid']), position)
			self.Seeked(position * 1000000)
		return

	@dbus.service.method(__player_interface, in_signature='ox', out_signature='')
	def SetPosition(self, trackid, position):
		song=self.client.currentsong()
		# FIXME: use real dbus objects
		if str(trackid) != '/org/mpris/MediaPlayer2/Track/%s' % song['id']:
			return
		# Convert position to seconds
		position=int(position) / 1000000
		if position <= int(song['time']):
			self.client.seekid(int(song['id']), position)
			self.Seeked(position * 1000000)
		return

	@dbus.service.signal(__player_interface, signature='x')
	def Seeked(self, position):
		return float(position)

	@dbus.service.method(__player_interface, in_signature='', out_signature='')
	def OpenUri(self):
		return

class Settings(Gio.Settings):
	BASE_KEY="org.mpdevil"
	def __init__(self):
		super().__init__(schema=self.BASE_KEY)
		if len(self.get_value("profiles")) < (self.get_int("active-profile")+1):
			self.set_int("active-profile", 0)

	def array_append(self, vtype, key, value):  # append to Gio.Settings (self.settings) array
		array=self.get_value(key).unpack()
		array.append(value)
		self.set_value(key, GLib.Variant(vtype, array))

	def array_delete(self, vtype, key, pos):  # delete entry of Gio.Settings (self.settings) array
		array=self.get_value(key).unpack()
		array.pop(pos)
		self.set_value(key, GLib.Variant(vtype, array))

	def array_modify(self, vtype, key, pos, value):  # modify entry of Gio.Settings (self.settings) array
		array=self.get_value(key).unpack()
		array[pos]=value
		self.set_value(key, GLib.Variant(vtype, array))

	def get_gtk_icon_size(self, key):
		icon_size=self.get_int(key)
		sizes=[(48, Gtk.IconSize.DIALOG), (32, Gtk.IconSize.DND), (24, Gtk.IconSize.LARGE_TOOLBAR), (16, Gtk.IconSize.BUTTON)]
		for pixel_size, gtk_size in sizes:
			if icon_size >= pixel_size:
				return gtk_size
		return Gtk.IconSize.INVALID

	def get_artist_type(self):
		if self.get_boolean("use-album-artist"):
			return ("albumartist")
		else:
			return ("artist")

class SongPopover(Gtk.Popover):
	def __init__(self, song, relative, x, y):
		Gtk.Popover.__init__(self)
		rect=Gdk.Rectangle()
		rect.x=x
		# Gtk places popovers 26px above the given position for no obvious reasons, so I move them 26px
		rect.y=y+26
		rect.width = 1
		rect.height = 1
		self.set_pointing_to(rect)
		self.set_relative_to(relative)

		# Store
		# (tag, display-value, tooltip)
		self.store=Gtk.ListStore(str, str, str)

		# TreeView
		self.treeview=Gtk.TreeView(model=self.store)
		self.treeview.set_can_focus(False)
		self.treeview.set_search_column(-1)
		self.treeview.set_tooltip_column(2)
		self.treeview.set_headers_visible(False)
		sel=self.treeview.get_selection()
		sel.set_mode(Gtk.SelectionMode.NONE)

		frame=Gtk.Frame()
		frame.add(self.treeview)
		frame.set_property("border-width", 3)

		# Column
		renderer_text=Gtk.CellRendererText(width_chars=50, ellipsize=Pango.EllipsizeMode.MIDDLE, ellipsize_set=True)
		renderer_text_ralign=Gtk.CellRendererText(xalign=1.0)

		self.column_tag=Gtk.TreeViewColumn(_("MPD-Tag"), renderer_text_ralign, text=0)
		self.column_tag.set_property("resizable", False)
		self.treeview.append_column(self.column_tag)

		self.column_value=Gtk.TreeViewColumn(_("Value"), renderer_text, text=1)
		self.column_value.set_property("resizable", False)
		self.treeview.append_column(self.column_value)

		# packing
		self.add(frame)

		song=ClientHelper.song_to_str_dict(song)
		for tag, value in song.items():
			tooltip=value.replace("&", "&amp;")
			if tag == "time":
				self.store.append([tag+":", str(datetime.timedelta(seconds=int(value))), tooltip])
			elif tag == "last-modified":
				time=datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')
				self.store.append([tag+":", time.strftime('%a %d %B %Y, %H:%M UTC'), tooltip])
			else:
				self.store.append([tag+":", value, tooltip])
		frame.show_all()

class SongsView(Gtk.TreeView):
	def __init__(self, client, store, file_column_id):
		Gtk.TreeView.__init__(self)
		self.set_model(store)
		self.set_search_column(-1)
		self.columns_autosize()

		# add vars
		self.client=client
		self.store=store
		self.file_column_id=file_column_id

		# selection
		self.selection=self.get_selection()
		self.selection.set_mode(Gtk.SelectionMode.SINGLE)

		# connect
		self.connect("row-activated", self.on_row_activated)
		self.connect("button-press-event", self.on_button_press_event)
		self.key_press_event=self.connect("key-press-event", self.on_key_press_event)

	def on_row_activated(self, widget, path, view_column):
		self.client.files_to_playlist([self.store[path][self.file_column_id]], False, True)

	def on_button_press_event(self, widget, event):
		if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
			try:
				path=widget.get_path_at_pos(int(event.x), int(event.y))[0]
				self.client.files_to_playlist([self.store[path][self.file_column_id]], False)
			except:
				pass
		elif event.button == 2 and event.type == Gdk.EventType.BUTTON_PRESS:
			try:
				path=widget.get_path_at_pos(int(event.x), int(event.y))[0]
				self.client.files_to_playlist([self.store[path][self.file_column_id]], True)
			except:
				pass
		elif event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
			try:
				path=widget.get_path_at_pos(int(event.x), int(event.y))[0]
				file_name=self.store[path][self.file_column_id]
				pop=SongPopover(self.client.lsinfo(file_name)[0], widget, int(event.x), int(event.y))
				pop.popup()
				pop.show_all()
			except:
				pass

	def on_key_press_event(self, widget, event):
		self.handler_block(self.key_press_event)
		if event.keyval == 112:  # p
			treeview, treeiter=self.selection.get_selected()
			if not treeiter == None:
				self.client.files_to_playlist([self.store.get_value(treeiter, self.file_column_id)], False)
		elif event.keyval == 97:  # a
			treeview, treeiter=self.selection.get_selected()
			if not treeiter == None:
				self.client.files_to_playlist([self.store.get_value(treeiter, self.file_column_id)], True)
		elif event.keyval == 65383:  # menu key
			treeview, treeiter=self.selection.get_selected()
			if not treeiter == None:
				path=self.store.get_path(treeiter)
				cell=self.get_cell_area(path, None)
				file_name=self.store[path][self.file_column_id]
				pop=SongPopover(self.client.lsinfo(file_name)[0], widget, int(cell.x), int(cell.y))
				pop.popup()
				pop.show_all()
		self.handler_unblock(self.key_press_event)

	def clear(self):
		self.store.clear()

	def count(self):
		return len(self.store)

	def get_files(self):
		return_list=[]
		for row in self.store:
			return_list.append(row[self.file_column_id])
		return return_list

class AlbumDialog(Gtk.Dialog):
	def __init__(self, parent, client, settings, album, artist, year):
		Gtk.Dialog.__init__(self, transient_for=parent)
		self.add_buttons(Gtk.STOCK_ADD, Gtk.ResponseType.ACCEPT, Gtk.STOCK_MEDIA_PLAY, Gtk.ResponseType.YES, Gtk.STOCK_OPEN, Gtk.ResponseType.OK, Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)

		# metadata
		self.album=album
		self.artist=artist
		self.year=year

		# adding vars
		self.client=client
		self.settings=settings
		songs=self.client.find("album", self.album, "date", self.year, self.settings.get_artist_type(), self.artist)

		# determine size
		size=parent.get_size()
		diagonal=(size[0]**2+size[1]**2)**(0.5)
		h=diagonal//4
		w=h*5//4
		self.set_default_size(w, h)

		# title
		album_duration=ClientHelper.calc_display_length(songs)
		if year == "":
			self.set_title(artist+" - "+album+" ("+album_duration+")")
		else:
			self.set_title(artist+" - "+album+" ("+year+") ("+album_duration+")")

		# store
		# (track, title (artist), duration, file)
		self.store=Gtk.ListStore(int, str, str, str)

		# songs view
		self.songs_view=SongsView(self.client, self.store, 3)
		for s in songs:
			song=ClientHelper.extend_song_for_display(s)
			if type(song["title"]) == list:  # could be impossible
				title=(', '.join(song["title"]))
			else:
				title=song["title"]
			if type(song["artist"]) == list:
				try:
					song["artist"].remove(self.artist)
				except:
					pass
				artist=(', '.join(song["artist"]))
			else:
				artist=song["artist"]
			if artist != self.artist:
				title_artist="<b>"+title+"</b> - "+artist
			else:
				title_artist="<b>"+title+"</b>"
			title_artist=title_artist.replace("&", "&amp;")
			self.store.append([int(song["track"]), title_artist, song["human_duration"], song["file"]])

		# columns
		renderer_text=Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END, ellipsize_set=True)
		renderer_text_ralign=Gtk.CellRendererText(xalign=1.0)

		self.column_track=Gtk.TreeViewColumn(_("No"), renderer_text_ralign, text=0)
		self.column_track.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_track.set_property("resizable", False)
		self.songs_view.append_column(self.column_track)

		self.column_title=Gtk.TreeViewColumn(_("Title"), renderer_text, markup=1)
		self.column_title.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_title.set_property("resizable", False)
		self.column_title.set_property("expand", True)
		self.songs_view.append_column(self.column_title)

		self.column_time=Gtk.TreeViewColumn(_("Length"), renderer_text, text=2)
		self.column_time.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_time.set_property("resizable", False)
		self.songs_view.append_column(self.column_time)

		# scroll
		scroll=Gtk.ScrolledWindow()
		scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
		scroll.add(self.songs_view)

		# packing
		self.vbox.pack_start(scroll, True, True, 0)  # vbox default widget of dialogs
		self.vbox.set_spacing(3)
		self.show_all()

	def open(self):
		response=self.run()
		if response == Gtk.ResponseType.OK:
			self.client.album_to_playlist(self.album, self.artist, self.year, False)
		elif response == Gtk.ResponseType.ACCEPT:
			self.client.album_to_playlist(self.album, self.artist, self.year, True)
		elif response == Gtk.ResponseType.YES:
			self.client.album_to_playlist(self.album, self.artist, self.year, False, True)

class GenreSelect(Gtk.ComboBoxText):
	def __init__(self, client, settings):
		Gtk.ComboBoxText.__init__(self)

		# adding vars
		self.client=client
		self.settings=settings

		# connect
		self.changed=self.connect("changed", self.on_changed)
		self.update_signal=self.client.emitter.connect("update", self.refresh)

	def deactivate(self):
		self.set_active(0)

	def refresh(self, *args):
		self.handler_block(self.changed)
		self.remove_all()
		self.append_text(_("all genres"))
		for genre in self.client.comp_list("genre"):
			self.append_text(genre)
		self.set_active(0)
		self.handler_unblock(self.changed)

	def clear(self, *args):
		self.handler_block(self.changed)
		self.remove_all()
		self.handler_unblock(self.changed)

	def get_value(self):
		if self.get_active() == 0:
			return None
		else:
			return self.get_active_text()

	def on_changed(self, *args):
		self.client.emitter.handler_block(self.update_signal)
		self.client.emitter.emit("update")
		self.client.emitter.handler_unblock(self.update_signal)

class ArtistView(FocusFrame):
	def __init__(self, client, settings, genre_select):
		FocusFrame.__init__(self)

		# adding vars
		self.client=client
		self.settings=settings
		self.genre_select=genre_select

		# artistStore
		# (name, weight, initial-letter, weight-initials)
		self.store=Gtk.ListStore(str, Pango.Weight, str, Pango.Weight)

		# TreeView
		self.treeview=Gtk.TreeView(model=self.store)
		self.treeview.set_search_column(0)
		self.treeview.columns_autosize()
		self.treeview.set_property("activate-on-single-click", True)

		# artistSelection
		self.selection=self.treeview.get_selection()
		self.selection.set_mode(Gtk.SelectionMode.SINGLE)

		# Columns
		renderer_text_malign=Gtk.CellRendererText(xalign=0.5)
		self.column_initials=Gtk.TreeViewColumn("", renderer_text_malign, text=2, weight=3)
		self.column_initials.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_initials.set_property("resizable", False)
		self.column_initials.set_visible(self.settings.get_boolean("show-initials"))
		self.treeview.append_column(self.column_initials)

		renderer_text=Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END, ellipsize_set=True)
		self.column_name=Gtk.TreeViewColumn("", renderer_text, text=0, weight=1)
		self.column_name.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_name.set_property("resizable", False)
		self.treeview.append_column(self.column_name)

		# scroll
		scroll=Gtk.ScrolledWindow()
		scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
		scroll.add(self.treeview)

		# connect
		self.treeview.connect("row-activated", self.on_row_activated)
		self.settings.connect("changed::use-album-artist", self.refresh)
		self.settings.connect("changed::show-initials", self.on_show_initials_settings_changed)
		self.client.emitter.connect("update", self.refresh)

		self.set_widget(self.treeview)
		self.add(scroll)

	@GObject.Signal
	def artists_changed(self):
		pass

	def clear(self):
		self.store.clear()

	def refresh(self, *args):
		self.selection.set_mode(Gtk.SelectionMode.NONE)
		self.clear()
		if self.settings.get_artist_type() == "albumartist":
			self.column_name.set_title(_("Album Artist"))
		else:
			self.column_name.set_title(_("Artist"))
		self.store.append([_("all artists"), Pango.Weight.BOOK, "", Pango.Weight.BOOK])
		genre=self.genre_select.get_value()
		if genre == None:
			artists=self.client.comp_list(self.settings.get_artist_type())
		else:
			artists=self.client.comp_list(self.settings.get_artist_type(), "genre", genre)
		current_char=""
		for artist in artists:
			try:
				if current_char != artist[0]:
					self.store.append([artist, Pango.Weight.BOOK, artist[0], Pango.Weight.BOLD])
					current_char=artist[0]
				else:
					self.store.append([artist, Pango.Weight.BOOK, "", Pango.Weight.BOOK])
			except:
				self.store.append([artist, Pango.Weight.BOOK, "", Pango.Weight.BOOK])
		self.selection.set_mode(Gtk.SelectionMode.SINGLE)

	def get_selected_artists(self):
		artists=[]
		if self.store[Gtk.TreePath(0)][1] == Pango.Weight.BOLD:
			for row in self.store:
				artists.append(row[0])
			return artists[1:]
		else:
			for row in self.store:
				if row[1] == Pango.Weight.BOLD:
					artists.append(row[0])
					break
			return artists

	def highlight_selected(self):
		for path, row in enumerate(self.store):
			if row[1] == Pango.Weight.BOLD:
				self.treeview.set_cursor(path, None, False)
				break

	def on_row_activated(self, widget, path, view_column):
		for row in self.store:  # reset bold text
			row[1]=Pango.Weight.BOOK
		self.store[path][1]=Pango.Weight.BOLD
		self.emit("artists_changed")

	def on_show_initials_settings_changed(self, *args):
		self.column_initials.set_visible(self.settings.get_boolean("show-initials"))

class AlbumIconView(Gtk.IconView):
	def __init__(self, client, settings, genre_select, window):
		Gtk.IconView.__init__(self)

		# adding vars
		self.settings=settings
		self.client=client
		self.genre_select=genre_select
		self.window=window
		self.stop_flag=True
		self.button_event=(None, None)

		# cover, display_label, display_label_artist, tooltip(titles), album, year, artist
		self.store=Gtk.ListStore(GdkPixbuf.Pixbuf, str, str, str, str, str, str)
		self.sort_settings()

		# iconview
		self.set_model(self.store)
		self.set_pixbuf_column(0)
		self.set_markup_column(1)
		self.set_item_width(0)
		self.tooltip_settings()

		# connect
		self.connect("item-activated", self.on_item_activated)
		self.connect("button-release-event", self.on_button_release_event)
		self.connect("button-press-event", self.on_button_press_event)
		self.key_press_event=self.connect("key-press-event", self.on_key_press_event)
		self.settings.connect("changed::show-album-view-tooltips", self.tooltip_settings)
		self.settings.connect("changed::sort-albums-by-year", self.sort_settings)

	@GObject.Signal
	def done(self):
		self.stop_flag=True
		pass

	def tooltip_settings(self, *args):
		if self.settings.get_boolean("show-album-view-tooltips"):
			self.set_tooltip_column(3)
		else:
			self.set_tooltip_column(-1)

	def sort_settings(self, *args):
		if self.settings.get_boolean("sort-albums-by-year"):
			self.store.set_sort_column_id(5, Gtk.SortType.ASCENDING)
		else:
			self.store.set_sort_column_id(1, Gtk.SortType.ASCENDING)
		return False

	def add_row(self, row, cover, size):
		row[0]=cover.get_pixbuf(size)
		self.store.append(row)
		return False

	def populate(self, artists):
		self.stop_flag=False
		# prepare albmus list
		self.store.clear()
		if len(artists) > 1:
			self.set_markup_column(2)
		else:
			self.set_markup_column(1)
		albums=[]
		genre=self.genre_select.get_value()
		artist_type=self.settings.get_artist_type()
		for artist in artists:
			try:  # client cloud meanwhile disconnect
				if not self.stop_flag:
					if genre == None:
						album_candidates=self.client.comp_list("album", artist_type, artist)
					else:
						album_candidates=self.client.comp_list("album", artist_type, artist, "genre", genre)
					for album in album_candidates:
						years=self.client.comp_list("date", "album", album, artist_type, artist)
						for year in years:
							songs=self.client.find("album", album, "date", year, artist_type, artist)
							albums.append({"artist": artist, "album": album, "year": year, "songs": songs})
					while Gtk.events_pending():
						Gtk.main_iteration_do(True)
				else:
					GLib.idle_add(self.emit, "done")
					return
			except:
				GLib.idle_add(self.emit, "done")
				return
		# display albums
		if self.settings.get_boolean("sort-albums-by-year"):
			albums=sorted(albums, key=lambda k: k['year'])
		else:
			albums=sorted(albums, key=lambda k: k['album'])
		music_lib=self.settings.get_value("paths")[self.settings.get_int("active-profile")]
		size=self.settings.get_int("album-cover")
		for i, album in enumerate(albums):
			if not self.stop_flag:
				cover=Cover(lib_path=music_lib, song_file=album["songs"][0]["file"])
				# tooltip
				length_human_readable=ClientHelper.calc_display_length(album["songs"])
				try:
					discs=int(album["songs"][-1]["disc"])
				except:
					discs=1
				if discs > 1:
					tooltip=(_("%(total_tracks)i titles on %(discs)i discs (%(total_length)s)") % {"total_tracks": len(album["songs"]), "discs": discs, "total_length": length_human_readable})
				else:
					tooltip=(_("%(total_tracks)i titles (%(total_length)s)") % {"total_tracks": len(album["songs"]), "total_length": length_human_readable})
				display_label="<b>"+album["album"]+"</b>"
				if album["year"] != "":
					display_label=display_label+" ("+album["year"]+")"
				display_label_artist=display_label+"\n"+album["artist"]
				display_label=display_label.replace("&", "&amp;")
				display_label_artist=display_label_artist.replace("&", "&amp;")
				GLib.idle_add(self.add_row, [None, display_label, display_label_artist, tooltip, album["album"], album["year"], album["artist"]], cover, size)
				if i%16 == 0:
					while Gtk.events_pending():
						Gtk.main_iteration_do(True)
			else:
				break
		GLib.idle_add(self.emit, "done")

	def scroll_to_selected_album(self):
		song=ClientHelper.song_to_first_str_dict(self.client.currentsong())
		self.unselect_all()
		row_num=len(self.store)
		for i in range(0, row_num):
			path=Gtk.TreePath(i)
			treeiter=self.store.get_iter(path)
			if self.store.get_value(treeiter, 4) == song["album"]:
				self.set_cursor(path, None, False)
				self.select_path(path)
				self.scroll_to_path(path, True, 0, 0)
				break

	def path_to_playlist(self, path, add, force=False):
		album=self.store[path][4]
		year=self.store[path][5]
		artist=self.store[path][6]
		self.client.album_to_playlist(album, artist, year, add, force)

	def open_album_dialog(self, path):
		if self.client.connected():
			album=self.store[path][4]
			year=self.store[path][5]
			artist=self.store[path][6]
			album_dialog=AlbumDialog(self.window, self.client, self.settings, album, artist, year)
			album_dialog.open()
			album_dialog.destroy()

	def on_button_press_event(self, widget, event):
		path=widget.get_path_at_pos(int(event.x), int(event.y))
		if event.type == Gdk.EventType.BUTTON_PRESS:
			self.button_event=(event.button, path)

	def on_button_release_event(self, widget, event):
		path=widget.get_path_at_pos(int(event.x), int(event.y))
		if not path == None:
			if self.button_event == (event.button, path):
				if event.button == 1 and event.type == Gdk.EventType.BUTTON_RELEASE:
					self.path_to_playlist(path, False)
				elif event.button == 2 and event.type == Gdk.EventType.BUTTON_RELEASE:
					self.path_to_playlist(path, True)
				elif event.button == 3 and event.type == Gdk.EventType.BUTTON_RELEASE:
					self.open_album_dialog(path)

	def on_key_press_event(self, widget, event):
		self.handler_block(self.key_press_event)
		if event.keyval == 112:  # p
			paths=self.get_selected_items()
			if not len(paths) == 0:
				self.path_to_playlist(paths[0], False)
		elif event.keyval == 97:  # a
			paths=self.get_selected_items()
			if not len(paths) == 0:
				self.path_to_playlist(paths[0], True)
		elif event.keyval == 65383:  # menu key
			paths=self.get_selected_items()
			if not len(paths) == 0:
				self.open_album_dialog(paths[0])
		self.handler_unblock(self.key_press_event)

	def on_item_activated(self, widget, path):
		treeiter=self.store.get_iter(path)
		selected_album=self.store.get_value(treeiter, 4)
		selected_album_year=self.store.get_value(treeiter, 5)
		selected_artist=self.store.get_value(treeiter, 6)
		self.client.album_to_playlist(selected_album, selected_artist, selected_album_year, False, True)

class AlbumView(FocusFrame):
	def __init__(self, client, settings, genre_select, window):
		FocusFrame.__init__(self)

		# adding vars
		self.settings=settings
		self.client=client
		self.genre_select=genre_select
		self.window=window
		self.artists=[]
		self.done=True
		self.pending=[]

		# iconview
		self.iconview=AlbumIconView(self.client, self.settings, self.genre_select, self.window)

		# scroll
		scroll=Gtk.ScrolledWindow()
		scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
		scroll.add(self.iconview)

		# connect
		self.settings.connect("changed::album-cover", self.on_settings_changed)
		self.iconview.connect("done", self.on_done)
		self.client.emitter.connect("update", self.clear)
		self.settings.connect("changed::use-album-artist", self.clear)

		self.set_widget(self.iconview)
		self.add(scroll)

	def clear(self, *args):
		if self.done:
			self.iconview.store.clear()
		elif not self.clear in self.pending:
			self.iconview.stop_flag=True
			self.pending.append(self.clear)

	def refresh(self, artists):
		self.artists=artists
		if self.done:
			self.done=False
			self.populate()
		elif not self.populate in self.pending:
			self.iconview.stop_flag=True
			self.pending.append(self.populate)

	def populate(self):
		self.iconview.populate(self.artists)

	def scroll_to_selected_album(self):
		if self.done:
			self.iconview.scroll_to_selected_album()
		elif not self.scroll_to_selected_album in self.pending:
			self.pending.append(self.scroll_to_selected_album)

	def on_done(self, *args):
		self.done=True
		pending=self.pending
		self.pending=[]
		for p in pending:
			try:
				p()
			except:
				pass

	def on_settings_changed(self, *args):
		if self.done:
			self.populate()

class MainCover(Gtk.Frame):
	def __init__(self, client, settings, window):
		Gtk.Frame.__init__(self)
		# diable auto resize
		self.set_halign(3)
		self.set_valign(3)
		# css
		style_context=self.get_style_context()
		provider=Gtk.CssProvider()
		css=b"""* {background-color: @theme_base_color; border-radius: 6px;}"""
		provider.load_from_data(css)
		style_context.add_provider(provider, 800)

		# adding vars
		self.client=client
		self.settings=settings
		self.window=window

		# event box
		event_box=Gtk.EventBox()
		event_box.set_property("border-width", 6)

		# cover
		self.cover=Gtk.Image.new()
		size=self.settings.get_int("track-cover")
		self.cover.set_from_pixbuf(Cover(lib_path=self.settings.get_value("paths")[self.settings.get_int("active-profile")], song_file=None).get_pixbuf(size))  # set to fallback cover
		# set default size
		self.cover.set_size_request(size, size)

		# connect
		event_box.connect("button-press-event", self.on_button_press_event)
		self.client.emitter.connect("playing_file_changed", self.refresh)
		self.settings.connect("changed::track-cover", self.on_settings_changed)

		event_box.add(self.cover)
		self.add(event_box)

	def refresh(self, *args):
		try:
			current_song=self.client.currentsong()
			song_file=current_song['file']
		except:
			song_file=None
		self.cover.set_from_pixbuf(Cover(lib_path=self.settings.get_value("paths")[self.settings.get_int("active-profile")], song_file=song_file).get_pixbuf(self.settings.get_int("track-cover")))

	def clear(self, *args):
		self.cover.set_from_pixbuf(Cover(lib_path=self.settings.get_value("paths")[self.settings.get_int("active-profile")], song_file=None).get_pixbuf(self.settings.get_int("track-cover")))
		self.song_file=None

	def on_button_press_event(self, widget, event):
		if self.client.connected():
			song=ClientHelper.song_to_first_str_dict(self.client.currentsong())
			if not song == {}:
				try:
					artist=song[self.settings.get_artist_type()]
				except:
					try:
						artist=song["artist"]
					except:
						artist=""
				try:
					album=song["album"]
				except:
					album=""
				try:
					album_year=song["date"]
				except:
					album_year=""
				if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
					self.client.album_to_playlist(album, artist, album_year, False)
				elif event.button == 2 and event.type == Gdk.EventType.BUTTON_PRESS:
					self.client.album_to_playlist(album, artist, album_year, True)
				elif event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
					album_dialog=AlbumDialog(self.window, self.client, self.settings, album, artist, album_year)
					album_dialog.open()
					album_dialog.destroy()

	def on_settings_changed(self, *args):
		size=self.settings.get_int("track-cover")
		self.cover.set_size_request(size, size)
		self.song_file=None
		self.refresh()

class PlaylistView(Gtk.Box):
	def __init__(self, client, settings):
		Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)

		# adding vars
		self.client=client
		self.settings=settings
		self.playlist_version=None

		# Store
		# (track, disc, title, artist, album, duration, date, genre, file, weight)
		self.store=Gtk.ListStore(str, str, str, str, str, str, str, str, str, Pango.Weight)

		# TreeView
		self.treeview=Gtk.TreeView(model=self.store)
		self.treeview.set_search_column(2)
		self.treeview.set_property("activate-on-single-click", True)

		# selection
		self.selection=self.treeview.get_selection()
		self.selection.set_mode(Gtk.SelectionMode.SINGLE)

		# Column
		renderer_text=Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END, ellipsize_set=True)
		renderer_text_ralign=Gtk.CellRendererText(xalign=1.0)
		self.columns=[None, None, None, None, None, None, None, None]

		self.columns[0]=Gtk.TreeViewColumn(_("No"), renderer_text_ralign, text=0, weight=9)
		self.columns[0].set_property("resizable", True)

		self.columns[1]=Gtk.TreeViewColumn(_("Disc"), renderer_text_ralign, text=1, weight=9)
		self.columns[1].set_property("resizable", True)

		self.columns[2]=Gtk.TreeViewColumn(_("Title"), renderer_text, text=2, weight=9)
		self.columns[2].set_property("resizable", True)

		self.columns[3]=Gtk.TreeViewColumn(_("Artist"), renderer_text, text=3, weight=9)
		self.columns[3].set_property("resizable", True)

		self.columns[4]=Gtk.TreeViewColumn(_("Album"), renderer_text, text=4, weight=9)
		self.columns[4].set_property("resizable", True)

		self.columns[5]=Gtk.TreeViewColumn(_("Length"), renderer_text, text=5, weight=9)
		self.columns[5].set_property("resizable", True)

		self.columns[6]=Gtk.TreeViewColumn(_("Year"), renderer_text, text=6, weight=9)
		self.columns[6].set_property("resizable", True)

		self.columns[7]=Gtk.TreeViewColumn(_("Genre"), renderer_text, text=7, weight=9)
		self.columns[7].set_property("resizable", True)

		self.load_settings()

		# scroll
		scroll=Gtk.ScrolledWindow()
		scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
		scroll.add(self.treeview)

		# frame
		frame=FocusFrame()
		frame.set_widget(self.treeview)
		frame.add(scroll)

		# audio infos
		audio=AudioType(self.client)
		audio.set_margin_end(3)
		audio.set_xalign(1)
		audio.set_ellipsize(Pango.EllipsizeMode.END)

		# playlist info
		self.playlist_info=Gtk.Label()
		self.playlist_info.set_margin_start(3)
		self.playlist_info.set_xalign(0)
		self.playlist_info.set_ellipsize(Pango.EllipsizeMode.END)

		# status bar
		status_bar=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
		status_bar.set_property("border-width", 3)
		status_bar.pack_start(self.playlist_info, True, True, 0)
		status_bar.pack_end(audio, False, False, 0)

		# connect
		self.treeview.connect("row-activated", self.on_row_activated)
		self.key_press_event=self.treeview.connect("key-press-event", self.on_key_press_event)
		self.treeview.connect("button-press-event", self.on_button_press_event)

		self.client.emitter.connect("playlist", self.on_playlist_changed)
		self.client.emitter.connect("playing_file_changed", self.on_file_changed)
		self.client.emitter.connect("disconnected", self.on_disconnected)

		self.settings.connect("changed::column-visibilities", self.load_settings)
		self.settings.connect("changed::column-permutation", self.load_settings)

		# packing
		self.pack_start(frame, True, True, 0)
		self.pack_start(Gtk.Separator.new(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
		self.pack_end(status_bar, False, False, 0)

	def save_settings(self):  # only saves the column sizes
		columns=self.treeview.get_columns()
		permutation=self.settings.get_value("column-permutation").unpack()
		sizes=[0] * len(permutation)
		for i in range(len(permutation)):
			sizes[permutation[i]]=columns[i].get_width()
		self.settings.set_value("column-sizes", GLib.Variant("ai", sizes))

	def load_settings(self, *args):
		columns=self.treeview.get_columns()
		for column in columns:
			self.treeview.remove_column(column)
		sizes=self.settings.get_value("column-sizes").unpack()
		visibilities=self.settings.get_value("column-visibilities").unpack()
		for i in self.settings.get_value("column-permutation"):
			if sizes[i] > 0:
				self.columns[i].set_fixed_width(sizes[i])
			self.columns[i].set_visible(visibilities[i])
			self.treeview.append_column(self.columns[i])

	def scroll_to_selected_title(self):
		treeview, treeiter=self.selection.get_selected()
		if not treeiter == None:
			path=treeview.get_path(treeiter)
			self.treeview.scroll_to_cell(path, None, True, 0.25)

	def refresh_playlist_info(self):
		songs=self.client.playlistinfo()
		if not songs == []:
			whole_length_human_readable=ClientHelper.calc_display_length(songs)
			self.playlist_info.set_text(_("%(total_tracks)i titles (%(total_length)s)") % {"total_tracks": len(songs), "total_length": whole_length_human_readable})
		else:
			self.playlist_info.set_text("")

	def refresh_selection(self):  # Gtk.TreePath(len(self.store) is used to generate an invalid TreePath (needed to unset cursor)
		self.treeview.set_cursor(Gtk.TreePath(len(self.store)), None, False)
		for row in self.store:  # reset bold text
			row[9]=Pango.Weight.BOOK
		try:
			song=self.client.status()["song"]
			path=Gtk.TreePath(int(song))
			self.selection.select_path(path)
			self.store[path][9]=Pango.Weight.BOLD
			self.scroll_to_selected_title()
		except:
			self.selection.unselect_all()

	def clear(self, *args):
		self.playlist_info.set_text("")
		self.store.clear()
		self.playlist_version=None

	def remove_song(self, path):
		self.client.delete(path)  # bad song index possible
		self.store.remove(self.store.get_iter(path))
		self.playlist_version=self.client.status()["playlist"]

	def on_key_press_event(self, widget, event):
		self.treeview.handler_block(self.key_press_event)
		if event.keyval == 65535:  # entf
			treeview, treeiter=self.selection.get_selected()
			if not treeiter == None:
				path=self.store.get_path(treeiter)
				try:
					self.remove_song(path)
				except:
					pass
		elif event.keyval == 65383:  # menu key
			treeview, treeiter=self.selection.get_selected()
			if not treeiter == None:
				path=self.store.get_path(treeiter)
				cell=self.treeview.get_cell_area(path, None)
				file_name=self.store[path][8]
				pop=SongPopover(self.client.lsinfo(file_name)[0], widget, int(cell.x), int(cell.y))
				pop.popup()
				pop.show_all()
		self.treeview.handler_unblock(self.key_press_event)

	def on_button_press_event(self, widget, event):
		if event.button == 2 and event.type == Gdk.EventType.BUTTON_PRESS:
			try:
				path=widget.get_path_at_pos(int(event.x), int(event.y))[0]
				self.remove_song(path)
			except:
				pass
		elif event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
			try:
				path=widget.get_path_at_pos(int(event.x), int(event.y))[0]
				pop=SongPopover(self.client.playlistinfo(path)[0], widget, int(event.x), int(event.y))
				pop.popup()
			except:
				pass

	def on_row_activated(self, widget, path, view_column):
		self.client.play(path)

	def on_playlist_changed(self, *args):
		songs=[]
		if not self.playlist_version == None:
			songs=self.client.plchanges(self.playlist_version)
		else:
			songs=self.client.playlistinfo()
		if not songs == []:
			self.playlist_info.set_text("")
			for s in songs:
				song=ClientHelper.extend_song_for_display(ClientHelper.song_to_str_dict(s))
				try:
					treeiter=self.store.get_iter(song["pos"])
					self.store.set(treeiter, 0, song["track"], 1, song["disc"], 2, song["title"], 3, song["artist"], 4, song["album"], 5, song["human_duration"], 6, song["date"], 7, song["genre"], 8, song["file"], 9, Pango.Weight.BOOK)
				except:
					self.store.append([song["track"], song["disc"], song["title"], song["artist"], song["album"], song["human_duration"], song["date"], song["genre"], song["file"], Pango.Weight.BOOK])
		for i in reversed(range(int(self.client.status()["playlistlength"]), len(self.store))):
			treeiter=self.store.get_iter(i)
			self.store.remove(treeiter)
		self.refresh_playlist_info()
		if self.playlist_version == None or not songs == []:
			self.refresh_selection()
		self.playlist_version=self.client.status()["playlist"]

	def on_file_changed(self, *args):
		self.refresh_selection()

	def on_disconnected(self, *args):
		self.clear()

class CoverLyricsOSD(Gtk.Overlay):
	def __init__(self, client, settings, window):
		Gtk.Overlay.__init__(self)

		# adding vars
		self.client=client
		self.settings=settings
		self.window=window

		# cover
		self.cover=MainCover(self.client, self.settings, self.window)
		self.cover.set_property("border-width", 3)

		# lyrics button
		self.lyrics_button=Gtk.Button(image=Gtk.Image.new_from_icon_name("media-view-subtitles-symbolic", Gtk.IconSize.BUTTON))
		self.lyrics_button.set_tooltip_text(_("Show lyrics"))
		style_context=self.lyrics_button.get_style_context()
		style_context.add_class("circular")

		# revealer
		# workaround to get tooltips in overlay
		self.revealer=Gtk.Revealer()
		self.revealer.set_halign(2)
		self.revealer.set_valign(1)
		self.revealer.set_margin_top(6)
		self.revealer.set_margin_end(6)
		self.revealer.add(self.lyrics_button)

		# event box
		self.event_box=Gtk.EventBox()
		self.event_box.add(self.cover)

		# packing
		self.add(self.event_box)
		self.add_overlay(self.revealer)

		# connect
		self.lyrics_button.connect("clicked", self.on_lyrics_clicked)
		self.client.emitter.connect("disconnected", self.on_disconnected)
		self.client.emitter.connect("reconnected", self.on_reconnected)
		self.settings.connect("changed::show-lyrics-button", self.on_settings_changed)

		self.on_settings_changed()  # hide lyrics button

	def show_lyrics(self, *args):
		if self.lyrics_button.get_sensitive():
			self.lyrics_button.emit("clicked")

	def on_reconnected(self, *args):
		self.lyrics_button.set_sensitive(True)

	def on_disconnected(self, *args):
		self.lyrics_button.set_sensitive(False)
		self.cover.clear()
		try:
			self.lyrics_win.destroy()
		except:
			pass

	def on_lyrics_clicked(self, widget):
		self.lyrics_button.set_sensitive(False)
		self.lyrics_win=LyricsWindow(self.client, self.settings)
		def on_destroy(*args):
			self.lyrics_button.set_sensitive(True)
		self.lyrics_win.connect("destroy", on_destroy)
		self.add_overlay(self.lyrics_win)

	def on_settings_changed(self, *args):
		if self.settings.get_boolean("show-lyrics-button"):
			self.revealer.set_reveal_child(True)
		else:
			self.revealer.set_reveal_child(False)

class CoverPlaylistView(Gtk.Paned):
	def __init__(self, client, settings, window):
		Gtk.Paned.__init__(self)  # paned0

		# adding vars
		self.client=client
		self.settings=settings
		self.window=window

		# widgets
		self.cover=CoverLyricsOSD(self.client, self.settings, self.window)
		self.playlist_view=PlaylistView(self.client, self.settings)

		# packing
		self.pack1(self.cover, False, False)
		self.pack2(self.playlist_view, True, False)

		self.set_position(self.settings.get_int("paned0"))

	def show_lyrics(self, *args):
		self.cover.show_lyrics()

	def save_settings(self):
		self.settings.set_int("paned0", self.get_position())
		self.playlist_view.save_settings()

class Browser(Gtk.Paned):
	def __init__(self, client, settings, window):
		Gtk.Paned.__init__(self)  # paned1
		self.set_orientation(Gtk.Orientation.HORIZONTAL)

		# adding vars
		self.client=client
		self.settings=settings
		self.window=window
		self.use_csd=self.settings.get_boolean("use-csd")

		if self.use_csd:
			self.icon_size=0
		else:
			self.icon_size=self.settings.get_int("icon-size")

		# widgets
		self.icons={}
		icons_data=["go-previous-symbolic", "system-search-symbolic"]
		for data in icons_data:
			self.icons[data]=PixelSizedIcon(data, self.icon_size)

		self.back_to_album_button=Gtk.Button(image=self.icons["go-previous-symbolic"])
		self.back_to_album_button.set_tooltip_text(_("Back to current album"))
		self.search_button=Gtk.ToggleButton(image=self.icons["system-search-symbolic"])
		self.search_button.set_tooltip_text(_("Search"))
		self.genre_select=GenreSelect(self.client, self.settings)
		self.artist_view=ArtistView(self.client, self.settings, self.genre_select)
		self.search=SearchWindow(self.client)
		self.album_view=AlbumView(self.client, self.settings, self.genre_select, self.window)

		# connect
		self.back_to_album_button.connect("clicked", self.back_to_album)
		self.search_button.connect("toggled", self.on_search_toggled)
		self.artist_view.connect("artists_changed", self.on_artists_changed)
		if not self.use_csd:
			self.settings.connect("changed::icon-size", self.on_icon_size_changed)
		self.client.emitter.connect("disconnected", self.on_disconnected)
		self.client.emitter.connect("reconnected", self.on_reconnected)

		# packing
		self.stack=Gtk.Stack()
		self.stack.set_transition_type(1)
		self.stack.add_named(self.album_view, "albums")
		self.stack.add_named(self.search, "search")

		if self.use_csd:
			self.pack1(self.artist_view, False, False)
		else:
			hbox=Gtk.Box(spacing=6)
			hbox.set_property("border-width", 6)
			hbox.pack_start(self.back_to_album_button, False, False, 0)
			hbox.pack_start(self.genre_select, True, True, 0)
			hbox.pack_start(self.search_button, False, False, 0)
			box1=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
			box1.pack_start(hbox, False, False, 0)
			box1.pack_start(Gtk.Separator.new(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
			box1.pack_start(self.artist_view, True, True, 0)
			self.pack1(box1, False, False)
		self.pack2(self.stack, True, False)

		self.set_position(self.settings.get_int("paned1"))

	def save_settings(self):
		self.settings.set_int("paned1", self.get_position())

	def clear(self, *args):
		self.genre_select.clear()
		self.artist_view.clear()
		self.album_view.clear()
		self.search.clear()

	def search_started(self):
		return self.search.started()

	def back_to_album(self, *args):
		try:  # since this can still be running when the connection is lost, various exceptions can occur
			song=ClientHelper.song_to_first_str_dict(self.client.currentsong())
			try:
				artist=song[self.settings.get_artist_type()]
			except:
				try:
					artist=song["artist"]
				except:
					artist=""
			try:
				if not song['genre'] == self.genre_select.get_value():
					self.genre_select.deactivate()  # deactivate genre filter to show all artists
			except:
				self.genre_select.deactivate()  # deactivate genre filter to show all artists
			if len(self.artist_view.get_selected_artists()) <= 1:
				row_num=len(self.artist_view.store)
				for i in range(0, row_num):
					path=Gtk.TreePath(i)
					if self.artist_view.store[path][0] == artist:
						self.artist_view.treeview.set_cursor(path, None, False)
						if not self.artist_view.get_selected_artists() == [artist]:
							self.artist_view.treeview.row_activated(path, self.artist_view.column_name)
						else:
							self.search_button.set_active(False)
							self.artist_view.highlight_selected()
						break
			else:
				self.search_button.set_active(False)
				self.artist_view.treeview.set_cursor(Gtk.TreePath(0), None, False)  # set cursor to 'all artists'
			self.album_view.scroll_to_selected_album()
		except:
			pass

	def on_search_toggled(self, widget):
		if widget.get_active():
			self.stack.set_visible_child_name("search")
			self.search.start()
		else:
			self.stack.set_visible_child_name("albums")

	def on_reconnected(self, *args):
		self.back_to_album_button.set_sensitive(True)
		self.search_button.set_sensitive(True)
		self.genre_select.set_sensitive(True)

	def on_disconnected(self, *args):
		self.clear()
		self.back_to_album_button.set_sensitive(False)
		self.search_button.set_active(False)
		self.search_button.set_sensitive(False)
		self.genre_select.set_sensitive(False)

	def on_artists_changed(self, *args):
		self.search_button.set_active(False)
		artists=self.artist_view.get_selected_artists()
		self.album_view.refresh(artists)

	def on_icon_size_changed(self, *args):
		pixel_size=self.settings.get_int("icon-size")
		for icon in self.icons.values():
			icon.set_pixel_size(pixel_size)

class ProfileSettings(Gtk.Grid):
	def __init__(self, parent, settings):
		Gtk.Grid.__init__(self)
		self.set_row_spacing(6)
		self.set_column_spacing(12)
		self.set_property("border-width", 18)

		# adding vars
		self.settings=settings
		self.gui_modification=False  # indicates whether the settings where changed from the settings dialog

		# widgets
		self.profiles_combo=Gtk.ComboBoxText()
		self.profiles_combo.set_entry_text_column(0)

		add_button=Gtk.Button(label=None, image=Gtk.Image(stock=Gtk.STOCK_ADD))
		delete_button=Gtk.Button(label=None, image=Gtk.Image(stock=Gtk.STOCK_DELETE))
		add_delete_buttons=Gtk.ButtonBox()
		add_delete_buttons.set_property("layout-style", Gtk.ButtonBoxStyle.EXPAND)
		add_delete_buttons.pack_start(add_button, True, True, 0)
		add_delete_buttons.pack_start(delete_button, True, True, 0)

		self.profile_entry=Gtk.Entry()
		self.host_entry=Gtk.Entry()
		self.port_entry=IntEntry(0, 0, 65535, 1)
		address_entry=Gtk.Box(spacing=6)
		address_entry.pack_start(self.host_entry, True, True, 0)
		address_entry.pack_start(self.port_entry, False, False, 0)
		self.password_entry=Gtk.Entry()
		self.password_entry.set_visibility(False)
		self.path_entry=Gtk.Entry()
		self.path_select_button=Gtk.Button(image=Gtk.Image(stock=Gtk.STOCK_OPEN))
		path_box=Gtk.Box(spacing=6)
		path_box.pack_start(self.path_entry, True, True, 0)
		path_box.pack_start(self.path_select_button, False, False, 0)

		profiles_label=Gtk.Label(label=_("Profile:"))
		profiles_label.set_xalign(1)
		profile_label=Gtk.Label(label=_("Name:"))
		profile_label.set_xalign(1)
		host_label=Gtk.Label(label=_("Host:"))
		host_label.set_xalign(1)
		password_label=Gtk.Label(label=_("Password:"))
		password_label.set_xalign(1)
		path_label=Gtk.Label(label=_("Music lib:"))
		path_label.set_xalign(1)

		# connect
		add_button.connect("clicked", self.on_add_button_clicked)
		delete_button.connect("clicked", self.on_delete_button_clicked)
		self.path_select_button.connect("clicked", self.on_path_select_button_clicked, parent)
		self.profiles_combo_changed=self.profiles_combo.connect("changed", self.on_profiles_changed)
		self.entry_changed_handlers=[]
		self.entry_changed_handlers.append((self.profile_entry, self.profile_entry.connect("changed", self.on_profile_entry_changed)))
		self.entry_changed_handlers.append((self.host_entry, self.host_entry.connect("changed", self.on_host_entry_changed)))
		self.entry_changed_handlers.append((self.port_entry, self.port_entry.connect("value-changed", self.on_port_entry_changed)))
		self.entry_changed_handlers.append((self.password_entry, self.password_entry.connect("changed", self.on_password_entry_changed)))
		self.entry_changed_handlers.append((self.path_entry, self.path_entry.connect("changed", self.on_path_entry_changed)))
		self.settings_handlers=[]
		self.settings_handlers.append(self.settings.connect("changed::profiles", self.on_settings_changed))
		self.settings_handlers.append(self.settings.connect("changed::hosts", self.on_settings_changed))
		self.settings_handlers.append(self.settings.connect("changed::ports", self.on_settings_changed))
		self.settings_handlers.append(self.settings.connect("changed::passwords", self.on_settings_changed))
		self.settings_handlers.append(self.settings.connect("changed::paths", self.on_settings_changed))
		self.connect("destroy", self.remove_handlers)

		self.profiles_combo_reload()
		self.profiles_combo.set_active(0)

		# packing
		self.add(profiles_label)
		self.attach_next_to(profile_label, profiles_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(host_label, profile_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(password_label, host_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(path_label, password_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(self.profiles_combo, profiles_label, Gtk.PositionType.RIGHT, 2, 1)
		self.attach_next_to(add_delete_buttons, self.profiles_combo, Gtk.PositionType.RIGHT, 1, 1)
		self.attach_next_to(self.profile_entry, profile_label, Gtk.PositionType.RIGHT, 2, 1)
		self.attach_next_to(address_entry, host_label, Gtk.PositionType.RIGHT, 2, 1)
		self.attach_next_to(self.password_entry, password_label, Gtk.PositionType.RIGHT, 2, 1)
		self.attach_next_to(path_box, path_label, Gtk.PositionType.RIGHT, 2, 1)

	def remove_handlers(self, *args):
		for handler in self.settings_handlers:
			self.settings.disconnect(handler)

	def on_settings_changed(self, *args):
		if self.gui_modification:
			self.gui_modification=False
		else:
			self.profiles_combo_reload()
			self.profiles_combo.set_active(0)

	def block_entry_changed_handlers(self, *args):
		for obj, handler in self.entry_changed_handlers:
			obj.handler_block(handler)

	def unblock_entry_changed_handlers(self, *args):
		for obj, handler in self.entry_changed_handlers:
			obj.handler_unblock(handler)

	def profiles_combo_reload(self, *args):
		self.block_entry_changed_handlers()

		self.profiles_combo.remove_all()
		for profile in self.settings.get_value("profiles"):
			self.profiles_combo.append_text(profile)

		self.unblock_entry_changed_handlers()

	def on_add_button_clicked(self, *args):
		pos=self.profiles_combo.get_active()
		self.settings.array_append('as', "profiles", "new profile")
		self.settings.array_append('as', "hosts", "localhost")
		self.settings.array_append('ai', "ports", 6600)
		self.settings.array_append('as', "passwords", "")
		self.settings.array_append('as', "paths", "")
		self.profiles_combo_reload()
		self.profiles_combo.set_active(pos)

	def on_delete_button_clicked(self, *args):
		pos=self.profiles_combo.get_active()
		self.settings.array_delete('as', "profiles", pos)
		self.settings.array_delete('as', "hosts", pos)
		self.settings.array_delete('ai', "ports", pos)
		self.settings.array_delete('as', "passwords", pos)
		self.settings.array_delete('as', "paths", pos)
		if len(self.settings.get_value("profiles")) == 0:
			self.on_add_button_clicked()
		else:
			self.profiles_combo_reload()
			self.profiles_combo.set_active(0)	

	def on_profile_entry_changed(self, *args):
		self.gui_modification=True
		pos=self.profiles_combo.get_active()
		self.settings.array_modify('as', "profiles", pos, self.profile_entry.get_text())
		self.profiles_combo_reload()
		self.profiles_combo.set_active(pos)

	def on_host_entry_changed(self, *args):
		self.gui_modification=True
		self.settings.array_modify('as', "hosts", self.profiles_combo.get_active(), self.host_entry.get_text())

	def on_port_entry_changed(self, *args):
		self.gui_modification=True
		self.settings.array_modify('ai', "ports", self.profiles_combo.get_active(), self.port_entry.get_int())

	def on_password_entry_changed(self, *args):
		self.gui_modification=True
		self.settings.array_modify('as', "passwords", self.profiles_combo.get_active(), self.password_entry.get_text())

	def on_path_entry_changed(self, *args):
		self.gui_modification=True
		self.settings.array_modify('as', "paths", self.profiles_combo.get_active(), self.path_entry.get_text())

	def on_path_select_button_clicked(self, widget, parent):
		dialog=Gtk.FileChooserDialog(title=_("Choose directory"), transient_for=parent, action=Gtk.FileChooserAction.SELECT_FOLDER)
		dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
		dialog.add_buttons(Gtk.STOCK_OK, Gtk.ResponseType.OK)
		dialog.set_default_size(800, 400)
		dialog.set_current_folder(self.settings.get_value("paths")[self.profiles_combo.get_active()])
		response=dialog.run()
		if response == Gtk.ResponseType.OK:
			self.gui_modification=True
			self.settings.array_modify('as', "paths", self.profiles_combo.get_active(), dialog.get_filename())
			self.path_entry.set_text(dialog.get_filename())
		dialog.destroy()

	def on_profiles_changed(self, *args):
		active=self.profiles_combo.get_active()
		self.block_entry_changed_handlers()

		self.profile_entry.set_text(self.settings.get_value("profiles")[active])
		self.host_entry.set_text(self.settings.get_value("hosts")[active])
		self.port_entry.set_int(self.settings.get_value("ports")[active])
		self.password_entry.set_text(self.settings.get_value("passwords")[active])
		self.path_entry.set_text(self.settings.get_value("paths")[active])

		self.unblock_entry_changed_handlers()

class GeneralSettings(Gtk.Box):
	def __init__(self, settings):
		Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=6)
		self.set_property("border-width", 18)

		# adding vars
		self.settings=settings
		self.settings_handlers=[]

		# int_settings
		int_settings={}
		int_settings_data=[(_("Main cover size:"), (100, 1200, 10), "track-cover"),\
				(_("Album view cover size:"), (50, 600, 10), "album-cover"),\
				(_("Button icon size:"), (16, 64, 2), "icon-size")]
		for data in int_settings_data:
			int_settings[data[2]]=(Gtk.Label(), IntEntry(self.settings.get_int(data[2]), data[1][0], data[1][1], data[1][2]))
			int_settings[data[2]][0].set_label(data[0])
			int_settings[data[2]][0].set_xalign(0)
			int_settings[data[2]][1].connect("value-changed", self.on_int_changed, data[2])
			self.settings_handlers.append(self.settings.connect("changed::"+data[2], self.on_int_settings_changed, int_settings[data[2]][1]))

		# combo_settings
		combo_settings={}
		combo_settings_data=[(_("Sort albums by:"), _("name"), _("year"), "sort-albums-by-year"), \
					(_("Position of playlist:"), _("bottom"), _("right"), "playlist-right")]
		for data in combo_settings_data:
			combo_settings[data[3]]=(Gtk.Label(), Gtk.ComboBoxText())
			combo_settings[data[3]][0].set_label(data[0])
			combo_settings[data[3]][0].set_xalign(0)
			combo_settings[data[3]][1].set_entry_text_column(0)
			combo_settings[data[3]][1].append_text(data[1])
			combo_settings[data[3]][1].append_text(data[2])
			if self.settings.get_boolean(data[3]):
				combo_settings[data[3]][1].set_active(1)
			else:
				combo_settings[data[3]][1].set_active(0)
			combo_settings[data[3]][1].connect("changed", self.on_combo_changed, data[3])
			self.settings_handlers.append(self.settings.connect("changed::"+data[3], self.on_combo_settings_changed, combo_settings[data[3]][1]))

		# check buttons
		check_buttons={}
		check_buttons_data=[(_("Use Client-side decoration"), "use-csd"), \
				(_("Show stop button"), "show-stop"), \
				(_("Show lyrics button"), "show-lyrics-button"), \
				(_("Show initials in artist view"), "show-initials"), \
				(_("Show tooltips in album view"), "show-album-view-tooltips"), \
				(_("Use 'Album Artist' tag"), "use-album-artist"), \
				(_("Send notification on title change"), "send-notify"), \
				(_("Stop playback on quit"), "stop-on-quit"), \
				(_("Play selected albums and titles immediately"), "force-mode")]

		for data in check_buttons_data:
			check_buttons[data[1]]=Gtk.CheckButton(label=data[0])
			check_buttons[data[1]].set_active(self.settings.get_boolean(data[1]))
			check_buttons[data[1]].set_margin_start(12)
			check_buttons[data[1]].connect("toggled", self.on_toggled, data[1])
			self.settings_handlers.append(self.settings.connect("changed::"+data[1], self.on_check_settings_changed, check_buttons[data[1]]))

		# headings
		view_heading=Gtk.Label()
		view_heading.set_markup(_("<b>View</b>"))
		view_heading.set_xalign(0)
		behavior_heading=Gtk.Label()
		behavior_heading.set_markup(_("<b>Behavior</b>"))
		behavior_heading.set_xalign(0)

		# view grid
		view_grid=Gtk.Grid()
		view_grid.set_row_spacing(6)
		view_grid.set_column_spacing(12)
		view_grid.set_margin_start(12)
		view_grid.add(int_settings["track-cover"][0])
		view_grid.attach_next_to(int_settings["album-cover"][0], int_settings["track-cover"][0], Gtk.PositionType.BOTTOM, 1, 1)
		view_grid.attach_next_to(int_settings["icon-size"][0], int_settings["album-cover"][0], Gtk.PositionType.BOTTOM, 1, 1)
		view_grid.attach_next_to(combo_settings["playlist-right"][0], int_settings["icon-size"][0], Gtk.PositionType.BOTTOM, 1, 1)
		view_grid.attach_next_to(int_settings["track-cover"][1], int_settings["track-cover"][0], Gtk.PositionType.RIGHT, 1, 1)
		view_grid.attach_next_to(int_settings["album-cover"][1], int_settings["album-cover"][0], Gtk.PositionType.RIGHT, 1, 1)
		view_grid.attach_next_to(int_settings["icon-size"][1], int_settings["icon-size"][0], Gtk.PositionType.RIGHT, 1, 1)
		view_grid.attach_next_to(combo_settings["playlist-right"][1], combo_settings["playlist-right"][0], Gtk.PositionType.RIGHT, 1, 1)

		# behavior grid
		behavior_grid=Gtk.Grid()
		behavior_grid.set_row_spacing(6)
		behavior_grid.set_column_spacing(12)
		behavior_grid.set_margin_start(12)
		behavior_grid.add(combo_settings["sort-albums-by-year"][0])
		behavior_grid.attach_next_to(combo_settings["sort-albums-by-year"][1], combo_settings["sort-albums-by-year"][0], Gtk.PositionType.RIGHT, 1, 1)

		# connect
		self.connect("destroy", self.remove_handlers)

		# packing
		box=Gtk.Box(spacing=12)
		box.pack_start(check_buttons["use-csd"], False, False, 0)
		box.pack_start(Gtk.Label(label=_("(restart required)"), sensitive=False), False, False, 0)
		self.pack_start(view_heading, True, True, 0)
		self.pack_start(box, True, True, 0)
		self.pack_start(check_buttons["show-stop"], True, True, 0)
		self.pack_start(check_buttons["show-lyrics-button"], True, True, 0)
		self.pack_start(check_buttons["show-initials"], True, True, 0)
		self.pack_start(check_buttons["show-album-view-tooltips"], True, True, 0)
		self.pack_start(view_grid, True, True, 0)
		self.pack_start(behavior_heading, True, True, 0)
		self.pack_start(check_buttons["use-album-artist"], True, True, 0)
		self.pack_start(check_buttons["send-notify"], True, True, 0)
		self.pack_start(check_buttons["stop-on-quit"], True, True, 0)
		self.pack_start(check_buttons["force-mode"], True, True, 0)
		self.pack_start(behavior_grid, True, True, 0)

	def remove_handlers(self, *args):
		for handler in self.settings_handlers:
			self.settings.disconnect(handler)

	def on_int_settings_changed(self, settings, key, entry):
		entry.set_value(settings.get_int(key))

	def on_combo_settings_changed(self, settings, key, combo):
		if settings.get_boolean(key):
			combo.set_active(1)
		else:
			combo.set_active(0)

	def on_check_settings_changed(self, settings, key, button):
		button.set_active(settings.get_boolean(key))

	def on_int_changed(self, widget, key):
		self.settings.set_int(key, widget.get_int())

	def on_combo_changed(self, box, key):
		active=box.get_active()
		if active == 0:
			self.settings.set_boolean(key, False)
		else:
			self.settings.set_boolean(key, True)

	def on_toggled(self, widget, key):
		self.settings.set_boolean(key, widget.get_active())

class PlaylistSettings(Gtk.Box):
	def __init__(self, settings):
		Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=6)
		self.set_property("border-width", 18)

		# adding vars
		self.settings=settings

		# label
		label=Gtk.Label(label=_("Choose the order of information to appear in the playlist:"))
		label.set_line_wrap(True)
		label.set_xalign(0)

		# Store
		# (toggle, header, actual_index)
		self.store=Gtk.ListStore(bool, str, int)

		# TreeView
		self.treeview=Gtk.TreeView(model=self.store)
		self.treeview.set_search_column(-1)
		self.treeview.set_reorderable(True)
		self.treeview.set_headers_visible(False)

		# selection
		self.selection=self.treeview.get_selection()

		# Column
		renderer_text=Gtk.CellRendererText()
		renderer_toggle=Gtk.CellRendererToggle()

		column_toggle=Gtk.TreeViewColumn("", renderer_toggle, active=0)
		self.treeview.append_column(column_toggle)

		column_text=Gtk.TreeViewColumn("", renderer_text, text=1)
		self.treeview.append_column(column_text)

		# fill store
		self.headers=[_("No"), _("Disc"), _("Title"), _("Artist"), _("Album"), _("Length"), _("Year"), _("Genre")]
		self.fill()

		# scroll
		scroll=Gtk.ScrolledWindow()
		scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
		scroll.add(self.treeview)
		frame=Gtk.Frame()
		frame.add(scroll)

		# Toolbar
		toolbar=Gtk.Toolbar()
		style_context=toolbar.get_style_context()
		style_context.add_class("inline-toolbar")
		self.up_button=Gtk.ToolButton.new(Gtk.Image.new_from_icon_name("go-up-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
		self.up_button.set_sensitive(False)
		self.down_button=Gtk.ToolButton.new(Gtk.Image.new_from_icon_name("go-down-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
		self.down_button.set_sensitive(False)
		toolbar.insert(self.up_button, 0)
		toolbar.insert(self.down_button, 1)

		# column chooser
		column_chooser=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		column_chooser.pack_start(frame, True, True, 0)
		column_chooser.pack_start(toolbar, False, False, 0)

		# connect
		self.row_deleted=self.store.connect("row-deleted", self.save_permutation)
		renderer_toggle.connect("toggled", self.on_cell_toggled)
		self.up_button.connect("clicked", self.on_up_button_clicked)
		self.down_button.connect("clicked", self.on_down_button_clicked)
		self.selection.connect("changed", self.set_button_sensitivity)
		self.settings_handlers=[]
		self.settings_handlers.append(self.settings.connect("changed::column-visibilities", self.on_visibilities_changed))
		self.settings_handlers.append(self.settings.connect("changed::column-permutation", self.on_permutation_changed))
		self.connect("destroy", self.remove_handlers)

		# packing
		self.pack_start(label, False, False, 0)
		self.pack_start(column_chooser, True, True, 0)

	def remove_handlers(self, *args):
		for handler in self.settings_handlers:
			self.settings.disconnect(handler)

	def fill(self, *args):
		visibilities=self.settings.get_value("column-visibilities").unpack()
		for actual_index in self.settings.get_value("column-permutation"):
			self.store.append([visibilities[actual_index], self.headers[actual_index], actual_index])

	def save_permutation(self, *args):
		permutation=[]
		for row in self.store:
			permutation.append(row[2])
		self.settings.set_value("column-permutation", GLib.Variant("ai", permutation))

	def set_button_sensitivity(self, *args):
		treeiter=self.selection.get_selected()[1]
		if treeiter == None:
			self.up_button.set_sensitive(False)
			self.down_button.set_sensitive(False)
		else:
			path=self.store.get_path(treeiter)
			if self.store.iter_next(treeiter) == None:
				self.up_button.set_sensitive(True)
				self.down_button.set_sensitive(False)
			elif not path.prev():
				self.up_button.set_sensitive(False)
				self.down_button.set_sensitive(True)
			else:
				self.up_button.set_sensitive(True)
				self.down_button.set_sensitive(True)

	def on_cell_toggled(self, widget, path):
		self.store[path][0]=not self.store[path][0]
		self.settings.array_modify('ab', "column-visibilities", self.store[path][2], self.store[path][0])

	def on_up_button_clicked(self, *args):
		treeiter=self.selection.get_selected()[1]
		path=self.store.get_path(treeiter)
		path.prev()
		prev=self.store.get_iter(path)
		self.store.move_before(treeiter, prev)
		self.set_button_sensitivity()
		self.save_permutation()

	def on_down_button_clicked(self, *args):
		treeiter=self.selection.get_selected()[1]
		path=self.store.get_path(treeiter)
		next=self.store.iter_next(treeiter)
		self.store.move_after(treeiter, next)
		self.set_button_sensitivity()
		self.save_permutation()

	def on_visibilities_changed(self, *args):
		visibilities=self.settings.get_value("column-visibilities").unpack()
		for i, actual_index in enumerate(self.settings.get_value("column-permutation")):
			self.store[i][0]=visibilities[actual_index]

	def on_permutation_changed(self, *args):
		equal=True
		perm=self.settings.get_value("column-permutation")
		for i, e in enumerate(self.store):
			if e[2] != perm[i]:
				equal=False
				break
		if not equal:
			self.store.handler_block(self.row_deleted)
			self.store.clear()
			self.fill()
			self.store.handler_unblock(self.row_deleted)

class SettingsDialog(Gtk.Dialog):
	def __init__(self, parent, settings):
		Gtk.Dialog.__init__(self, title=_("Settings"), transient_for=parent)
		self.add_button(Gtk.STOCK_OK, Gtk.ResponseType.OK)
		self.set_default_size(500, 400)

		# adding vars
		self.settings=settings

		# widgets
		general=GeneralSettings(self.settings)
		profiles=ProfileSettings(parent, self.settings)
		playlist=PlaylistSettings(self.settings)

		# packing
		tabs=Gtk.Notebook()
		tabs.append_page(general, Gtk.Label(label=_("General")))
		tabs.append_page(profiles, Gtk.Label(label=_("Profiles")))
		tabs.append_page(playlist, Gtk.Label(label=_("Playlist")))
		self.vbox.pack_start(tabs, True, True, 0)  # vbox default widget of dialogs
		self.vbox.set_spacing(3)

		self.show_all()

class ClientControl(Gtk.ButtonBox):
	def __init__(self, client, settings):
		Gtk.ButtonBox.__init__(self, spacing=6)
		self.set_property("layout-style", Gtk.ButtonBoxStyle.EXPAND)

		# adding vars
		self.client=client
		self.settings=settings
		self.icon_size=self.settings.get_int("icon-size")

		# widgets
		self.icons={}
		icons_data=["media-playback-start-symbolic", "media-playback-stop-symbolic", "media-playback-pause-symbolic", \
				"media-skip-backward-symbolic", "media-skip-forward-symbolic"]
		for data in icons_data:
			self.icons[data]=PixelSizedIcon(data, self.icon_size)

		self.play_button=Gtk.Button(image=self.icons["media-playback-start-symbolic"])
		self.stop_button=Gtk.Button(image=self.icons["media-playback-stop-symbolic"])
		self.prev_button=Gtk.Button(image=self.icons["media-skip-backward-symbolic"])
		self.next_button=Gtk.Button(image=self.icons["media-skip-forward-symbolic"])

		# connect
		self.play_button.connect("clicked", self.on_play_clicked)
		self.stop_button.connect("clicked", self.on_stop_clicked)
		self.prev_button.connect("clicked", self.on_prev_clicked)
		self.next_button.connect("clicked", self.on_next_clicked)
		self.settings.connect("changed::show-stop", self.on_settings_changed)
		self.settings.connect("changed::icon-size", self.on_icon_size_changed)
		self.client.emitter.connect("player", self.refresh)

		# packing
		self.pack_start(self.prev_button, True, True, 0)
		self.pack_start(self.play_button, True, True, 0)
		if self.settings.get_boolean("show-stop"):
			self.pack_start(self.stop_button, True, True, 0)
		self.pack_start(self.next_button, True, True, 0)

	def refresh(self, *args):
		status=self.client.status()
		if status["state"] == "play":
			self.play_button.set_image(self.icons["media-playback-pause-symbolic"])
			self.prev_button.set_sensitive(True)
			self.next_button.set_sensitive(True)
		elif status["state"] == "pause":
			self.play_button.set_image(self.icons["media-playback-start-symbolic"])
			self.prev_button.set_sensitive(True)
			self.next_button.set_sensitive(True)
		else:
			self.play_button.set_image(self.icons["media-playback-start-symbolic"])
			self.prev_button.set_sensitive(False)
			self.next_button.set_sensitive(False)

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
						self.client.play()
					except:
						pass

	def on_stop_clicked(self, widget):
		if self.client.connected():
			self.client.stop()

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

	def on_icon_size_changed(self, *args):
		pixel_size=self.settings.get_int("icon-size")
		for icon in self.icons.values():
			icon.set_pixel_size(pixel_size)

class SeekBar(Gtk.Box):
	def __init__(self, client):
		Gtk.Box.__init__(self)
		self.set_hexpand(True)

		# adding vars
		self.client=client
		self.seek_time="10"  # seek increment in seconds
		self.update=True
		self.jumped=False

		# labels
		self.elapsed=Gtk.Label()
		self.elapsed.set_width_chars(5)
		self.rest=Gtk.Label()
		self.rest.set_width_chars(6)

		# progress bar
		self.scale=Gtk.Scale.new_with_range(orientation=Gtk.Orientation.HORIZONTAL, min=0, max=100, step=0.001)
		self.scale.set_show_fill_level(True)
		self.scale.set_restrict_to_fill_level(False)
		self.scale.set_draw_value(False)

		# css (scale)
		style_context=self.scale.get_style_context()
		provider=Gtk.CssProvider()
		css=b"""scale fill { background-color: @theme_selected_bg_color; }"""
		provider.load_from_data(css)
		style_context.add_provider(provider, 800)

		# event boxes
		self.elapsed_event_box=Gtk.EventBox()
		self.rest_event_box=Gtk.EventBox()

		# connect
		self.elapsed_event_box.connect("button-press-event", self.on_elapsed_button_press_event)
		self.rest_event_box.connect("button-press-event", self.on_rest_button_press_event)
		self.scale.connect("change-value", self.on_change_value)
		self.scale.connect("scroll-event", self.dummy)  # disable mouse wheel
		self.scale.connect("button-press-event", self.on_scale_button_press_event)
		self.scale.connect("button-release-event", self.on_scale_button_release_event)
		self.client.emitter.connect("disconnected", self.disable)
		self.client.emitter.connect("player", self.on_player)
		# periodic_signal
		self.periodic_signal=self.client.emitter.connect("periodic_signal", self.refresh)

		# packing
		self.elapsed_event_box.add(self.elapsed)
		self.rest_event_box.add(self.rest)
		self.pack_start(self.elapsed_event_box, False, False, 0)
		self.pack_start(self.scale, True, True, 0)
		self.pack_end(self.rest_event_box, False, False, 0)

		self.disable()

	def dummy(self, *args):
		return True

	def on_scale_button_press_event(self, widget, event):
		if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
			self.update=False
			self.scale.set_has_origin(False)
		if event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
			self.jumped=False

	def on_scale_button_release_event(self, widget, event):
		if event.button == 1:
			if self.jumped:  # actual seek
				status=self.client.status()
				duration=float(status["duration"])
				factor=(self.scale.get_value()/100)
				pos=(duration*factor)
				self.client.seekcur(pos)
				self.jumped=False
			self.scale.set_has_origin(True)
			self.update=True
			self.refresh()

	def on_change_value(self, range, scroll, value):  # value is inaccurate
		if scroll == Gtk.ScrollType.STEP_BACKWARD:
			self.seek_backward()
		elif scroll == Gtk.ScrollType.STEP_FORWARD:
			self.seek_forward()
		elif scroll == Gtk.ScrollType.JUMP:
			status=self.client.status()
			duration=float(status["duration"])
			factor=(value/100)
			if factor > 1:  # fix display error
				factor=1
			elapsed=(factor*duration)
			self.elapsed.set_text(str(datetime.timedelta(seconds=int(elapsed))).lstrip("0").lstrip(":"))
			self.rest.set_text("-"+str(datetime.timedelta(seconds=int(duration-elapsed))).lstrip("0").lstrip(":"))
			self.jumped=True

	def seek_forward(self):
		self.client.seekcur("+"+self.seek_time)

	def seek_backward(self):
		self.client.seekcur("-"+self.seek_time)

	def enable(self, *args):
		self.scale.set_sensitive(True)
		self.scale.set_range(0, 100)
		self.elapsed_event_box.set_sensitive(True)
		self.rest_event_box.set_sensitive(True)

	def disable(self, *args):
		self.scale.set_sensitive(False)
		self.scale.set_range(0, 0)
		self.elapsed_event_box.set_sensitive(False)
		self.rest_event_box.set_sensitive(False)
		self.elapsed.set_text("00:00")
		self.rest.set_text("-00:00")

	def on_elapsed_button_press_event(self, widget, event):
		if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
			self.seek_backward()
		elif event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
			self.seek_forward()

	def on_rest_button_press_event(self, widget, event):
		if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
			self.seek_forward()
		elif event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
			self.seek_backward()

	def on_player(self, *args):
		status=self.client.status()
		if status['state'] == "stop":
			self.disable()
		elif status['state'] == "pause":  # needed for seeking in paused state
			self.enable()
			self.refresh()
		else:
			self.enable()

	def refresh(self, *args):
		try:
			status=self.client.status()
			duration=float(status["duration"])
			elapsed=float(status["elapsed"])
			if elapsed > duration:  # fix display error
				elapsed=duration
			fraction=(elapsed/duration)*100
			if self.update:
				self.scale.set_value(fraction)
				self.elapsed.set_text(str(datetime.timedelta(seconds=int(elapsed))).lstrip("0").lstrip(":"))
				self.rest.set_text("-"+str(datetime.timedelta(seconds=int(duration-elapsed))).lstrip("0").lstrip(":"))
			self.scale.set_fill_level(fraction)
		except:
			self.disable()

class PlaybackOptions(Gtk.Box):
	def __init__(self, client, settings):
		Gtk.Box.__init__(self, spacing=6)

		# adding vars
		self.client=client
		self.settings=settings
		self.icon_size=self.settings.get_int("icon-size")

		# widgets
		self.icons={}
		icons_data=["media-playlist-shuffle-symbolic", "media-playlist-repeat-symbolic", "zoom-original-symbolic", "edit-cut-symbolic"]
		for data in icons_data:
			self.icons[data]=PixelSizedIcon(data, self.icon_size)

		self.random=Gtk.ToggleButton(image=self.icons["media-playlist-shuffle-symbolic"])
		self.random.set_tooltip_text(_("Random mode"))
		self.repeat=Gtk.ToggleButton(image=self.icons["media-playlist-repeat-symbolic"])
		self.repeat.set_tooltip_text(_("Repeat mode"))
		self.single=Gtk.ToggleButton(image=self.icons["zoom-original-symbolic"])
		self.single.set_tooltip_text(_("Single mode"))
		self.consume=Gtk.ToggleButton(image=self.icons["edit-cut-symbolic"])
		self.consume.set_tooltip_text(_("Consume mode"))
		self.volume=Gtk.VolumeButton()
		self.volume.set_property("use-symbolic", True)
		self.volume.set_property("size", self.settings.get_gtk_icon_size("icon-size"))

		# connect
		self.random_toggled=self.random.connect("toggled", self.set_random)
		self.repeat_toggled=self.repeat.connect("toggled", self.set_repeat)
		self.single_toggled=self.single.connect("toggled", self.set_single)
		self.consume_toggled=self.consume.connect("toggled", self.set_consume)
		self.volume_changed=self.volume.connect("value-changed", self.set_volume)
		self.options_changed=self.client.emitter.connect("options", self.options_refresh)
		self.mixer_changed=self.client.emitter.connect("mixer", self.mixer_refresh)
		self.settings.connect("changed::icon-size", self.on_icon_size_changed)

		# packing
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

	def options_refresh(self, *args):
		self.repeat.handler_block(self.repeat_toggled)
		self.random.handler_block(self.random_toggled)
		self.single.handler_block(self.single_toggled)
		self.consume.handler_block(self.consume_toggled)
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
		self.repeat.handler_unblock(self.repeat_toggled)
		self.random.handler_unblock(self.random_toggled)
		self.single.handler_unblock(self.single_toggled)
		self.consume.handler_unblock(self.consume_toggled)

	def mixer_refresh(self, *args):
		self.volume.handler_block(self.volume_changed)
		status=self.client.status()
		try:
			self.volume.set_value((int(status["volume"])/100))
		except:
			self.volume.set_value(0)
		self.volume.handler_unblock(self.volume_changed)

	def on_icon_size_changed(self, *args):
		pixel_size=self.settings.get_int("icon-size")
		for icon in self.icons.values():
			icon.set_pixel_size(pixel_size)
		self.volume.set_property("size", self.settings.get_gtk_icon_size("icon-size"))

class AudioType(Gtk.Label):
	def __init__(self, client):
		Gtk.Label.__init__(self)

		# adding vars
		self.client=client

		# connect
		self.client.emitter.connect("periodic_signal", self.refresh)  # periodic_signal
		self.client.emitter.connect("disconnected", self.clear)
		self.client.emitter.connect("player", self.on_player)

	def clear(self, *args):
		self.set_text("")

	def refresh(self, *args):
		try:
			file_type=self.client.currentsong()["file"].split('.')[-1]
			status=self.client.status()
			freq, res, chan=status["audio"].split(':')
			freq=str(float(freq)/1000)
			brate=status["bitrate"]
			string=_("%(bitrate)s kb/s, %(frequency)s kHz, %(resolution)s bit, %(channels)s channels, %(file_type)s") % {"bitrate": brate, "frequency": freq, "resolution": res, "channels": chan, "file_type": file_type}
			self.set_text(string)
		except:
			self.clear()

	def on_player(self, *args):
		status=self.client.status()
		if status['state'] == "stop":
			self.clear()

class ProfileSelect(Gtk.ComboBoxText):
	def __init__(self, client, settings):
		Gtk.ComboBoxText.__init__(self)

		# adding vars
		self.client=client
		self.settings=settings

		# connect
		self.changed=self.connect("changed", self.on_changed)
		self.settings.connect("changed::profiles", self.refresh)
		self.settings.connect("changed::hosts", self.refresh)
		self.settings.connect("changed::ports", self.refresh)
		self.settings.connect("changed::passwords", self.refresh)
		self.settings.connect("changed::paths", self.refresh)

		self.refresh()

	def refresh(self, *args):
		self.handler_block(self.changed)
		self.remove_all()
		for profile in self.settings.get_value("profiles"):
			self.append_text(profile)
		self.set_active(self.settings.get_int("active-profile"))
		self.handler_unblock(self.changed)

	def on_changed(self, *args):
		active=self.get_active()
		self.settings.set_int("active-profile", active)

class ServerStats(Gtk.Dialog):
	def __init__(self, parent, client):
		Gtk.Dialog.__init__(self, title=_("Stats"), transient_for=parent)
		self.add_buttons(Gtk.STOCK_OK, Gtk.ResponseType.OK)

		# adding vars
		self.client=client

		# Store
		# (tag, value)
		self.store=Gtk.ListStore(str, str)

		# TreeView
		self.treeview=Gtk.TreeView(model=self.store)
		self.treeview.set_can_focus(False)
		self.treeview.set_search_column(-1)
		self.treeview.set_headers_visible(False)

		# selection
		sel=self.treeview.get_selection()
		sel.set_mode(Gtk.SelectionMode.NONE)

		# Column
		renderer_text=Gtk.CellRendererText()
		renderer_text_ralign=Gtk.CellRendererText(xalign=1.0)

		self.column_tag=Gtk.TreeViewColumn("", renderer_text_ralign, text=0)
		self.treeview.append_column(self.column_tag)

		self.column_value=Gtk.TreeViewColumn("", renderer_text, text=1)
		self.treeview.append_column(self.column_value)

		self.store.append(["protocol:", str(self.client.mpd_version)])

		stats=self.client.stats()
		for key in stats:
			print_key=key+":"
			if key == "uptime" or key == "playtime" or key == "db_playtime":
				self.store.append([print_key, str(datetime.timedelta(seconds=int(stats[key])))])
			elif key == "db_update":
				self.store.append([print_key, str(datetime.datetime.fromtimestamp(int(stats[key])))])
			else:
				self.store.append([print_key, stats[key]])
		frame=Gtk.Frame()
		frame.add(self.treeview)
		self.vbox.pack_start(frame, True, True, 0)
		self.vbox.set_spacing(3)
		self.show_all()
		self.run()

class SearchWindow(Gtk.Box):
	def __init__(self, client):
		Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)

		# adding vars
		self.client=client

		# tag switcher
		self.tags=Gtk.ComboBoxText()

		# search entry
		self.search_entry=Gtk.SearchEntry()

		# label
		self.label=Gtk.Label()
		self.label.set_xalign(1)
		self.label.set_margin_end(6)

		# store
		# (track, title, artist, album, duration, file)
		self.store=Gtk.ListStore(int, str, str, str, str, str)

		# songs view
		self.songs_view=SongsView(self.client, self.store, 5)

		# columns
		renderer_text=Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END, ellipsize_set=True)
		renderer_text_ralign=Gtk.CellRendererText(xalign=1.0)

		self.column_track=Gtk.TreeViewColumn(_("No"), renderer_text_ralign, text=0)
		self.column_track.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_track.set_property("resizable", False)
		self.songs_view.append_column(self.column_track)

		self.column_title=Gtk.TreeViewColumn(_("Title"), renderer_text, text=1)
		self.column_title.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_title.set_property("resizable", False)
		self.column_title.set_property("expand", True)
		self.songs_view.append_column(self.column_title)

		self.column_artist=Gtk.TreeViewColumn(_("Artist"), renderer_text, text=2)
		self.column_artist.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_artist.set_property("resizable", False)
		self.column_artist.set_property("expand", True)
		self.songs_view.append_column(self.column_artist)

		self.column_album=Gtk.TreeViewColumn(_("Album"), renderer_text, text=3)
		self.column_album.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_album.set_property("resizable", False)
		self.column_album.set_property("expand", True)
		self.songs_view.append_column(self.column_album)

		self.column_time=Gtk.TreeViewColumn(_("Length"), renderer_text, text=4)
		self.column_time.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
		self.column_time.set_property("resizable", False)
		self.songs_view.append_column(self.column_time)

		self.column_track.set_sort_column_id(0)
		self.column_title.set_sort_column_id(1)
		self.column_artist.set_sort_column_id(2)
		self.column_album.set_sort_column_id(3)
		self.column_time.set_sort_column_id(4)

		# scroll
		scroll=Gtk.ScrolledWindow()
		scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
		scroll.add(self.songs_view)

		# buttons
		self.add_button=Gtk.Button(image=Gtk.Image(stock=Gtk.STOCK_ADD), label=_("Add"))
		self.add_button.set_sensitive(False)
		self.add_button.set_relief(Gtk.ReliefStyle.NONE)
		self.play_button=Gtk.Button(image=Gtk.Image(stock=Gtk.STOCK_MEDIA_PLAY), label=_("Play"))
		self.play_button.set_sensitive(False)
		self.play_button.set_relief(Gtk.ReliefStyle.NONE)
		self.open_button=Gtk.Button(image=Gtk.Image(stock=Gtk.STOCK_OPEN), label=_("Open"))
		self.open_button.set_sensitive(False)
		self.open_button.set_relief(Gtk.ReliefStyle.NONE)

		# connect
		self.search_entry.connect("search-changed", self.on_search_changed)
		self.tags.connect("changed", self.on_search_changed)
		self.add_button.connect("clicked", self.on_add_clicked)
		self.play_button.connect("clicked", self.on_play_clicked)
		self.open_button.connect("clicked", self.on_open_clicked)
		self.client.emitter.connect("reconnected", self.on_reconnected)

		# packing
		vbox=Gtk.Box(spacing=6)
		vbox.set_property("border-width", 6)
		vbox.pack_start(self.search_entry, True, True, 0)
		vbox.pack_end(self.tags, False, False, 0)
		frame=FocusFrame()
		frame.set_widget(self.songs_view)
		frame.add(scroll)
		ButtonBox=Gtk.ButtonBox(spacing=1)
		ButtonBox.set_property("border-width", 1)
		ButtonBox.pack_start(self.add_button, True, True, 0)
		ButtonBox.pack_start(self.play_button, True, True, 0)
		ButtonBox.pack_start(self.open_button, True, True, 0)
		hbox=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
		hbox.pack_start(ButtonBox, 0, False, False)
		hbox.pack_end(self.label, 0, False, False)
		self.pack_start(vbox, False, False, 0)
		self.pack_start(Gtk.Separator.new(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
		self.pack_start(frame, True, True, 0)
		self.pack_start(Gtk.Separator.new(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
		self.pack_start(hbox, False, False, 0)

	def start(self):
		self.search_entry.grab_focus()

	def started(self):
		return self.search_entry.has_focus()

	def clear(self, *args):
		self.songs_view.clear()
		self.search_entry.set_text("")
		self.tags.remove_all()

	def on_reconnected(self, *args):
		self.tags.append_text("any")
		for tag in self.client.tagtypes():
			if not tag.startswith("MUSICBRAINZ"):
				self.tags.append_text(tag)
		self.tags.set_active(0)

	def on_search_changed(self, widget):
		self.songs_view.clear()
		self.label.set_text("")
		if len(self.search_entry.get_text()) > 1:
			songs=self.client.search(self.tags.get_active_text(), self.search_entry.get_text())
			for s in songs:
				song=ClientHelper.extend_song_for_display(ClientHelper.song_to_str_dict(s))
				self.store.append([int(song["track"]), song["title"], song["artist"], song["album"], song["human_duration"], song["file"]])
			self.label.set_text(_("hits: %i") % (self.songs_view.count()))
		if self.songs_view.count() == 0:
			self.add_button.set_sensitive(False)
			self.play_button.set_sensitive(False)
			self.open_button.set_sensitive(False)
		else:
			self.add_button.set_sensitive(True)
			self.play_button.set_sensitive(True)
			self.open_button.set_sensitive(True)

	def on_add_clicked(self, *args):
		self.client.files_to_playlist(self.songs_view.get_files(), True)

	def on_play_clicked(self, *args):
		self.client.files_to_playlist(self.songs_view.get_files(), False, True)

	def on_open_clicked(self, *args):
		self.client.files_to_playlist(self.songs_view.get_files(), False)

class LyricsWindow(Gtk.Overlay):
	def __init__(self, client, settings):
		Gtk.Overlay.__init__(self)

		# adding vars
		self.settings=settings
		self.client=client

		# widgets
		self.text_view=Gtk.TextView()
		self.text_view.set_editable(False)
		self.text_view.set_left_margin(5)
		self.text_view.set_bottom_margin(5)
		self.text_view.set_cursor_visible(False)
		self.text_view.set_wrap_mode(Gtk.WrapMode.WORD)
		self.text_view.set_justification(Gtk.Justification.CENTER)
		self.text_buffer=self.text_view.get_buffer()

		# scroll
		self.scroll=Gtk.ScrolledWindow()
		self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
		self.scroll.add(self.text_view)

		# frame
		frame=FocusFrame()
		frame.set_widget(self.text_view)
		style_context=frame.get_style_context()
		provider=Gtk.CssProvider()
		css=b"""* {border: 0px; background-color: @theme_base_color; opacity: 0.9;}"""
		provider.load_from_data(css)
		style_context.add_provider(provider, 800)

		# close button
		close_button=Gtk.ToggleButton(image=Gtk.Image.new_from_icon_name("window-close-symbolic", Gtk.IconSize.BUTTON))
		close_button.set_margin_top(6)
		close_button.set_margin_end(6)
		style_context=close_button.get_style_context()
		style_context.add_class("circular")

		close_button.set_halign(2)
		close_button.set_valign(1)

		# connect
		self.file_changed=self.client.emitter.connect("playing_file_changed", self.refresh)
		self.connect("destroy", self.remove_handlers)
		close_button.connect("clicked", self.on_close_button_clicked)

		# packing
		frame.add(self.scroll)
		self.add(frame)
		self.add_overlay(close_button)

		self.show_all()
		self.refresh()
		GLib.idle_add(self.text_view.grab_focus)  # focus textview

	def remove_handlers(self, *args):
		self.client.emitter.disconnect(self.file_changed)

	def display_lyrics(self, current_song):
		GLib.idle_add(self.text_buffer.set_text, _("searching..."), -1)
		try:
			text=self.getLyrics(current_song["artist"], current_song["title"])
		except:
			text=_("lyrics not found")
		GLib.idle_add(self.text_buffer.set_text, text, -1)

	def refresh(self, *args):
		update_thread=threading.Thread(target=self.display_lyrics, kwargs={"current_song": ClientHelper.song_to_first_str_dict(self.client.currentsong())}, daemon=True)
		update_thread.start()

	def getLyrics(self, singer, song):  # partially copied from PyLyrics 1.1.0
		# Replace spaces with _
		singer=singer.replace(' ', '_')
		song=song.replace(' ', '_')
		r=requests.get('http://lyrics.wikia.com/{0}:{1}'.format(singer,song))
		s=BeautifulSoup(r.text)
		# Get main lyrics holder
		lyrics=s.find("div",{'class':'lyricbox'})
		if lyrics is None:
			raise ValueError("Song or Singer does not exist or the API does not have Lyrics")
			return None
		# Remove Scripts
		[s.extract() for s in lyrics('script')]
		# Remove Comments
		comments=lyrics.findAll(text=lambda text:isinstance(text, Comment))
		[comment.extract() for comment in comments]
		# Remove span tag (Needed for instrumantal)
		if not lyrics.span == None:
			lyrics.span.extract()
		# Remove unecessary tags
		for tag in ['div','i','b','a']:
			for match in lyrics.findAll(tag):
				match.replaceWithChildren()
		# Get output as a string and remove non unicode characters and replace <br> with newlines
		output=str(lyrics).encode('utf-8', errors='replace')[22:-6:].decode("utf-8").replace('\n','').replace('<br/>','\n')
		try:
			return output
		except:
			return output.encode('utf-8')

	def on_close_button_clicked(self, *args):
		self.destroy()

class MainWindow(Gtk.ApplicationWindow):
	def __init__(self, app, client, settings):
		Gtk.ApplicationWindow.__init__(self, title=("mpdevil"), application=app)
		Notify.init("mpdevil")
		self.set_icon_name("mpdevil")
		self.settings=settings
		self.set_default_size(self.settings.get_int("width"), self.settings.get_int("height"))

		# adding vars
		self.app=app
		self.client=client
		self.use_csd=self.settings.get_boolean("use-csd")
		if self.use_csd:
			self.icon_size=0
		else:
			self.icon_size=self.settings.get_int("icon-size")

		# MPRIS
		DBusGMainLoop(set_as_default=True)
		self.dbus_service=MPRISInterface(self, self.client, self.settings)

		# actions
		save_action=Gio.SimpleAction.new("save", None)
		save_action.connect("activate", self.on_save)
		self.add_action(save_action)

		settings_action=Gio.SimpleAction.new("settings", None)
		settings_action.connect("activate", self.on_settings)
		self.add_action(settings_action)

		stats_action=Gio.SimpleAction.new("stats", None)
		stats_action.connect("activate", self.on_stats)
		self.add_action(stats_action)

		self.update_action=Gio.SimpleAction.new("update", None)
		self.update_action.connect("activate", self.on_update)
		self.add_action(self.update_action)

		self.help_action=Gio.SimpleAction.new("help", None)
		self.help_action.connect("activate", self.on_help)
		self.add_action(self.help_action)

		# widgets
		self.icons={}
		icons_data=["open-menu-symbolic"]
		for data in icons_data:
			self.icons[data]=PixelSizedIcon(data, self.icon_size)

		self.browser=Browser(self.client, self.settings, self)
		self.cover_playlist_view=CoverPlaylistView(self.client, self.settings, self)
		self.profiles=ProfileSelect(self.client, self.settings)
		self.profiles.set_tooltip_text(_("Select profile"))
		self.control=ClientControl(self.client, self.settings)
		self.progress=SeekBar(self.client)
		self.play_opts=PlaybackOptions(self.client, self.settings)

		# menu
		subsection=Gio.Menu()
		subsection.append(_("Settings"), "win.settings")
		subsection.append(_("Help"), "win.help")
		subsection.append(_("About"), "app.about")
		subsection.append(_("Quit"), "app.quit")

		menu=Gio.Menu()
		menu.append(_("Save window layout"), "win.save")
		menu.append(_("Update database"), "win.update")
		menu.append(_("Server stats"), "win.stats")
		menu.append_section(None, subsection)

		menu_button=Gtk.MenuButton.new()
		menu_popover=Gtk.Popover.new_from_model(menu_button, menu)
		menu_button.set_popover(menu_popover)
		menu_button.set_tooltip_text(_("Menu"))
		menu_button.set_image(image=self.icons["open-menu-symbolic"])

		# connect
		self.settings.connect("changed::profiles", self.on_settings_changed)
		self.settings.connect("changed::playlist-right", self.on_playlist_pos_settings_changed)
		if not self.use_csd:
			self.settings.connect("changed::icon-size", self.on_icon_size_changed)
		self.client.emitter.connect("playing_file_changed", self.on_file_changed)
		self.client.emitter.connect("disconnected", self.on_disconnected)
		self.client.emitter.connect("reconnected", self.on_reconnected)
		# unmap space
		binding_set=Gtk.binding_set_find('GtkTreeView')
		Gtk.binding_entry_remove(binding_set, 32, Gdk.ModifierType.MOD2_MASK)
		# map space play/pause
		self.connect("key-press-event", self.on_key_press_event)

		# packing
		self.paned2=Gtk.Paned()
		self.paned2.set_position(self.settings.get_int("paned2"))
		self.on_playlist_pos_settings_changed()  # set orientation
		self.paned2.pack1(self.browser, True, False)
		self.paned2.pack2(self.cover_playlist_view, False, False)
		self.vbox=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.action_bar=Gtk.ActionBar()
		self.vbox.pack_start(self.paned2, True, True, 0)
		self.vbox.pack_start(self.action_bar, False, False, 0)
		self.action_bar.pack_start(self.control)
		self.action_bar.pack_start(self.progress)
		self.action_bar.pack_start(self.play_opts)

		if self.use_csd:
			self.header_bar=Gtk.HeaderBar()
			self.header_bar.set_show_close_button(True)
			self.header_bar.set_title("mpdevil")
			self.set_titlebar(self.header_bar)
			self.header_bar.pack_start(self.browser.back_to_album_button)
			self.header_bar.pack_start(self.browser.genre_select)
			self.header_bar.pack_end(menu_button)
			self.header_bar.pack_end(self.profiles)
			self.header_bar.pack_end(self.browser.search_button)
		else:
			self.action_bar.pack_start(Gtk.Separator.new(orientation=Gtk.Orientation.VERTICAL))
			self.action_bar.pack_start(self.profiles)
			self.action_bar.pack_start(menu_button)

		self.add(self.vbox)

		self.show_all()
		if self.settings.get_boolean("maximize"):
			self.maximize()
		self.on_settings_changed()  # hide profiles button
		self.client.start()  # connect client

	def on_file_changed(self, *args):
		try:
			song=self.client.currentsong()
			if song == {}:
				raise ValueError("Song out of range")
			song=ClientHelper.extend_song_for_display(ClientHelper.song_to_str_dict(song))
			if song["date"] != "":
				date=" ("+song["date"]+")"
			else:
				date=""
			if self.use_csd:
				self.header_bar.set_title(song["title"]+" - "+song["artist"])
				self.header_bar.set_subtitle(song["album"]+date)
			else:
				self.set_title(song["title"]+" - "+song["artist"]+" - "+song["album"]+date)
			if self.settings.get_boolean("send-notify"):
				if not self.is_active() and self.client.status()["state"] == "play":
					notify=Notify.Notification.new(song["title"], song["artist"]+"\n"+song["album"]+date)
					pixbuf=Cover(lib_path=self.settings.get_value("paths")[self.settings.get_int("active-profile")], song_file=song["file"]).get_pixbuf(400)
					notify.set_image_from_pixbuf(pixbuf)
					notify.show()
		except:
			if self.use_csd:
				self.header_bar.set_title("mpdevil")
				self.header_bar.set_subtitle("")
			else:
				self.set_title("mpdevil")

	def on_reconnected(self, *args):
		self.dbus_service.acquire_name()
		self.progress.set_sensitive(True)
		self.control.set_sensitive(True)
		self.play_opts.set_sensitive(True)
		self.browser.back_to_album()

	def on_disconnected(self, *args):
		self.dbus_service.release_name()
		if self.use_csd:
			self.header_bar.set_title("mpdevil")
			self.header_bar.set_subtitle("(not connected)")
		else:
			self.set_title("mpdevil (not connected)")
		self.songid_playing=None
		self.progress.set_sensitive(False)
		self.control.set_sensitive(False)
		self.play_opts.set_sensitive(False)

	def on_key_press_event(self, widget, event):
		ctrl = (event.state & Gdk.ModifierType.CONTROL_MASK)
		if ctrl:
			if event.keyval == 108:  # ctrl + l
				self.cover_playlist_view.show_lyrics()
		else:
			if event.keyval == 32:  # space
				if not self.browser.search_started():
					self.control.play_button.grab_focus()
			elif event.keyval == 269025044:  # AudioPlay
				self.control.play_button.grab_focus()
				self.control.play_button.emit("clicked")
			elif event.keyval == 269025047:  # AudioNext
				self.control.next_button.grab_focus()
				self.control.next_button.emit("clicked")
			elif event.keyval == 43 or event.keyval == 65451:  # +
				if not self.browser.search_started():
					self.control.next_button.grab_focus()
					self.control.next_button.emit("clicked")
			elif event.keyval == 269025046:  # AudioPrev
				self.control.prev_button.grab_focus()
				self.control.prev_button.emit("clicked")
			elif event.keyval == 45 or event.keyval == 65453:  # -
				if not self.browser.search_started():
					self.control.prev_button.grab_focus()
					self.control.prev_button.emit("clicked")
			elif event.keyval == 65307:  # esc
				self.browser.back_to_album()
			elif event.keyval == 65450:  # *
				if not self.browser.search_started():
					self.progress.scale.grab_focus()
					self.progress.seek_forward()
			elif event.keyval == 65455:  # /
				if not self.browser.search_started():
					self.progress.scale.grab_focus()
					self.progress.seek_backward()
			elif event.keyval == 65474:  # F5
				self.update_action.emit("activate", None)
			elif event.keyval == 65470:  # F1
				self.help_action.emit("activate", None)

	def on_save(self, action, param):
		size=self.get_size()
		self.settings.set_int("width", size[0])
		self.settings.set_int("height", size[1])
		self.settings.set_boolean("maximize", self.is_maximized())
		self.browser.save_settings()
		self.cover_playlist_view.save_settings()
		self.settings.set_int("paned2", self.paned2.get_position())

	def on_settings(self, action, param):
		settings=SettingsDialog(self, self.settings)
		settings.run()
		settings.destroy()

	def on_stats(self, action, param):
		if self.client.connected():
			stats=ServerStats(self, self.client)
			stats.destroy()

	def on_update(self, action, param):
		if self.client.connected():
			self.client.update()

	def on_help(self, action, param):
		Gtk.show_uri_on_window(self, "https://github.com/SoongNoonien/mpdevil/wiki/Usage", Gdk.CURRENT_TIME)

	def on_settings_changed(self, *args):
		if len(self.settings.get_value("profiles")) > 1:
			self.profiles.set_property("visible", True)
		else:
			self.profiles.set_property("visible", False)

	def on_playlist_pos_settings_changed(self, *args):
		if self.settings.get_boolean("playlist-right"):
			self.cover_playlist_view.set_orientation(Gtk.Orientation.VERTICAL)
			self.paned2.set_orientation(Gtk.Orientation.HORIZONTAL)
		else:
			self.cover_playlist_view.set_orientation(Gtk.Orientation.HORIZONTAL)
			self.paned2.set_orientation(Gtk.Orientation.VERTICAL)

	def on_icon_size_changed(self, *args):
		pixel_size=self.settings.get_int("icon-size")
		for icon in self.icons.values():
			icon.set_pixel_size(pixel_size)

class mpdevil(Gtk.Application):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, application_id="org.mpdevil", flags=Gio.ApplicationFlags.FLAGS_NONE, **kwargs)
		self.settings=Settings()
		self.client=Client(self.settings)
		self.window=None

	def do_activate(self):
		if not self.window:  # allow just one instance
			self.window=MainWindow(self, self.client, self.settings)
			self.window.connect("delete-event", self.on_delete_event)
		self.window.present()

	def do_startup(self):
		Gtk.Application.do_startup(self)

		action=Gio.SimpleAction.new("about", None)
		action.connect("activate", self.on_about)
		self.add_action(action)

		action=Gio.SimpleAction.new("quit", None)
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
		dialog.set_copyright("\xa9 2020 Martin Wagner")
		dialog.set_logo_icon_name(PACKAGE)
		dialog.run()
		dialog.destroy()

	def on_quit(self, action, param):
		if self.settings.get_boolean("stop-on-quit") and self.client.connected():
			self.client.stop()
		self.quit()

if __name__ == '__main__':
	app=mpdevil()
	app.run(sys.argv)

