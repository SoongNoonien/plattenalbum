#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# mpdevil - MPD Client.
# Copyright (C) 2020-2022 Martin Wagner <martin.wagner.dev@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Notify", "0.7")
from gi.repository import Gtk, Gio, Gdk, GdkPixbuf, Pango, GObject, GLib, Notify
from mpd import MPDClient, base as MPDBase
import requests
from bs4 import BeautifulSoup
import threading
import functools
import datetime
import collections
import os
import sys
import re
import locale
from gettext import gettext as _, ngettext, textdomain, bindtextdomain

try:
	locale.setlocale(locale.LC_ALL, "")
except locale.Error as e:
	print(e)
locale.bindtextdomain("mpdevil", "@LOCALE_DIR@")
locale.textdomain("mpdevil")
bindtextdomain("mpdevil", localedir="@LOCALE_DIR@")
textdomain("mpdevil")
Gio.Resource._register(Gio.resource_load(os.path.join("@RESOURCES_DIR@", "mpdevil.gresource")))

COVER_REGEX=r"^\.?(album|cover|folder|front).*\.(gif|jpeg|jpg|png)$"
FALLBACK_COVER=Gtk.IconTheme.get_default().lookup_icon("media-optical", 128, Gtk.IconLookupFlags.FORCE_SVG).get_filename()
FALLBACK_SOCKET=os.path.join(GLib.get_user_runtime_dir(), "mpd/socket")
FALLBACK_LIB=GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_MUSIC)

##############
# Decorators #
##############

def main_thread_function(func):
	@functools.wraps(func)
	def wrapper_decorator(*args, **kwargs):
		def glib_callback(event, result, *args, **kwargs):
			try:
				result.append(func(*args, **kwargs))
			except Exception as e:  # handle exceptions to avoid deadlocks
				result.append(e)
			event.set()
			return False
		event=threading.Event()
		result=[]
		GLib.idle_add(glib_callback, event, result, *args, **kwargs)
		event.wait()
		if isinstance(result[0], Exception):
			raise result[0]
		else:
			return result[0]
	return wrapper_decorator

#########
# MPRIS #
#########

class MPRISInterface:  # TODO emit Seeked if needed
	"""
	based on 'Lollypop' (master 22.12.2020) by Cedric Bellegarde <cedric.bellegarde@adishatz.org>
	and 'mpDris2' (master 19.03.2020) by Jean-Philippe Braun <eon@patapon.info>, Mantas Mikulėnas <grawity@gmail.com>
	"""
	_MPRIS_IFACE="org.mpris.MediaPlayer2"
	_MPRIS_PLAYER_IFACE="org.mpris.MediaPlayer2.Player"
	_MPRIS_NAME="org.mpris.MediaPlayer2.mpdevil"
	_MPRIS_PATH="/org/mpris/MediaPlayer2"
	_INTERFACES_XML="""
	<!DOCTYPE node PUBLIC
	"-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
	"http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
	<node>
		<interface name="org.freedesktop.DBus.Introspectable">
			<method name="Introspect">
				<arg name="data" direction="out" type="s"/>
			</method>
		</interface>
		<interface name="org.freedesktop.DBus.Properties">
			<method name="Get">
				<arg name="interface" direction="in" type="s"/>
				<arg name="property" direction="in" type="s"/>
				<arg name="value" direction="out" type="v"/>
			</method>
			<method name="Set">
				<arg name="interface_name" direction="in" type="s"/>
				<arg name="property_name" direction="in" type="s"/>
				<arg name="value" direction="in" type="v"/>
			</method>
			<method name="GetAll">
				<arg name="interface" direction="in" type="s"/>
				<arg name="properties" direction="out" type="a{sv}"/>
			</method>
		</interface>
		<interface name="org.mpris.MediaPlayer2">
			<method name="Raise">
			</method>
			<method name="Quit">
			</method>
			<property name="CanQuit" type="b" access="read" />
			<property name="CanRaise" type="b" access="read" />
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
			<property name="PlaybackStatus" type="s" access="read"/>
			<property name="LoopStatus" type="s" access="readwrite"/>
			<property name="Rate" type="d" access="readwrite"/>
			<property name="Shuffle" type="b" access="readwrite"/>
			<property name="Metadata" type="a{sv}" access="read"/>
			<property name="Volume" type="d" access="readwrite"/>
			<property name="Position" type="x" access="read"/>
			<property name="MinimumRate" type="d" access="read"/>
			<property name="MaximumRate" type="d" access="read"/>
			<property name="CanGoNext" type="b" access="read"/>
			<property name="CanGoPrevious" type="b" access="read"/>
			<property name="CanPlay" type="b" access="read"/>
			<property name="CanPause" type="b" access="read"/>
			<property name="CanSeek" type="b" access="read"/>
			<property name="CanControl" type="b" access="read"/>
		</interface>
	</node>
	"""

	def __init__(self, window, client, settings):
		self._window=window
		self._client=client
		self._settings=settings
		self._metadata={}

		# MPRIS property mappings
		self._prop_mapping={
			self._MPRIS_IFACE:
				{"CanQuit": (GLib.Variant("b", False), None),
				"CanRaise": (GLib.Variant("b", True), None),
				"HasTrackList": (GLib.Variant("b", False), None),
				"Identity": (GLib.Variant("s", "mpdevil"), None),
				"DesktopEntry": (GLib.Variant("s", "org.mpdevil.mpdevil"), None),
				"SupportedUriSchemes": (GLib.Variant("s", "None"), None),
				"SupportedMimeTypes": (GLib.Variant("s", "None"), None)},
			self._MPRIS_PLAYER_IFACE:
				{"PlaybackStatus": (self._get_playback_status, None),
				"LoopStatus": (self._get_loop_status, self._set_loop_status),
				"Rate": (GLib.Variant("d", 1.0), None),
				"Shuffle": (self._get_shuffle, self._set_shuffle),
				"Metadata": (self._get_metadata, None),
				"Volume": (self._get_volume, self._set_volume),
				"Position": (self._get_position, None),
				"MinimumRate": (GLib.Variant("d", 1.0), None),
				"MaximumRate": (GLib.Variant("d", 1.0), None),
				"CanGoNext": (self._get_can_next_prev, None),
				"CanGoPrevious": (self._get_can_next_prev, None),
				"CanPlay": (self._get_can_play_pause_seek, None),
				"CanPause": (self._get_can_play_pause_seek, None),
				"CanSeek": (self._get_can_play_pause_seek, None),
				"CanControl": (GLib.Variant("b", True), None)},
		}

		# start
		self._bus=Gio.bus_get_sync(Gio.BusType.SESSION, None)
		Gio.bus_own_name_on_connection(self._bus, self._MPRIS_NAME, Gio.BusNameOwnerFlags.NONE, None, None)
		self._node_info=Gio.DBusNodeInfo.new_for_xml(self._INTERFACES_XML)
		for interface in self._node_info.interfaces:
			self._bus.register_object(self._MPRIS_PATH, interface, self._handle_method_call, None, None)

		# connect
		self._client.emitter.connect("state", self._on_state_changed)
		self._client.emitter.connect("current_song", self._on_song_changed)
		self._client.emitter.connect("volume", self._on_volume_changed)
		self._client.emitter.connect("repeat", self._on_loop_changed)
		self._client.emitter.connect("single", self._on_loop_changed)
		self._client.emitter.connect("random", self._on_random_changed)
		self._client.emitter.connect("connection_error", self._on_connection_error)
		self._client.emitter.connect("reconnected", self._on_reconnected)

	def _handle_method_call(self, connection, sender, object_path, interface_name, method_name, parameters, invocation):
		args=list(parameters.unpack())
		result=getattr(self, method_name)(*args)
		out_args=self._node_info.lookup_interface(interface_name).lookup_method(method_name).out_args
		if out_args:
			signature="("+"".join([arg.signature for arg in out_args])+")"
			variant=GLib.Variant(signature, (result,))
			invocation.return_value(variant)
		else:
			invocation.return_value(None)

	# setter and getter
	def _get_playback_status(self):
		if self._client.connected():
			status=self._client.status()
			return GLib.Variant("s", {"play": "Playing", "pause": "Paused", "stop": "Stopped"}[status["state"]])
		return GLib.Variant("s", "Stopped")

	def _set_loop_status(self, value):
		if self._client.connected():
			if value == "Playlist":
				self._client.repeat(1)
				self._client.single(0)
			elif value == "Track":
				self._client.repeat(1)
				self._client.single(1)
			elif value == "None":
				self._client.repeat(0)
				self._client.single(0)

	def _get_loop_status(self):
		if self._client.connected():
			status=self._client.status()
			if status["repeat"] == "1":
				if status.get("single", "0") == "0":
					return GLib.Variant("s", "Playlist")
				else:
					return GLib.Variant("s", "Track")
			else:
				return GLib.Variant("s", "None")
		return GLib.Variant("s", "None")

	def _set_shuffle(self, value):
		if self._client.connected():
			if value:
				self._client.random("1")
			else:
				self._client.random("0")

	def _get_shuffle(self):
		if self._client.connected():
			if self._client.status()["random"] == "1":
				return GLib.Variant("b", True)
			else:
				return GLib.Variant("b", False)
		return GLib.Variant("b", False)

	def _get_metadata(self):
		return GLib.Variant("a{sv}", self._metadata)

	def _get_volume(self):
		if self._client.connected():
			return GLib.Variant("d", float(self._client.status().get("volume", 0))/100)
		return GLib.Variant("d", 0)

	def _set_volume(self, value):
		if self._client.connected():
			if value >= 0 and value <= 1:
				self._client.setvol(int(value * 100))

	def _get_position(self):
		if self._client.connected():
			status=self._client.status()
			return GLib.Variant("x", float(status.get("elapsed", 0))*1000000)
		return GLib.Variant("x", 0)

	def _get_can_next_prev(self):
		if self._client.connected():
			status=self._client.status()
			if status["state"] == "stop":
				return GLib.Variant("b", False)
			else:
				return GLib.Variant("b", True)
		return GLib.Variant("b", False)

	def _get_can_play_pause_seek(self):
		return GLib.Variant("b", self._client.connected())

	# introspect methods
	def Introspect(self):
		return self._INTERFACES_XML

	# property methods
	def Get(self, interface_name, prop):
		getter, setter=self._prop_mapping[interface_name][prop]
		if callable(getter):
			return getter()
		return getter

	def Set(self, interface_name, prop, value):
		getter, setter=self._prop_mapping[interface_name][prop]
		if setter is not None:
			setter(value)

	def GetAll(self, interface_name):
		read_props={}
		try:
			props=self._prop_mapping[interface_name]
			for key, (getter, setter) in props.items():
				if callable(getter):
					getter=getter()
				read_props[key]=getter
		except KeyError:  # interface has no properties
			pass
		return read_props

	def PropertiesChanged(self, interface_name, changed_properties, invalidated_properties):
		self._bus.emit_signal(
			None, self._MPRIS_PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
			GLib.Variant.new_tuple(
				GLib.Variant("s", interface_name),
				GLib.Variant("a{sv}", changed_properties),
				GLib.Variant("as", invalidated_properties)
			)
		)

	# root methods
	def Raise(self):
		self._window.present()

	def Quit(self):
		app_action_group=self._window.get_action_group("app")
		quit_action=app_action_group.lookup_action("quit")
		quit_action.activate()

	# player methods
	def Next(self):
		self._client.next()

	def Previous(self):
		self._client.conditional_previous()

	def Pause(self):
		self._client.pause(1)

	def PlayPause(self):
		self._client.toggle_play()

	def Stop(self):
		self._client.stop()

	def Play(self):
		self._client.play()

	def Seek(self, offset):
		if offset > 0:
			offset="+"+str(offset/1000000)
		else:
			offset=str(offset/1000000)
		self._client.seekcur(offset)

	def SetPosition(self, trackid, position):
		song=self._client.currentsong()
		if str(trackid).split("/")[-1] != song["id"]:
			return
		mpd_pos=position/1000000
		if mpd_pos >= 0 and mpd_pos <= float(song["duration"]):
			self._client.seekcur(str(mpd_pos))

	def OpenUri(self, uri):
		pass

	def Seeked(self, position):
		self._bus.emit_signal(
			None, self._MPRIS_PATH, self._MPRIS_PLAYER_IFACE, "Seeked",
			GLib.Variant.new_tuple(GLib.Variant("x", position))
		)

	# other methods
	def _update_metadata(self):
		"""
		Translate metadata returned by MPD to the MPRIS v2 syntax.
		http://www.freedesktop.org/wiki/Specifications/mpris-spec/metadata
		"""
		song=self._client.currentsong()
		self._metadata={}
		for tag, xesam_tag in (("album","album"),("title","title"),("date","contentCreated")):
			if tag in song:
				self._metadata[f"xesam:{xesam_tag}"]=GLib.Variant("s", song[tag][0])
		for tag, xesam_tag in (("track","trackNumber"),("disc","discNumber")):
			if tag in song:
				self._metadata[f"xesam:{xesam_tag}"]=GLib.Variant("i", int(song[tag][0]))
		for tag, xesam_tag in (("albumartist","albumArtist"),("artist","artist"),("composer","composer"),("genre","genre")):
			if tag in song:
				self._metadata[f"xesam:{xesam_tag}"]=GLib.Variant("as", song[tag])
		if "id" in song:
			self._metadata["mpris:trackid"]=GLib.Variant("o", f"{self._MPRIS_PATH}/Track/{song['id']}")
		if "duration" in song:
			self._metadata["mpris:length"]=GLib.Variant("x", float(song["duration"])*1000000)
		if "file" in song:
			song_file=song["file"]
			if "://" in song_file:  # remote file
				self._metadata["xesam:url"]=GLib.Variant("s", song_file)
			else:
				song_path=self._client.get_absolute_path(song_file)
				if song_path is not None:
					self._metadata["xesam:url"]=GLib.Variant("s", f"file://{song_path}")
				cover_path=self._client.get_cover_path(song)
				if cover_path is not None:
					self._metadata["mpris:artUrl"]=GLib.Variant("s", f"file://{cover_path}")

	def _update_property(self, interface_name, prop):
		getter, setter=self._prop_mapping[interface_name][prop]
		if callable(getter):
			value=getter()
		else:
			value=getter
		self.PropertiesChanged(interface_name, {prop: value}, [])
		return value

	def _on_state_changed(self, *args):
		self._update_property(self._MPRIS_PLAYER_IFACE, "PlaybackStatus")
		self._update_property(self._MPRIS_PLAYER_IFACE, "CanGoNext")
		self._update_property(self._MPRIS_PLAYER_IFACE, "CanGoPrevious")

	def _on_song_changed(self, *args):
		self._update_metadata()
		self._update_property(self._MPRIS_PLAYER_IFACE, "Metadata")

	def _on_volume_changed(self, *args):
		self._update_property(self._MPRIS_PLAYER_IFACE, "Volume")

	def _on_loop_changed(self, *args):
		self._update_property(self._MPRIS_PLAYER_IFACE, "LoopStatus")

	def _on_random_changed(self, *args):
		self._update_property(self._MPRIS_PLAYER_IFACE, "Shuffle")

	def _on_reconnected(self, *args):
		properties=("CanPlay","CanPause","CanSeek")
		for p in properties:
			self._update_property(self._MPRIS_PLAYER_IFACE, p)

	def _on_connection_error(self, *args):
		self._metadata={}
		properties=("PlaybackStatus","CanGoNext","CanGoPrevious","Metadata","Volume","LoopStatus","Shuffle","CanPlay","CanPause","CanSeek")
		for p in properties:
			self._update_property(self._MPRIS_PLAYER_IFACE, p)

######################
# MPD client wrapper #
######################

class Duration():
	def __init__(self, value=None):
		if value is None:
			self._fallback=True
			self._value=0.0
		else:
			self._fallback=False
			self._value=float(value)

	def __str__(self):
		if self._fallback:
			return "‒‒∶‒‒"
		else:
			if self._value < 0:
				sign="−"
				value=-int(self._value)
			else:
				sign=""
				value=int(self._value)
			delta=datetime.timedelta(seconds=value)
			if delta.days > 0:
				days=ngettext("{days} day", "{days} days", delta.days).format(days=delta.days)
				time_string=f"{days}, {datetime.timedelta(seconds=delta.seconds)}"
			else:
				time_string=str(delta).lstrip("0").lstrip(":")
			return sign+time_string.replace(":", "∶")  # use 'ratio' as delimiter

	def __float__(self):
		return self._value

class LastModified():
	def __init__(self, date):
		self._date=date

	def __str__(self):
		time=datetime.datetime.strptime(self._date, "%Y-%m-%dT%H:%M:%SZ")
		return time.strftime("%a %d %B %Y, %H∶%M UTC")

	def raw(self):
		return self._date

class Format():
	def __init__(self, audio_format):
		self._format=audio_format

	def __str__(self):
		# see: https://www.musicpd.org/doc/html/user.html#audio-output-format
		samplerate, bits, channels=self._format.split(":")
		if bits == "f":
			bits="32fp"
		try:
			int_chan=int(channels)
		except ValueError:
			int_chan=0
		try:
			freq=locale.str(int(samplerate)/1000)
		except ValueError:
			freq=samplerate
		channels=ngettext("{channels} channel", "{channels} channels", int_chan).format(channels=int_chan)
		return f"{freq} kHz • {bits} bit • {channels}"

	def raw(self):
		return self._format

class MultiTag(list):
	def __str__(self):
		return ", ".join(self)

