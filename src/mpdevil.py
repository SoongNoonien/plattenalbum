#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# mpdevil - MPD Client.
# Copyright (C) 2020-2023 Martin Wagner <martin.wagner.dev@gmail.com>
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
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, Gdk, Pango, GObject, GLib
from mpd import MPDClient, CommandError, ConnectionError
from html.parser import HTMLParser
import urllib.request
import urllib.parse
import urllib.error
import threading
import functools
import itertools
import collections
import os
import sys
import signal
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

FALLBACK_REGEX=r"^\.?(album|cover|folder|front).*\.(gif|jpeg|jpg|png)$"
FALLBACK_COVER="media-optical"
FALLBACK_SOCKET=os.path.join(GLib.get_user_runtime_dir(), "mpd/socket")
FALLBACK_MUSIC_DIRECTORY=GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_MUSIC)

############################
# decorators and functions #
############################

def idle_add(*args, **kwargs):
	GLib.idle_add(*args, priority=GLib.PRIORITY_DEFAULT, **kwargs)

def lookup_icon(icon_name, size, scale=1):
	return Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).lookup_icon(
			icon_name, None, size, scale, Gtk.TextDirection.NONE, Gtk.IconLookupFlags.FORCE_REGULAR)

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
		idle_add(glib_callback, event, result, *args, **kwargs)
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

	def __init__(self, application, window, client, settings):
		self._application=application
		self._window=window
		self._client=client
		self._settings=settings
		self._metadata={}
		self._tmp_cover_file,_=Gio.File.new_tmp(None)

		# MPRIS property mappings
		self._prop_mapping={
			self._MPRIS_IFACE:
				{"CanQuit": (GLib.Variant("b", False), None),
				"CanRaise": (GLib.Variant("b", True), None),
				"HasTrackList": (GLib.Variant("b", False), None),
				"Identity": (GLib.Variant("s", "mpdevil"), None),
				"DesktopEntry": (GLib.Variant("s", "org.mpdevil.mpdevil"), None),
				"SupportedUriSchemes": (GLib.Variant("as", []), None),
				"SupportedMimeTypes": (GLib.Variant("as", []), None)},
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
		self._application.connect("shutdown", lambda *args: self._tmp_cover_file.delete(None))
		self._client.emitter.connect("state", self._on_state_changed)
		self._client.emitter.connect("current_song", self._on_song_changed)
		self._client.emitter.connect("volume", self._on_volume_changed)
		self._client.emitter.connect("repeat", self._on_loop_changed)
		self._client.emitter.connect("single", self._on_loop_changed)
		self._client.emitter.connect("random", self._on_random_changed)
		self._client.emitter.connect("connection_error", self._on_connection_error)
		self._client.emitter.connect("connected", self._on_connected)
		self._client.emitter.connect("disconnected", self._on_disconnected)

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
			if 0 <= value <= 1:
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
		try:
			props=self._prop_mapping[interface_name]
		except KeyError:  # interface has no properties
			return {}
		else:
			read_props={}
			for key, (getter, setter) in props.items():
				if callable(getter):
					getter=getter()
				read_props[key]=getter
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
		self._application.quit()

	# player methods
	def Next(self):
		self._client.next()

	def Previous(self):
		self._client.previous()

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
		if 0 <= mpd_pos <= float(song["duration"]):
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
		self._tmp_cover_file.replace_contents(b"", None, False, Gio.FileCreateFlags.NONE, None)
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
			if "://" in (song_file:=song["file"]):  # remote file
				self._metadata["xesam:url"]=GLib.Variant("s", song_file)
			else:
				if (song_path:=self._client.get_absolute_path(song_file)) is not None:
					self._metadata["xesam:url"]=GLib.Variant("s", Gio.File.new_for_path(song_path).get_uri())
				if isinstance(self._client.current_cover, FileCover):
					self._metadata["mpris:artUrl"]=GLib.Variant("s", Gio.File.new_for_path(self._client.current_cover).get_uri())
				elif isinstance(self._client.current_cover, BinaryCover):
					self._tmp_cover_file.replace_contents(self._client.current_cover, None, False, Gio.FileCreateFlags.NONE, None)
					self._metadata["mpris:artUrl"]=GLib.Variant("s", self._tmp_cover_file.get_uri())

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

	def _on_connected(self, *args):
		for p in ("CanPlay","CanPause","CanSeek"):
			self._update_property(self._MPRIS_PLAYER_IFACE, p)

	def _on_disconnected(self, *args):
		self._metadata={}
		self._tmp_cover_file.replace_contents(b"", None, False, Gio.FileCreateFlags.NONE, None)
		self._update_property(self._MPRIS_PLAYER_IFACE, "Metadata")

	def _on_connection_error(self, *args):
		self._metadata={}
		self._tmp_cover_file.replace_contents(b"", None, False, Gio.FileCreateFlags.NONE, None)
		for p in ("PlaybackStatus","CanGoNext","CanGoPrevious","Metadata","Volume","LoopStatus","Shuffle","CanPlay","CanPause","CanSeek"):
			self._update_property(self._MPRIS_PLAYER_IFACE, p)

######################
# MPD client wrapper #
######################

class Duration():
	def __init__(self, seconds=None):
		if seconds is None:
			self._fallback=True
			self._seconds=0.0
		else:
			self._fallback=False
			self._seconds=float(seconds)

	def __str__(self):
		if self._fallback:
			return "‒‒∶‒‒"
		else:
			seconds=int(self._seconds)
			days,seconds=divmod(seconds, 86400) # 86400 seconds make a day
			hours,seconds=divmod(seconds, 3600) # 3600 seconds make an hour
			minutes,seconds=divmod(seconds, 60)
			if days > 0:
				days_string=ngettext("{days} day", "{days} days", days).format(days=days)
				return f"{days_string}, {hours:02d}∶{minutes:02d}∶{seconds:02d}"
			elif hours > 0:
				return f"{hours}∶{minutes:02d}∶{seconds:02d}"
			else:
				return f"{minutes:02d}∶{seconds:02d}"

	def __float__(self):
		return self._seconds

class LastModified():
	def __init__(self, date):
		self._date=date

	def __str__(self):
		return GLib.DateTime.new_from_iso8601(self._date).to_local().format("%a %d %B %Y, %H∶%M")

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

class SongMetaclass(type(GObject.Object), type(collections.UserDict)): pass
class Song(collections.UserDict, GObject.Object, metaclass=SongMetaclass):
	widget=GObject.Property(type=Gtk.Widget, default=None)  # current widget representing the song in the UI
	def __init__(self, data):
		collections.UserDict.__init__(self, data)
		GObject.Object.__init__(self)
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

	def get_album_with_date(self):
		if "date" in self:
			return f"{self['album'][0]} ({self['date']})"
		else:
			return self["album"][0]

	def get_markup(self):
		if "artist" in self:
			title=f"<b>{GLib.markup_escape_text(self['title'][0])}</b> • {GLib.markup_escape_text(str(self['artist']))}"
		else:
			title=f"<b>{GLib.markup_escape_text(self['title'][0])}</b>"
		if "album" in self:
			return f"{title}\n<small>{GLib.markup_escape_text(self.get_album_with_date())}</small>"
		else:
			return f"{title}"

class BinaryCover(bytes):
	def get_paintable(self):
		try:
			paintable=Gdk.Texture.new_from_bytes(GLib.Bytes.new(self))
		except gi.repository.GLib.Error:  # load fallback if cover can't be loaded
			paintable=lookup_icon(FALLBACK_COVER, 1024)
		return paintable

class FileCover(str):
	def get_paintable(self):
		try:
			paintable=Gdk.Texture.new_from_filename(self)
		except gi.repository.GLib.Error:  # load fallback if cover can't be loaded
			paintable=lookup_icon(FALLBACK_COVER, 1024)
		return paintable

class EventEmitter(GObject.Object):
	__gsignals__={
		"updating_db": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"updated_db": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"disconnected": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"connected": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"connecting": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"connection_error": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"current_song": (GObject.SignalFlags.RUN_FIRST, None, (str,str,str,)),
		"state": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
		"elapsed": (GObject.SignalFlags.RUN_FIRST, None, (float,float,)),
		"volume": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
		"playlist": (GObject.SignalFlags.RUN_FIRST, None, (int,int,str)),
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
		self._start_idle_id=None
		self.music_directory=None
		self.current_cover=None
		self._bus=Gio.bus_get_sync(Gio.BusType.SESSION, None)  # used for "show in file manager"

	# overloads to use Song class
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
	def listplaylistinfo(self, name):
		return [Song(song) for song in super().listplaylistinfo(name)]

	def start(self):
		self.emitter.emit("connecting")
		def callback():
			if self._settings.get_boolean("socket-connection"):
				args=(self._settings.get_socket(), None)
			else:
				args=(self._settings.get_string("host"), self._settings.get_int("port"))
			try:
				self.connect(*args)
				if self._settings.get_string("password"):
					self.password(self._settings.get_string("password"))
			except:
				self.emitter.emit("connection_error")
				self._start_idle_id=None
				return False
			# connect successful
			if self._settings.get_boolean("socket-connection"):
				if "config" in self.commands():
					self.music_directory=self.config()
				else:
					print("No permission to get music directory.")
			else:
				self.music_directory=self._settings.get_music_directory()
			if "status" in self.commands():
				self.emitter.emit("connected")
				self._main_timeout_id=GLib.timeout_add(self._refresh_interval, self._main_loop)
			else:
				self.disconnect()
				self.emitter.emit("connection_error")
				print("No read permission, check your mpd config.")
			self._start_idle_id=None
			return False
		self._start_idle_id=GLib.idle_add(callback)

	def reconnect(self):
		if self._main_timeout_id is not None:
			GLib.source_remove(self._main_timeout_id)
			self._main_timeout_id=None
		if self._start_idle_id is not None:
			GLib.source_remove(self._start_idle_id)
			self._start_idle_id=None
		self.disconnect()
		self.start()

	def disconnect(self):
		super().disconnect()
		self._last_status={}
		self.emitter.emit("disconnected")

	def connected(self):
		try:
			self.ping()
			return True
		except:
			return False

	def tidy_playlist(self):
		status=self.status()
		song_number=status.get("song")
		if song_number is None:
			self.clear()
		else:
			self.move(song_number, 0)
			if int(status["playlistlength"]) > 1:
				self.delete((1,))

	def file_to_playlist(self, file, mode):  # modes: play, append, as_next
		if mode == "append":
			self.addid(file)
		elif mode == "play":
			self.clear()
			self.addid(file)
			self.play()
		elif mode == "as_next":
			self.addid(file, "+0")
		else:
			raise ValueError(f"Unknown mode: {mode}")

	def filter_to_playlist(self, tag_filter, mode):  # modes: play, append, enqueue
		if mode == "append":
			self.findadd(*tag_filter)
		elif mode == "play":
			self.clear()
			self.findadd(*tag_filter)
			self.play()
		elif mode == "enqueue":
			status=self.status()
			if (songid:=status.get("songid")) is None:
				self.clear()
				self.findadd(*tag_filter)
			else:
				self.moveid(songid, 0)
				if int(status["playlistlength"]) > 1:
					self.delete((1,))
				self.findadd(*tag_filter)
				duplicates=self.playlistfind("file", self.currentsong()["file"])
				if len(duplicates) > 1:
					self.swap(0, duplicates[1]["pos"])
					self.delete(0)
		else:
			raise ValueError(f"Unknown mode: {mode}")

	def album_to_playlist(self, albumartist, album, date, mode):
		self.filter_to_playlist(("albumartist", albumartist, "album", album, "date", date), mode)

	def get_cover_path(self, song):
		path=None
		song_file=song["file"]
		if self.music_directory is not None:
			regex_str=self._settings.get_string("regex")
			if regex_str:
				regex_str=regex_str.replace("%AlbumArtist%", re.escape(song["albumartist"][0]))
				regex_str=regex_str.replace("%Album%", re.escape(song["album"][0]))
				try:
					regex=re.compile(regex_str, flags=re.IGNORECASE)
				except re.error:
					print("illegal regex:", regex_str)
					return None
			else:
				regex=re.compile(FALLBACK_REGEX, flags=re.IGNORECASE)
			song_dir=os.path.join(self.music_directory, os.path.dirname(song_file))
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
		if (cover_path:=self.get_cover_path(song)) is not None:
			return FileCover(cover_path)
		elif (cover_binary:=self.get_cover_binary(song["file"])) is not None:
			return BinaryCover(cover_binary)
		else:
			return None

	def get_absolute_path(self, uri):
		if self.music_directory is not None:
			path=re.sub(r"(.*\.cue)\/track\d+$", r"\1", os.path.join(self.music_directory, uri), flags=re.IGNORECASE)
			if os.path.isfile(path):
				return path
			else:
				return None
		else:
			return None

	def can_show_in_file_manager(self, uri):
		try:
			self._bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "StartServiceByName",
				GLib.Variant("(su)",("org.freedesktop.FileManager1",0)), GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, -1, None)
		except GLib.GError:
			return False
		return self.get_absolute_path(uri) is not None

	def show_in_file_manager(self, uri):
		file=Gio.File.new_for_path(self.get_absolute_path(uri))
		self._bus.call_sync("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1",
			"ShowItems", GLib.Variant("(ass)", ((file.get_uri(),),"")), None, Gio.DBusCallFlags.NONE, -1, None)

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

	def _main_loop(self, *args):  # TODO fix order of signals
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
				elif key in ("state", "single", "audio"):
					self.emitter.emit(key, val)
				elif key == "volume":
					self.emitter.emit("volume", float(val))
				elif key == "playlist":
					self.emitter.emit("playlist", int(val), int(status["playlistlength"]), status.get("song"))
				elif key in ("repeat", "random", "consume"):
					if val == "1":
						self.emitter.emit(key, True)
					else:
						self.emitter.emit(key, False)
				elif key == "updating_db":
					self.emitter.emit("updating_db")
			if "songid" in dict(diff):
				self.current_cover=self.get_cover(self.currentsong())
				self.emitter.emit("current_song", status["song"], status["songid"], status["state"])
			diff=set(self._last_status)-set(status)
			for key in diff:
				if "songid" == key:
					self.current_cover=None
					self.emitter.emit("current_song", None, None, status["state"])
				elif "volume" == key:
					self.emitter.emit("volume", -1)
				elif "updating_db" == key:
					self.emitter.emit("updated_db")
				elif "bitrate" == key:
					self.emitter.emit("bitrate", None)
				elif "audio" == key:
					self.emitter.emit("audio", None)
			self._last_status=status
		except (ConnectionError, ConnectionResetError) as e:
			self.disconnect()
			self.emitter.emit("connection_error")
			self._main_timeout_id=None
			self.music_directory=None
			self.current_cover=None
			return False
		return True

########################
# gio settings wrapper #
########################

class Settings(Gio.Settings):
	BASE_KEY="org.mpdevil.mpdevil"
	# temp settings
	cursor_watch=GObject.Property(type=bool, default=False)
	def __init__(self):
		super().__init__(schema=self.BASE_KEY)

	def get_socket(self):
		socket=self.get_string("socket")
		if not socket:
			socket=FALLBACK_SOCKET
		return socket

	def get_music_directory(self):
		music_directory=self.get_string("music-directory")
		if not music_directory:
			music_directory=FALLBACK_MUSIC_DIRECTORY
		return music_directory

###################
# settings dialog #
###################

class ViewSettings(Adw.PreferencesGroup):
	def __init__(self, settings):
		super().__init__(title=_("View"))
		toggle_data=(
			(_("Use Client-side decoration"), "use-csd", _("restart required")),
			(_("Show stop button"), "show-stop", ""),
			(_("Show audio format"), "show-audio-format", ""),
			(_("Show lyrics button"), "show-lyrics-button", ""),
		)
		for title, key, subtitle in toggle_data:
			row=Adw.SwitchRow(title=title, subtitle=subtitle)
			settings.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
			self.add(row)
		int_data=(
			(_("Album view cover size"), (50, 600, 10), "album-cover"),
			(_("Action bar icon size"), (16, 64, 2), "icon-size"),
		)
		for title, (vmin, vmax, step), key in int_data:
			row=Adw.SpinRow.new_with_range(vmin, vmax, step)
			row.set_title(title)
			settings.bind(key, row, "value", Gio.SettingsBindFlags.DEFAULT)
			self.add(row)

class BehaviorSettings(Adw.PreferencesGroup):
	def __init__(self, settings):
		super().__init__(title=_("Behavior"))
		toggle_data=(
			(_("Support “MPRIS”"), "mpris", _("restart required")),
			(_("Sort albums by year"), "sort-albums-by-year", ""),
			(_("Send notification on title change"), "send-notify", ""),
			(_("Rewind via previous button"), "rewind-mode", ""),
			(_("Stop playback on quit"), "stop-on-quit", ""),
		)
		for title, key, subtitle in toggle_data:
			row=Adw.SwitchRow(title=title, subtitle=subtitle)
			settings.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
			self.add(row)

class ConnectionSettings(Adw.PreferencesGroup):
	def __init__(self, client, settings, parent):
		super().__init__(title=_("Connection"))

		socket_connect_row=Adw.SwitchRow(title=_("Connect via Unix domain socket"))
		settings.bind("socket-connection", socket_connect_row, "active", Gio.SettingsBindFlags.DEFAULT)
		self.add(socket_connect_row)

		socket_row=Adw.EntryRow(title=_("Socket Path"), show_apply_button=True)
		settings.bind("socket", socket_row, "text", Gio.SettingsBindFlags.DEFAULT)
		settings.bind("socket-connection", socket_row, "visible", Gio.SettingsBindFlags.GET)
		self.add(socket_row)

		port_row=Adw.SpinRow.new_with_range(0, 65535, 1)
		port_row.set_title(_("Port"))
		settings.bind("port", port_row, "value", Gio.SettingsBindFlags.DEFAULT)
		settings.bind("socket-connection", port_row, "visible", Gio.SettingsBindFlags.GET|Gio.SettingsBindFlags.INVERT_BOOLEAN)
		self.add(port_row)

		hostname_row=Adw.EntryRow(title=_("Hostname"))
		settings.bind("host", hostname_row, "text", Gio.SettingsBindFlags.DEFAULT)
		settings.bind("socket-connection", hostname_row, "visible", Gio.SettingsBindFlags.GET|Gio.SettingsBindFlags.INVERT_BOOLEAN)
		self.add(hostname_row)

		music_directory_row=Adw.EntryRow(title=_("Music Library"))
		settings.bind("music-directory", music_directory_row, "text", Gio.SettingsBindFlags.DEFAULT)
		settings.bind("socket-connection", music_directory_row, "visible", Gio.SettingsBindFlags.GET|Gio.SettingsBindFlags.INVERT_BOOLEAN)
		self.add(music_directory_row)

		regex_row=Adw.EntryRow(title=_("Regex"))
		regex_row.set_tooltip_text(
			_("The first image in the same directory as the song file "\
			"matching this regex will be displayed. %AlbumArtist% and "\
			"%Album% will be replaced by the corresponding tags of the song.")
		)
		settings.bind("regex", regex_row, "text", Gio.SettingsBindFlags.DEFAULT)
		self.add(regex_row)

		password_row=Adw.PasswordEntryRow(title=_("Password"))
		settings.bind("password", password_row, "text", Gio.SettingsBindFlags.DEFAULT)
		self.add(password_row)

		# connect button
		connect_button=Gtk.Button(label=_("Connect"))
		connect_button.add_css_class("suggested-action")
		connect_button.add_css_class("pill")
		connect_button.connect("clicked", lambda *args: client.reconnect())
		self.set_header_suffix(connect_button)

class SettingsDialog(Adw.PreferencesWindow):  # TODO open at specific setting
	def __init__(self, parent, client, settings, tab="view"):
		super().__init__(transient_for=parent)
		page=Adw.PreferencesPage()
		page.add(ViewSettings(settings))
		page.add(BehaviorSettings(settings))
		page.add(ConnectionSettings(client, settings, parent))
		self.add(page)

#################
# other dialogs #
#################

class ServerStats(Gtk.Window):
	def __init__(self, parent, client, settings):
		super().__init__(title=_("Stats"), transient_for=parent, resizable=False)
		if settings.get_boolean("use-csd"):
			self.set_titlebar(Gtk.HeaderBar())

		# grid
		grid=Gtk.Grid(row_spacing=6, column_spacing=12, margin_start=6, margin_end=6, margin_top=6, margin_bottom=6)

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
		stats["db_update"]=GLib.DateTime.new_from_unix_local(int(stats["db_update"])).format("%a %d %B %Y, %H∶%M")
		for i, key in enumerate(("protocol","uptime","playtime","db_update","db_playtime","artists","albums","songs")):
			grid.attach(Gtk.Label(label=display_str[key], use_markup=True, xalign=1), 0, i, 1, 1)
			grid.attach(Gtk.Label(label=stats[key], xalign=0), 1, i, 1, 1)

		# packing
		self.set_child(grid)

###########################
# general purpose widgets #
###########################

class AutoSizedIcon(Gtk.Image):
	def __init__(self, icon_name, settings_key, settings):
		super().__init__(icon_name=icon_name)
		settings.bind(settings_key, self, "pixel-size", Gio.SettingsBindFlags.GET)

class ListModel(GObject.Object, Gio.ListModel):
	def __init__(self, item_type):
		super().__init__()
		self.data=[]
		self._item_type=item_type

	def do_get_item(self, position):
		try:
			return self.data[position]
		except IndexError:
			return None

	def do_get_item_type(self):
		return self._item_type

	def do_get_n_items(self):
		return len(self.data)

class SelectionModel(ListModel, Gtk.SelectionModel):  # TODO
	def __init__(self, item_type):
		super().__init__(item_type)
		self._selected=None

	def clear(self, position=0):
		n=self.get_n_items()-position
		self.data=self.data[:position]
		if self._selected is not None:
			if self._selected >= self.get_n_items():
				self._selected=None
		self.items_changed(position, n, 0)

	def append(self, data):
		n=self.get_n_items()
		self.data.extend(data)
		self.items_changed(n, 0, self.get_n_items())

	def sort(self, **kwargs):
		self.unselect()
		self.data.sort(**kwargs)
		self.items_changed(0, self.get_n_items(), self.get_n_items())

	def get_selected(self):
		return self._selected

	def get_selected_song(self):
		return self.get_item(self.get_selected())

	def set(self, position, song):
		if position < len(self.data):
			self.data[position]=song
			self.items_changed(position, 1, 1)
		else:
			self.data.append(song)
			self.items_changed(position, 0, 1)

	def select(self, position):
		self.unselect()
		self._selected=position
		self.selection_changed(position, 1)

	def unselect(self):
		old_selected=self._selected
		self._selected=None
		if old_selected is not None:
			self.selection_changed(old_selected, 1)

	def do_select_all(self): return False
	def do_select_range(self, position, n_items, unselect_rest): return False
	def do_set_selection(self, selected, mask): return False
	def do_unselect_all(self): return False
	def do_unselect_item(self, position): return False
	def do_unselect_range(self, position, n_items): return False

	def do_get_selection_in_range(self, position, n_items):  # TODO
		return Gtk.Bitset.new_range(0, n_items)

	def do_is_selected(self, position):
		return position == self._selected

	def do_select_item(self, position, unselect_rest):
		return False

class SongMenu(Gtk.PopoverMenu):
	def __init__(self, client):
		super().__init__(has_arrow=False, halign=Gtk.Align.START)
		self._client=client
		self._file=None

		# action group
		action_group=Gio.SimpleActionGroup()
		action=Gio.SimpleAction.new("append", None)
		action.connect("activate", lambda *args: self._client.file_to_playlist(self._file, "append"))
		action_group.add_action(action)
		action=Gio.SimpleAction.new("as_next", None)
		action.connect("activate", lambda *args: self._client.file_to_playlist(self._file, "as_next"))
		action_group.add_action(action)
		action=Gio.SimpleAction.new("play", None)
		action.connect("activate", lambda *args: self._client.file_to_playlist(self._file, "play"))
		action_group.add_action(action)
		self._show_action=Gio.SimpleAction.new("show", None)
		self._show_action.connect("activate", lambda *args: self._client.show_in_file_manager(self._file))
		action_group.add_action(self._show_action)
		self.insert_action_group("menu", action_group)

		# menu model
		menu=Gio.Menu()
		menu.append(_("Append"), "menu.append")
		menu.append(_("As Next"), "menu.as_next")
		menu.append(_("Play"), "menu.play")
		subsection=Gio.Menu()
		subsection.append(_("Show"), "menu.show")
		menu.append_section(None, subsection)
		self.set_menu_model(menu)

	def open(self, file, x, y):
		self._file=file
		rect=Gdk.Rectangle()
		rect.x,rect.y=x,y
		self.set_pointing_to(rect)
		self._show_action.set_enabled(self._client.can_show_in_file_manager(file))
		self.popup()

class SongListRow(Gtk.Box):
	position=GObject.Property(type=int, default=-1)
	def __init__(self):
		super().__init__(can_target=False)  # can_target=False is needed to use Gtk.Widget.pick() in Gtk.ListView

		# labels
		attrs=Pango.AttrList()
		attrs.insert(Pango.AttrFontFeatures.new("tnum 1"))
		self._track=Gtk.Label(xalign=1, width_chars=3, attributes=attrs)
		self._title=Gtk.Label(use_markup=True, xalign=0, ellipsize=Pango.EllipsizeMode.END, hexpand=True)
		self._length=Gtk.Label(xalign=1, attributes=attrs)

		# packing
		self.append(self._track)
		self.append(self._title)
		self.append(self._length)

	def set_song(self, song):
		self._track.set_label(song["track"][0])
		self._title.set_label(song.get_markup())
		self._length.set_label(str(song["duration"]))

	def unset_song(self):
		self._track.set_label("")
		self._title.set_label("")
		self._length.set_label("")

class SongList(Gtk.ListView):
	def __init__(self):
		super().__init__(single_click_activate=True, tab_behavior=Gtk.ListTabBehavior.ITEM, css_classes=["rich-list"])
		self.set_model(SelectionModel(Song))

		# factory
		def setup(factory, item):
			item.set_child(SongListRow())
		def bind(factory, item):
			row=item.get_child()
			song=item.get_item()
			row.set_song(song)
			song.set_property("widget", row)
			row.set_property("position", item.get_position())
		def unbind(factory, item):
			row=item.get_child()
			song=item.get_item()
			row.unset_song()
			song.set_property("widget", None)
			row.set_property("position", -1)
		factory=Gtk.SignalListItemFactory()
		factory.connect("setup", setup)
		factory.connect("bind", bind)
		factory.connect("unbind", unbind)
		self.set_factory(factory)

	def _get_focus_row(self):
		return self.get_focus_child().get_first_child()

	def get_focus_popup_point(self):
		return self._get_focus_row().translate_coordinates(self, 0, 0)

	def get_focus_position(self):
		return self._get_focus_row().get_property("position")

	def get_focus_song(self):
		return self.get_model().get_item(self.get_focus_position())

	def get_position_at(self, x, y):
		item=self.pick(x,y,Gtk.PickFlags.DEFAULT)
		if item is self:
			return None
		return item.get_first_child().get_property("position")

class BrowserSongList(SongList):
	def __init__(self, client):
		super().__init__()
		self._client=client

		# menu
		self._menu=SongMenu(client)
		self._menu.set_parent(self)

		# action group
		action_group=Gio.SimpleActionGroup()
		action=Gio.SimpleAction.new("menu", None)
		action.connect("activate", self._on_menu)
		action_group.add_action(action)
		self.insert_action_group("view", action_group)

		# shortcuts
		self.add_shortcut(Gtk.Shortcut.new(Gtk.KeyvalTrigger.new(Gdk.KEY_Menu, 0), Gtk.NamedAction.new("view.menu")))
		self.add_shortcut(Gtk.Shortcut.new(Gtk.KeyvalTrigger.new(Gdk.KEY_F10, Gdk.ModifierType.SHIFT_MASK), Gtk.NamedAction.new("view.menu")))

		# event controller
		button_controller=Gtk.GestureClick(button=0)
		self.add_controller(button_controller)
		drag_source=Gtk.DragSource()
		drag_source.set_icon(lookup_icon("audio-x-generic", 32, self.get_scale_factor()), 0, 0)
		self.add_controller(drag_source)

		# connect
		self.connect("activate", self._on_activate)
		button_controller.connect("released", self._on_button_released)
		drag_source.connect("prepare", self._on_drag_prepare)

	def clear(self):
		self._menu.popdown()
		self.get_model().clear()

	def append(self, data):
		self.get_model().append(data)

	def _on_activate(self, listview, pos):
		self._client.file_to_playlist(self.get_model().get_item(pos)["file"], "play")

	def _on_button_released(self, controller, n_press, x, y):
		item=self.pick(x,y,Gtk.PickFlags.DEFAULT)
		if item is not self:
			row=item.get_first_child()
			song=self.get_model().get_item(row.get_property("position"))
			if controller.get_current_button() == 2 and n_press == 1:
				self._client.file_to_playlist(song["file"], "append")
			elif controller.get_current_button() == 3 and n_press == 1:
				self._menu.open(song["file"], x, y)

	def _on_menu(self, action, state):
		self._menu.open(self.get_focus_song()["file"], *self.get_focus_popup_point())

	def _on_drag_prepare(self, drag_source, x, y):
		if (position:=self.get_position_at(x,y)) is not None:
			return Gdk.ContentProvider.new_for_value(self.get_model().get_item(position))

##########
# search #
##########

class SearchThread(threading.Thread):  # TODO progress indicator
	def __init__(self, client, search_entry, songs_list, hits_label, search_tag):
		super().__init__(daemon=True)
		self._client=client
		self._search_entry=search_entry
		self._songs_list=songs_list
		self._hits_label=hits_label
		self._search_tag=search_tag
		self._stop_flag=False
		self._callback=None

	def set_callback(self, callback):
		self._callback=callback

	def stop(self):
		self._stop_flag=True

	def start(self):
		self._songs_list.clear()
		self._hits_label.set_text("")
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
			if self._stop_flag:
				self._exit()
				return
			hits+=len(songs)
			idle_add(self._songs_list.append, songs)
			idle_add(self._hits_label.set_text, ngettext("{hits} hit", "{hits} hits", hits).format(hits=hits))
			stripe_end=stripe_start+stripe_size
			songs=self._get_songs(stripe_start, stripe_end)
			stripe_start=stripe_end
		self._exit()

	def _exit(self):
		def callback():
			if self._callback is not None:
				self._callback()
			return False
		idle_add(callback)

	@main_thread_function
	def _get_songs(self, start, end):
		if self._stop_flag:
			return []
		else:
			self._client.restrict_tagtypes("track", "title", "artist", "album", "date")
			songs=self._client.search(self._search_tag, self._search_text, "window", f"{start}:{end}")
			self._client.tagtypes("all")
			return songs

class SearchWindow(Gtk.Box):
	def __init__(self, client):
		super().__init__(orientation=Gtk.Orientation.VERTICAL)
		self._client=client

		# widgets
		self._tag_list=Gtk.StringList()
		self._tag_drop_down=Gtk.DropDown(model=self._tag_list)
		self.search_entry=Gtk.SearchEntry(max_width_chars=20)  # TODO truncate_multiline=True
		self._hits_label=Gtk.Label(xalign=1, ellipsize=Pango.EllipsizeMode.END)

		# songs list
		self._songs_list=BrowserSongList(self._client)

		# search thread
		self._search_thread=SearchThread(self._client, self.search_entry, self._songs_list, self._hits_label, "any")

		# event controller
		controller_focus=Gtk.EventControllerFocus()
		self.search_entry.add_controller(controller_focus)

		# connect
		self.search_entry.connect("activate", self._search)
		self._search_entry_changed=self.search_entry.connect("search-changed", self._search)
		self._tag_drop_down_changed=self._tag_drop_down.connect("notify::selected", self._search)
		controller_focus.connect("enter", self._on_search_entry_focus_event, True)
		controller_focus.connect("leave", self._on_search_entry_focus_event, False)
		self._client.emitter.connect("connected", self._on_connected)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("updated_db", self._search)

		# packing
		hbox=Gtk.CenterBox(margin_start=6, margin_end=6, margin_top=6, margin_bottom=6)
		hbox.set_start_widget(self._tag_drop_down)
		hbox.set_center_widget(self.search_entry)
		hbox.set_end_widget(self._hits_label)
		self.append(hbox)
		self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
		self.append(Gtk.ScrolledWindow(child=self._songs_list, vexpand=True))

	def _on_disconnected(self, *args):
		self._search_thread.stop()

	def _on_connected(self, *args):
		def callback():
			self._songs_list.clear()
			self._hits_label.set_text("")
			self.search_entry.handler_block(self._search_entry_changed)
			self.search_entry.set_text("")
			self.search_entry.handler_unblock(self._search_entry_changed)
			self._tag_drop_down.handler_block(self._tag_drop_down_changed)
			for i in range(len(self._tag_list)):
				self._tag_list.remove(0)
			self._tag_list.append(_("all tags"))
			for tag in self._client.tagtypes():
				if not tag.startswith("MUSICBRAINZ"):
					self._tag_list.append(tag)
			self._tag_drop_down.set_selected(0)
			self._tag_drop_down.handler_unblock(self._tag_drop_down_changed)
		if self._search_thread.is_alive():
			self._search_thread.set_callback(callback)
			self._search_thread.stop()
		else:
			callback()

	def _search(self, *args):
		def callback():
			if (selected:=self._tag_drop_down.get_selected()) == 0:
				search_tag="any"
			else:
				search_tag=self._tag_list.get_string(selected)
			self._search_thread=SearchThread(self._client, self.search_entry, self._songs_list, self._hits_label, search_tag)
			self._search_thread.start()
		if self._search_thread.is_alive():
			self._search_thread.set_callback(callback)
			self._search_thread.stop()
		else:
			callback()

	def _on_search_entry_focus_event(self, controller, focus):
		app=self.get_root().get_application()
		if focus:
			app.set_accels_for_action("mpd.toggle-play", [])
		else:
			app.set_accels_for_action("mpd.toggle-play", ["space"])

###########
# browser #
###########

class Artist(GObject.Object):
	def __init__(self, name, section_name, section_start):
		GObject.Object.__init__(self)
		self.name=name
		self.section_name=section_name
		self.section_start=section_start

class ArtistSelectionModel(ListModel, Gtk.SelectionModel, Gtk.SectionModel):
	__gsignals__={"selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
			"reselected": (GObject.SignalFlags.RUN_FIRST, None, ()),
			"clear": (GObject.SignalFlags.RUN_FIRST, None, ())}
	def __init__(self):
		super().__init__(Artist)
		self._selected=None

	def clear(self):
		n=self.get_n_items()
		self.data=[]
		self._selected=None
		self.items_changed(0, n, 0)
		self.emit("clear")

	def set_artists(self, artists):
		self.clear()
		letters="ABCDEFGHIJKLMNOPQRSTUVWXYZ"
		artists.extend(zip([""]*len(letters), letters))
		artists.sort(key=lambda item: locale.strxfrm(item[1]))
		char="#"
		section_start=0
		section_length=0
		for item in artists:
			if item[0]:
				self.data.append(Artist(item[0], char, section_start))
				section_length+=1
			else:
				char=item[1]
				section_start+=section_length
				section_length=0
		self.items_changed(0, 0, self.get_n_items())

	def get_selected(self):
		return self._selected

	def get_selected_artist(self):
		if self._selected is None:
			return None
		return self.data[self._selected].name

	def select_artist(self, name):
		row_num=self.get_n_items()
		for i in range(0, row_num):
			if self.data[i].name == name:
				self.select_item(i, True)
				return

	def do_select_all(self): return False
	def do_select_range(self, position, n_items, unselect_rest): return False
	def do_set_selection(self, selected, mask): return False
	def do_unselect_all(self): return False
	def do_unselect_item(self, position): return False
	def do_unselect_range(self, position, n_items): return False

	def do_get_selection_in_range(self, position, n_items):  # TODO
		return Gtk.Bitset.new_range(0, n_items)

	def do_is_selected(self, position):
		return position == self._selected

	def do_select_item(self, position, unselect_rest):
		if position < self.get_n_items():
			if position == self._selected:
				self.emit("reselected")
			else:
				old_selected=self._selected
				self._selected=position
				if old_selected is not None:
					self.selection_changed(old_selected, 1)
				self.selection_changed(position, 1)
				self.emit("selected", self.data[position].name)
			return True
		else:
			return False

	def do_get_section(self, position):
		if position < self.get_n_items():
			section_start=self.data[position].section_start
			for artist in self.data[position+1:]:
				if artist.section_start > section_start:
					return (section_start, artist.section_start)
			return (section_start, self.get_n_items())
		else:
			return (self.get_n_items(), GObject.G_MAXUINT)

class ArtistList(Gtk.ListView):
	def __init__(self, client, settings):
		super().__init__(tab_behavior=Gtk.ListTabBehavior.ITEM, css_classes=["rich-list"])
		self._client=client
		self._settings=settings

		# factory
		def setup(factory, item):
			label=Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, valign=Gtk.Align.FILL, vexpand=True)
			item.set_child(label)
		def bind(factory, item):
			label=item.get_child()
			label.set_label(item.get_item().name)
		factory=Gtk.SignalListItemFactory()
		factory.connect("setup", setup)
		factory.connect("bind", bind)
		self.set_factory(factory)

		# header factory
		def header_setup(factory, item):
			label=Gtk.Label(xalign=0)
			item.set_child(label)
		def header_bind(factory, item):
			label=item.get_child()
			label.set_label(item.get_item().section_name)
		header_factory=Gtk.SignalListItemFactory()
		header_factory.connect("setup", header_setup)
		header_factory.connect("bind", header_bind)
		self.set_header_factory(header_factory)

		# model
		self.artist_selection_model=ArtistSelectionModel()
		self.set_model(self.artist_selection_model)

		# connect
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)
		self._client.emitter.connect("updated_db", self._on_updated_db)

	def _select(self, name):
		self.artist_selection_model.select_artist(name)
		self.scroll_to(self.artist_selection_model.get_selected(), Gtk.ListScrollFlags.FOCUS, None)

	def _refresh(self):
		artists=self._client.list("albumartistsort", "group", "albumartist")
		filtered_artists=[]
		for name, artist in itertools.groupby(((artist["albumartist"], artist["albumartistsort"]) for artist in artists), key=lambda x: x[0]):
			filtered_artists.append(next(artist))
			# ignore multiple albumartistsort values
			if next(artist, None) is not None:
				filtered_artists[-1]=(name, name)
		self.artist_selection_model.set_artists(filtered_artists)

	def _on_disconnected(self, *args):
		self.set_sensitive(False)
		self.artist_selection_model.clear()

	def _on_connected(self, *args):
		self._refresh()
		if (song:=self._client.currentsong()):
			artist=song["albumartist"][0]
			self._select(artist)
		else:
			self.scroll_to(0, Gtk.ListScrollFlags.SELECT|Gtk.ListScrollFlags.FOCUS, None)
		self.set_sensitive(True)

	def _on_updated_db(self, *args):
		if self.artist_selection_model.get_selected_artist() is None:
			self._refresh()
		else:
			artist=self.artist_selection_model.get_selected_artist()
			self._refresh()
			self._select(artist)