class Song(collections.UserDict):
	def __setitem__(self, key, value):
		if key == "time":  # time is deprecated https://mpd.readthedocs.io/en/latest/protocol.html#other-metadata
			pass
		elif key == "duration":
			super().__setitem__(key, Duration(value))
		elif key == "format":
			super().__setitem__(key, Format(value))
		elif key == "last-modified":
			super().__setitem__(key, LastModified(value))
		elif key in ("range", "file", "pos", "id"):
			super().__setitem__(key, value)
		else:
			if isinstance(value, list):
				super().__setitem__(key, MultiTag(value))
			else:
				super().__setitem__(key, MultiTag([value]))

	def __missing__(self, key):
		if self.data:
			if key == "albumartist":
				return self["artist"]
			elif key == "albumartistsort":
				return self["albumartist"]
			elif key == "artistsort":
				return self["artist"]
			elif key == "albumsort":
				return self["album"]
			elif key == "title":
				return MultiTag([os.path.basename(self.data["file"])])
			elif key == "duration":
				return Duration()
			else:
				return MultiTag([""])
		else:
			return None

class BinaryCover(bytes):
	def get_pixbuf(self, size):
		loader=GdkPixbuf.PixbufLoader()
		try:
			loader.write(self)
			loader.close()
			raw_pixbuf=loader.get_pixbuf()
			ratio=raw_pixbuf.get_width()/raw_pixbuf.get_height()
			if ratio > 1:
				pixbuf=raw_pixbuf.scale_simple(size,size/ratio,GdkPixbuf.InterpType.BILINEAR)
			else:
				pixbuf=raw_pixbuf.scale_simple(size*ratio,size,GdkPixbuf.InterpType.BILINEAR)
		except gi.repository.GLib.Error:  # load fallback if cover can't be loaded
			pixbuf=GdkPixbuf.Pixbuf.new_from_file_at_size(FALLBACK_COVER, size, size)
		return pixbuf

class FileCover(str):
	def get_pixbuf(self, size):
		try:
			pixbuf=GdkPixbuf.Pixbuf.new_from_file_at_size(self, size, size)
		except gi.repository.GLib.Error:  # load fallback if cover can't be loaded
			pixbuf=GdkPixbuf.Pixbuf.new_from_file_at_size(FALLBACK_COVER, size, size)
		return pixbuf

class EventEmitter(GObject.Object):
	__gsignals__={
		"updating_db": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"updated_db": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"disconnected": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"reconnected": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"connection_error": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"current_song": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"state": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
		"elapsed": (GObject.SignalFlags.RUN_FIRST, None, (float,float,)),
		"volume": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
		"playlist": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
		"repeat": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
		"random": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
		"single": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
		"consume": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
		"audio": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
		"bitrate": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
	}

class Client(MPDClient):
	def __init__(self, settings):
		super().__init__()
		self._settings=settings
		self.emitter=EventEmitter()
		self._last_status={}
		self._refresh_interval=self._settings.get_int("refresh-interval")
		self._main_timeout_id=None
		self.lib_path=None

		# connect
		self._settings.connect("changed::active-profile", self._on_active_profile_changed)

	# workaround for list group
	# see: https://github.com/Mic92/python-mpd2/pull/187
	def _parse_objects(self, lines, delimiters=[], lookup_delimiter=False):
		obj = {}
		for key, value in self._parse_pairs(lines):
			key = key.lower()
			if lookup_delimiter and key not in delimiters:
				delimiters = delimiters + [key]
			if obj:
				if key in delimiters:
					if lookup_delimiter:
						if key in obj:
							yield obj
							obj = obj.copy()
							while delimiters[-1] != key:
								obj.pop(delimiters[-1], None)
								delimiters.pop()
					else:
						yield obj
						obj = {}
				elif key in obj:
					if not isinstance(obj[key], list):
						obj[key] = [obj[key], value]
					else:
						obj[key].append(value)
					continue
			obj[key] = value
		if obj:
			yield obj
	_parse_objects_direct = _parse_objects

	# overloads
	def currentsong(self, *args):
		return Song(super().currentsong(*args))
	def search(self, *args):
		return [Song(song) for song in super().search(*args)]
	def find(self, *args):
		return [Song(song) for song in super().find(*args)]
	def playlistinfo(self):
		return [Song(song) for song in super().playlistinfo()]
	def plchanges(self, version):
		return [Song(song) for song in super().plchanges(version)]
	def lsinfo(self, uri):
		return [Song(song) for song in super().lsinfo(uri)]

	def start(self):
		self.emitter.emit("disconnected")  # bring player in defined state
		profile=self._settings.get_active_profile()
		if profile.get_boolean("socket-connection"):
			socket=profile.get_string("socket")
			if not socket:
				socket=FALLBACK_SOCKET
			args=(socket, None)
		else:
			args=(profile.get_string("host"), profile.get_int("port"))
		try:
			self.connect(*args)
			if profile.get_string("password"):
				self.password(profile.get_string("password"))
		except:
			self.emitter.emit("connection_error")
			return False
		# connect successful
		if profile.get_boolean("socket-connection"):
			self.lib_path=self.config()
		else:
			self.lib_path=self._settings.get_active_profile().get_string("path")
			if not self.lib_path:
				self.lib_path=FALLBACK_LIB
		if "status" in self.commands():
			self._main_timeout_id=GLib.timeout_add(self._refresh_interval, self._main_loop)
			self.emitter.emit("reconnected")
			return True
		else:
			self.disconnect()
			self.emitter.emit("connection_error")
			print("No read permission, check your mpd config.")
			return False

	def reconnect(self):
		if self._main_timeout_id is not None:
			GLib.source_remove(self._main_timeout_id)
			self._main_timeout_id=None
		self._last_status={}
		self.disconnect()
		self.start()

	def connected(self):
		try:
			self.ping()
			return True
		except:
			return False

	def _to_playlist(self, append, mode="default"):  # modes: default, play, append, enqueue
		if mode == "default":
			if self._settings.get_boolean("force-mode"):
				mode="play"
			else:
				mode="enqueue"
		if mode == "append":
			append()
		elif mode == "play":
			self.clear()
			append()
			self.play()
		elif mode == "enqueue":
			status=self.status()
			if status["state"] == "stop":
				self.clear()
				append()
			else:
				self.moveid(status["songid"], 0)
				current_song_file=self.currentsong()["file"]
				try:
					self.delete((1,))  # delete all songs, but the first. bad song index possible
				except MPDBase.CommandError:
					pass
				append()
				duplicates=self.playlistfind("file", current_song_file)
				if len(duplicates) > 1:
					self.move(0, duplicates[1]["pos"])
					self.delete(int(duplicates[1]["pos"])-1)


	def files_to_playlist(self, files, mode="default"):
		def append():
			for f in files:
				self.add(f)
		self._to_playlist(append, mode)

	def filter_to_playlist(self, tag_filter, mode="default"):
		def append():
			if tag_filter:
				self.findadd(*tag_filter)
			else:
				self.searchadd("any", "")
		self._to_playlist(append, mode)

	def album_to_playlist(self, albumartist, albumartistsort, album, albumsort, date, mode="default"):
		tag_filter=("albumartist", albumartist, "albumartistsort", albumartistsort, "album", album, "albumsort", albumsort, "date", date)
		self.filter_to_playlist(tag_filter, mode)

	def artist_to_playlist(self, artist, genre, mode="default"):
		def append():
			if genre is None:
				genre_filter=()
			else:
				genre_filter=("genre", genre)
			if artist is None:
				artists=self.get_artists(genre)
			else:
				artists=[artist]
			for albumartist, albumartistsort in artists:
				albums=self.list(
					"album", "albumartist", albumartist, "albumartistsort", albumartistsort,
					*genre_filter, "group", "date", "group", "albumsort")
				for album in albums:
					self.findadd("albumartist", albumartist, "albumartistsort", albumartistsort,
						"album", album["album"], "albumsort", album["albumsort"], "date", album["date"])
		self._to_playlist(append, mode)

	def comp_list(self, *args):  # simulates listing behavior of python-mpd2 1.0
		native_list=self.list(*args)
		if len(native_list) > 0:
			if isinstance(native_list[0], dict):
				return ([l[args[0]] for l in native_list])
			else:
				return native_list
		else:
			return([])

	def get_artists(self, genre):
		if genre is None:
			artists=self.list("albumartist", "group", "albumartistsort")
		else:
			artists=self.list("albumartist", "genre", genre, "group", "albumartistsort")
		return [(artist["albumartist"], artist["albumartistsort"]) for artist in artists]

	def get_cover_path(self, song):
		path=None
		song_file=song["file"]
		profile=self._settings.get_active_profile()
		if self.lib_path is not None:
			regex_str=profile.get_string("regex")
			if regex_str:
				regex_str=regex_str.replace("%AlbumArtist%", re.escape(song["albumartist"][0]))
				regex_str=regex_str.replace("%Album%", re.escape(song["album"][0]))
				try:
					regex=re.compile(regex_str, flags=re.IGNORECASE)
				except re.error:
					print("illegal regex:", regex_str)
					return None
			else:
				regex=re.compile(COVER_REGEX, flags=re.IGNORECASE)
			song_dir=os.path.join(self.lib_path, os.path.dirname(song_file))
			if song_dir.lower().endswith(".cue"):
				song_dir=os.path.dirname(song_dir)  # get actual directory of .cue file
			if os.path.isdir(song_dir):
				for f in os.listdir(song_dir):
					if regex.match(f):
						path=os.path.join(song_dir, f)
						break
		return path

	def get_cover_binary(self, uri):
		try:
			binary=self.albumart(uri)["binary"]
		except:
			try:
				binary=self.readpicture(uri)["binary"]
			except:
				binary=None
		return binary

	def get_cover(self, song):
		cover_path=self.get_cover_path(song)
		if cover_path is None:
			cover_binary=self.get_cover_binary(song["file"])
			if cover_binary is None:
				cover=FileCover(FALLBACK_COVER)
			else:
				cover=BinaryCover(cover_binary)
		else:
			cover=FileCover(cover_path)
		return cover

	def get_absolute_path(self, uri):
		if self.lib_path is not None:
			path=os.path.join(self.lib_path, uri)
			if os.path.isfile(path):
				return path
			else:
				return None
		else:
			return None

	def toggle_play(self):
		status=self.status()
		if status["state"] == "play":
			self.pause(1)
		elif status["state"] == "pause":
			self.pause(0)
		else:
			try:
				self.play()
			except:
				pass

	def toggle_option(self, option):  # repeat, random, single, consume
		new_state=int(self.status()[option] == "0")
		func=getattr(self, option)
		func(new_state)

	def conditional_previous(self):
		if self._settings.get_boolean("rewind-mode"):
			double_click_time=Gtk.Settings.get_default().get_property("gtk-double-click-time")
			status=self.status()
			if float(status.get("elapsed", 0))*1000 > double_click_time:
				self.seekcur(0)
			else:
				self.previous()
		else:
			self.previous()

	def restrict_tagtypes(self, *tags):
		self.command_list_ok_begin()
		self.tagtypes("clear")
		for tag in tags:
			self.tagtypes("enable", tag)
		self.command_list_end()

	def _main_loop(self, *args):
		try:
			status=self.status()
			diff=set(status.items())-set(self._last_status.items())
			for key, val in diff:
				if key == "elapsed":
					if "duration" in status:
						self.emitter.emit("elapsed", float(val), float(status["duration"]))
					else:
						self.emitter.emit("elapsed", float(val), 0.0)
				elif key == "bitrate":
					if val == "0":
						self.emitter.emit("bitrate", None)
					else:
						self.emitter.emit("bitrate", val)
				elif key == "songid":
					self.emitter.emit("current_song")
				elif key in ("state", "single", "audio"):
					self.emitter.emit(key, val)
				elif key == "volume":
					self.emitter.emit("volume", float(val))
				elif key == "playlist":
					self.emitter.emit("playlist", int(val))
				elif key in ("repeat", "random", "consume"):
					if val == "1":
						self.emitter.emit(key, True)
					else:
						self.emitter.emit(key, False)
				elif key == "updating_db":
					self.emitter.emit("updating_db")
			diff=set(self._last_status)-set(status)
			for key in diff:
				if "songid" == key:
					self.emitter.emit("current_song")
				elif "volume" == key:
					self.emitter.emit("volume", -1)
				elif "updating_db" == key:
					self.emitter.emit("updated_db")
				elif "bitrate" == key:
					self.emitter.emit("bitrate", None)
				elif "audio" == key:
					self.emitter.emit("audio", None)
			self._last_status=status
		except (MPDBase.ConnectionError, ConnectionResetError) as e:
			self.disconnect()
			self._last_status={}
			self.emitter.emit("disconnected")
			self.emitter.emit("connection_error")
			self._main_timeout_id=None
			return False
		return True

	def _on_active_profile_changed(self, *args):
		self.reconnect()

########################
# gio settings wrapper #
########################

class Settings(Gio.Settings):
	BASE_KEY="org.mpdevil.mpdevil"
	# temp settings
	cursor_watch=GObject.Property(type=bool, default=False)
	def __init__(self):
		super().__init__(schema=self.BASE_KEY)
		self._profiles=(self.get_child("profile1"), self.get_child("profile2"), self.get_child("profile3"))

	def array_append(self, vtype, key, value):  # append to Gio.Settings array
		array=self.get_value(key).unpack()
		array.append(value)
		self.set_value(key, GLib.Variant(vtype, array))

	def array_delete(self, vtype, key, pos):  # delete entry of Gio.Settings array
		array=self.get_value(key).unpack()
		array.pop(pos)
		self.set_value(key, GLib.Variant(vtype, array))

	def array_modify(self, vtype, key, pos, value):  # modify entry of Gio.Settings array
		array=self.get_value(key).unpack()
		array[pos]=value
		self.set_value(key, GLib.Variant(vtype, array))

	def get_profile(self, num):
		return self._profiles[num]

	def get_active_profile(self):
		return self.get_profile(self.get_int("active-profile"))

###################
# settings dialog #
###################

class ToggleRow(Gtk.ListBoxRow):
	def __init__(self, label, settings, key, restart_required=False):
		super().__init__()
		label=Gtk.Label(label=label, xalign=0, valign=Gtk.Align.CENTER, margin=6)
		self._switch=Gtk.Switch(halign=Gtk.Align.END, valign=Gtk.Align.CENTER, margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
		settings.bind(key, self._switch, "active", Gio.SettingsBindFlags.DEFAULT)
		box=Gtk.Box()
		box.pack_start(label, False, False, 0)
		box.pack_end(self._switch, False, False, 0)
		if restart_required:
			box.pack_end(Gtk.Label(label=_("(restart required)"), margin=6, sensitive=False), False, False, 0)
		self.add(box)

	def toggle(self):
		self._switch.set_active(not self._switch.get_active())

class IntRow(Gtk.ListBoxRow):
	def __init__(self, label, vmin, vmax, step, settings, key):
		super().__init__(activatable=False)
		label=Gtk.Label(label=label, xalign=0, valign=Gtk.Align.CENTER, margin=6)
		spin_button=Gtk.SpinButton.new_with_range(vmin, vmax, step)
		spin_button.set_valign(Gtk.Align.CENTER)
		spin_button.set_halign(Gtk.Align.END)
		spin_button.set_margin_end(12)
		spin_button.set_margin_start(12)
		spin_button.set_margin_top(6)
		spin_button.set_margin_bottom(6)
		settings.bind(key, spin_button, "value", Gio.SettingsBindFlags.DEFAULT)
		box=Gtk.Box()
		box.pack_start(label, False, False, 0)
		box.pack_end(spin_button, False, False, 0)
		self.add(box)

class SettingsList(Gtk.Frame):
	def __init__(self):
		super().__init__(border_width=18, valign=Gtk.Align.START)
		self._list_box=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
		self._list_box.set_header_func(self._header_func)
		self._list_box.connect("row-activated", self._on_row_activated)
		self.add(self._list_box)

	def append(self, row):
		self._list_box.insert(row, -1)

	def _header_func(self, row, before, *args):
		if before is not None:
			row.set_header(Gtk.Separator())

	def _on_row_activated(self, list_box, row):
		if isinstance(row, ToggleRow):
			row.toggle()

class ViewSettings(SettingsList):
	def __init__(self, settings):
		super().__init__()
		toggle_data=[
			(_("Use Client-side decoration"), "use-csd", True),
			(_("Show stop button"), "show-stop", False),
			(_("Show audio format"), "show-audio-format", False),
			(_("Show lyrics button"), "show-lyrics-button", False),
			(_("Place playlist at the side"), "playlist-right", False),
		]
		for label, key, restart_required in toggle_data:
			row=ToggleRow(label, settings, key, restart_required)
			self.append(row)
		int_data=[
			(_("Main cover size"), (100, 1200, 10), "track-cover"),
			(_("Album view cover size"), (50, 600, 10), "album-cover"),
			(_("Action bar icon size"), (16, 64, 2), "icon-size"),
		]
		for label, (vmin, vmax, step), key in int_data:
			row=IntRow(label, vmin, vmax, step, settings, key)
			self.append(row)

class BehaviorSettings(SettingsList):
	def __init__(self, settings):
		super().__init__()
		toggle_data=[
			(_("Support “MPRIS”"), "mpris", True),
			(_("Sort albums by year"), "sort-albums-by-year", False),
			(_("Send notification on title change"), "send-notify", False),
			(_("Play selected albums and titles immediately"), "force-mode", False),
			(_("Rewind via previous button"), "rewind-mode", False),
			(_("Stop playback on quit"), "stop-on-quit", False),
		]
		for label, key, restart_required in toggle_data:
			row=ToggleRow(label, settings, key, restart_required)
			self.append(row)

class PasswordEntry(Gtk.Entry):
	def __init__(self, **kwargs):
		super().__init__(visibility=False, caps_lock_warning=False, input_purpose=Gtk.InputPurpose.PASSWORD, **kwargs)
		self.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "view-conceal-symbolic")
		self.connect("icon-release", self._on_icon_release)

	def _on_icon_release(self, *args):
		if self.get_icon_name(Gtk.EntryIconPosition.SECONDARY) == "view-conceal-symbolic":
			self.set_visibility(True)
			self.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "view-reveal-symbolic")
		else:
			self.set_visibility(False)
			self.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "view-conceal-symbolic")