class Album(GObject.Object):
	def __init__(self, artist, name, sortname, date):
		GObject.Object.__init__(self)
		self.artist=artist
		self.name=name
		self.sortname=sortname
		self.date=date
		self.cover=None

class AlbumListRow(Gtk.Box):
	def __init__(self, client):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6, margin_top=6, margin_bottom=6)
		self._client=client
		self._cover=Gtk.Image(hexpand=True)
		self._label=Gtk.Label(use_markup=True, justify=Gtk.Justification.CENTER, wrap=True)
		self.append(self._cover)
		self.append(self._label)

	def set_album(self, album):
		if album.date:
			display_label=f"<b>{GLib.markup_escape_text(album.name)}</b> ({GLib.markup_escape_text(album.date)})"
		else:
			display_label=f"<b>{GLib.markup_escape_text(album.name)}</b>"
		self._label.set_label(display_label)
		if album.cover is None:
			self._client.restrict_tagtypes("albumartist", "album")
			song=self._client.find("albumartist", album.artist, "album", album.name, "date", album.date, "window", "0:1")[0]
			self._client.tagtypes("all")
			if (cover:=self._client.get_cover(song)) is None:
				album.cover=lookup_icon(FALLBACK_COVER, 1024)
			else:
				album.cover=cover.get_paintable()
		self._cover.set_from_paintable(album.cover)

class AlbumList(Gtk.GridView):
	__gsignals__={"album-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,str,str,))}
	def __init__(self, client, settings):
		super().__init__(tab_behavior=Gtk.ListTabBehavior.ITEM, single_click_activate=True, vexpand=True)
		self._settings=settings
		self._client=client

		# factory
		def setup(factory, item):
			item.set_child(AlbumListRow(self._client))
		def bind(factory, item):
			row=item.get_child()
			row.set_album(item.get_item())
			settings.bind("album-cover", row._cover, "height-request", Gio.SettingsBindFlags.GET)
			settings.bind("album-cover", row._cover, "width-request", Gio.SettingsBindFlags.GET)
		def unbind(factory, item):
			row=item.get_child()
			settings.unbind(row._cover, "height-request")
			settings.unbind(row._cover, "width-request")
		factory=Gtk.SignalListItemFactory()
		factory.connect("setup", setup)
		factory.connect("bind", bind)
		factory.connect("unbind", unbind)
		self.set_factory(factory)

		# model
		self._selection_model=SelectionModel(Album)
		self.set_model(self._selection_model)

		# connect
		self.connect("activate", self._on_activate)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)
		self._settings.connect("changed::sort-albums-by-year", self._sort_settings)

	def clear(self, *args):
		self._selection_model.clear()

	def _get_albums(self, artist):
		albums=self._client.list("albumsort", "albumartist", artist, "group", "date", "group", "album")
		for _, album in itertools.groupby(albums, key=lambda x: (x["album"], x["date"])):
			tmp=next(album)
			# ignore multiple albumsort values
			if next(album, None) is None:
				yield Album(artist, tmp["album"], tmp["albumsort"], tmp["date"])
			else:
				yield Album(artist, tmp["album"], tmp["album"], tmp["date"])

	def _sort_settings(self, *args):
		if self._settings.get_boolean("sort-albums-by-year"):
			self._selection_model.sort(key=lambda item: item.date)
		else:
			self._selection_model.sort(key=lambda item: locale.strxfrm(item.sortname))

	def display(self, artist):
		self._settings.set_property("cursor-watch", True)
		self._selection_model.clear()
		# ensure list is empty
		main=GLib.main_context_default()
		while main.pending():
			main.iteration()
		if self._settings.get_boolean("sort-albums-by-year"):
			self._selection_model.append(sorted(self._get_albums(artist), key=lambda item: item.date))
		else:
			self._selection_model.append(sorted(self._get_albums(artist), key=lambda item: locale.strxfrm(item.sortname)))
		self._settings.set_property("cursor-watch", False)

	def _on_activate(self, widget, pos):
		album=self._selection_model.get_item(pos)
		self.emit("album-selected", album.artist, album.name, album.date)

	def _on_disconnected(self, *args):
		self.set_sensitive(False)

	def _on_connected(self, *args):
		self.set_sensitive(True)