class LibPathEntry(Gtk.Entry):
	def __init__(self, parent, **kwargs):
		super().__init__(placeholder_text=FALLBACK_LIB, **kwargs)
		self.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "folder-open-symbolic")
		self.connect("icon-release", self._on_icon_release, parent)

	def _on_icon_release(self, widget, icon_pos, event, parent):
		dialog=Gtk.FileChooserNative(title=_("Choose directory"), transient_for=parent, action=Gtk.FileChooserAction.SELECT_FOLDER)
		folder=self.get_text()
		if not folder:
			folder=self.get_placeholder_text()
		dialog.set_current_folder(folder)
		response=dialog.run()
		if response == Gtk.ResponseType.ACCEPT:
			self.set_text(dialog.get_filename())
		dialog.destroy()

class ProfileEntryMask(Gtk.Grid):
	def __init__(self, profile, parent):
		super().__init__(row_spacing=6, column_spacing=6, border_width=18)
		socket_button=Gtk.CheckButton(label=_("Connect via Unix domain socket"))
		profile.bind("socket-connection", socket_button, "active", Gio.SettingsBindFlags.DEFAULT)
		socket_entry=Gtk.Entry(placeholder_text=FALLBACK_SOCKET, hexpand=True, no_show_all=True)
		profile.bind("socket", socket_entry, "text", Gio.SettingsBindFlags.DEFAULT)
		profile.bind("socket-connection", socket_entry, "visible", Gio.SettingsBindFlags.GET)
		host_entry=Gtk.Entry(hexpand=True, no_show_all=True)
		profile.bind("host", host_entry, "text", Gio.SettingsBindFlags.DEFAULT)
		profile.bind("socket-connection", host_entry, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)
		port_entry=Gtk.SpinButton.new_with_range(0, 65535, 1)
		port_entry.set_property("no-show-all", True)
		profile.bind("port", port_entry, "value", Gio.SettingsBindFlags.DEFAULT)
		profile.bind("socket-connection", port_entry, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)
		password_entry=PasswordEntry(hexpand=True)
		profile.bind("password", password_entry, "text", Gio.SettingsBindFlags.DEFAULT)
		path_entry=LibPathEntry(parent, hexpand=True, no_show_all=True)
		profile.bind("path", path_entry, "text", Gio.SettingsBindFlags.DEFAULT)
		profile.bind("socket-connection", path_entry, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)
		regex_entry=Gtk.Entry(hexpand=True, placeholder_text=COVER_REGEX)
		regex_entry.set_tooltip_text(
			_("The first image in the same directory as the song file "\
			"matching this regex will be displayed. %AlbumArtist% and "\
			"%Album% will be replaced by the corresponding tags of the song.")
		)
		profile.bind("regex", regex_entry, "text", Gio.SettingsBindFlags.DEFAULT)
		socket_label=Gtk.Label(label=_("Socket:"), xalign=1, margin_end=6, no_show_all=True)
		profile.bind("socket-connection", socket_label, "visible", Gio.SettingsBindFlags.GET)
		host_label=Gtk.Label(label=_("Host:"), xalign=1, margin_end=6, no_show_all=True)
		profile.bind("socket-connection", host_label, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)
		password_label=Gtk.Label(label=_("Password:"), xalign=1, margin_end=6)
		path_label=Gtk.Label(label=_("Music lib:"), xalign=1, no_show_all=True)
		profile.bind("socket-connection", path_label, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)
		regex_label=Gtk.Label(label=_("Cover regex:"), xalign=1, margin_end=6)

		# packing
		self.attach(socket_button, 0, 0, 3, 1)
		self.attach(socket_label, 0, 1, 1, 1)
		self.attach_next_to(host_label, socket_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(password_label, host_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(path_label, password_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(regex_label, path_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(socket_entry, socket_label, Gtk.PositionType.RIGHT, 2, 1)
		self.attach_next_to(host_entry, host_label, Gtk.PositionType.RIGHT, 1, 1)
		self.attach_next_to(port_entry, host_entry, Gtk.PositionType.RIGHT, 1, 1)
		self.attach_next_to(password_entry, password_label, Gtk.PositionType.RIGHT, 2, 1)
		self.attach_next_to(path_entry, path_label, Gtk.PositionType.RIGHT, 2, 1)
		self.attach_next_to(regex_entry, regex_label, Gtk.PositionType.RIGHT, 2, 1)

class ProfileSettings(Gtk.Box):
	def __init__(self, parent, client, settings):
		super().__init__()
		self._client=client
		self._settings=settings

		# stack
		self._stack=Gtk.Stack()
		self._stack.add_titled(ProfileEntryMask(settings.get_profile(0), parent), "0", _("Profile 1"))
		self._stack.add_titled(ProfileEntryMask(settings.get_profile(1), parent), "1", _("Profile 2"))
		self._stack.add_titled(ProfileEntryMask(settings.get_profile(2), parent), "2", _("Profile 3"))
		self._stack.connect("show", lambda *args: self._stack.set_visible_child_name(str(self._settings.get_int("active-profile"))))

		# connect button
		connect_button=Gtk.Button(label=_("Connect"), margin_start=18, margin_end=18, margin_bottom=18, halign=Gtk.Align.CENTER)
		connect_button.get_style_context().add_class("suggested-action")
		connect_button.connect("clicked", self._on_connect_button_clicked)

		# packing
		vbox=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		vbox.pack_start(self._stack, False, False, 0)
		vbox.pack_start(connect_button, False, False, 0)
		switcher=Gtk.StackSidebar(stack=self._stack)
		self.pack_start(switcher, False, False, 0)
		self.pack_start(vbox, True, True, 0)

	def _on_connect_button_clicked(self, *args):
		selected=int(self._stack.get_visible_child_name())
		if selected == self._settings.get_int("active-profile"):
			self._client.reconnect()
		else:
			self._settings.set_int("active-profile", selected)

class PlaylistSettings(Gtk.Box):
	def __init__(self, settings):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, border_width=18)
		self._settings=settings

		# label
		label=Gtk.Label(label=_("Choose the order of information to appear in the playlist:"), wrap=True, xalign=0)

		# treeview
		# (toggle, header, actual_index)
		self._store=Gtk.ListStore(bool, str, int)
		treeview=Gtk.TreeView(model=self._store, reorderable=True, headers_visible=False, search_column=-1)
		self._selection=treeview.get_selection()

		# columns
		renderer_text=Gtk.CellRendererText()
		renderer_toggle=Gtk.CellRendererToggle()
		column_toggle=Gtk.TreeViewColumn("", renderer_toggle, active=0)
		treeview.append_column(column_toggle)
		column_text=Gtk.TreeViewColumn("", renderer_text, text=1)
		treeview.append_column(column_text)

		# fill store
		self._headers=[_("No"), _("Disc"), _("Title"), _("Artist"), _("Album"), _("Length"), _("Year"), _("Genre")]
		self._fill()

		# scroll
		scroll=Gtk.ScrolledWindow(child=treeview)

		# toolbar
		toolbar=Gtk.Toolbar(icon_size=Gtk.IconSize.SMALL_TOOLBAR)
		toolbar.get_style_context().add_class("inline-toolbar")
		self._up_button=Gtk.ToolButton(icon_name="go-up-symbolic", sensitive=False)
		self._down_button=Gtk.ToolButton(icon_name="go-down-symbolic", sensitive=False)
		toolbar.insert(self._up_button, 0)
		toolbar.insert(self._down_button, 1)

		# column chooser
		frame=Gtk.Frame(child=scroll)
		column_chooser=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		column_chooser.pack_start(frame, True, True, 0)
		column_chooser.pack_start(toolbar, False, False, 0)

		# connect
		self._row_deleted=self._store.connect("row-deleted", self._save_permutation)
		renderer_toggle.connect("toggled", self._on_cell_toggled)
		self._up_button.connect("clicked", self._on_up_button_clicked)
		self._down_button.connect("clicked", self._on_down_button_clicked)
		self._selection.connect("changed", self._set_button_sensitivity)

		# packing
		self.pack_start(label, False, False, 0)
		self.pack_start(column_chooser, True, True, 0)

	def _fill(self, *args):
		visibilities=self._settings.get_value("column-visibilities").unpack()
		for actual_index in self._settings.get_value("column-permutation"):
			self._store.append([visibilities[actual_index], self._headers[actual_index], actual_index])

	def _save_permutation(self, *args):
		permutation=[]
		for row in self._store:
			permutation.append(row[2])
		self._settings.set_value("column-permutation", GLib.Variant("ai", permutation))

	def _set_button_sensitivity(self, *args):
		treeiter=self._selection.get_selected()[1]
		if treeiter is None:
			self._up_button.set_sensitive(False)
			self._down_button.set_sensitive(False)
		else:
			path=self._store.get_path(treeiter)
			if self._store.iter_next(treeiter) is None:
				self._up_button.set_sensitive(True)
				self._down_button.set_sensitive(False)
			elif not path.prev():
				self._up_button.set_sensitive(False)
				self._down_button.set_sensitive(True)
			else:
				self._up_button.set_sensitive(True)
				self._down_button.set_sensitive(True)

	def _on_cell_toggled(self, widget, path):
		self._store[path][0]=not self._store[path][0]
		self._settings.array_modify("ab", "column-visibilities", self._store[path][2], self._store[path][0])

	def _on_up_button_clicked(self, *args):
		treeiter=self._selection.get_selected()[1]
		path=self._store.get_path(treeiter)
		path.prev()
		prev=self._store.get_iter(path)
		self._store.move_before(treeiter, prev)
		self._set_button_sensitivity()
		self._save_permutation()

	def _on_down_button_clicked(self, *args):
		treeiter=self._selection.get_selected()[1]
		path=self._store.get_path(treeiter)
		next=self._store.iter_next(treeiter)
		self._store.move_after(treeiter, next)
		self._set_button_sensitivity()
		self._save_permutation()

class SettingsDialog(Gtk.Dialog):
	def __init__(self, parent, client, settings, tab="view"):
		use_csd=settings.get_boolean("use-csd")
		if use_csd:
			super().__init__(title=_("Preferences"), transient_for=parent, use_header_bar=True)
		else:
			super().__init__(title=_("Preferences"), transient_for=parent)
			self.add_button(Gtk.STOCK_OK, Gtk.ResponseType.OK)
		self.set_default_size(500, 400)

		# widgets
		view=ViewSettings(settings)
		behavior=BehaviorSettings(settings)
		profiles=ProfileSettings(parent, client, settings)
		playlist=PlaylistSettings(settings)

		# packing
		vbox=self.get_content_area()
		if use_csd:
			stack=Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
			stack.add_titled(view, "view", _("View"))
			stack.add_titled(behavior, "behavior", _("Behavior"))
			stack.add_titled(playlist, "playlist", _("Playlist"))
			stack.add_titled(profiles, "profiles", _("Profiles"))
			stack_switcher=Gtk.StackSwitcher(stack=stack)
			vbox.set_property("border-width", 0)
			vbox.pack_start(stack, True, True, 0)
			header_bar=self.get_header_bar()
			header_bar.set_custom_title(stack_switcher)
		else:
			tabs=Gtk.Notebook()
			tabs.append_page(view, Gtk.Label(label=_("View")))
			tabs.append_page(behavior, Gtk.Label(label=_("Behavior")))
			tabs.append_page(playlist, Gtk.Label(label=_("Playlist")))
			tabs.append_page(profiles, Gtk.Label(label=_("Profiles")))
			vbox.set_property("spacing", 6)
			vbox.set_property("border-width", 6)
			vbox.pack_start(tabs, True, True, 0)
		self.show_all()
		if use_csd:
			stack.set_visible_child_name(tab)
		else:
			tabs.set_current_page({"view": 0, "behavior": 1, "playlist": 2, "profiles": 3}[tab])

#################
# other dialogs #
#################

class ServerStats(Gtk.Dialog):
	def __init__(self, parent, client, settings):
		use_csd=settings.get_boolean("use-csd")
		super().__init__(title=_("Stats"), transient_for=parent, use_header_bar=use_csd, resizable=False)
		if not use_csd:
			self.add_button(Gtk.STOCK_OK, Gtk.ResponseType.OK)

		# grid
		grid=Gtk.Grid(row_spacing=6, column_spacing=12, border_width=6)

		# populate
		display_str={
			"protocol": _("<b>Protocol:</b>"),
			"uptime": _("<b>Uptime:</b>"),
			"playtime": _("<b>Playtime:</b>"),
			"artists": _("<b>Artists:</b>"),
			"albums": _("<b>Albums:</b>"),
			"songs": _("<b>Songs:</b>"),
			"db_playtime": _("<b>Total Playtime:</b>"),
			"db_update": _("<b>Database Update:</b>")
		}
		stats=client.stats()
		stats["protocol"]=str(client.mpd_version)
		for key in ("uptime","playtime","db_playtime"):
			stats[key]=str(Duration(stats[key]))
		stats["db_update"]=str(datetime.datetime.fromtimestamp(int(stats["db_update"]))).replace(":", "∶")

		for i, key in enumerate(("protocol","uptime","playtime","db_update","db_playtime","artists","albums","songs")):
			grid.attach(Gtk.Label(label=display_str[key], use_markup=True, xalign=1), 0, i, 1, 1)
			grid.attach(Gtk.Label(label=stats[key], xalign=0), 1, i, 1, 1)

		# packing
		vbox=self.get_content_area()
		vbox.set_property("border-width", 6)
		vbox.pack_start(grid, True, True, 0)
		self.show_all()
		self.run()

###########################
# general purpose widgets #
###########################

class TreeView(Gtk.TreeView):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def get_popover_point(self, path):
		cell=self.get_cell_area(path, None)
		cell.x,cell.y=self.convert_bin_window_to_widget_coords(cell.x,cell.y)
		rect=self.get_visible_rect()
		rect.x,rect.y=self.convert_tree_to_widget_coords(rect.x,rect.y)
		return (rect.x+rect.width//2, max(min(cell.y+cell.height//2, rect.y+rect.height), rect.y))

class AutoSizedIcon(Gtk.Image):
	def __init__(self, icon_name, settings_key, settings):
		super().__init__(icon_name=icon_name)
		settings.bind(settings_key, self, "pixel-size", Gio.SettingsBindFlags.GET)

class SongPopover(Gtk.Popover):
	def __init__(self, client, show_buttons=True):
		super().__init__()
		self._client=client
		self._rect=Gdk.Rectangle()
		self._uri=None
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, border_width=6, spacing=6)

		# open-with button
		open_button=Gtk.Button(image=Gtk.Image.new_from_icon_name("document-open-symbolic",Gtk.IconSize.BUTTON),tooltip_text=_("Open with…"))
		open_button.get_style_context().add_class("osd")

		# open button revealer
		self._open_button_revealer=Gtk.Revealer(
			child=open_button, transition_duration=0, margin_bottom=6, margin_end=6, halign=Gtk.Align.END, valign=Gtk.Align.END)

		# buttons
		if show_buttons:
			button_box=Gtk.ButtonBox(layout_style=Gtk.ButtonBoxStyle.EXPAND)
			data=((_("Append"), "list-add-symbolic", "append"),
				(_("Play"), "media-playback-start-symbolic", "play"),
				(_("Enqueue"), "insert-object-symbolic", "enqueue")
			)
			for label, icon, mode in data:
				button=Gtk.Button(label=label, image=Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
				button.connect("clicked", self._on_button_clicked, mode)
				button_box.pack_start(button, True, True, 0)
			box.pack_end(button_box, False, False, 0)

		# treeview
		# (tag, display-value, tooltip)
		self._store=Gtk.ListStore(str, str, str)
		self._treeview=Gtk.TreeView(model=self._store, headers_visible=False, search_column=-1, tooltip_column=2, can_focus=False)
		self._treeview.get_selection().set_mode(Gtk.SelectionMode.NONE)

		# columns
		renderer_text=Gtk.CellRendererText(width_chars=50, ellipsize=Pango.EllipsizeMode.MIDDLE, ellipsize_set=True)
		renderer_text_ralign=Gtk.CellRendererText(xalign=1.0, weight=Pango.Weight.BOLD)
		column_tag=Gtk.TreeViewColumn(_("MPD-Tag"), renderer_text_ralign, text=0)
		column_tag.set_property("resizable", False)
		self._treeview.append_column(column_tag)
		column_value=Gtk.TreeViewColumn(_("Value"), renderer_text, text=1)
		column_value.set_property("resizable", False)
		self._treeview.append_column(column_value)

		# scroll
		self._scroll=Gtk.ScrolledWindow(child=self._treeview, propagate_natural_height=True)
		self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

		# overlay
		overlay=Gtk.Overlay(child=self._scroll)
		overlay.add_overlay(self._open_button_revealer)

		# connect
		open_button.connect("clicked", self._on_open_button_clicked)

		# packing
		frame=Gtk.Frame(child=overlay)
		box.pack_start(frame, True, True, 0)
		self.add(box)
		box.show_all()

	def open(self, uri, widget, x, y):
		self._uri=uri
		self._rect.x,self._rect.y=x,y
		self.set_pointing_to(self._rect)
		self.set_relative_to(widget)
		window=self.get_toplevel()
		self._scroll.set_max_content_height(window.get_size()[1]//2)
		self._store.clear()
		song=self._client.lsinfo(uri)[0]
		for tag, value in song.items():
			if tag == "duration":
				self._store.append([tag+":", str(value), locale.str(value)])
			elif tag in ("last-modified", "format"):
				self._store.append([tag+":", str(value), value.raw()])
			else:
				self._store.append([tag+":", str(value), GLib.markup_escape_text(str(value))])
		abs_path=self._client.get_absolute_path(uri)
		if abs_path is None:  # show open with button when song is on the same computer
			self._open_button_revealer.set_reveal_child(False)
		else:
			self._gfile=Gio.File.new_for_path(abs_path)
			self._open_button_revealer.set_reveal_child(True)
		self.popup()
		self._treeview.columns_autosize()

	def _on_open_button_clicked(self, *args):
		self.popdown()
		dialog=Gtk.AppChooserDialog(gfile=self._gfile, transient_for=self.get_toplevel())
		app_chooser=dialog.get_widget()
		response=dialog.run()
		if response == Gtk.ResponseType.OK:
			app=app_chooser.get_app_info()
			app.launch([self._gfile], None)
		dialog.destroy()

	def _on_button_clicked(self, widget, mode):
		self._client.files_to_playlist([self._uri], mode)
		self.popdown()

class SongsView(TreeView):
	def __init__(self, client, store, file_column_id):
		super().__init__(model=store, search_column=-1, activate_on_single_click=True)
		self._client=client
		self._store=store
		self._file_column_id=file_column_id

		# selection
		self._selection=self.get_selection()

		# song popover
		self._song_popover=SongPopover(self._client)

		# connect
		self.connect("row-activated", self._on_row_activated)
		self.connect("button-press-event", self._on_button_press_event)

	def clear(self):
		self._song_popover.popdown()
		self._store.clear()

	def get_files(self):
		return_list=[]
		for row in self._store:
			return_list.append(row[self._file_column_id])
		return return_list

	def _on_row_activated(self, widget, path, view_column):
		self._client.files_to_playlist([self._store[path][self._file_column_id]])

	def _on_button_press_event(self, widget, event):
		path_re=widget.get_path_at_pos(int(event.x), int(event.y))
		if path_re is not None:
			path=path_re[0]
			if event.button == 1 and event.type == Gdk.EventType._2BUTTON_PRESS:
				self._client.files_to_playlist([self._store[path][self._file_column_id]], "play")
			elif event.button == 2 and event.type == Gdk.EventType.BUTTON_PRESS:
				self._client.files_to_playlist([self._store[path][self._file_column_id]], "append")
			elif event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
				uri=self._store[path][self._file_column_id]
				point=self.convert_bin_window_to_widget_coords(event.x,event.y)
				self._song_popover.open(uri, widget, *point)

	def show_info(self):
		treeview, treeiter=self._selection.get_selected()
		if treeiter is not None:
			path=self._store.get_path(treeiter)
			self._song_popover.open(self._store[path][self._file_column_id], self, *self.get_popover_point(path))

	def add_to_playlist(self, mode):
		treeview, treeiter=self._selection.get_selected()
		if treeiter is not None:
			self._client.files_to_playlist([self._store.get_value(treeiter, self._file_column_id)], mode)

class SongsWindow(Gtk.Box):
	__gsignals__={"button-clicked": (GObject.SignalFlags.RUN_FIRST, None, ())}
	def __init__(self, client, store, file_column_id, popover_mode=False):
		if popover_mode:
			super().__init__(orientation=Gtk.Orientation.VERTICAL, border_width=6, spacing=6)
		else:
			super().__init__(orientation=Gtk.Orientation.VERTICAL)
		self._client=client

		# treeview
		self._songs_view=SongsView(client, store, file_column_id)

		# scroll
		self._scroll=Gtk.ScrolledWindow(child=self._songs_view)

		# buttons
		button_box=Gtk.ButtonBox(layout_style=Gtk.ButtonBoxStyle.EXPAND)
		data=((_("_Append"), _("Add all titles to playlist"), "list-add-symbolic", "append"),
			(_("_Play"), _("Directly play all titles"), "media-playback-start-symbolic", "play"),
			(_("_Enqueue"), _("Append all titles after the currently playing track and clear the playlist from all other songs"),
			"insert-object-symbolic", "enqueue")
		)
		for label, tooltip, icon, mode in data:
			button=Gtk.Button.new_with_mnemonic(label)
			button.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
			button.set_tooltip_text(tooltip)
			button.connect("clicked", self._on_button_clicked, mode)
			button_box.pack_start(button, True, True, 0)

		# action bar
		self._action_bar=Gtk.ActionBar()

		# packing
		if popover_mode:
			self.pack_end(button_box, False, False, 0)
			frame=Gtk.Frame(child=self._scroll)
			self.pack_start(frame, True, True, 0)
		else:
			self._action_bar.pack_start(button_box)
			self.pack_end(self._action_bar, False, False, 0)
			self.pack_start(self._scroll, True, True, 0)

	def get_treeview(self):
		return self._songs_view

	def get_action_bar(self):
		return self._action_bar

	def get_scroll(self):
		return self._scroll

	def _on_button_clicked(self, widget, mode):
		self._client.files_to_playlist(self._songs_view.get_files(), mode)
		self.emit("button-clicked")

class AlbumPopover(Gtk.Popover):
	def __init__(self, client, settings):
		super().__init__()
		self._client=client
		self._settings=settings
		self._rect=Gdk.Rectangle()

		# songs window
		# (track, title (artist), duration, file, search text)
		self._store=Gtk.ListStore(str, str, str, str, str)
		songs_window=SongsWindow(self._client, self._store, 3, popover_mode=True)

		# scroll
		self._scroll=songs_window.get_scroll()
		self._scroll.set_propagate_natural_height(True)
		self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

		# songs view
		self._songs_view=songs_window.get_treeview()
		self._songs_view.set_property("search-column", 4)

		# columns
		renderer_text=Gtk.CellRendererText(width_chars=80, ellipsize=Pango.EllipsizeMode.END, ellipsize_set=True)
		attrs=Pango.AttrList()
		attrs.insert(Pango.AttrFontFeatures.new("tnum 1"))
		renderer_text_tnum=Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END, ellipsize_set=True, attributes=attrs)
		renderer_text_ralign_tnum=Gtk.CellRendererText(xalign=1.0, attributes=attrs)
		column_track=Gtk.TreeViewColumn(_("No"), renderer_text_ralign_tnum, text=0)
		column_track.set_property("resizable", False)
		self._songs_view.append_column(column_track)
		self._column_title=Gtk.TreeViewColumn(_("Title"), renderer_text, markup=1)
		self._column_title.set_property("resizable", False)
		self._column_title.set_property("expand", True)
		self._songs_view.append_column(self._column_title)
		column_time=Gtk.TreeViewColumn(_("Length"), renderer_text_tnum, text=2)
		column_time.set_property("resizable", False)
		self._songs_view.append_column(column_time)

		# connect
		songs_window.connect("button-clicked", lambda *args: self.popdown())

		# packing
		self.add(songs_window)
		songs_window.show_all()

	def open(self, albumartist, albumartistsort, album, albumsort, date, widget, x, y):
		self._rect.x=x
		self._rect.y=y
		self.set_pointing_to(self._rect)
		self.set_relative_to(widget)
		self._scroll.set_max_content_height(4*widget.get_allocated_height()//7)
		self._store.clear()
		tag_filter=("albumartist", albumartist, "albumartistsort", albumartistsort, "album", album, "albumsort", albumsort, "date", date)
		count=self._client.count(*tag_filter)
		duration=str(Duration(float(count["playtime"])))
		length=int(count["songs"])
		text=ngettext("{number} song ({duration})", "{number} songs ({duration})", length).format(number=length, duration=duration)
		self._column_title.set_title(" • ".join([_("Title"), text]))
		self._client.restrict_tagtypes("track", "title", "artist")
		songs=self._client.find(*tag_filter)
		self._client.tagtypes("all")
		for song in songs:
			track=song["track"][0]
			title=song["title"][0]
			# only show artists =/= albumartist
			try:
				song["artist"].remove(albumartist)
			except ValueError:
				pass
			artist=str(song["artist"])
			if artist == albumartist or not artist:
				title_artist=f"<b>{GLib.markup_escape_text(title)}</b>"
			else:
				title_artist=f"<b>{GLib.markup_escape_text(title)}</b> • {GLib.markup_escape_text(artist)}"
			self._store.append([track, title_artist, str(song["duration"]), song["file"], title])
		self._songs_view.scroll_to_cell(Gtk.TreePath(0), None, False)  # clear old scroll position
		self.popup()
		self._songs_view.columns_autosize()

class ArtistPopover(Gtk.Popover):
	def __init__(self, client):
		super().__init__()
		self._client=client
		self._rect=Gdk.Rectangle()
		self._artist=None
		self._genre=None

		# buttons
		vbox=Gtk.ButtonBox(orientation=Gtk.Orientation.VERTICAL, border_width=9)
		data=((_("Append"), "list-add-symbolic", "append"),
			(_("Play"), "media-playback-start-symbolic", "play"),
			(_("Enqueue"), "insert-object-symbolic", "enqueue")
		)
		for label, icon, mode in data:
			button=Gtk.ModelButton(label=label, image=Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
			button.get_child().set_property("xalign", 0)
			button.connect("clicked", self._on_button_clicked, mode)
			vbox.pack_start(button, True, True, 0)

		self.add(vbox)
		vbox.show_all()

	def open(self, artist, genre, widget, x, y):
		self._rect.x=x
		self._rect.y=y
		self.set_pointing_to(self._rect)
		self.set_relative_to(widget)
		self._artist=artist
		self._genre=genre
		self.popup()

	def _on_button_clicked(self, widget, mode):
		self._client.artist_to_playlist(self._artist, self._genre, mode)
		self.popdown()

##########
# search #
##########

class SearchThread(threading.Thread):
	def __init__(self, client, search_entry, songs_window, hits_label, search_tag):
		super().__init__(daemon=True)
		self._client=client
		self._search_entry=search_entry
		self._songs_view=songs_window.get_treeview()
		self._store=self._songs_view.get_model()
		self._action_bar=songs_window.get_action_bar()
		self._hits_label=hits_label
		self._search_tag=search_tag
		self._stop_flag=False
		self._callback=None

	def set_callback(self, callback):
		self._callback=callback

	def stop(self):
		self._stop_flag=True

	def start(self):
		self._songs_view.clear()
		self._hits_label.set_text("")
		self._action_bar.set_sensitive(False)
		self._search_text=self._search_entry.get_text()
		if self._search_text:
			super().start()
		else:
			self._exit()

	def run(self):
		hits=0
		stripe_size=1000
		songs=self._get_songs(0, stripe_size)
		stripe_start=stripe_size
		while songs:
			hits+=len(songs)
			if not self._append_songs(songs):
				self._exit()
				return
			GLib.idle_add(self._search_entry.progress_pulse)
			GLib.idle_add(self._hits_label.set_text, ngettext("{hits} hit", "{hits} hits", hits).format(hits=hits))
			stripe_end=stripe_start+stripe_size
			songs=self._get_songs(stripe_start, stripe_end)
			stripe_start=stripe_end
		if hits > 0:
			GLib.idle_add(self._action_bar.set_sensitive, True)
		self._exit()

	def _exit(self):
		def callback():
			self._search_entry.set_progress_fraction(0.0)
			if self._callback is not None:
				self._callback()
			return False
		GLib.idle_add(callback)

	@main_thread_function
	def _get_songs(self, start, end):
		if self._stop_flag:
			return []
		else:
			self._client.restrict_tagtypes("track", "title", "artist", "album")
			songs=self._client.search(self._search_tag, self._search_text, "window", f"{start}:{end}")
			self._client.tagtypes("all")
			return songs

	@main_thread_function
	def _append_songs(self, songs):
		for song in songs:
			if self._stop_flag:
				return False
			try:
				int_track=int(song["track"][0])
			except ValueError:
				int_track=0
			self._store.insert_with_valuesv(-1, range(7), [
					song["track"][0], song["title"][0],
					str(song["artist"]), song["album"][0],
					str(song["duration"]), song["file"],
					int_track
			])
		return True

class SearchWindow(Gtk.Box):
	__gsignals__={"close": (GObject.SignalFlags.RUN_FIRST, None, ())}
	def __init__(self, client):
		super().__init__(orientation=Gtk.Orientation.VERTICAL)
		self._client=client

		# widgets
		self._tag_combo_box=Gtk.ComboBoxText()
		self.search_entry=Gtk.SearchEntry()
		self._hits_label=Gtk.Label(xalign=1)
		close_button=Gtk.Button(image=Gtk.Image.new_from_icon_name("window-close-symbolic", Gtk.IconSize.BUTTON), relief=Gtk.ReliefStyle.NONE)

		# songs window
		# (track, title, artist, album, duration, file, sort track)
		self._store=Gtk.ListStore(str, str, str, str, str, str, int)
		self._store.set_default_sort_func(lambda *args: 0)
		self._songs_window=SongsWindow(self._client, self._store, 5)
		self._action_bar=self._songs_window.get_action_bar()
		self._songs_view=self._songs_window.get_treeview()

		# columns
		renderer_text=Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END, ellipsize_set=True)
		attrs=Pango.AttrList()
		attrs.insert(Pango.AttrFontFeatures.new("tnum 1"))
		renderer_text_tnum=Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END, ellipsize_set=True, attributes=attrs)
		renderer_text_ralign_tnum=Gtk.CellRendererText(xalign=1.0, attributes=attrs)
		column_data=(
			(_("No"), renderer_text_ralign_tnum, False, 0, 6),
			(_("Title"), renderer_text, True, 1, 1),
			(_("Artist"), renderer_text, True, 2, 2),
			(_("Album"), renderer_text, True, 3, 3),
			(_("Length"), renderer_text_tnum, False, 4, 4),
		)
		for title, renderer, expand, text, sort in column_data:
			column=Gtk.TreeViewColumn(title, renderer, text=text)
			column.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
			column.set_property("resizable", False)
			column.set_property("expand", expand)
			column.set_sort_column_id(sort)
			self._songs_view.append_column(column)

		# search thread
		self._search_thread=SearchThread(self._client, self.search_entry, self._songs_window, self._hits_label, "any")

		# connect
		self.search_entry.connect("activate", self._search)
		self._search_entry_changed=self.search_entry.connect("search-changed", self._search)
		self.search_entry.connect("focus_in_event", self._on_search_entry_focus_event, True)
		self.search_entry.connect("focus_out_event", self._on_search_entry_focus_event, False)
		self._tag_combo_box_changed=self._tag_combo_box.connect("changed", self._search)
		self._client.emitter.connect("reconnected", self._on_reconnected)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("updated_db", self._search)
		close_button.connect("clicked", lambda *args: self.emit("close"))

		# packing
		hbox=Gtk.Box(spacing=6, border_width=6)
		hbox.pack_start(close_button, False, False, 0)
		hbox.pack_start(self.search_entry, True, True, 0)
		hbox.pack_end(self._tag_combo_box, False, False, 0)
		self._hits_label.set_margin_end(6)
		self._action_bar.pack_end(self._hits_label)
		self.pack_start(hbox, False, False, 0)
		self.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
		self.pack_start(self._songs_window, True, True, 0)

	def _on_disconnected(self, *args):
		self._search_thread.stop()

	def _on_reconnected(self, *args):
		def callback():
			self._action_bar.set_sensitive(False)
			self._songs_view.clear()
			self._hits_label.set_text("")
			self.search_entry.handler_block(self._search_entry_changed)
			self.search_entry.set_text("")
			self.search_entry.handler_unblock(self._search_entry_changed)
			self._tag_combo_box.handler_block(self._tag_combo_box_changed)
			self._tag_combo_box.remove_all()
			self._tag_combo_box.append_text(_("all tags"))
			for tag in self._client.tagtypes():
				if not tag.startswith("MUSICBRAINZ"):
					self._tag_combo_box.append_text(tag)
			self._tag_combo_box.set_active(0)
			self._tag_combo_box.handler_unblock(self._tag_combo_box_changed)
		if self._search_thread.is_alive():
			self._search_thread.set_callback(callback)
			self._search_thread.stop()
		else:
			callback()

	def _search(self, *args):
		def callback():
			if self._tag_combo_box.get_active() == 0:
				search_tag="any"
			else:
				search_tag=self._tag_combo_box.get_active_text()
			self._search_thread=SearchThread(self._client, self.search_entry, self._songs_window, self._hits_label, search_tag)
			self._search_thread.start()
		if self._search_thread.is_alive():
			self._search_thread.set_callback(callback)
			self._search_thread.stop()
		else:
			callback()

	def _on_search_entry_focus_event(self, widget, event, focus):
		app=self.get_toplevel().get_application()
		if focus:
			app.set_accels_for_action("mpd.toggle-play", [])
		else:
			app.set_accels_for_action("mpd.toggle-play", ["space"])

###########
# browser #
###########

class SelectionList(TreeView):
	__gsignals__={"item-selected": (GObject.SignalFlags.RUN_FIRST, None, ()), "clear": (GObject.SignalFlags.RUN_FIRST, None, ())}
	def __init__(self, select_all_string):
		super().__init__(activate_on_single_click=True, search_column=0, headers_visible=False, fixed_height_mode=True)
		self.select_all_string=select_all_string
		self._selected_path=None

		# store
		# (item, weight, initial-letter, weight-initials, sort-string)
		self._store=Gtk.ListStore(str, Pango.Weight, str, Pango.Weight, str)
		self._store.append([self.select_all_string, Pango.Weight.BOOK, "", Pango.Weight.BOOK, ""])
		self.set_model(self._store)
		self._selection=self.get_selection()

		# columns
		renderer_text_malign=Gtk.CellRendererText(xalign=0.5)
		self._column_initial=Gtk.TreeViewColumn("", renderer_text_malign, text=2, weight=3)
		self._column_initial.set_property("sizing", Gtk.TreeViewColumnSizing.FIXED)
		self._column_initial.set_property("min-width", 30)
		self.append_column(self._column_initial)
		renderer_text=Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END, ellipsize_set=True)
		self._column_item=Gtk.TreeViewColumn("", renderer_text, text=0, weight=1)
		self._column_item.set_property("sizing", Gtk.TreeViewColumnSizing.FIXED)
		self._column_item.set_property("expand", True)
		self.append_column(self._column_item)

		# connect
		self.connect("row-activated", self._on_row_activated)

	def clear(self):
		self._store.clear()
		self._store.append([self.select_all_string, Pango.Weight.BOOK, "", Pango.Weight.BOOK, ""])
		self._selected_path=None
		self.emit("clear")

	def set_items(self, items):
		self.clear()
		current_char=""
		items.sort(key=lambda item: locale.strxfrm(item[1]))
		items.sort(key=lambda item: locale.strxfrm(item[1][:1]))
		for item in items:
			if current_char == item[1][:1].upper():
				self._store.insert_with_valuesv(-1, range(5), [item[0], Pango.Weight.BOOK, "", Pango.Weight.BOOK, item[1]])
			else:
				self._store.insert_with_valuesv(
					-1, range(5), [item[0], Pango.Weight.BOOK, item[1][:1].upper(), Pango.Weight.BOLD, item[1]])
				current_char=item[1][:1].upper()

	def get_item_at_path(self, path):
		if path == Gtk.TreePath(0):
			return None
		else:
			return self._store[path][0,4]

	def length(self):
		return len(self._store)-1

	def select_path(self, path):
		self.set_cursor(path, None, False)
		self.row_activated(path, self._column_item)

	def select(self, item):
		row_num=len(self._store)
		for i in range(0, row_num):
			path=Gtk.TreePath(i)
			if self._store[path][0] == item[0] and self._store[path][4] == item[1]:
				self.select_path(path)
				break

	def select_all(self):
		self.set_cursor(Gtk.TreePath(0), None, False)
		self.row_activated(Gtk.TreePath(0), self._column_item)

	def get_path_selected(self):
		if self._selected_path is None:
			raise ValueError("None selected")
		else:
			return self._selected_path

	def get_item_selected(self):
		return self.get_item_at_path(self.get_path_selected())

	def highlight_selected(self):
		self.set_cursor(self._selected_path, None, False)

	def _on_row_activated(self, widget, path, view_column):
		if path != self._selected_path:
			if self._selected_path is not None:
				self._store[self._selected_path][1]=Pango.Weight.BOOK
			self._store[path][1]=Pango.Weight.BOLD
			self._selected_path=path
			self.emit("item-selected")

class GenreList(SelectionList):
	def __init__(self, client):
		super().__init__(_("all genres"))
		self._client=client

		# connect
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect_after("reconnected", self._on_reconnected)
		self._client.emitter.connect("updated_db", self._refresh)

	def deactivate(self):
		self.select_all()

	def _refresh(self, *args):
		l=self._client.comp_list("genre")
		self.set_items(list(zip(l,l)))
		self.select_all()

	def _on_disconnected(self, *args):
		self.set_sensitive(False)
		self.clear()

	def _on_reconnected(self, *args):
		self._refresh()
		self.set_sensitive(True)

class ArtistList(SelectionList):
	def __init__(self, client, settings, genre_list):
		super().__init__(_("all artists"))
		self._client=client
		self._settings=settings
		self.genre_list=genre_list

		# selection
		self._selection=self.get_selection()

		# artist popover
		self._artist_popover=ArtistPopover(self._client)

		# connect
		self.connect("clear", lambda *args: self._artist_popover.popdown())
		self.connect("button-press-event", self._on_button_press_event)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("reconnected", self._on_reconnected)
		self.genre_list.connect_after("item-selected", self._refresh)

	def _refresh(self, *args):
		genre=self.genre_list.get_item_selected()
		if genre is not None:
			genre=genre[0]
		artists=self._client.get_artists(genre)
		self.set_items(artists)
		if genre is not None:
			self.select_all()
		else:
			song=self._client.currentsong()
			if song:
				artist=(song["albumartist"][0],song["albumartistsort"][0])
				self.select(artist)
			else:
				if self.length() > 0:
					self.select_path(Gtk.TreePath(1))
				else:
					self.select_path(Gtk.TreePath(0))

	def _on_button_press_event(self, widget, event):
		if ((event.button in (2,3) and event.type == Gdk.EventType.BUTTON_PRESS)
			or (event.button == 1 and event.type == Gdk.EventType._2BUTTON_PRESS)):
			path_re=widget.get_path_at_pos(int(event.x), int(event.y))
			if path_re is not None:
				path=path_re[0]
				artist,genre=self.get_artist_at_path(path)
				if event.button == 1:
					self._client.artist_to_playlist(artist, genre, "play")
				elif event.button == 2:
					self._client.artist_to_playlist(artist, genre, "append")
				elif event.button == 3:
					self._artist_popover.open(artist, genre, self, event.x, event.y)

	def get_artist_at_path(self, path):
		genre=self.genre_list.get_item_selected()
		artist=self.get_item_at_path(path)
		if genre is not None:
			genre=genre[0]
		return (artist, genre)

	def get_artist_selected(self):
		return self.get_artist_at_path(self.get_path_selected())

	def add_to_playlist(self, mode):
		selected_rows=self._selection.get_selected_rows()
		if selected_rows is not None:
			path=selected_rows[1][0]
			artist,genre=self.get_artist_at_path(path)
			self._client.artist_to_playlist(artist, genre, mode)

	def show_info(self):
		treeview, treeiter=self._selection.get_selected()
		if treeiter is not None:
			path=self._store.get_path(treeiter)
			artist,genre=self.get_artist_at_path(path)
			self._artist_popover.open(artist, genre, self, *self.get_popover_point(path))

	def _on_disconnected(self, *args):
		self.set_sensitive(False)
		self.clear()

	def _on_reconnected(self, *args):
		self.set_sensitive(True)

class AlbumLoadingThread(threading.Thread):
	def __init__(self, client, settings, progress_bar, iconview, store, artist, genre):
		super().__init__(daemon=True)
		self._client=client
		self._settings=settings
		self._progress_bar=progress_bar
		self._iconview=iconview
		self._store=store
		self._artist=artist
		self._genre=genre

	def _get_albums(self):
		for albumartist, albumartistsort in self._artists:
			albums=main_thread_function(self._client.list)(
				"album", "albumartist", albumartist, "albumartistsort", albumartistsort,
				*self._genre_filter, "group", "date", "group", "albumsort")
			for album in albums:
				album["albumartist"]=albumartist
				album["albumartistsort"]=albumartistsort
				yield album

	def set_callback(self, callback):
		self._callback=callback

	def stop(self):
		self._stop_flag=True

	def start(self):
		self._settings.set_property("cursor-watch", True)
		self._progress_bar.show()
		self._callback=None
		self._stop_flag=False
		self._iconview.set_model(None)
		self._store.clear()
		self._cover_size=self._settings.get_int("album-cover")
		if self._artist is None:
			self._iconview.set_markup_column(2)  # show artist names
		else:
			self._iconview.set_markup_column(1)  # hide artist names
		if self._genre is None:
			self._genre_filter=()
		else:
			self._genre_filter=("genre", self._genre)
		if self._artist is None:
			self._artists=self._client.get_artists(self._genre)
		else:
			self._artists=[self._artist]
		super().start()

	def run(self):
		# temporarily display all albums with fallback cover
		fallback_cover=GdkPixbuf.Pixbuf.new_from_file_at_size(FALLBACK_COVER, self._cover_size, self._cover_size)
		add=main_thread_function(self._store.append)
		for i, album in enumerate(self._get_albums()):
			# album label
			if album["date"]:
				display_label=f"<b>{GLib.markup_escape_text(album['album'])}</b> ({GLib.markup_escape_text(album['date'])})"
			else:
				display_label=f"<b>{GLib.markup_escape_text(album['album'])}</b>"
			display_label_artist=f"{display_label}\n{GLib.markup_escape_text(album['albumartist'])}"
			# add album
			add([fallback_cover,display_label,display_label_artist,
				album["albumartist"],album["albumartistsort"],album["album"],album["albumsort"],album["date"]])
			if i%10 == 0:
				if self._stop_flag:
					self._exit()
					return
				GLib.idle_add(self._progress_bar.pulse)
		# sort model
		if main_thread_function(self._settings.get_boolean)("sort-albums-by-year"):
			main_thread_function(self._store.set_sort_column_id)(7, Gtk.SortType.ASCENDING)
		else:
			main_thread_function(self._store.set_sort_column_id)(6, Gtk.SortType.ASCENDING)
		GLib.idle_add(self._iconview.set_model, self._store)
		# load covers
		total=2*len(self._store)
		@main_thread_function
		def get_cover(row):
			if self._stop_flag:
				return None
			else:
				self._client.restrict_tagtypes("albumartist", "album")
				song=self._client.find("albumartist", row[3], "albumartistsort",
					row[4], "album", row[5], "albumsort", row[6],
					"date", row[7], "window", "0:1")[0]
				self._client.tagtypes("all")
				return self._client.get_cover(song)
		covers=[]
		for i, row in enumerate(self._store):
			cover=get_cover(row)
			if cover is None:
				self._exit()
				return
			covers.append(cover)
			GLib.idle_add(self._progress_bar.set_fraction, (i+1)/total)
		treeiter=self._store.get_iter_first()
		i=0
		def set_cover(treeiter, cover):
			if self._store.iter_is_valid(treeiter):
				self._store.set_value(treeiter, 0, cover)
		while treeiter is not None:
			if self._stop_flag:
				self._exit()
				return
			cover=covers[i].get_pixbuf(self._cover_size)
			GLib.idle_add(set_cover, treeiter, cover)
			GLib.idle_add(self._progress_bar.set_fraction, 0.5+(i+1)/total)
			i+=1
			treeiter=self._store.iter_next(treeiter)
		self._exit()

	def _exit(self):
		def callback():
			self._settings.set_property("cursor-watch", False)
			self._progress_bar.hide()
			self._progress_bar.set_fraction(0)
			if self._callback is not None:
				self._callback()
			return False
		GLib.idle_add(callback)

class AlbumList(Gtk.IconView):
	def __init__(self, client, settings, artist_list):
		super().__init__(item_width=0, pixbuf_column=0, markup_column=1, activate_on_single_click=True)
		self._settings=settings
		self._client=client
		self._artist_list=artist_list

		# cover, display_label, display_label_artist, albumartist, albumartistsort, album, albumsort, date
		self._store=Gtk.ListStore(GdkPixbuf.Pixbuf, str, str, str, str, str, str, str)
		self._store.set_default_sort_func(lambda *args: 0)
		self.set_model(self._store)

		# progress bar
		self.progress_bar=Gtk.ProgressBar(no_show_all=True)

		# popover
		self._album_popover=AlbumPopover(self._client, self._settings)

		# cover thread
		self._cover_thread=AlbumLoadingThread(self._client, self._settings, self.progress_bar, self, self._store, None, None)

		# connect
		self.connect("item-activated", self._on_item_activated)
		self.connect("button-press-event", self._on_button_press_event)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("reconnected", self._on_reconnected)
		self._settings.connect("changed::sort-albums-by-year", self._sort_settings)
		self._settings.connect("changed::album-cover", self._on_cover_size_changed)
		self._artist_list.connect("item-selected", self._refresh)
		self._artist_list.connect("clear", self._clear)

	def _workaround_clear(self):
		self._store.clear()
		# workaround (scrollbar still visible after clear)
		self.set_model(None)
		self.set_model(self._store)

	def _clear(self, *args):
		def callback():
			self._album_popover.popdown()
			self._workaround_clear()
		if self._cover_thread.is_alive():
			self._cover_thread.set_callback(callback)
			self._cover_thread.stop()
		else:
			callback()

	def scroll_to_current_album(self):
		def callback():
			song=self._client.currentsong()
			album=song["album"][0]
			self.unselect_all()
			row_num=len(self._store)
			for i in range(0, row_num):
				path=Gtk.TreePath(i)
				if self._store[path][5] == album:
					self.set_cursor(path, None, False)
					self.select_path(path)
					self.scroll_to_path(path, True, 0, 0)
					break
		if self._cover_thread.is_alive():
			self._cover_thread.set_callback(callback)
		else:
			callback()

	def _sort_settings(self, *args):
		if not self._cover_thread.is_alive():
			if self._settings.get_boolean("sort-albums-by-year"):
				self._store.set_sort_column_id(7, Gtk.SortType.ASCENDING)
			else:
				self._store.set_sort_column_id(6, Gtk.SortType.ASCENDING)

	def _refresh(self, *args):
		def callback():
			if self._cover_thread.is_alive():  # already started?
				return False
			artist,genre=self._artist_list.get_artist_selected()
			self._cover_thread=AlbumLoadingThread(self._client,self._settings,self.progress_bar,self,self._store,artist,genre)
			self._cover_thread.start()
		if self._cover_thread.is_alive():
			self._cover_thread.set_callback(callback)
			self._cover_thread.stop()
		else:
			callback()

	def _path_to_playlist(self, path, mode="default"):
		tags=self._store[path][3:8]
		self._client.album_to_playlist(*tags, mode)

	def _on_button_press_event(self, widget, event):
		path=widget.get_path_at_pos(int(event.x), int(event.y))
		if event.button == 1 and event.type == Gdk.EventType._2BUTTON_PRESS:
			if path is not None:
				self._path_to_playlist(path, "play")
		elif event.button == 2 and event.type == Gdk.EventType.BUTTON_PRESS:
			if path is not None:
				self._path_to_playlist(path, "append")
		elif event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
			v=self.get_vadjustment().get_value()
			h=self.get_hadjustment().get_value()
			if path is not None:
				tags=self._store[path][3:8]
				# when using "button-press-event" in iconview popovers only show up in combination with idle_add (bug in GTK?)
				GLib.idle_add(self._album_popover.open, *tags, widget, event.x-h, event.y-v)

	def _on_item_activated(self, widget, path):
		self._path_to_playlist(path)

	def _on_disconnected(self, *args):
		self.set_sensitive(False)

	def _on_reconnected(self, *args):
		self.set_sensitive(True)

	def show_info(self):
		paths=self.get_selected_items()
		if len(paths) > 0:
			path=paths[0]
			cell=self.get_cell_rect(path, None)[1]
			rect=self.get_allocation()
			x=max(min(rect.x+cell.width//2, rect.x+rect.width), rect.x)
			y=max(min(cell.y+cell.height//2, rect.y+rect.height), rect.y)
			tags=self._store[path][3:8]
			self._album_popover.open(*tags, self, x, y)

	def add_to_playlist(self, mode):
		paths=self.get_selected_items()
		if len(paths) != 0:
			self._path_to_playlist(paths[0], mode)

	def _on_cover_size_changed(self, *args):
		if self._client.connected():
			self._refresh()

class Browser(Gtk.Paned):
	def __init__(self, client, settings):
		super().__init__()
		self._client=client
		self._settings=settings

		# widgets
		self._genre_list=GenreList(self._client)
		self._artist_list=ArtistList(self._client, self._settings, self._genre_list)
		self._album_list=AlbumList(self._client, self._settings, self._artist_list)
		genre_window=Gtk.ScrolledWindow(child=self._genre_list)
		artist_window=Gtk.ScrolledWindow(child=self._artist_list)
		album_window=Gtk.ScrolledWindow(child=self._album_list)

		# hide/show genre filter
		self._genre_list.set_property("visible", True)
		self._settings.bind("genre-filter", genre_window, "no-show-all", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)
		self._settings.bind("genre-filter", genre_window, "visible", Gio.SettingsBindFlags.GET)
		self._settings.connect("changed::genre-filter", self._on_genre_filter_changed)

		# packing
		album_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		album_box.pack_start(album_window, True, True, 0)
		album_box.pack_start(self._album_list.progress_bar, False, False, 0)
		self.paned1=Gtk.Paned()
		self.paned1.pack1(artist_window, False, False)
		self.paned1.pack2(album_box, True, False)
		self.pack1(genre_window, False, False)
		self.pack2(self.paned1, True, False)

	def back_to_current_album(self, force=False):
		song=self._client.currentsong()
		if song:
			artist,genre=self._artist_list.get_artist_selected()
			# deactivate genre filter to show all artists (if needed)
			if song["genre"][0] != genre or force:
				self._genre_list.deactivate()
			# select artist
			if artist is None and not force:  # all artists selected
				self._artist_list.highlight_selected()
			else:  # one artist selected
				self._artist_list.select((song["albumartist"][0],song["albumartistsort"][0]))
			self._album_list.scroll_to_current_album()
		else:
			self._genre_list.deactivate()

	def _on_genre_filter_changed(self, settings, key):
		if self._client.connected():
			if not settings.get_boolean(key):
				self._genre_list.deactivate()

############
# playlist #
############

class PlaylistView(TreeView):
	selected_path=GObject.Property(type=Gtk.TreePath, default=None)  # currently marked song (bold text)
	def __init__(self, client, settings):
		super().__init__(activate_on_single_click=True, reorderable=True, search_column=2, fixed_height_mode=True)
		self._client=client
		self._settings=settings
		self._playlist_version=None
		self._inserted_path=None  # needed for drag and drop
		self._selection=self.get_selection()

		# store
		# (track, disc, title, artist, album, human duration, date, genre, file, weight, duration)
		self._store=Gtk.ListStore(str, str, str, str, str, str, str, str, str, Pango.Weight, float)
		self.set_model(self._store)

		# columns
		renderer_text=Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END, ellipsize_set=True)
		renderer_text_ralign=Gtk.CellRendererText(xalign=1.0)
		attrs=Pango.AttrList()
		attrs.insert(Pango.AttrFontFeatures.new("tnum 1"))
		renderer_text_tnum=Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END, ellipsize_set=True, attributes=attrs)
		renderer_text_ralign_tnum=Gtk.CellRendererText(xalign=1.0, attributes=attrs)
		self._columns=(
			Gtk.TreeViewColumn(_("No"), renderer_text_ralign_tnum, text=0, weight=9),
			Gtk.TreeViewColumn(_("Disc"), renderer_text_ralign, text=1, weight=9),
			Gtk.TreeViewColumn(_("Title"), renderer_text, text=2, weight=9),
			Gtk.TreeViewColumn(_("Artist"), renderer_text, text=3, weight=9),
			Gtk.TreeViewColumn(_("Album"), renderer_text, text=4, weight=9),
			Gtk.TreeViewColumn(_("Length"), renderer_text_tnum, text=5, weight=9),
			Gtk.TreeViewColumn(_("Year"), renderer_text_tnum, text=6, weight=9),
			Gtk.TreeViewColumn(_("Genre"), renderer_text, text=7, weight=9)
		)
		for i, column in enumerate(self._columns):
			column.set_property("resizable", True)
			column.set_property("sizing", Gtk.TreeViewColumnSizing.FIXED)
			column.set_min_width(30)
			column.connect("notify::fixed-width", self._on_column_width, i)
		self._load_settings()

		# song popover
		self._song_popover=SongPopover(self._client, show_buttons=False)

		# connect
		self.connect("row-activated", self._on_row_activated)
		self.connect("button-press-event", self._on_button_press_event)
		self.connect("key-release-event", self._on_key_release_event)
		self._row_deleted=self._store.connect("row-deleted", self._on_row_deleted)
		self._row_inserted=self._store.connect("row-inserted", self._on_row_inserted)

		self._client.emitter.connect("playlist", self._on_playlist_changed)
		self._client.emitter.connect("current_song", self._on_song_changed)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("reconnected", self._on_reconnected)

		self._settings.connect("changed::column-visibilities", self._load_settings)
		self._settings.connect("changed::column-permutation", self._load_settings)

	def _on_column_width(self, obj, typestring, pos):
		self._settings.array_modify("ai", "column-sizes", pos, obj.get_property("fixed-width"))

	def _load_settings(self, *args):
		columns=self.get_columns()
		for column in columns:
			self.remove_column(column)
		sizes=self._settings.get_value("column-sizes").unpack()
		visibilities=self._settings.get_value("column-visibilities").unpack()
		for i in self._settings.get_value("column-permutation"):
			if sizes[i] > 0:
				self._columns[i].set_fixed_width(sizes[i])
			self._columns[i].set_visible(visibilities[i])
			self.append_column(self._columns[i])

	def _clear(self, *args):
		self._song_popover.popdown()
		self._set_playlist_info("")
		self._playlist_version=None
		self.set_property("selected-path", None)
		self._store.handler_block(self._row_inserted)
		self._store.handler_block(self._row_deleted)
		self._store.clear()
		self._store.handler_unblock(self._row_inserted)
		self._store.handler_unblock(self._row_deleted)

	def _select(self, path):
		self._unselect()
		try:
			self._store[path][9]=Pango.Weight.BOLD
			self.set_property("selected-path", path)
		except IndexError:  # invalid path
			pass

	def _unselect(self):
		if self.get_property("selected-path") is not None:
			try:
				self._store[self.get_property("selected-path")][9]=Pango.Weight.BOOK
				self.set_property("selected-path", None)
			except IndexError:  # invalid path
				self.set_property("selected-path", None)

	def scroll_to_selected_title(self):
		treeview, treeiter=self._selection.get_selected()
		if treeiter is not None:
			path=treeview.get_path(treeiter)
			self.scroll_to_cell(path, None, True, 0.25)

	def _refresh_selection(self):  # Gtk.TreePath(len(self._store) is used to generate an invalid TreePath (needed to unset cursor)
		self.set_cursor(Gtk.TreePath(len(self._store)), None, False)
		song=self._client.status().get("song")
		if song is None:
			self._selection.unselect_all()
			self._unselect()
		else:
			path=Gtk.TreePath(int(song))
			self._selection.select_path(path)
			self._select(path)

	def _set_playlist_info(self, text):
		if text:
			self._columns[2].set_title(" • ".join([_("Title"), text]))
		else:
			self._columns[2].set_title(_("Title"))

	def _on_button_press_event(self, widget, event):
		path_re=widget.get_path_at_pos(int(event.x), int(event.y))
		if path_re is not None:
			path=path_re[0]
			if event.button == 2 and event.type == Gdk.EventType.BUTTON_PRESS:
				self._store.remove(self._store.get_iter(path))
			elif event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
				point=self.convert_bin_window_to_widget_coords(event.x,event.y)
				self._song_popover.open(self._store[path][8], widget, *point)

	def _on_key_release_event(self, widget, event):
		if event.keyval == Gdk.keyval_from_name("Delete"):
			treeview, treeiter=self._selection.get_selected()
			if treeiter is not None:
				try:
					self._store.remove(treeiter)
				except:
					pass

	def _on_row_deleted(self, model, path):  # sync treeview to mpd
		try:
			if self._inserted_path is not None:  # move
				path=int(path.to_string())
				if path > self._inserted_path:
					path=path-1
				if path < self._inserted_path:
					self._inserted_path=self._inserted_path-1
				self._client.move(path, self._inserted_path)
				self._inserted_path=None
			else:  # delete
				self._client.delete(path)  # bad song index possible
			self._playlist_version=int(self._client.status()["playlist"])
		except MPDBase.CommandError as e:
			self._playlist_version=None
			self._client.emitter.emit("playlist", int(self._client.status()["playlist"]))
			raise e  # propagate exception

	def _on_row_inserted(self, model, path, treeiter):
		self._inserted_path=int(path.to_string())

	def _on_row_activated(self, widget, path, view_column):
		self._client.play(path)

	def _on_playlist_changed(self, emitter, version):
		self._store.handler_block(self._row_inserted)
		self._store.handler_block(self._row_deleted)
		self._song_popover.popdown()
		self._unselect()
		self._client.restrict_tagtypes("track", "disc", "title", "artist", "album", "date", "genre")
		songs=[]
		if self._playlist_version is not None:
			songs=self._client.plchanges(self._playlist_version)
		else:
			songs=self._client.playlistinfo()
		self._client.tagtypes("all")
		if songs:
			self.freeze_child_notify()
			self._set_playlist_info("")
			for song in songs:
				try:
					treeiter=self._store.get_iter(song["pos"])
					self._store.set(treeiter,
						0, song["track"][0],
						1, song["disc"][0],
						2, song["title"][0],
						3, str(song["artist"]),
						4, song["album"][0],
						5, str(song["duration"]),
						6, song["date"][0],
						7, str(song["genre"]),
						8, song["file"],
						9, Pango.Weight.BOOK,
						10, float(song["duration"])
					)
				except:
					self._store.insert_with_valuesv(-1, range(11), [
						song["track"][0], song["disc"][0],
						song["title"][0], str(song["artist"]),
						song["album"][0], str(song["duration"]),
						song["date"][0], str(song["genre"]),
						song["file"], Pango.Weight.BOOK,
						float(song["duration"])
					])
			self.thaw_child_notify()
		for i in reversed(range(int(self._client.status()["playlistlength"]), len(self._store))):
			treeiter=self._store.get_iter(i)
			self._store.remove(treeiter)
		playlist_length=len(self._store)
		if playlist_length == 0:
			self._set_playlist_info("")
		else:
			duration=Duration(sum([row[10] for row in self._store]))
			translated_string=ngettext("{number} song ({duration})", "{number} songs ({duration})", playlist_length)
			self._set_playlist_info(translated_string.format(number=playlist_length, duration=duration))
		self._refresh_selection()
		if self._playlist_version != version:
			self.scroll_to_selected_title()
		self._playlist_version=version
		self._store.handler_unblock(self._row_inserted)
		self._store.handler_unblock(self._row_deleted)

	def _on_song_changed(self, *args):
		self._refresh_selection()
		if self._client.status()["state"] == "play":
			self.scroll_to_selected_title()

	def _on_disconnected(self, *args):
		self.set_sensitive(False)
		self._clear()

	def _on_reconnected(self, *args):
		self.set_sensitive(True)

	def show_info(self):
		treeview, treeiter=self._selection.get_selected()
		if treeiter is not None:
			path=self._store.get_path(treeiter)
			self._song_popover.open(self._store[path][8], self, *self.get_popover_point(path))

class PlaylistWindow(Gtk.Overlay):
	def __init__(self, client, settings):
		super().__init__()
		self._back_to_current_song_button=Gtk.Button(
			image=Gtk.Image.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON), tooltip_text=_("Scroll to current song"),
			can_focus=False
		)
		self._back_to_current_song_button.get_style_context().add_class("osd")
		self._back_button_revealer=Gtk.Revealer(
			child=self._back_to_current_song_button, transition_duration=0,
			margin_bottom=6, margin_start=6, halign=Gtk.Align.START, valign=Gtk.Align.END
		)
		self._treeview=PlaylistView(client, settings)
		scroll=Gtk.ScrolledWindow(child=self._treeview)

		# connect
		self._back_to_current_song_button.connect("clicked", self._on_back_to_current_song_button_clicked)
		scroll.get_vadjustment().connect("value-changed", self._on_show_hide_back_button)
		self._treeview.connect("notify::selected-path", self._on_show_hide_back_button)
		settings.bind("mini-player", self, "no-show-all", Gio.SettingsBindFlags.GET)
		settings.bind("mini-player", self, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)

		# packing
		self.add(scroll)
		self.add_overlay(self._back_button_revealer)

	def _on_show_hide_back_button(self, *args):
		visible_range=self._treeview.get_visible_range()
		if visible_range is None or self._treeview.get_property("selected-path") is None:
			self._back_button_revealer.set_reveal_child(False)
		else:
			current_song_visible=(visible_range[0] <= self._treeview.get_property("selected-path") <= visible_range[1])
			self._back_button_revealer.set_reveal_child(not(current_song_visible))

	def _on_back_to_current_song_button_clicked(self, *args):
		self._treeview.set_cursor(Gtk.TreePath(len(self._treeview.get_model())), None, False)  # unset cursor
		if self._treeview.get_property("selected-path") is not None:
			self._treeview.get_selection().select_path(self._treeview.get_property("selected-path"))
		self._treeview.scroll_to_selected_title()

####################
# cover and lyrics #
####################

class LyricsWindow(Gtk.ScrolledWindow):
	def __init__(self, client, settings):
		super().__init__()
		self._settings=settings
		self._client=client
		self._displayed_song_file=None

		# text view
		self._text_view=Gtk.TextView(
			editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD,
			justification=Gtk.Justification.CENTER, opacity=0.9,
			left_margin=5, right_margin=5, bottom_margin=5, top_margin=3
		)

		# text buffer
		self._text_buffer=self._text_view.get_buffer()

		# connect
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._song_changed=self._client.emitter.connect("current_song", self._refresh)
		self._client.emitter.handler_block(self._song_changed)

		# packing
		self.add(self._text_view)

	def enable(self, *args):
		current_song=self._client.currentsong()
		if current_song:
			if current_song["file"] != self._displayed_song_file:
				self._refresh()
		else:
			if self._displayed_song_file is not None:
				self._refresh()
		self._client.emitter.handler_unblock(self._song_changed)
		GLib.idle_add(self._text_view.grab_focus)  # focus textview

	def disable(self, *args):
		self._client.emitter.handler_block(self._song_changed)

	def _get_lyrics(self, title, artist):
		replaces=((" ", "+"),(".", "_"),("@", "_"),(",", "_"),(";", "_"),("&", "_"),("\\", "_"),("/", "_"),('"', "_"),("(", "_"),(")", "_"))
		for char1, char2 in replaces:
			title=title.replace(char1, char2)
			artist=artist.replace(char1, char2)
		req=requests.get(f"https://www.letras.mus.br/winamp.php?musica={title}&artista={artist}")
		soup=BeautifulSoup(req.text, "html.parser")
		soup=soup.find(id="letra-cnt")
		if soup is None:
			raise ValueError("Not found")
		paragraphs=[i for i in soup.children][1]  # remove unneded paragraphs (NavigableString)
		lyrics=""
		for paragraph in paragraphs:
			for line in paragraph.stripped_strings:
				lyrics+=line+"\n"
			lyrics+="\n"
		output=lyrics[:-2]  # omit last two newlines
		if output:
			return output
		else:  # assume song is instrumental when lyrics are empty
			return "Instrumental"

	def _display_lyrics(self, current_song):
		GLib.idle_add(self._text_buffer.set_text, _("searching…"), -1)
		try:
			text=self._get_lyrics(current_song["title"][0], current_song["artist"][0])
		except requests.exceptions.ConnectionError:
			self._displayed_song_file=None
			text=_("connection error")
		except ValueError:
			text=_("lyrics not found")
		GLib.idle_add(self._text_buffer.set_text, text, -1)

	def _refresh(self, *args):
		current_song=self._client.currentsong()
		if current_song:
			self._displayed_song_file=current_song["file"]
			update_thread=threading.Thread(
					target=self._display_lyrics,
					kwargs={"current_song": current_song},
					daemon=True
			)
			update_thread.start()
		else:
			self._displayed_song_file=None
			self._text_buffer.set_text("", -1)

	def _on_disconnected(self, *args):
		self._displayed_song_file=None
		self._text_buffer.set_text("", -1)

class CoverEventBox(Gtk.EventBox):
	def __init__(self, client, settings):
		super().__init__()
		self._client=client
		self._settings=settings

		# album popover
		self._album_popover=AlbumPopover(self._client, self._settings)

		# connect
		self._button_press_event=self.connect("button-press-event", self._on_button_press_event)
		self._client.emitter.connect("disconnected", self._on_disconnected)

	def _on_button_press_event(self, widget, event):
		if self._settings.get_boolean("mini-player"):
			if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
				window=self.get_toplevel()
				window.begin_move_drag(1, event.x_root, event.y_root, Gdk.CURRENT_TIME)
		else:
			if self._client.connected():
				song=self._client.currentsong()
				if song:
					tags=(song["albumartist"][0], song["albumartistsort"][0],
						song["album"][0], song["albumsort"][0], song["date"][0])
					if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
						self._client.album_to_playlist(*tags)
					elif event.button == 1 and event.type == Gdk.EventType._2BUTTON_PRESS:
						self._client.album_to_playlist(*tags, "play")
					elif event.button == 2 and event.type == Gdk.EventType.BUTTON_PRESS:
						self._client.album_to_playlist(*tags, "append")
					elif event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
						self._album_popover.open(*tags, widget, event.x, event.y)

	def _on_disconnected(self, *args):
		self._album_popover.popdown()

class MainCover(Gtk.Image):
	def __init__(self, client, settings):
		super().__init__()
		self._client=client
		self._settings=settings
		# set default size
		size=self._settings.get_int("track-cover")
		self.set_size_request(size, size)

		# connect
		self._client.emitter.connect("current_song", self._refresh)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("reconnected", self._on_reconnected)
		self._settings.connect("changed::track-cover", self._on_settings_changed)

	def _clear(self):
		size=self._settings.get_int("track-cover")
		self.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(FALLBACK_COVER, size, size))

	def _refresh(self, *args):
		song=self._client.currentsong()
		if song:
			self.set_from_pixbuf(self._client.get_cover(song).get_pixbuf(self._settings.get_int("track-cover")))
		else:
			self._clear()

	def _on_disconnected(self, *args):
		self.set_sensitive(False)
		self._clear()

	def _on_reconnected(self, *args):
		self.set_sensitive(True)

	def _on_settings_changed(self, *args):
		size=self._settings.get_int("track-cover")
		self.set_size_request(size, size)
		self._refresh()

class CoverLyricsWindow(Gtk.Overlay):
	def __init__(self, client, settings):
		super().__init__()
		self._client=client
		self._settings=settings

		# cover
		main_cover=MainCover(self._client, self._settings)
		self._cover_event_box=CoverEventBox(self._client, self._settings)

		# lyrics button
		self.lyrics_button=Gtk.ToggleButton(
			image=Gtk.Image.new_from_icon_name("org.mpdevil.mpdevil-lyrics-symbolic", Gtk.IconSize.BUTTON), tooltip_text=_("Lyrics"),
			can_focus=False
		)
		self.lyrics_button.get_style_context().add_class("osd")

		# lyrics window
		self._lyrics_window=LyricsWindow(self._client, self._settings)

		# revealer
		self._lyrics_button_revealer=Gtk.Revealer(
			child=self.lyrics_button, transition_duration=0, margin_top=6, margin_end=6, halign=Gtk.Align.END, valign=Gtk.Align.START)
		self._settings.bind("show-lyrics-button", self._lyrics_button_revealer, "reveal-child", Gio.SettingsBindFlags.DEFAULT)

		# stack
		self._stack=Gtk.Stack(transition_type=Gtk.StackTransitionType.OVER_DOWN_UP)
		self._stack.add_named(self._cover_event_box, "cover")
		self._stack.add_named(self._lyrics_window, "lyrics")
		self._stack.set_visible_child(self._cover_event_box)

		# connect
		self.lyrics_button.connect("toggled", self._on_lyrics_toggled)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("reconnected", self._on_reconnected)

		# packing
		self.add(main_cover)
		self.add_overlay(self._stack)
		self.add_overlay(self._lyrics_button_revealer)

	def _on_reconnected(self, *args):
		self.lyrics_button.set_sensitive(True)

	def _on_disconnected(self, *args):
		self.lyrics_button.set_active(False)
		self.lyrics_button.set_sensitive(False)

	def _on_lyrics_toggled(self, widget):
		if widget.get_active():
			self._stack.set_visible_child(self._lyrics_window)
			self._lyrics_window.enable()
		else:
			self._stack.set_visible_child(self._cover_event_box)
			self._lyrics_window.disable()

######################
# action bar widgets #
######################

class PlaybackControl(Gtk.ButtonBox):
	def __init__(self, client, settings):
		super().__init__(layout_style=Gtk.ButtonBoxStyle.EXPAND)
		self._client=client
		self._settings=settings

		# widgets
		self._play_button_icon=AutoSizedIcon("media-playback-start-symbolic", "icon-size", self._settings)
		self._play_button=Gtk.Button(image=self._play_button_icon, action_name="mpd.toggle-play", can_focus=False)
		self._stop_button=Gtk.Button(
			image=AutoSizedIcon("media-playback-stop-symbolic", "icon-size", self._settings), action_name="mpd.stop",
			can_focus=False, no_show_all=True
		)
		self._prev_button=Gtk.Button(
			image=AutoSizedIcon("media-skip-backward-symbolic", "icon-size", self._settings), action_name="mpd.prev", can_focus=False)
		self._next_button=Gtk.Button(
			image=AutoSizedIcon("media-skip-forward-symbolic", "icon-size", self._settings), action_name="mpd.next", can_focus=False)

		# connect
		self._settings.connect("changed::mini-player", self._mini_player)
		self._settings.connect("changed::show-stop", self._mini_player)
		self._client.emitter.connect("state", self._on_state)
		self._client.emitter.connect("playlist", self._refresh_tooltips)
		self._client.emitter.connect("current_song", self._refresh_tooltips)
		self._client.emitter.connect("disconnected", self._on_disconnected)

		# packing
		self.pack_start(self._prev_button, True, True, 0)
		self.pack_start(self._play_button, True, True, 0)
		self.pack_start(self._stop_button, True, True, 0)
		self.pack_start(self._next_button, True, True, 0)
		self._mini_player()

	def _refresh_tooltips(self, *args):
		status=self._client.status()
		song=status.get("song")
		length=status.get("playlistlength")
		if song is None or length is None:
			self._prev_button.set_tooltip_text("")
			self._next_button.set_tooltip_text("")
		else:
			elapsed=int(song)
			rest=int(length)-elapsed-1
			elapsed_songs=ngettext("{number} song", "{number} songs", elapsed).format(number=elapsed)
			rest_songs=ngettext("{number} song", "{number} songs", rest).format(number=rest)
			self._prev_button.set_tooltip_text(elapsed_songs)
			self._next_button.set_tooltip_text(rest_songs)

	def _mini_player(self, *args):
		visibility=(self._settings.get_boolean("show-stop") and not self._settings.get_boolean("mini-player"))
		self._stop_button.set_property("visible", visibility)

	def _on_state(self, emitter, state):
		if state == "play":
			self._play_button_icon.set_property("icon-name", "media-playback-pause-symbolic")
		else:
			self._play_button_icon.set_property("icon-name", "media-playback-start-symbolic")

	def _on_disconnected(self, *args):
		self._prev_button.set_tooltip_text("")
		self._next_button.set_tooltip_text("")

class SeekBar(Gtk.Box):
	def __init__(self, client):
		super().__init__(hexpand=True, margin_start=6, margin_right=6)
		self._client=client
		self._update=True
		self._jumped=False

		# labels
		attrs=Pango.AttrList()
		attrs.insert(Pango.AttrFontFeatures.new("tnum 1"))
		self._elapsed=Gtk.Label(xalign=0, attributes=attrs)
		self._rest=Gtk.Label(xalign=1, attributes=attrs)

		# event boxes
		elapsed_event_box=Gtk.EventBox(child=self._elapsed)
		rest_event_box=Gtk.EventBox(child=self._rest)

		# progress bar
		self._scale=Gtk.Scale(
			orientation=Gtk.Orientation.HORIZONTAL, show_fill_level=True, restrict_to_fill_level=False, draw_value=False, can_focus=False)
		self._scale.set_increments(10, 60)
		self._adjustment=self._scale.get_adjustment()

		# connect
		elapsed_event_box.connect("button-release-event", self._on_elapsed_button_release_event)
		rest_event_box.connect("button-release-event", self._on_rest_button_release_event)
		self._scale.connect("change-value", self._on_change_value)
		self._scale.connect("scroll-event", lambda *args: True)  # disable mouse wheel
		self._scale.connect("button-press-event", self._on_scale_button_press_event)
		self._scale.connect("button-release-event", self._on_scale_button_release_event)
		self._client.emitter.connect("disconnected", self._disable)
		self._client.emitter.connect("state", self._on_state)
		self._client.emitter.connect("elapsed", self._refresh)

		# packing
		self.pack_start(elapsed_event_box, False, False, 0)
		self.pack_start(self._scale, True, True, 0)
		self.pack_end(rest_event_box, False, False, 0)

	def _refresh(self, emitter, elapsed, duration):
		self.set_sensitive(True)
		if duration > 0:
			if elapsed > duration:  # fix display error
				elapsed=duration
			self._adjustment.set_upper(duration)
			if self._update:
				self._scale.set_value(elapsed)
				self._elapsed.set_text(str(Duration(elapsed)))
				self._rest.set_text(str(Duration(elapsed-duration)))
			self._scale.set_fill_level(elapsed)
		else:
			self._disable()
			self._elapsed.set_text(str(Duration(elapsed)))

	def _disable(self, *args):
		self.set_sensitive(False)
		self._scale.set_fill_level(0)
		self._scale.set_range(0, 0)
		self._elapsed.set_text(str(Duration()))
		self._rest.set_text(str(Duration()))

	def _on_scale_button_press_event(self, widget, event):
		if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
			self._update=False
			self._scale.set_has_origin(False)
		elif event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
			self._jumped=False

	def _on_scale_button_release_event(self, widget, event):
		if event.button == 1:
			self._update=True
			self._scale.set_has_origin(True)
			if self._jumped:  # actual seek
				self._client.seekcur(self._scale.get_value())
				self._jumped=False
			else:  # restore state
				status=self._client.status()
				self._refresh(None, float(status["elapsed"]), float(status["duration"]))

	def _on_change_value(self, range, scroll, value):  # value is inaccurate (can be above upper limit)
		if (scroll == Gtk.ScrollType.STEP_BACKWARD or scroll == Gtk.ScrollType.STEP_FORWARD or
			scroll == Gtk.ScrollType.PAGE_BACKWARD or scroll == Gtk.ScrollType.PAGE_FORWARD):
			self._client.seekcur(value)
		elif scroll == Gtk.ScrollType.JUMP:
			duration=self._adjustment.get_upper()
			if value > duration:  # fix display error
				elapsed=duration
			else:
				elapsed=value
			self._elapsed.set_text(str(Duration(elapsed)))
			self._rest.set_text(str(Duration(elapsed-duration)))
			self._jumped=True

	def _on_elapsed_button_release_event(self, widget, event):
		if event.button == 1:
			self._client.seekcur("-"+str(self._adjustment.get_property("step-increment")))
		elif event.button == 3:
			self._client.seekcur("+"+str(self._adjustment.get_property("step-increment")))

	def _on_rest_button_release_event(self, widget, event):
		if event.button == 1:
			self._client.seekcur("+"+str(self._adjustment.get_property("step-increment")))
		elif event.button == 3:
			self._client.seekcur("-"+str(self._adjustment.get_property("step-increment")))

	def _on_state(self, emitter, state):
		if state == "stop":
			self._disable()

class AudioFormat(Gtk.Box):
	def __init__(self, client, settings):
		super().__init__(spacing=6)
		self._client=client
		self._settings=settings
		self._file_type_label=Gtk.Label(xalign=1, visible=True)
		self._separator_label=Gtk.Label(xalign=1, visible=True)
		attrs=Pango.AttrList()
		attrs.insert(Pango.AttrFontFeatures.new("tnum 1"))
		self._brate_label=Gtk.Label(xalign=1, width_chars=5, visible=True, attributes=attrs)
		self._format_label=Gtk.Label(visible=True)

		# connect
		self._settings.connect("changed::mini-player", self._mini_player)
		self._settings.connect("changed::show-audio-format", self._mini_player)
		self._client.emitter.connect("audio", self._on_audio)
		self._client.emitter.connect("bitrate", self._on_bitrate)
		self._client.emitter.connect("current_song", self._on_song_changed)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("reconnected", self._on_reconnected)

		# packing
		hbox=Gtk.Box(halign=Gtk.Align.END, visible=True)
		hbox.pack_start(self._brate_label, False, False, 0)
		hbox.pack_start(self._separator_label, False, False, 0)
		hbox.pack_start(self._file_type_label, False, False, 0)
		vbox=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, visible=True)
		vbox.pack_start(hbox, False, False, 0)
		vbox.pack_start(self._format_label, False, False, 0)
		self.pack_start(Gtk.Separator(visible=True), False, False, 0)
		self.pack_start(vbox, False, False, 0)
		self.pack_start(Gtk.Separator(visible=True), False, False, 0)
		self._mini_player()

	def _mini_player(self, *args):
		visibility=(self._settings.get_boolean("show-audio-format") and not self._settings.get_boolean("mini-player"))
		self.set_property("no-show-all", not(visibility))
		self.set_property("visible", visibility)

	def _on_audio(self, emitter, audio_format):
		if audio_format is None:
			self._format_label.set_markup("<small> </small>")
		else:
			self._format_label.set_markup(f"<small>{Format(audio_format)}</small>")

	def _on_bitrate(self, emitter, brate):
		# handle unknown bitrates: https://github.com/MusicPlayerDaemon/MPD/issues/428#issuecomment-442430365
		if brate is None:
			self._brate_label.set_text("—")
		else:
			self._brate_label.set_text(brate)

	def _on_song_changed(self, *args):
		current_song=self._client.currentsong()
		if current_song:
			file_type=current_song["file"].split(".")[-1].split("/")[0].upper()
			self._separator_label.set_text(" kb∕s • ")
			self._file_type_label.set_text(file_type)
		else:
			self._file_type_label.set_text("")
			self._separator_label.set_text(" kb∕s")
			self._format_label.set_markup("<small> </small>")

	def _on_disconnected(self, *args):
		self.set_sensitive(False)
		self._brate_label.set_text("—")
		self._separator_label.set_text(" kb/s")
		self._file_type_label.set_text("")
		self._format_label.set_markup("<small> </small>")

	def _on_reconnected(self, *args):
		self.set_sensitive(True)

class PlaybackOptions(Gtk.ButtonBox):
	def __init__(self, client, settings):
		super().__init__(layout_style=Gtk.ButtonBoxStyle.EXPAND)
		self._client=client
		self._settings=settings

		# buttons
		self._buttons={}
		data=(
			("repeat", "media-playlist-repeat-symbolic", _("Repeat mode")),
			("random", "media-playlist-shuffle-symbolic", _("Random mode")),
			("single", "org.mpdevil.mpdevil-single-symbolic", _("Single mode")),
			("consume", "org.mpdevil.mpdevil-consume-symbolic", _("Consume mode")),
		)
		for name, icon, tooltip in data:
			button=Gtk.ToggleButton(image=AutoSizedIcon(icon, "icon-size", self._settings), tooltip_text=tooltip, can_focus=False)
			handler=button.connect("toggled", self._set_option, name)
			self.pack_start(button, True, True, 0)
			self._buttons[name]=(button, handler)

		# css
		self._provider=Gtk.CssProvider()
		self._provider.load_from_data(b"""image {color: @error_color;}""")  # red icon

		# connect
		for name in ("repeat", "random", "consume"):
			self._client.emitter.connect(name, self._button_refresh, name)
		self._client.emitter.connect("single", self._single_refresh)
		self._buttons["single"][0].connect("button-press-event", self._on_single_button_press_event)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("reconnected", self._on_reconnected)
		self._settings.bind("mini-player", self, "no-show-all", Gio.SettingsBindFlags.GET)
		self._settings.bind("mini-player", self, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)

	def _set_option(self, widget, option):
		func=getattr(self._client, option)
		if widget.get_active():
			func("1")
		else:
			func("0")

	def _button_refresh(self, emitter, val, name):
		self._buttons[name][0].handler_block(self._buttons[name][1])
		self._buttons[name][0].set_active(val)
		self._buttons[name][0].handler_unblock(self._buttons[name][1])

	def _single_refresh(self, emitter, val):
		self._buttons["single"][0].handler_block(self._buttons["single"][1])
		self._buttons["single"][0].set_active((val in ("1", "oneshot")))
		if val == "oneshot":
			self._buttons["single"][0].get_image().get_style_context().add_provider(self._provider, 600)
		else:
			self._buttons["single"][0].get_image().get_style_context().remove_provider(self._provider)
		self._buttons["single"][0].handler_unblock(self._buttons["single"][1])

	def _on_single_button_press_event(self, widget, event):
		if event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
			state=self._client.status()["single"]
			if state == "oneshot":
				self._client.single("0")
			else:
				self._client.single("oneshot")

	def _on_disconnected(self, *args):
		self.set_sensitive(False)
		for name in ("repeat", "random", "consume"):
			self._button_refresh(None, False, name)
		self._single_refresh(None, "0")

	def _on_reconnected(self, *args):
		self.set_sensitive(True)

class OutputPopover(Gtk.Popover):
	def __init__(self, client, relative):
		super().__init__()
		self.set_relative_to(relative)
		self._client=client

		# widgets
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, border_width=9)
		for output in self._client.outputs():
			button=Gtk.ModelButton(label=f"{output['outputname']} ({output['plugin']})", role=Gtk.ButtonRole.CHECK)
			button.get_child().set_property("xalign", 0)
			if output["outputenabled"] == "1":
				button.set_property("active", True)
			button.connect("clicked", self._on_button_clicked, output["outputid"])
			box.pack_start(button, False, False, 0)

		#connect
		self.connect("closed", lambda *args: self.destroy())

		# packing
		self.add(box)
		box.show_all()

	def _on_button_clicked(self, button, out_id):
		if button.get_property("active"):
			self._client.disableoutput(out_id)
			button.set_property("active", False)
		else:
			self._client.enableoutput(out_id)
			button.set_property("active", True)

class VolumeButton(Gtk.VolumeButton):
	def __init__(self, client, settings):
		super().__init__(use_symbolic=True, can_focus=False)
		self._client=client
		self._popover=None
		self._adj=self.get_adjustment()
		self._adj.set_step_increment(5)
		self._adj.set_page_increment(10)
		self._adj.set_upper(0)  # do not allow volume change by user when MPD has not yet reported volume (no output enabled/avail)
		settings.bind("icon-size", self.get_child(), "pixel-size", Gio.SettingsBindFlags.GET)

		# connect
		self._changed=self.connect("value-changed", self._set_volume)
		self._client.emitter.connect("volume", self._refresh)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("reconnected", self._on_reconnected)
		self.connect("button-press-event", self._on_button_press_event)

	def _set_volume(self, widget, value):
		self._client.setvol(str(int(value)))

	def _refresh(self, emitter, volume):
		self.handler_block(self._changed)
		if volume < 0:
			self.set_value(0)
			self._adj.set_upper(0)
		else:
			self._adj.set_upper(100)
			self.set_value(volume)
		self.handler_unblock(self._changed)

	def _on_button_press_event(self, widget, event):
		if event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
			self._popover=OutputPopover(self._client, self)
			self._popover.popup()

	def _on_reconnected(self, *args):
		self.set_sensitive(True)

	def _on_disconnected(self, *args):
		self.set_sensitive(False)
		self._refresh(None, -1)
		if self._popover is not None:
			self._popover.popdown()
			self._popover=None

###################
# MPD gio actions #
###################
class MPDActionGroup(Gio.SimpleActionGroup):
	def __init__(self, client):
		super().__init__()
		self._client=client

		# actions
		self._disable_on_stop_data=("next","prev","seek-forward","seek-backward")
		self._enable_on_reconnect_data=("toggle-play","stop","clear","update","repeat","random","single","consume","single-oneshot")
		self._data=self._disable_on_stop_data+self._enable_on_reconnect_data
		for name in self._data:
			action=Gio.SimpleAction.new(name, None)
			action.connect("activate", getattr(self, ("_on_"+name.replace("-","_"))))
			self.add_action(action)

		# connect
		self._client.emitter.connect("state", self._on_state)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("reconnected", self._on_reconnected)

	def _on_toggle_play(self, action, param):
		self._client.toggle_play()

	def _on_stop(self, action, param):
		self._client.stop()

	def _on_next(self, action, param):
		self._client.next()

	def _on_prev(self, action, param):
		self._client.conditional_previous()

	def _on_seek_forward(self, action, param):
		self._client.seekcur("+10")

	def _on_seek_backward(self, action, param):
		self._client.seekcur("-10")

	def _on_clear(self, action, param):
		self._client.clear()

	def _on_update(self, action, param):
		self._client.update()

	def _on_repeat(self, action, param):
		self._client.toggle_option("repeat")

	def _on_random(self, action, param):
		self._client.toggle_option("random")

	def _on_single(self, action, param):
		self._client.toggle_option("single")

	def _on_consume(self, action, param):
		self._client.toggle_option("consume")

	def _on_single_oneshot(self, action, param):
		self._client.single("oneshot")

	def _on_state(self, emitter, state):
		state_dict={"play": True, "pause": True, "stop": False}
		for action in self._disable_on_stop_data:
			self.lookup_action(action).set_enabled(state_dict[state])

	def _on_disconnected(self, *args):
		for action in self._data:
			self.lookup_action(action).set_enabled(False)

	def _on_reconnected(self, *args):
		for action in self._enable_on_reconnect_data:
			self.lookup_action(action).set_enabled(True)

###############
# main window #
###############

class UpdateNotify(Gtk.Revealer):
	def __init__(self, client):
		super().__init__(valign=Gtk.Align.START, halign=Gtk.Align.CENTER)
		self._client=client

		# widgets
		self._spinner=Gtk.Spinner()
		label=Gtk.Label(label=_("Updating Database…"))

		# connect
		self._client.emitter.connect("updating_db", self._show)
		self._client.emitter.connect("updated_db", self._hide)
		self._client.emitter.connect("disconnected", self._hide)

		# packing
		box=Gtk.Box(spacing=12)
		box.get_style_context().add_class("app-notification")
		box.pack_start(self._spinner, False, False, 0)
		box.pack_end(label, True, True, 0)
		self.add(box)

	def _show(self, *args):
		self._spinner.start()
		self.set_reveal_child(True)

	def _hide(self, *args):
		self._spinner.stop()
		self.set_reveal_child(False)

class ConnectionNotify(Gtk.Revealer):
	def __init__(self, client, settings):
		super().__init__(valign=Gtk.Align.START, halign=Gtk.Align.CENTER)
		self._client=client
		self._settings=settings

		# widgets
		self._label=Gtk.Label(wrap=True)
		connect_button=Gtk.Button(label=_("Connect"))
		settings_button=Gtk.Button(label=_("Preferences"), action_name="win.profile-settings")

		# connect
		connect_button.connect("clicked", self._on_connect_button_clicked)
		self._client.emitter.connect("connection_error", self._on_connection_error)
		self._client.emitter.connect("reconnected", self._on_reconnected)

		# packing
		box=Gtk.Box(spacing=12)
		box.get_style_context().add_class("app-notification")
		box.pack_start(self._label, False, True, 6)
		box.pack_end(connect_button, False, True, 0)
		box.pack_end(settings_button, False, True, 0)
		self.add(box)

	def _on_connection_error(self, *args):
		profile=self._settings.get_active_profile()
		if profile.get_boolean("socket-connection"):
			socket=profile.get_string("socket")
			if not socket:
				socket=FALLBACK_SOCKET
			text=_("Connection to “{socket}” failed").format(socket=socket)
		else:
			text=_("Connection to “{host}:{port}” failed").format(host=profile.get_string("host"), port=profile.get_int("port"))
		self._label.set_text(text)
		self.set_reveal_child(True)

	def _on_reconnected(self, *args):
		self.set_reveal_child(False)

	def _on_connect_button_clicked(self, *args):
		self._client.reconnect()

class MainWindow(Gtk.ApplicationWindow):
	def __init__(self, client, settings, notify, **kwargs):
		super().__init__(title=("mpdevil"), icon_name="org.mpdevil.mpdevil", **kwargs)
		self.set_default_icon_name("org.mpdevil.mpdevil")
		self.set_default_size(settings.get_int("width"), settings.get_int("height"))
		if settings.get_boolean("maximize"):
			self.maximize()  # request maximize
		self._client=client
		self._settings=settings
		self._notify=notify
		self._use_csd=self._settings.get_boolean("use-csd")
		self._size=None  # needed for window size saving

		# MPRIS
		if self._settings.get_boolean("mpris"):
			dbus_service=MPRISInterface(self, self._client, self._settings)

		# actions
		simple_actions_data=(
			"settings","profile-settings","stats","help","menu",
			"toggle-lyrics","back-to-current-album","toggle-search",
			"profile-next","profile-prev","show-info"
		)
		for name in simple_actions_data:
			action=Gio.SimpleAction.new(name, None)
			action.connect("activate", getattr(self, ("_on_"+name.replace("-","_"))))
			self.add_action(action)
		for name in ("append","play","enqueue"):
			action=Gio.SimpleAction.new(name, None)
			action.connect("activate", self._on_add_to_playlist, name)
			self.add_action(action)
		self.add_action(self._settings.create_action("mini-player"))
		self.add_action(self._settings.create_action("genre-filter"))
		self.add_action(self._settings.create_action("active-profile"))

		# shortcuts
		builder=Gtk.Builder()
		builder.add_from_resource("/org/mpdevil/mpdevil/ShortcutsWindow.ui")
		self.set_help_overlay(builder.get_object("shortcuts_window"))

		# widgets
		self._paned0=Gtk.Paned()
		self._paned2=Gtk.Paned()
		self._browser=Browser(self._client, self._settings)
		self._search_window=SearchWindow(self._client)
		self._cover_lyrics_window=CoverLyricsWindow(self._client, self._settings)
		playlist_window=PlaylistWindow(self._client, self._settings)
		playback_control=PlaybackControl(self._client, self._settings)
		seek_bar=SeekBar(self._client)
		audio=AudioFormat(self._client, self._settings)
		playback_options=PlaybackOptions(self._client, self._settings)
		volume_button=VolumeButton(self._client, self._settings)
		update_notify=UpdateNotify(self._client)
		connection_notify=ConnectionNotify(self._client, self._settings)
		def icon(name):
			if self._use_csd:
				return Gtk.Image.new_from_icon_name(name, Gtk.IconSize.BUTTON)
			else:
				return AutoSizedIcon(name, "icon-size", self._settings)
		self._search_button=Gtk.ToggleButton(
			image=icon("system-search-symbolic"), tooltip_text=_("Search"), can_focus=False, no_show_all=True)
		self._settings.bind("mini-player", self._search_button, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)
		self._back_button=Gtk.Button(
			image=icon("go-previous-symbolic"), tooltip_text=_("Back to current album"), can_focus=False, no_show_all=True)
		self._settings.bind("mini-player", self._back_button, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)

		# stack
		self._stack=Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
		self._stack.add_named(self._browser, "browser")
		self._stack.add_named(self._search_window, "search")
		self._settings.bind("mini-player", self._stack, "no-show-all", Gio.SettingsBindFlags.GET)
		self._settings.bind("mini-player", self._stack, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)

		# menu
		subsection=Gio.Menu()
		subsection.append(_("Preferences"), "win.settings")
		subsection.append(_("Keyboard Shortcuts"), "win.show-help-overlay")
		subsection.append(_("Help"), "win.help")
		subsection.append(_("About mpdevil"), "app.about")
		mpd_subsection=Gio.Menu()
		mpd_subsection.append(_("Update Database"), "mpd.update")
		mpd_subsection.append(_("Server Stats"), "win.stats")
		profiles_subsection=Gio.Menu()
		for num, profile in enumerate((_("Profile 1"), _("Profile 2"), _("Profile 3"))):
			item=Gio.MenuItem.new(profile, None)
			item.set_action_and_target_value("win.active-profile", GLib.Variant("i", num))
			profiles_subsection.append_item(item)
		menu=Gio.Menu()
		menu.append(_("Mini Player"), "win.mini-player")
		menu.append(_("Genre Filter"), "win.genre-filter")
		menu.append_section(None, profiles_subsection)
		menu.append_section(None, mpd_subsection)
		menu.append_section(None, subsection)

		# menu button / popover
		if self._use_csd:
			menu_icon=Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON)
		else:
			menu_icon=AutoSizedIcon("open-menu-symbolic", "icon-size", self._settings)
		self._menu_button=Gtk.MenuButton(image=menu_icon, tooltip_text=_("Menu"), can_focus=False)
		menu_popover=Gtk.Popover.new_from_model(self._menu_button, menu)
		self._menu_button.set_popover(menu_popover)

		# connect
		self._search_button.connect("toggled", self._on_search_button_toggled)
		self._back_button.connect("clicked", self._on_back_button_clicked)
		self._back_button.connect("button-press-event", self._on_back_button_press_event)
		self._search_window.connect("close", lambda *args: self._search_button.set_active(False))
		self._settings.connect_after("changed::mini-player", self._mini_player)
		self._settings.connect_after("notify::cursor-watch", self._on_cursor_watch)
		self._settings.connect("changed::playlist-right", self._on_playlist_pos_changed)
		self._client.emitter.connect("current_song", self._on_song_changed)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("reconnected", self._on_reconnected)
		# auto save window state and size
		self.connect("size-allocate", self._on_size_allocate)
		self._settings.bind("maximize", self, "is-maximized", Gio.SettingsBindFlags.SET)

		# packing
		self._on_playlist_pos_changed()  # set orientation
		self._paned0.pack1(self._cover_lyrics_window, False, False)
		self._paned0.pack2(playlist_window, True, False)
		self._paned2.pack1(self._stack, True, False)
		self._paned2.pack2(self._paned0, False, False)
		action_bar=Gtk.ActionBar()
		if self._use_csd:
			self._header_bar=Gtk.HeaderBar(show_close_button=True)
			self.set_titlebar(self._header_bar)
			self._header_bar.pack_start(self._back_button)
			self._header_bar.pack_end(self._menu_button)
			self._header_bar.pack_end(self._search_button)
		else:
			action_bar.pack_start(self._back_button)
			action_bar.pack_end(self._menu_button)
			action_bar.pack_end(self._search_button)
		action_bar.pack_start(playback_control)
		action_bar.pack_start(seek_bar)
		action_bar.pack_start(audio)
		action_bar.pack_start(playback_options)
		action_bar.pack_start(volume_button)
		vbox=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		vbox.pack_start(self._paned2, True, True, 0)
		vbox.pack_start(action_bar, False, False, 0)
		overlay=Gtk.Overlay(child=vbox)
		overlay.add_overlay(update_notify)
		overlay.add_overlay(connection_notify)
		self.add(overlay)
		# bring player in consistent state
		self._client.emitter.emit("disconnected")
		self._mini_player()
		# indicate connection process in window title
		if self._use_csd:
			self._header_bar.set_subtitle(_("connecting…"))
		else:
			self.set_title("mpdevil "+_("connecting…"))
		self.show_all()
		while Gtk.events_pending():  # ensure window is visible
			Gtk.main_iteration_do(True)
		# restore paned settings when window is visible (fixes a bug when window is maximized)
		self._settings.bind("paned0", self._paned0, "position", Gio.SettingsBindFlags.DEFAULT)
		self._settings.bind("paned1", self._browser.paned1, "position", Gio.SettingsBindFlags.DEFAULT)
		self._settings.bind("paned2", self._paned2, "position", Gio.SettingsBindFlags.DEFAULT)
		self._settings.bind("paned3", self._browser, "position", Gio.SettingsBindFlags.DEFAULT)

		# start client
		def callback(*args):
			self._client.start()  # connect client
			return False
		GLib.idle_add(callback)

	def _mini_player(self, *args):
		if self._settings.get_boolean("mini-player"):
			if self.is_maximized():
				self.unmaximize()
			self.resize(1,1)
		else:
			self.resize(self._settings.get_int("width"), self._settings.get_int("height"))
			self.show_all()

	def _on_toggle_lyrics(self, action, param):
		self._cover_lyrics_window.lyrics_button.emit("clicked")

	def _on_back_to_current_album(self, action, param):
		self._back_button.emit("clicked")

	def _on_toggle_search(self, action, param):
		self._search_button.emit("clicked")

	def _on_settings(self, action, param):
		settings=SettingsDialog(self, self._client, self._settings)
		settings.run()
		settings.destroy()

	def _on_profile_settings(self, action, param):
		settings=SettingsDialog(self, self._client, self._settings, "profiles")
		settings.run()
		settings.destroy()

	def _on_stats(self, action, param):
		stats=ServerStats(self, self._client, self._settings)
		stats.destroy()

	def _on_help(self, action, param):
		Gtk.show_uri_on_window(self, "https://github.com/SoongNoonien/mpdevil/wiki/Usage", Gdk.CURRENT_TIME)

	def _on_menu(self, action, param):
		self._menu_button.emit("clicked")

	def _on_profile_next(self, action, param):
		current_profile=self._settings.get_int("active-profile")
		self._settings.set_int("active-profile", ((current_profile+1)%3))

	def _on_profile_prev(self, action, param):
		current_profile=self._settings.get_int("active-profile")
		self._settings.set_int("active-profile", ((current_profile-1)%3))

	def _on_show_info(self, action, param):
		widget=self.get_focus()
		if hasattr(widget, "show_info") and callable(widget.show_info):
			widget.show_info()

	def _on_add_to_playlist(self, action, param, mode):
		widget=self.get_focus()
		if hasattr(widget, "add_to_playlist") and callable(widget.add_to_playlist):
			widget.add_to_playlist(mode)

	def _on_search_button_toggled(self, button):
		if button.get_active():
			self._stack.set_visible_child_name("search")
			self._search_window.search_entry.grab_focus()
		else:
			self._stack.set_visible_child_name("browser")

	def _on_back_button_clicked(self, *args):
		self._search_button.set_active(False)
		self._browser.back_to_current_album()

	def _on_back_button_press_event(self, widget, event):
		if event.button == 1 and event.type == Gdk.EventType._2BUTTON_PRESS:
			self._browser.back_to_current_album(force=True)

	def _on_song_changed(self, *args):
		song=self._client.currentsong()
		if song:
			if "date" in song:
				date=f"({song['date']})"
			else:
				date=""
			album_with_date=" ".join(filter(None, (str(song["album"]), date)))
			if self._use_csd:
				self.set_title(" • ".join(filter(None, (str(song["title"]), str(song["artist"])))))
				self._header_bar.set_subtitle(album_with_date)
			else:
				self.set_title(" • ".join(filter(None, (str(song["title"]), str(song["artist"]), album_with_date))))
			if self._settings.get_boolean("send-notify"):
				if not self.is_active() and self._client.status()["state"] == "play":
					self._notify.update(str(song["title"]), f"{song['artist']}\n{album_with_date}")
					pixbuf=self._client.get_cover(song).get_pixbuf(400)
					self._notify.set_image_from_pixbuf(pixbuf)
					self._notify.show()
		else:
			self.set_title("mpdevil")
			if self._use_csd:
				self._header_bar.set_subtitle("")

	def _on_reconnected(self, *args):
		for action in ("stats","toggle-lyrics","back-to-current-album","toggle-search"):
			self.lookup_action(action).set_enabled(True)
		self._search_button.set_sensitive(True)
		self._back_button.set_sensitive(True)

	def _on_disconnected(self, *args):
		self.set_title("mpdevil")
		if self._use_csd:
			self._header_bar.set_subtitle("")
		for action in ("stats","toggle-lyrics","back-to-current-album","toggle-search"):
			self.lookup_action(action).set_enabled(False)
		self._search_button.set_active(False)
		self._search_button.set_sensitive(False)
		self._back_button.set_sensitive(False)

	def _on_size_allocate(self, widget, rect):
		if not self.is_maximized() and not self._settings.get_boolean("mini-player"):
			size=self.get_size()
			if size != self._size:  # prevent unneeded write operations
				self._settings.set_int("width", size[0])
				self._settings.set_int("height", size[1])
				self._size=size

	def _on_cursor_watch(self, obj, typestring):
		if obj.get_property("cursor-watch"):
			watch_cursor=Gdk.Cursor(Gdk.CursorType.WATCH)
			self.get_window().set_cursor(watch_cursor)
		else:
			self.get_window().set_cursor(None)

	def _on_playlist_pos_changed(self, *args):
		if self._settings.get_boolean("playlist-right"):
			self._paned0.set_orientation(Gtk.Orientation.VERTICAL)
			self._paned2.set_orientation(Gtk.Orientation.HORIZONTAL)
		else:
			self._paned0.set_orientation(Gtk.Orientation.HORIZONTAL)
			self._paned2.set_orientation(Gtk.Orientation.VERTICAL)