class AlbumView(Gtk.Box):
	__gsignals__={"close": (GObject.SignalFlags.RUN_FIRST, None, ())}
	def __init__(self, client, settings):
		super().__init__(orientation=Gtk.Orientation.VERTICAL)
		self._client=client
		self._settings=settings
		self._tag_filter=()

		# songs list
		self.songs_list=BrowserSongList(self._client)
		scroll=Gtk.ScrolledWindow(child=self.songs_list, vexpand=True)
		scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

		# buttons
		self._buttons=Gtk.Box(css_classes=["linked"], halign=Gtk.Align.END)
		data=((_("Append"), "list-add-symbolic", "append"),
			(_("Play"), "media-playback-start-symbolic", "play")
		)
		for tooltip, icon_name, mode in data:
			button=Gtk.Button(icon_name=icon_name)
			button.set_tooltip_text(tooltip)
			button.connect("clicked", self._on_button_clicked, mode)
			self._buttons.append(button)

		# cover
		self._cover=Gtk.Image()

		# labels
		self._title=Gtk.Label(margin_start=12, margin_end=12, xalign=0, wrap=True, vexpand=True)
		self._duration=Gtk.Label(xalign=1, ellipsize=Pango.EllipsizeMode.END)

		# event controller
		button1_controller=Gtk.GestureClick(button=1)
		self._cover.add_controller(button1_controller)

		# connect
		button1_controller.connect("released", self._on_button1_released)

		# packing
		hbox=Gtk.Box(spacing=12, halign=Gtk.Align.END)
		hbox.append(self._duration)
		hbox.append(self._buttons)
		vbox=Gtk.CenterBox(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6, margin_top=6, margin_bottom=6, hexpand=True)
		vbox.set_center_widget(self._title)
		vbox.set_end_widget(hbox)
		header=Gtk.Box()
		header.append(self._cover)
		header.append(Gtk.Separator())
		header.append(vbox)
		self.append(header)
		self.append(Gtk.Separator())
		self.append(scroll)

	def display(self, albumartist, album, date):
		if date:
			self._title.set_markup(f"<b>{GLib.markup_escape_text(album)}</b> ({GLib.markup_escape_text(date)})\n"
				f"{GLib.markup_escape_text(albumartist)}")
		else:
			self._title.set_markup(f"<b>{GLib.markup_escape_text(album)}</b>\n{GLib.markup_escape_text(albumartist)}")
		self.songs_list.clear()
		self._tag_filter=("albumartist", albumartist, "album", album, "date", date)
		count=self._client.count(*self._tag_filter)
		duration=str(Duration(count["playtime"]))
		length=int(count["songs"])
		text=ngettext("{number} song ({duration})", "{number} songs ({duration})", length).format(number=length, duration=duration)
		self._duration.set_text(text)
		self._client.restrict_tagtypes("track", "title", "artist")
		songs=self._client.find(*self._tag_filter)
		self._client.tagtypes("all")
		self.songs_list.append(songs)
		size=self._settings.get_int("album-cover")*1.5
		if (cover:=self._client.get_cover({"file": songs[0]["file"], "albumartist": albumartist, "album": album})) is None:
			self._cover.set_from_paintable(lookup_icon(FALLBACK_COVER, 1024))
		else:
			self._cover.set_from_paintable(cover.get_paintable())
		self._cover.set_size_request(size, size)

	def _on_button1_released(self, controller, n_press, x, y):
		if self._cover.contains(x, y):
			self.emit("close")

	def _on_button_clicked(self, widget, mode):
		self._client.filter_to_playlist(self._tag_filter, mode)

class Browser(Gtk.Paned):
	def __init__(self, client, settings):
		super().__init__(resize_start_child=False, shrink_start_child=False, resize_end_child=True, shrink_end_child=False)
		self._client=client
		self._settings=settings

		# widgets
		self._artist_list=ArtistList(self._client, self._settings)
		self._album_list=AlbumList(self._client, self._settings)
		artist_window=Gtk.ScrolledWindow(child=self._artist_list)
		album_window=Gtk.ScrolledWindow(child=self._album_list)
		self._album_view=AlbumView(self._client, self._settings)

		# album stack
		self._album_stack=Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT, hhomogeneous=False, vhomogeneous=False)
		self._album_stack.add_named(album_window, "album_list")
		self._album_stack.add_named(self._album_view, "album_view")

		# connect
		self._album_list.connect("album-selected", self._on_album_selected)
		self._album_view.connect("close", lambda *args: self._album_stack.set_visible_child_name("album_list"))
		self._artist_list.artist_selection_model.connect("selected", self._on_artist_selected)
		self._artist_list.artist_selection_model.connect("reselected", lambda *args: self._album_stack.set_visible_child_name("album_list"))
		self._artist_list.artist_selection_model.connect("clear", self._album_list.clear)
		self._client.emitter.connect("disconnected", lambda *args: self._album_stack.set_visible_child_name("album_list"))
		self._settings.connect("changed::album-cover", lambda *args: self._album_stack.set_visible_child_name("album_list"))

		# packing
		self.set_start_child(artist_window)
		self.set_end_child(self._album_stack)

	def back(self):
		if self._album_stack.get_visible_child_name() == "album_view":
			self._album_stack.set_visible_child_name("album_list")

	def _on_artist_selected(self, obj, artist):
		self._album_stack.set_visible_child_name("album_list")
		self._album_list.display(artist)

	def _on_album_selected(self, widget, *tags):
		self._album_view.display(*tags)
		self._album_stack.set_visible_child_name("album_view")
		self._album_view.songs_list.grab_focus()

############
# playlist #
############

class PlaylistMenu(Gtk.PopoverMenu):  # TODO
	def __init__(self, client):
		super().__init__(has_arrow=False, halign=Gtk.Align.START)
		self._client=client
		self._file=None
		self._position=None

		# action group
		action_group=Gio.SimpleActionGroup()
		self._remove_action=Gio.SimpleAction.new("remove", None)
		self._remove_action.connect("activate", lambda *args: self._client.delete(self._position))
		action_group.add_action(self._remove_action)
		self._show_action=Gio.SimpleAction.new("show", None)
		self._show_action.connect("activate", lambda *args: self._client.show_in_file_manager(self._file))
		action_group.add_action(self._show_action)
		self.insert_action_group("menu", action_group)

		# menu model
		menu=Gio.Menu()
		menu.append(_("Remove"), "menu.remove")
		menu.append(_("Show"), "menu.show")
		current_song_section=Gio.Menu()
		current_song_section.append(_("Enqueue Album"), "mpd.enqueue")
		current_song_section.append(_("Tidy"), "mpd.tidy")
		subsection=Gio.Menu()
		subsection.append(_("Clear"), "mpd.clear")
		menu.append_section(None, current_song_section)
		menu.append_section(None, subsection)
		self.set_menu_model(menu)

	def open(self, file, position, x, y):
		self._file=file
		self._position=position
		rect=Gdk.Rectangle()
		rect.x,rect.y=x,y
		self.set_pointing_to(rect)
		if file is None or position is None:
			self._remove_action.set_enabled(False)
			self._show_action.set_enabled(False)
		else:
			self._remove_action.set_enabled(True)
			self._show_action.set_enabled(self._client.can_show_in_file_manager(file))
		self.popup()

class PlaylistView(SongList):
	def __init__(self, client, settings):
		super().__init__()
		self._client=client
		self._settings=settings
		self._playlist_version=None

		# menu
		self._menu=PlaylistMenu(client)
		self._menu.set_parent(self)

		# action group
		action_group=Gio.SimpleActionGroup()
		action=Gio.SimpleAction.new("menu", None)
		action.connect("activate", self._on_menu)
		action_group.add_action(action)
		action=Gio.SimpleAction.new("delete", None)
		action.connect("activate", self._on_delete)
		action_group.add_action(action)
		self.insert_action_group("view", action_group)

		# shortcuts
		self.add_shortcut(Gtk.Shortcut.new(Gtk.KeyvalTrigger.new(Gdk.KEY_Menu, 0), Gtk.NamedAction.new("view.menu")))
		self.add_shortcut(Gtk.Shortcut.new(Gtk.KeyvalTrigger.new(Gdk.KEY_F10, Gdk.ModifierType.SHIFT_MASK), Gtk.NamedAction.new("view.menu")))
		self.add_shortcut(Gtk.Shortcut.new(Gtk.KeyvalTrigger.new(Gdk.KEY_Delete, 0), Gtk.NamedAction.new("view.delete")))

		# event controller
		button_controller=Gtk.GestureClick(button=0)
		self.add_controller(button_controller)
		drag_source=Gtk.DragSource()
		drag_source.set_icon(lookup_icon("audio-x-generic", 32, self.get_scale_factor()), 0, 0)
		drag_source.set_actions(Gdk.DragAction.MOVE)
		self.add_controller(drag_source)
		drop_target=Gtk.DropTarget()
		drop_target.set_actions(Gdk.DragAction.COPY|Gdk.DragAction.MOVE)
		drop_target.set_gtypes((int,Song,))
		self.add_controller(drop_target)

		# connect
		self.connect("activate", self._on_activate)
		button_controller.connect("pressed", self._on_button_pressed)
		drag_source.connect("prepare", self._on_drag_prepare)
		drop_target.connect("drop", self._on_drop)
		self._client.emitter.connect("playlist", self._on_playlist_changed)
		self._client.emitter.connect("current_song", self._on_song_changed)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)

	def _clear(self, *args):
		self._menu.popdown()
		self._playlist_version=None
		self.get_model().clear()

	def _delete(self, position):
		if position == self.get_model().get_selected():
			self._client.tidy_playlist()
		else:
			self._client.delete(position)

	def _scroll_to_path(self, path):
		self.set_cursor(path, None, False)
		self.save_scroll_to_cell(path, None, True, 0.25)

	def _refresh_selection(self, song):
		if song is None:
			self.get_model().unselect()
		else:
			self.get_model().select(int(song))

	def _on_button_pressed(self, controller, n_press, x, y):
		if (position:=self.get_position_at(x,y)) is None:
			if controller.get_current_button() == 3 and n_press == 1:
				self._menu.open(None, None, x, y)
		else:
			if controller.get_current_button() == 2 and n_press == 1:
				self._delete(position)
			elif controller.get_current_button() == 3 and n_press == 1:
				song=self.get_model().get_item(position)
				self._menu.open(song["file"], position, x, y)

	def _on_activate(self, listview, pos):
		self._client.play(pos)

	def _on_playlist_changed(self, emitter, version, length, song_pos):
		self._menu.popdown()
		self._client.restrict_tagtypes("track", "title", "artist", "album", "date")
		songs=[]
		if self._playlist_version is not None:
			songs=self._client.plchanges(self._playlist_version)
		else:
			songs=self._client.playlistinfo()
		self._client.tagtypes("all")
		for song in songs:
			self.get_model().set(int(song["pos"]), song)
		self.get_model().clear(length)
		self._refresh_selection(song_pos)
		self._playlist_version=version

	def _on_song_changed(self, emitter, song, songid, state):
		self._refresh_selection(song)
		if (selected:=self.get_model().get_selected()) is not None:
			self.scroll_to(selected, Gtk.ListScrollFlags.FOCUS, None)

	def _on_menu(self, action, state):
		self._menu.open(self.get_focus_song()["file"], self.get_focus_position(), *self.get_focus_popup_point())

	def _on_delete(self, action, state):
		self._delete(self.get_focus_position())

	def _on_drag_prepare(self, drag_source, x, y):
		if (position:=self.get_position_at(x,y)) is not None:
			return Gdk.ContentProvider.new_for_value(position)

	def _on_drop(self, drop_target, value, x, y):  # TODO
		item=self.pick(x,y,Gtk.PickFlags.DEFAULT)
		if isinstance(value, int):
			if item is not self:
				row=item.get_first_child()
				position=row.get_property("position")
				if value == position:
					return False
				if value < position:
					position-=1
				if self.translate_coordinates(item, x, y)[1] > item.get_height()/2:
					position+=1
			else:
				position=self.get_model().get_n_items()-1
			if value == position:
				return False
			self._client.move(value, position)
			return True
		elif isinstance(value, Song):
			if item is not self:
				row=item.get_first_child()
				position=row.get_property("position")
				if self.translate_coordinates(item, x, y)[1] > item.get_height()/2:
					position+=1
			else:
				position=self.get_model().get_n_items()
			self._client.addid(value["file"], position)
			return True
		return False

	def _on_disconnected(self, *args):
		self.set_sensitive(False)
		self._clear()

	def _on_connected(self, *args):
		self.set_sensitive(True)