###################
# Gtk application #
###################

class mpdevil(Gtk.Application):
	def __init__(self):
		super().__init__(application_id="org.mpdevil.mpdevil", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
		self.add_main_option("debug", ord("d"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE, _("Debug mode"), None)
		self._settings=Settings()
		self._client=Client(self._settings)
		Notify.init("mpdevil")
		self._notify=Notify.Notification()
		self._window=None

	def do_activate(self):
		if not self._window:  # allow just one instance
			self._window=MainWindow(self._client, self._settings, self._notify, application=self)
			self._window.connect("delete-event", self._on_quit)
			self._window.insert_action_group("mpd", MPDActionGroup(self._client))
			# accelerators
			action_accels=(
				("app.quit", ["<Control>q"]),("win.mini-player", ["<Control>m"]),("win.help", ["F1"]),("win.menu", ["F10"]),
				("win.show-help-overlay", ["<Control>question"]),("win.toggle-lyrics", ["<Control>l"]),
				("win.back-to-current-album", ["Escape"]),("win.toggle-search", ["<control>f"]),
				("mpd.update", ["F5"]),("mpd.clear", ["<Shift>Delete"]),("mpd.toggle-play", ["space"]),
				("mpd.stop", ["<Shift>space"]),("mpd.next", ["KP_Add"]),("mpd.prev", ["KP_Subtract"]),
				("mpd.repeat", ["<Control>r"]),("mpd.random", ["<Control>s"]),("mpd.single", ["<Control>1"]),
				("mpd.consume", ["<Control>o"]),("mpd.single-oneshot", ["<Control>space"]),("mpd.seek-forward", ["KP_Multiply"]),
				("mpd.seek-backward", ["KP_Divide"]),("win.profile-next", ["<Control>p"]),("win.profile-prev", ["<Shift><Control>p"]),
				("win.show-info", ["<Control>i","Menu"]),("win.append", ["<Control>plus"]),
				("win.play", ["<Control>Return"]),("win.enqueue", ["<Control>e"]),("win.genre-filter", ["<Control>g"])
			)
			for action, accels in action_accels:
				self.set_accels_for_action(action, accels)
			# disable item activation on space key pressed in treeviews
			Gtk.binding_entry_remove(Gtk.binding_set_find('GtkTreeView'), Gdk.keyval_from_name("space"), Gdk.ModifierType.MOD2_MASK)
		self._window.present()

	def do_startup(self):
		Gtk.Application.do_startup(self)
		action=Gio.SimpleAction.new("about", None)
		action.connect("activate", self._on_about)
		self.add_action(action)
		action=Gio.SimpleAction.new("quit", None)
		action.connect("activate", self._on_quit)
		self.add_action(action)

	def do_command_line(self, command_line):
		# convert GVariantDict -> GVariant -> dict
		options=command_line.get_options_dict().end().unpack()
		if "debug" in options:
			import logging
			logging.basicConfig(level=logging.DEBUG)
		self.activate()
		return 0

	def _on_about(self, *args):
		builder=Gtk.Builder()
		builder.add_from_resource("/org/mpdevil/mpdevil/AboutDialog.ui")
		dialog=builder.get_object("about_dialog")
		dialog.set_transient_for(self._window)
		dialog.run()
		dialog.destroy()

	def _on_quit(self, *args):
		if self._settings.get_boolean("stop-on-quit") and self._client.connected():
			self._client.stop()
		self._notify.close()
		Notify.uninit()
		self.quit()

if __name__ == "__main__":
	app=mpdevil()
	app.run(sys.argv)