class PlaylistWindow(Gtk.ScrolledWindow):  # TODO scroll to song
	def __init__(self, client, settings):
		super().__init__(hexpand=True, vexpand=True)
		self.set_child(PlaylistView(client, settings))

####################
# cover and lyrics #
####################

class LetrasParser(HTMLParser):
	def __init__(self):
		super().__init__()
		self._found_text=False
		self.text=""

	def handle_starttag(self, tag, attrs):
		if tag == "div" and ("id", "letra-cnt") in attrs:
			self._found_text=True

	def handle_endtag(self, tag):
		if self._found_text:
			if tag == "p":
				self.text+="\n"
			elif tag == "div":
				self._found_text=False

	def handle_data(self, data):
		if self._found_text and data:
			self.text+=data+"\n"

class LyricsWindow(Gtk.ScrolledWindow):  # TODO zoom
	def __init__(self, client, settings):
		super().__init__()
		self._settings=settings
		self._client=client
		self._displayed_song_file=None

		# text view
		self._text_view=Gtk.TextView(
			editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD,
			justification=Gtk.Justification.CENTER,
			left_margin=5, right_margin=5, bottom_margin=5, top_margin=3
		)

		# text buffer
		self._text_buffer=self._text_view.get_buffer()

		# connect
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._song_changed=self._client.emitter.connect("current_song", self._refresh)
		self._client.emitter.handler_block(self._song_changed)

		# packing
		self.set_child(self._text_view)

	def enable(self, *args):
		if (song:=self._client.currentsong()):
			if song["file"] != self._displayed_song_file:
				self._refresh()
		else:
			if self._displayed_song_file is not None:
				self._refresh()
		self._client.emitter.handler_unblock(self._song_changed)
		self._text_view.grab_focus()

	def disable(self, *args):
		self._client.emitter.handler_block(self._song_changed)

	def _get_lyrics(self, title, artist):
		title=urllib.parse.quote_plus(title)
		artist=urllib.parse.quote_plus(artist)
		parser=LetrasParser()
		with urllib.request.urlopen(f"https://www.letras.mus.br/winamp.php?musica={title}&artista={artist}") as response:
			parser.feed(response.read().decode("utf-8"))
		if not parser.text:
			raise ValueError("Not found")
		return parser.text.strip("\n ")

	def _display_lyrics(self, song):
		idle_add(self._text_buffer.set_text, _("searching…"), -1)
		try:
			text=self._get_lyrics(song["title"][0], song["artist"][0])
		except urllib.error.URLError:
			self._displayed_song_file=None
			text=_("connection error")
		except ValueError:
			text=_("lyrics not found")
		idle_add(self._text_buffer.set_text, text, -1)

	def _refresh(self, *args):
		if (song:=self._client.currentsong()):
			self._displayed_song_file=song["file"]
			update_thread=threading.Thread(
					target=self._display_lyrics,
					kwargs={"song": song},
					daemon=True
			)
			update_thread.start()
		else:
			self._displayed_song_file=None
			self._text_buffer.set_text("", -1)

	def _on_disconnected(self, *args):
		self._displayed_song_file=None
		self._text_buffer.set_text("", -1)

class MainCover(Gtk.Picture):
	def __init__(self, client):
		super().__init__()
		self._client=client

		# connect
		self._client.emitter.connect("current_song", self._refresh)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)

	def _clear(self):
		self.set_paintable(lookup_icon(FALLBACK_COVER, 1024))

	def _refresh(self, *args):
		if self._client.current_cover is None:
			self._clear()
		else:
			self.set_paintable(self._client.current_cover.get_paintable())

	def _on_disconnected(self, *args):
		self.set_sensitive(False)
		self._clear()

	def _on_connected(self, *args):
		self.set_sensitive(True)

class CoverLyricsWindow(Gtk.Overlay):
	def __init__(self, client, settings):
		super().__init__()
		self._client=client
		self._settings=settings

		# cover
		main_cover=MainCover(self._client)
		self._window_handle=Gtk.WindowHandle(child=main_cover)

		# lyrics button
		self.lyrics_button=Gtk.ToggleButton(icon_name="org.mpdevil.mpdevil-lyrics-symbolic", tooltip_text=_("Lyrics"), can_focus=False)
		self.lyrics_button.add_css_class("osd")
		self.lyrics_button.add_css_class("circular")

		# lyrics window
		self._lyrics_window=LyricsWindow(self._client, self._settings)

		# revealer
		self._lyrics_button_revealer=Gtk.Revealer(
			child=self.lyrics_button, transition_duration=0, margin_top=6, margin_end=6, halign=Gtk.Align.END, valign=Gtk.Align.START)
		self._settings.bind("show-lyrics-button", self._lyrics_button_revealer, "reveal-child", Gio.SettingsBindFlags.DEFAULT)

		# stack
		self._stack=Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
		self._stack.add_named(self._window_handle, "cover")
		self._stack.add_named(self._lyrics_window, "lyrics")
		self._stack.set_visible_child(self._window_handle)

		# connect
		self.lyrics_button.connect("toggled", self._on_lyrics_toggled)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)

		# packing
		self.set_child(self._stack)
		self.add_overlay(self._lyrics_button_revealer)

	def _on_connected(self, *args):
		self.lyrics_button.set_sensitive(True)

	def _on_disconnected(self, *args):
		self.lyrics_button.set_active(False)
		self.lyrics_button.set_sensitive(False)

	def _on_lyrics_toggled(self, widget):
		if widget.get_active():
			self._stack.set_visible_child(self._lyrics_window)
			self._lyrics_window.enable()
		else:
			self._stack.set_visible_child(self._window_handle)
			self._lyrics_window.disable()

######################
# action bar widgets #
######################

class PlaybackControl(Gtk.Box):
	def __init__(self, client, settings):
		super().__init__(css_classes=["linked"])
		self._client=client
		self._settings=settings

		# widgets
		self._play_button_icon=AutoSizedIcon("media-playback-start-symbolic", "icon-size", self._settings)
		self._play_button=Gtk.Button(
			child=self._play_button_icon, action_name="mpd.toggle-play", tooltip_text=_("Play"), can_focus=False)
		self._stop_button=Gtk.Button(
			child=AutoSizedIcon("media-playback-stop-symbolic", "icon-size", self._settings), tooltip_text=_("Stop"),
			action_name="mpd.stop", can_focus=False)
		self._prev_button=Gtk.Button(
			child=AutoSizedIcon("media-skip-backward-symbolic", "icon-size", self._settings),
			tooltip_text=_("Previous title"), action_name="mpd.prev", can_focus=False)
		self._next_button=Gtk.Button(
			child=AutoSizedIcon("media-skip-forward-symbolic", "icon-size", self._settings),
			tooltip_text=_("Next title"), action_name="mpd.next", can_focus=False)

		# connect
		self._settings.connect("changed::mini-player", self._mini_player)
		self._settings.connect("changed::show-stop", self._mini_player)
		self._client.emitter.connect("state", self._on_state)

		# packing
		self.append(self._prev_button)
		self.append(self._play_button)
		self.append(self._stop_button)
		self.append(self._next_button)
		self._mini_player()

	def _mini_player(self, *args):
		visibility=(self._settings.get_boolean("show-stop") and not self._settings.get_boolean("mini-player"))
		self._stop_button.set_property("visible", visibility)

	def _on_state(self, emitter, state):
		if state == "play":
			self._play_button_icon.set_property("icon-name", "media-playback-pause-symbolic")
			self._play_button.set_tooltip_text(_("Pause"))
		else:
			self._play_button_icon.set_property("icon-name", "media-playback-start-symbolic")
			self._play_button.set_tooltip_text(_("Play"))

class SeekBar(Gtk.Box):
	def __init__(self, client):
		super().__init__(hexpand=True, margin_start=6, margin_end=6)
		self._client=client
		self._first_mark=None
		self._second_mark=None

		# labels
		attrs=Pango.AttrList()
		attrs.insert(Pango.AttrFontFeatures.new("tnum 1"))
		self._elapsed=Gtk.Label(xalign=0, attributes=attrs)
		self._rest=Gtk.Label(xalign=1, attributes=attrs)

		# progress bar
		self._scale=Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, draw_value=False, hexpand=True, can_focus=False)
		self._scale.set_increments(10, 10)
		self._adjustment=self._scale.get_adjustment()

		# popover
		self._popover=Gtk.Popover(autohide=False, has_arrow=False)
		self._time_label=Gtk.Label(attributes=attrs)
		self._popover.set_child(self._time_label)
		self._popover.set_parent(self._scale)
		self._popover.set_position(Gtk.PositionType.TOP)

		# event controllers
		for label, sign1, sign3 in ((self._elapsed, "-", "+"), (self._rest, "+", "-")):
			con1=Gtk.GestureClick(button=1)
			con3=Gtk.GestureClick(button=3)
			label.add_controller(con1)
			label.add_controller(con3)
			con1.connect("released",
				lambda con, n, x, y, sign: self._client.seekcur(sign+str(self._adjustment.get_property("step-increment"))), sign1
			)
			con3.connect("released",
				lambda con, n, x, y, sign: self._client.seekcur(sign+str(self._adjustment.get_property("step-increment"))), sign3
			)
		controller_motion=Gtk.EventControllerMotion()
		self._scale.add_controller(controller_motion)
		controller_motion.connect("motion", self._on_pointer_motion)
		controller_motion.connect("leave", self._on_pointer_leave)
		button2_controller=Gtk.GestureClick(button=2)
		self._elapsed.add_controller(button2_controller)
		button2_controller.connect("pressed", self._on_label_button_pressed)
		button2_controller=Gtk.GestureClick(button=2)
		self._rest.add_controller(button2_controller)
		button2_controller.connect("pressed", self._on_label_button_pressed)

		# connect
		self._scale.connect("change-value", self._on_change_value)
		self._client.emitter.connect("disconnected", self._disable)
		self._client.emitter.connect("state", self._on_state)
		self._client.emitter.connect("elapsed", self._refresh)
		self._client.emitter.connect("current_song", self._on_song_changed)

		# packing
		self.append(self._elapsed)
		self.append(self._scale)
		self.append(self._rest)

	def _refresh(self, emitter, elapsed, duration):
		self.set_sensitive(True)
		if duration > 0:
			if elapsed > duration:  # fix display error
				elapsed=duration
			self._adjustment.set_upper(duration)
			self._scale.set_value(elapsed)
			self._elapsed.set_text(str(Duration(elapsed)))
			self._rest.set_text(str(Duration(duration-elapsed)))
			if self._second_mark is not None:
				if elapsed > self._second_mark:
					self._client.seekcur(self._first_mark)
		else:
			self._disable()
			self._elapsed.set_text(str(Duration(elapsed)))

	def _disable(self, *args):
		self._popover.popdown()
		self.set_sensitive(False)
		self._scale.set_range(0, 0)
		self._elapsed.set_text("")
		self._rest.set_text("")
		self._clear_marks()

	def _clear_marks(self, *args):
		self._first_mark=None
		self._second_mark=None
		self._scale.clear_marks()

	def _on_change_value(self, range, scroll, value):  # value is inaccurate (can be above upper limit)
		if (scroll == Gtk.ScrollType.STEP_BACKWARD or scroll == Gtk.ScrollType.STEP_FORWARD or
			scroll == Gtk.ScrollType.PAGE_BACKWARD or scroll == Gtk.ScrollType.PAGE_FORWARD or
			scroll == Gtk.ScrollType.JUMP):
			self._client.seekcur(value)
			duration=self._adjustment.get_upper()
			current_pos=self._scale.get_value()
			if value >= duration:
				self._scale.set_sensitive(False)
				pos=duration
				self._scale.set_sensitive(True)
				self._popover.popdown()
			elif value <= 0:
				pos=0
				self._popover.popdown()
			else:
				pos=value
			if abs(current_pos-pos) > 0.1:
				try:
					self._client.seekcur(pos)
				except:
					pass

	def _on_pointer_motion(self, controller, x, y):
		range_rect=self._scale.get_range_rect()
		duration=self._adjustment.get_upper()
		if self._scale.get_direction() == Gtk.TextDirection.RTL:
			elapsed=int(((range_rect.width-x)/range_rect.width*duration))
		else:
			elapsed=int((x/range_rect.width*duration))
		if elapsed > duration:  # fix display error
			elapsed=int(duration)
		elif elapsed < 0:
			elapsed=0
		self._time_label.set_text(str(Duration(elapsed)))
		rect=Gdk.Rectangle()
		rect.x,rect.y=x,0
		self._popover.set_pointing_to(rect)
		self._popover.popup()

	def _on_pointer_leave(self, *args):
		self._popover.popdown()

	def _on_label_button_pressed(self, controller, n_press, x, y):
		if n_press == 1:
			value=self._scale.get_value()
			if self._first_mark is None:
				self._first_mark=value
				self._scale.add_mark(value, Gtk.PositionType.BOTTOM, None)
			elif self._second_mark is None:
				if value < self._first_mark:
					self._second_mark=self._first_mark
					self._first_mark=value
				else:
					self._second_mark=value
				self._scale.add_mark(value, Gtk.PositionType.BOTTOM, None)
			else:
				self._clear_marks()

	def _on_state(self, emitter, state):
		if state == "stop":
			self._disable()

	def _on_song_changed(self, *args):
		self._clear_marks()
		self._popover.popdown()

class AudioFormat(Gtk.Box):
	def __init__(self, client, settings):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
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
		self._client.emitter.connect("connected", self._on_connected)

		# packing
		hbox=Gtk.Box(halign=Gtk.Align.END, visible=True)
		hbox.append(self._brate_label)
		hbox.append(self._separator_label)
		hbox.append(self._file_type_label)
		self.append(hbox)
		self.append(self._format_label)
		self._mini_player()

	def _mini_player(self, *args):
		visibility=(self._settings.get_boolean("show-audio-format") and not self._settings.get_boolean("mini-player"))
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
		if (song:=self._client.currentsong()):
			file_type=song["file"].split(".")[-1].split("/")[0].upper()
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

	def _on_connected(self, *args):
		self.set_sensitive(True)

class PlaybackOptions(Gtk.Box):
	def __init__(self, client, settings):
		super().__init__(css_classes=["linked"], homogeneous=False)
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
			button=Gtk.ToggleButton(child=AutoSizedIcon(icon, "icon-size", self._settings), tooltip_text=tooltip, can_focus=False)
			handler=button.connect("toggled", self._set_option, name)
			self.append(button)
			self._buttons[name]=(button, handler)

		# event controller
		button3_controller=Gtk.GestureClick(button=3)
		self._buttons["single"][0].add_controller(button3_controller)

		# connect
		button3_controller.connect("pressed", self._on_button3_pressed)
		for name in ("repeat", "random", "consume"):
			self._client.emitter.connect(name, self._button_refresh, name)
		self._client.emitter.connect("single", self._single_refresh)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)
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
			self._buttons["single"][0].add_css_class("suggested-action")
		else:
			self._buttons["single"][0].remove_css_class("suggested-action")
		self._buttons["single"][0].handler_unblock(self._buttons["single"][1])

	def _on_button3_pressed(self, controller, n_press, x, y):
		if n_press == 1:
			if self._client.status()["single"] == "oneshot":
				self._client.single("0")
			else:
				self._client.single("oneshot")

	def _on_disconnected(self, *args):
		self.set_sensitive(False)
		for name in ("repeat", "random", "consume"):
			self._button_refresh(None, False, name)
		self._single_refresh(None, "0")

	def _on_connected(self, *args):
		self.set_sensitive(True)

class VolumeButton(Gtk.VolumeButton):
	def __init__(self, client, settings):
		super().__init__(use_symbolic=True)
		self._client=client
		self._adj=self.get_adjustment()
		self._adj.set_step_increment(5)
		self._adj.set_page_increment(10)
		self._adj.set_upper(0)  # do not allow volume change by user when MPD has not yet reported volume (no output enabled/avail)
		self.get_popup().set_position(Gtk.PositionType.TOP)
		settings.bind("icon-size", self.get_first_child().get_child(), "pixel-size", Gio.SettingsBindFlags.GET)

		# connect
		self._changed=self.connect("value-changed", self._set_volume)
		self._client.emitter.connect("volume", self._refresh)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)

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

	def _on_button_toggled(self, button, out_id):
		if button.get_property("active"):
			self._client.enableoutput(out_id)
		else:
			self._client.disableoutput(out_id)

	def _on_connected(self, *args):
		self.set_sensitive(True)

	def _on_disconnected(self, *args):
		self.set_sensitive(False)
		self._refresh(None, -1)

###################
# MPD gio actions #
###################
class MPDActionGroup(Gio.SimpleActionGroup):
	def __init__(self, client):
		super().__init__()
		self._client=client

		# actions
		self._disable_on_stop_data=("next","prev","seek-forward","seek-backward")
		self._disable_no_song=("tidy","enqueue")
		self._enable_on_reconnect_data=("toggle-play","stop","clear","update","repeat","random","single","consume","single-oneshot")
		self._data=self._disable_on_stop_data+self._disable_no_song+self._enable_on_reconnect_data
		for name in self._data:
			action=Gio.SimpleAction.new(name, None)
			action.connect("activate", getattr(self, ("_on_"+name.replace("-","_"))))
			self.add_action(action)

		# connect
		self._client.emitter.connect("state", self._on_state)
		self._client.emitter.connect("current_song", self._on_song_changed)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)

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

	def _on_tidy(self, action, param):
		self._client.tidy_playlist()

	def _on_enqueue(self, action, param):
		song=self._client.currentsong()
		self._client.album_to_playlist(song["albumartist"][0], song["album"][0], song["date"][0], "enqueue")

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

	def _on_song_changed(self, emitter, song, songid, state):
		for action in self._disable_no_song:
			self.lookup_action(action).set_enabled(song is not None)

	def _on_disconnected(self, *args):
		for action in self._data:
			self.lookup_action(action).set_enabled(False)

	def _on_connected(self, *args):
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
		box.add_css_class("app-notification")
		box.append(self._spinner)
		box.append(label)
		self.set_child(box)

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
		settings_button=Gtk.Button(label=_("Preferences"), action_name="win.connection-settings")

		# connect
		connect_button.connect("clicked", self._on_connect_button_clicked)
		self._client.emitter.connect("connection_error", self._on_connection_error)
		self._client.emitter.connect("connected", self._on_connected)

		# packing
		box=Gtk.Box(spacing=12)
		box.add_css_class("app-notification")
		box.append(self._label)
		box.append(settings_button)
		box.append(connect_button)
		self.set_child(box)

	def _on_connection_error(self, *args):
		if self._settings.get_boolean("socket-connection"):
			text=_("Connection to “{socket}” failed").format(socket=self._settings.get_socket())
		else:
			text=_("Connection to “{host}:{port}” failed").format(
				host=self._settings.get_string("host"), port=self._settings.get_int("port"))
		self._label.set_text(text)
		self.set_reveal_child(True)

	def _on_connected(self, *args):
		self.set_reveal_child(False)

	def _on_connect_button_clicked(self, *args):
		self._client.reconnect()

class MainWindow(Gtk.ApplicationWindow):
	def __init__(self, client, settings, **kwargs):
		super().__init__(title="mpdevil", icon_name="org.mpdevil.mpdevil", **kwargs)
		self.set_default_icon_name("org.mpdevil.mpdevil")
		self._client=client
		self._settings=settings
		self._use_csd=self._settings.get_boolean("use-csd")
		self._size=None  # needed for window size saving

		# actions
		simple_actions_data=("settings","connection-settings","stats","help","toggle-lyrics","back","toggle-search")
		for name in simple_actions_data:
			action=Gio.SimpleAction.new(name, None)
			action.connect("activate", getattr(self, ("_on_"+name.replace("-","_"))))
			self.add_action(action)
		self.add_action(self._settings.create_action("mini-player"))

		# shortcuts
		builder=Gtk.Builder()
		builder.add_from_resource("/org/mpdevil/mpdevil/ShortcutsWindow.ui")
		self.set_help_overlay(builder.get_object("shortcuts_window"))

		# widgets
		self._cover_playlist_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self._paned2=Gtk.Paned(resize_start_child=True,shrink_start_child=False,resize_end_child=False,shrink_end_child=False,vexpand=True)
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
		if self._use_csd:
			self._search_button=Gtk.ToggleButton(icon_name="system-search-symbolic", tooltip_text=_("Search"), can_focus=False)
		else:
			search_icon=AutoSizedIcon("system-search-symbolic", "icon-size", self._settings)
			self._search_button=Gtk.ToggleButton(child=search_icon, tooltip_text=_("Search"), can_focus=False)
			self._search_button.add_css_class("flat")
		self._settings.bind("mini-player", self._search_button, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)

		# stack
		self._stack=Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
		self._stack.add_named(self._browser, "browser")
		self._stack.add_named(self._search_window, "search")
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
		menu=Gio.Menu()
		menu.append(_("Mini Player"), "win.mini-player")
		menu.append_section(None, mpd_subsection)
		menu.append_section(None, subsection)

		# menu button / popover
		if self._use_csd:
			self._menu_button=Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text=_("Menu"), menu_model=menu, primary=True)
		else:
			menu_icon=AutoSizedIcon("open-menu-symbolic", "icon-size", self._settings)
			self._menu_button=Gtk.MenuButton(child=menu_icon, tooltip_text=_("Menu"), menu_model=menu, primary=True)
			self._menu_button.set_direction(Gtk.ArrowType.UP)
			self._menu_button.add_css_class("flat")

		# connect
		self._search_button.connect("toggled", self._on_search_button_toggled)
		self._settings.connect_after("changed::mini-player", self._mini_player)
		self._settings.connect_after("notify::cursor-watch", self._on_cursor_watch)
		self._client.emitter.connect("current_song", self._on_song_changed)
		self._client.emitter.connect("connected", self._on_connected)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connecting", self._on_connecting)
		self._client.emitter.connect("connection_error", self._on_connection_error)

		# packing
		self._cover_playlist_box.append(self._cover_lyrics_window)
		self._cover_playlist_box.append(Gtk.Separator())
		self._cover_playlist_box.append(playlist_window)
		self._paned2.set_start_child(self._stack)
		self._paned2.set_end_child(self._cover_playlist_box)
		action_bar=Gtk.ActionBar()
		if self._use_csd:
			self._header_bar=Gtk.HeaderBar(title_widget=Adw.WindowTitle())
			self.set_titlebar(self._header_bar)
			self._header_bar.pack_end(self._menu_button)
			self._header_bar.pack_end(self._search_button)
		else:
			action_bar.pack_end(self._menu_button)
			action_bar.pack_end(self._search_button)
		action_bar.pack_start(playback_control)
		action_bar.pack_start(seek_bar)
		action_bar.pack_end(volume_button)
		action_bar.pack_end(playback_options)
		action_bar.pack_end(audio)
		vbox=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		vbox.append(self._paned2)
		vbox.append(action_bar)
		overlay=Gtk.Overlay(child=vbox)
		overlay.add_overlay(update_notify)
		overlay.add_overlay(connection_notify)
		self.set_child(overlay)

	def open(self):
		# bring player in consistent state
		self._client.emitter.emit("disconnected")
		self._client.emitter.emit("connecting")
		# set default window size
		if self._settings.get_boolean("mini-player"):
			self._bind_mini_player_dimension_settings()
		else:
			self._bind_default_dimension_settings()
			self._bind_paned_settings()
		if self._settings.get_boolean("maximize"):
			self.maximize()
		self.present()
		# ensure window is visible
		main=GLib.main_context_default()
		while main.pending():
			main.iteration()
		self._settings.bind("maximize", self, "maximized", Gio.SettingsBindFlags.SET)
		self._client.start()

	def _clear_title(self):
		self.set_title("mpdevil")
		if self._use_csd:
			self._header_bar.get_title_widget().set_title("mpdevil")
			self._header_bar.get_title_widget().set_subtitle(" ")

	def _bind_mini_player_dimension_settings(self):
		self.set_default_size(self._settings.get_int("mini-player-width"), self._settings.get_int("mini-player-height"))
		self._settings.bind("mini-player-width", self, "default-width", Gio.SettingsBindFlags.SET)
		self._settings.bind("mini-player-height", self, "default-height", Gio.SettingsBindFlags.SET)

	def _bind_default_dimension_settings(self):
		self.set_default_size(self._settings.get_int("width"), self._settings.get_int("height"))
		self._settings.bind("width", self, "default-width", Gio.SettingsBindFlags.SET)
		self._settings.bind("height", self, "default-height", Gio.SettingsBindFlags.SET)

	def _unbind_dimension_settings(self):
		self._settings.unbind(self, "default-width")
		self._settings.unbind(self, "default-height")

	def _bind_paned_settings(self):
		self._settings.bind("paned1", self._browser, "position", Gio.SettingsBindFlags.DEFAULT)
		self._settings.bind("paned2", self._paned2, "position", Gio.SettingsBindFlags.DEFAULT)

	def _unbind_paned_settings(self):
		self._settings.unbind(self._browser, "position")
		self._settings.unbind(self._paned2, "position")

	def _mini_player(self, *args):
		if self._settings.get_boolean("mini-player"):
			self._unbind_paned_settings()
			self._unbind_dimension_settings()
			self._bind_mini_player_dimension_settings()
		else:
			self._unbind_dimension_settings()
			self._bind_default_dimension_settings()
			self._bind_paned_settings()

	def _on_toggle_lyrics(self, action, param):
		self._cover_lyrics_window.lyrics_button.emit("clicked")

	def _on_back(self, action, param):
		if self._search_button.get_active():
			self._search_button.set_active(False)
		else:
			self._browser.back()

	def _on_toggle_search(self, action, param):
		self._search_button.emit("clicked")

	def _on_settings(self, action, param):
		settings=SettingsDialog(self, self._client, self._settings)
		settings.present()

	def _on_connection_settings(self, action, param):
		settings=SettingsDialog(self, self._client, self._settings, "connection")
		settings.present()

	def _on_stats(self, action, param):
		stats=ServerStats(self, self._client, self._settings)
		stats.present()

	def _on_help(self, action, param):
		Gtk.UriLauncher(uri="https://github.com/SoongNoonien/mpdevil/wiki/Usage").launch(self, None, None, None)

	def _on_search_button_toggled(self, button):
		if button.get_active():
			self._stack.set_visible_child_name("search")
			self._search_window.search_entry.grab_focus()
		else:
			self._stack.set_visible_child_name("browser")

	def _on_song_changed(self, *args):
		if (song:=self._client.currentsong()):
			album=song.get_album_with_date()
			title=" • ".join(filter(None, (song["title"][0], str(song["artist"]))))
			if self._use_csd:
				self.set_title(title)
				self._header_bar.get_title_widget().set_title(title)
				self._header_bar.get_title_widget().set_subtitle(album)
			else:
				self.set_title(" • ".join(filter(None, (title, album))))
			if self._settings.get_boolean("send-notify"):
				if not self.is_active() and self._client.status()["state"] == "play":
					notify=Gio.Notification()
					notify.set_title(title)
					notify.set_body(album)
					if isinstance(self._client.current_cover, FileCover):
						notify.set_icon(Gio.FileIcon.new(Gio.File.new_for_path(self._client.current_cover)))
					elif isinstance(self._client.current_cover, BinaryCover):
						notify.set_icon(Gio.BytesIcon.new(GLib.Bytes.new(self._client.current_cover)))
					self.get_application().send_notification("title-change", notify)
				else:
					self.get_application().withdraw_notification("title-change")
		else:
			self._clear_title()
			self.get_application().withdraw_notification("title-change")

	def _on_connected(self, *args):
		self._clear_title()
		for action in ("stats","toggle-lyrics","back","toggle-search"):
			self.lookup_action(action).set_enabled(True)
		self._search_button.set_sensitive(True)

	def _on_disconnected(self, *args):
		self._clear_title()
		for action in ("stats","toggle-lyrics","back","toggle-search"):
			self.lookup_action(action).set_enabled(False)
		self._search_button.set_active(False)
		self._search_button.set_sensitive(False)

	def _on_connecting(self, *args):
		if self._use_csd:
			self._header_bar.get_title_widget().set_subtitle(_("connecting…"))
		else:
			self.set_title("mpdevil "+_("connecting…"))

	def _on_connection_error(self, *args):
		self._clear_title()

	def _on_cursor_watch(self, obj, typestring):
		if obj.get_property("cursor-watch"):
			self.set_cursor_from_name("progress")
		else:
			self.set_cursor_from_name(None)

###################
# Gtk application #
###################

class mpdevil(Adw.Application):
	def __init__(self):
		super().__init__(application_id="org.mpdevil.mpdevil", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
		self.add_main_option("debug", ord("d"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE, _("Debug mode"), None)

	def do_startup(self):
		Adw.Application.do_startup(self)
		self._settings=Settings()
		self._client=Client(self._settings)
		self._window=MainWindow(self._client, self._settings, application=self)
		self._window.connect("close-request", self._on_quit)
		self._window.insert_action_group("mpd", MPDActionGroup(self._client))
		self._window.open()
		# MPRIS
		if self._settings.get_boolean("mpris"):
			dbus_service=MPRISInterface(self, self._window, self._client, self._settings)
		# actions
		action=Gio.SimpleAction.new("about", None)
		action.connect("activate", self._on_about)
		self.add_action(action)
		action=Gio.SimpleAction.new("quit", None)
		action.connect("activate", self._on_quit)
		self.add_action(action)
		# accelerators
		action_accels=(
			("app.quit", ["<Control>q"]),("win.mini-player", ["<Control>m"]),("win.help", ["F1"]),
			("win.show-help-overlay", ["<Control>question"]),("win.toggle-lyrics", ["<Control>l"]),
			("win.back", ["Escape"]),("win.toggle-search", ["<Control>f"]),
			("mpd.update", ["F5"]),("mpd.clear", ["<Shift>Delete"]),("mpd.toggle-play", ["space"]),("mpd.stop", ["<Shift>space"]),
			("mpd.next", ["<Alt>Down", "KP_Add"]),("mpd.prev", ["<Alt>Up", "KP_Subtract"]),("mpd.repeat", ["<Control>r"]),
			("mpd.random", ["<Control>n"]),("mpd.single", ["<Control>s"]),("mpd.consume", ["<Control>o"]),
			("mpd.single-oneshot", ["<Shift><Control>s"]),
			("mpd.seek-forward", ["<Alt>Right", "KP_Multiply"]),("mpd.seek-backward", ["<Alt>Left", "KP_Divide"])
		)
		for action, accels in action_accels:
			self.set_accels_for_action(action, accels)

	def do_activate(self):
		try:
			self._window.present()
		except:  # failed to show window so the user can't see anything
			self.quit()

	def do_shutdown(self):
		Adw.Application.do_shutdown(self)
		if self._settings.get_boolean("stop-on-quit") and self._client.connected():
			self._client.stop()
		self.withdraw_notification("title-change")

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
		dialog.present()

	def _on_quit(self, *args):
		self.quit()

if __name__ == "__main__":
	app=mpdevil()
	signal.signal(signal.SIGINT, signal.SIG_DFL)  # allow using ctrl-c to terminate
	app.run(sys.argv)
