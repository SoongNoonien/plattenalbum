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
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, Gdk, GdkPixbuf, Pango, GObject, GLib
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
FALLBACK_COVER=Gtk.IconTheme.get_default().lookup_icon("media-optical", 128, Gtk.IconLookupFlags.FORCE_SVG).get_filename()
FALLBACK_SOCKET=os.path.join(GLib.get_user_runtime_dir(), "mpd/socket")
FALLBACK_MUSIC_DIRECTORY=GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_MUSIC)

############################
# decorators and functions #
############################

def idle_add(*args, **kwargs):
	GLib.idle_add(*args, priority=GLib.PRIORITY_DEFAULT, **kwargs)

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
		return f"{title}\n<small>{GLib.markup_escape_text(self.get_album_with_date())}</small>"

class BinaryCover(bytes):
	def get_pixbuf(self, size=-1):
		loader=GdkPixbuf.PixbufLoader()
		try:
			loader.write(self)
		except gi.repository.GLib.Error:  # load fallback if cover can't be loaded
			pixbuf=GdkPixbuf.Pixbuf.new_from_file_at_size(FALLBACK_COVER, size, size)
		else:
			loader.close()
			if size == -1:
				pixbuf=loader.get_pixbuf()
			else:
				raw_pixbuf=loader.get_pixbuf()
				ratio=raw_pixbuf.get_width()/raw_pixbuf.get_height()
				if ratio > 1:
					pixbuf=raw_pixbuf.scale_simple(size,size/ratio,GdkPixbuf.InterpType.BILINEAR)
				else:
					pixbuf=raw_pixbuf.scale_simple(size*ratio,size,GdkPixbuf.InterpType.BILINEAR)
		return pixbuf

class FileCover(str):
	def get_pixbuf(self, size=-1):
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
		"connected": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"connecting": (GObject.SignalFlags.RUN_FIRST, None, ()),
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
		self._start_idle_id=None
		self.music_directory=None
		self.current_cover=None
		self._bus=Gio.bus_get_sync(Gio.BusType.SESSION, None)  # used for "show in file manager"

		# connect
		self._settings.connect("changed::socket-connection", lambda *args: self.reconnect())

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
				self._main_timeout_id=GLib.timeout_add(self._refresh_interval, self._main_loop)
				self.emitter.emit("connected")
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

	def tidy_playlist(self):  # this function assumes that a song is playing/stopped
		status=self.status()
		song_number=status["song"]
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

	def comp_list(self, *args):  # simulates listing behavior of python-mpd2 1.0
		native_list=self.list(*args)
		if len(native_list) > 0:
			if isinstance(native_list[0], dict):
				return ([l[args[0]] for l in native_list])
			else:
				return native_list
		else:
			return([])

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
					self.current_cover=self.get_cover(self.currentsong())
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
					self.current_cover=None
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
		toggle_data=(
			(_("Use Client-side decoration"), "use-csd", True),
			(_("Show stop button"), "show-stop", False),
			(_("Show audio format"), "show-audio-format", False),
			(_("Show lyrics button"), "show-lyrics-button", False),
			(_("Place playlist at the side"), "playlist-right", False),
		)
		for label, key, restart_required in toggle_data:
			row=ToggleRow(label, settings, key, restart_required)
			self.append(row)
		int_data=(
			(_("Album view cover size"), (50, 600, 10), "album-cover"),
			(_("Action bar icon size"), (16, 64, 2), "icon-size"),
		)
		for label, (vmin, vmax, step), key in int_data:
			row=IntRow(label, vmin, vmax, step, settings, key)
			self.append(row)

class BehaviorSettings(SettingsList):
	def __init__(self, settings):
		super().__init__()
		toggle_data=(
			(_("Support “MPRIS”"), "mpris", True),
			(_("Sort albums by year"), "sort-albums-by-year", False),
			(_("Send notification on title change"), "send-notify", False),
			(_("Rewind via previous button"), "rewind-mode", False),
			(_("Stop playback on quit"), "stop-on-quit", False),
		)
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

class MusicDirectoryEntry(Gtk.Entry):
	def __init__(self, parent, **kwargs):
		super().__init__(placeholder_text=FALLBACK_MUSIC_DIRECTORY, **kwargs)
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

class ConnectionSettings(Gtk.Grid):
	def __init__(self, parent, client, settings):
		super().__init__(row_spacing=6, column_spacing=6, border_width=18)

		# labels and entries
		socket_button=Gtk.CheckButton(label=_("Connect via Unix domain socket"))
		settings.bind("socket-connection", socket_button, "active", Gio.SettingsBindFlags.DEFAULT)
		socket_entry=Gtk.Entry(placeholder_text=FALLBACK_SOCKET, hexpand=True, no_show_all=True)
		settings.bind("socket", socket_entry, "text", Gio.SettingsBindFlags.DEFAULT)
		settings.bind("socket-connection", socket_entry, "visible", Gio.SettingsBindFlags.GET)
		host_entry=Gtk.Entry(hexpand=True, no_show_all=True)
		settings.bind("host", host_entry, "text", Gio.SettingsBindFlags.DEFAULT)
		settings.bind("socket-connection", host_entry, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)
		port_entry=Gtk.SpinButton.new_with_range(0, 65535, 1)
		port_entry.set_property("no-show-all", True)
		settings.bind("port", port_entry, "value", Gio.SettingsBindFlags.DEFAULT)
		settings.bind("socket-connection", port_entry, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)
		password_entry=PasswordEntry(hexpand=True)
		settings.bind("password", password_entry, "text", Gio.SettingsBindFlags.DEFAULT)
		music_directory_entry=MusicDirectoryEntry(parent, hexpand=True, no_show_all=True)
		settings.bind("music-directory", music_directory_entry, "text", Gio.SettingsBindFlags.DEFAULT)
		settings.bind("socket-connection", music_directory_entry, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)
		regex_entry=Gtk.Entry(hexpand=True, placeholder_text=FALLBACK_REGEX)
		regex_entry.set_tooltip_text(
			_("The first image in the same directory as the song file "\
			"matching this regex will be displayed. %AlbumArtist% and "\
			"%Album% will be replaced by the corresponding tags of the song.")
		)
		settings.bind("regex", regex_entry, "text", Gio.SettingsBindFlags.DEFAULT)
		socket_label=Gtk.Label(label=_("Socket:"), xalign=1, margin_end=6, no_show_all=True)
		settings.bind("socket-connection", socket_label, "visible", Gio.SettingsBindFlags.GET)
		host_label=Gtk.Label(label=_("Host:"), xalign=1, margin_end=6, no_show_all=True)
		settings.bind("socket-connection", host_label, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)
		password_label=Gtk.Label(label=_("Password:"), xalign=1, margin_end=6)
		music_directory_label=Gtk.Label(label=_("Music lib:"), xalign=1, margin_end=6, no_show_all=True)
		settings.bind("socket-connection", music_directory_label, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)
		regex_label=Gtk.Label(label=_("Cover regex:"), xalign=1, margin_end=6)

		# connect button
		connect_button=Gtk.Button(label=_("Connect"), margin_start=18, margin_end=18, margin_top=18, halign=Gtk.Align.CENTER)
		connect_button.get_style_context().add_class("suggested-action")
		connect_button.connect("clicked", lambda *args: client.reconnect())

		# packing
		self.attach(socket_button, 0, 0, 3, 1)
		self.attach(socket_label, 0, 1, 1, 1)
		self.attach_next_to(host_label, socket_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(password_label, host_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(music_directory_label, password_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(regex_label, music_directory_label, Gtk.PositionType.BOTTOM, 1, 1)
		self.attach_next_to(socket_entry, socket_label, Gtk.PositionType.RIGHT, 2, 1)
		self.attach_next_to(host_entry, host_label, Gtk.PositionType.RIGHT, 1, 1)
		self.attach_next_to(port_entry, host_entry, Gtk.PositionType.RIGHT, 1, 1)
		self.attach_next_to(password_entry, password_label, Gtk.PositionType.RIGHT, 2, 1)
		self.attach_next_to(music_directory_entry, music_directory_label, Gtk.PositionType.RIGHT, 2, 1)
		self.attach_next_to(regex_entry, regex_label, Gtk.PositionType.RIGHT, 2, 1)
		self.attach(connect_button, 0, 6, 3, 1)

class SettingsDialog(Gtk.Dialog):
	def __init__(self, parent, client, settings, tab="view"):
		use_csd=settings.get_boolean("use-csd")
		if use_csd:
			super().__init__(title=_("Preferences"), transient_for=parent, use_header_bar=True)
		else:
			super().__init__(title=_("Preferences"), transient_for=parent)
			self.add_button(Gtk.STOCK_OK, Gtk.ResponseType.OK)

		# widgets
		view=ViewSettings(settings)
		behavior=BehaviorSettings(settings)
		connection=ConnectionSettings(parent, client, settings)

		# packing
		vbox=self.get_content_area()
		if use_csd:
			stack=Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
			stack.add_titled(view, "view", _("View"))
			stack.add_titled(behavior, "behavior", _("Behavior"))
			stack.add_titled(connection, "connection", _("Connection"))
			stack_switcher=Gtk.StackSwitcher(stack=stack)
			vbox.set_property("border-width", 0)
			vbox.pack_start(stack, True, True, 0)
			header_bar=self.get_header_bar()
			header_bar.set_custom_title(stack_switcher)
		else:
			tabs=Gtk.Notebook()
			tabs.append_page(view, Gtk.Label(label=_("View")))
			tabs.append_page(behavior, Gtk.Label(label=_("Behavior")))
			tabs.append_page(connection, Gtk.Label(label=_("Connection")))
			vbox.set_property("spacing", 6)
			vbox.set_property("border-width", 6)
			vbox.pack_start(tabs, True, True, 0)
		self.show_all()
		if use_csd:
			stack.set_visible_child_name(tab)
		else:
			tabs.set_current_page({"view": 0, "behavior": 1, "connection": 2}[tab])

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
		stats["db_update"]=GLib.DateTime.new_from_unix_local(int(stats["db_update"])).format("%a %d %B %Y, %H∶%M")

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

	def save_set_cursor(self, *args, **kwargs):
		# The standard set_cursor function should scroll normally, but it doesn't work as it should when the treeview is not completely
		# initialized. This usually happens when the program is freshly started and the treeview isn't done with its internal tasks.
		# See: https://lazka.github.io/pgi-docs/GLib-2.0/constants.html#GLib.PRIORITY_HIGH_IDLE
		# Running set_cursor with a lower priority ensures that the treeview is done before it gets scrolled.
		GLib.idle_add(self.set_cursor, *args, **kwargs)

	def save_scroll_to_cell(self, *args, **kwargs):
		# Similar problem as above.
		GLib.idle_add(self.scroll_to_cell, *args, **kwargs)

class AutoSizedIcon(Gtk.Image):
	def __init__(self, icon_name, settings_key, settings):
		super().__init__(icon_name=icon_name)
		settings.bind(settings_key, self, "pixel-size", Gio.SettingsBindFlags.GET)

class SongsList(TreeView):
	def __init__(self, client):
		super().__init__(activate_on_single_click=True, headers_visible=False, enable_search=False, search_column=4)
		self._client=client

		# store
		# (track, title, duration, file, search string)
		self._store=Gtk.ListStore(str, str, str, str, str)
		self.set_model(self._store)

		# columns
		renderer_text=Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END, ellipsize_set=True)
		attrs=Pango.AttrList()
		attrs.insert(Pango.AttrFontFeatures.new("tnum 1"))
		renderer_text_ralign_tnum=Gtk.CellRendererText(xalign=1, attributes=attrs, ypad=6)
		renderer_text_centered_tnum=Gtk.CellRendererText(xalign=0.5, attributes=attrs)
		columns=(
			Gtk.TreeViewColumn(_("No"), renderer_text_centered_tnum, text=0),
			Gtk.TreeViewColumn(_("Title"), renderer_text, markup=1),
			Gtk.TreeViewColumn(_("Length"), renderer_text_ralign_tnum, text=2)
		)
		for column in columns:
			column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
			column.set_property("resizable", False)
			self.append_column(column)
		columns[1].set_property("expand", True)

		# selection
		self._selection=self.get_selection()
		self._selection.set_mode(Gtk.SelectionMode.BROWSE)

		# menu
		action_group=Gio.SimpleActionGroup()
		action=Gio.SimpleAction.new("append", None)
		action.connect("activate", lambda *args: self._client.file_to_playlist(self._store[self.get_cursor()[0]][3], "append"))
		action_group.add_action(action)
		action=Gio.SimpleAction.new("as_next", None)
		action.connect("activate", lambda *args: self._client.file_to_playlist(self._store[self.get_cursor()[0]][3], "as_next"))
		action_group.add_action(action)
		action=Gio.SimpleAction.new("play", None)
		action.connect("activate", lambda *args: self._client.file_to_playlist(self._store[self.get_cursor()[0]][3], "play"))
		action_group.add_action(action)
		self._show_action=Gio.SimpleAction.new("show", None)
		self._show_action.connect("activate", lambda *args: self._client.show_in_file_manager(self._store[self.get_cursor()[0]][3]))
		action_group.add_action(self._show_action)
		self.insert_action_group("menu", action_group)
		menu=Gio.Menu()
		menu.append(_("Append"), "menu.append")
		menu.append(_("As Next"), "menu.as_next")
		menu.append(_("Play"), "menu.play")
		subsection=Gio.Menu()
		subsection.append(_("Show"), "menu.show")
		menu.append_section(None, subsection)
		self._menu=Gtk.Popover.new_from_model(self, menu)
		self._menu.set_position(Gtk.PositionType.BOTTOM)

		# connect
		self.connect("row-activated", self._on_row_activated)
		self.connect("button-press-event", self._on_button_press_event)
		self.connect("key-press-event", self._on_key_press_event)

	def clear(self):
		self._menu.popdown()
		self._store.clear()

	def append(self, track, title, duration, file, search_string=""):
		self._store.insert_with_valuesv(-1, range(5), [track, title, duration, file, search_string])

	def _open_menu(self, uri, x, y):
		rect=Gdk.Rectangle()
		rect.x,rect.y=x,y
		self._menu.set_pointing_to(rect)
		self._show_action.set_enabled(self._client.can_show_in_file_manager(uri))
		self._menu.popup()

	def _on_row_activated(self, widget, path, view_column):
		self._client.file_to_playlist(self._store[path][3], "play")

	def _on_button_press_event(self, widget, event):
		if (path_re:=widget.get_path_at_pos(int(event.x), int(event.y))) is not None:
			path=path_re[0]
			if event.button == 2 and event.type == Gdk.EventType.BUTTON_PRESS:
				self._client.file_to_playlist(self._store[path][3], "append")
			elif event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
				uri=self._store[path][3]
				point=self.convert_bin_window_to_widget_coords(event.x,event.y)
				self._open_menu(uri, *point)

	def _on_key_press_event(self, widget, event):
		if event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval == Gdk.keyval_from_name("plus"):
			if (path:=self.get_cursor()[0]) is not None:
				self._client.file_to_playlist(self._store[path][3], "append")
		elif event.keyval == Gdk.keyval_from_name("Menu"):
			if (path:=self.get_cursor()[0]) is not None:
				self._open_menu(self._store[path][3], *self.get_popover_point(path))

##########
# search #
##########

class SearchThread(threading.Thread):
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
			hits+=len(songs)
			if not self._append_songs(songs):
				self._exit()
				return
			idle_add(self._search_entry.progress_pulse)
			idle_add(self._hits_label.set_text, ngettext("{hits} hit", "{hits} hits", hits).format(hits=hits))
			stripe_end=stripe_start+stripe_size
			songs=self._get_songs(stripe_start, stripe_end)
			stripe_start=stripe_end
		self._exit()

	def _exit(self):
		def callback():
			self._search_entry.set_progress_fraction(0.0)
			self._songs_list.columns_autosize()
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

	@main_thread_function
	def _append_songs(self, songs):
		for song in songs:
			if self._stop_flag:
				return False
			self._songs_list.append(song["track"][0], song.get_markup(), str(song["duration"]), song["file"])
		self._songs_list.columns_autosize()
		return True

class SearchWindow(Gtk.Box):
	def __init__(self, client):
		super().__init__(orientation=Gtk.Orientation.VERTICAL)
		self._client=client

		# widgets
		self._tag_combo_box=Gtk.ComboBoxText()
		self.search_entry=Gtk.SearchEntry(max_width_chars=20, truncate_multiline=True)
		self._hits_label=Gtk.Label(xalign=1, ellipsize=Pango.EllipsizeMode.END)

		# songs list
		self._songs_list=SongsList(self._client)

		# search thread
		self._search_thread=SearchThread(self._client, self.search_entry, self._songs_list, self._hits_label, "any")

		# connect
		self.search_entry.connect("activate", self._search)
		self._search_entry_changed=self.search_entry.connect("search-changed", self._search)
		self.search_entry.connect("focus_in_event", self._on_search_entry_focus_event, True)
		self.search_entry.connect("focus_out_event", self._on_search_entry_focus_event, False)
		self._tag_combo_box_changed=self._tag_combo_box.connect("changed", self._search)
		self._client.emitter.connect("connected", self._on_connected)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("updated_db", self._search)

		# packing
		hbox=Gtk.Box(spacing=6, border_width=6)
		hbox.pack_start(self._tag_combo_box, False, False, 0)
		hbox.set_center_widget(self.search_entry)
		hbox.pack_end(self._hits_label, False, False, 6)
		self.pack_start(hbox, False, False, 0)
		self.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
		self.pack_start(Gtk.ScrolledWindow(child=self._songs_list), True, True, 0)

	def _on_disconnected(self, *args):
		self._search_thread.stop()

	def _on_connected(self, *args):
		def callback():
			self._songs_list.clear()
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
			self._search_thread=SearchThread(self._client, self.search_entry, self._songs_list, self._hits_label, search_tag)
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
	__gsignals__={"item-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
			"item-reselected": (GObject.SignalFlags.RUN_FIRST, None, ()),
			"clear": (GObject.SignalFlags.RUN_FIRST, None, ())}
	def __init__(self, select_all_string):
		super().__init__(search_column=0, headers_visible=False, fixed_height_mode=True)
		self.select_all_string=select_all_string
		self._selected_path=None

		# store
		# item, initial-letter, weight-initials
		self._store=Gtk.ListStore(str, str, Pango.Weight)
		self._store.append([self.select_all_string, "", Pango.Weight.NORMAL])
		self.set_model(self._store)
		self._selection=self.get_selection()
		self._selection.set_mode(Gtk.SelectionMode.BROWSE)

		# columns
		renderer_text_malign=Gtk.CellRendererText(xalign=0.5)
		self._column_initial=Gtk.TreeViewColumn("", renderer_text_malign, text=1, weight=2)
		self._column_initial.set_property("sizing", Gtk.TreeViewColumnSizing.FIXED)
		self._column_initial.set_property("min-width", 30)
		self.append_column(self._column_initial)
		renderer_text=Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END, ellipsize_set=True, ypad=6)
		self._column_item=Gtk.TreeViewColumn("", renderer_text, text=0)
		self._column_item.set_property("sizing", Gtk.TreeViewColumnSizing.FIXED)
		self._column_item.set_property("expand", True)
		self.append_column(self._column_item)

		# connect
		self._selection.connect("changed", self._on_selection_changed)

	def clear(self):
		self._selection.set_mode(Gtk.SelectionMode.NONE)
		self._store.clear()
		self._store.append([self.select_all_string, "", Pango.Weight.NORMAL])
		self._selected_path=None
		self.emit("clear")

	def set_items(self, items):
		self.clear()
		letters="ABCDEFGHIJKLMNOPQRSTUVWXYZ"
		items.extend(zip([None]*len(letters), letters))
		items.sort(key=lambda item: locale.strxfrm(item[1]))
		char=""
		for item in items:
			if item[0] is None:
				char=item[1]
			else:
				self._store.insert_with_valuesv(-1, range(3), [item[0], char, Pango.Weight.BOLD])
				char=""
		self._selection.set_mode(Gtk.SelectionMode.BROWSE)

	def get_item_at_path(self, path):
		if path == Gtk.TreePath(0):
			return None
		else:
			return self._store[path][0]

	def length(self):
		return len(self._store)-1

	def select_path(self, path):
		self.set_cursor(path, None, False)

	def select(self, item):
		row_num=len(self._store)
		for i in range(0, row_num):
			path=Gtk.TreePath(i)
			if self._store[path][0] == item:
				self.select_path(path)
				break

	def select_all(self):
		self.select_path(Gtk.TreePath(0))

	def get_path_selected(self):
		if self._selected_path is None:
			raise ValueError("None selected")
		else:
			return self._selected_path

	def get_item_selected(self):
		return self.get_item_at_path(self.get_path_selected())

	def scroll_to_selected(self):
		self.save_scroll_to_cell(self._selected_path, None, True, 0.25)

	def _on_selection_changed(self, *args):
		if (treeiter:=self._selection.get_selected()[1]) is not None:
			if (path:=self._store.get_path(treeiter)) == self._selected_path:
				self.emit("item-reselected")
			else:
				self._selected_path=path
				self.emit("item-selected")

class GenreList(SelectionList):
	def __init__(self, client):
		super().__init__(_("all genres"))
		self._client=client

		# connect
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect_after("connected", self._on_connected)
		self._client.emitter.connect("updated_db", self._refresh)

	def _refresh(self, *args):
		l=self._client.comp_list("genre")
		self.set_items(list(zip(l,l)))
		self.select_all()

	def _on_disconnected(self, *args):
		self.set_sensitive(False)
		self.clear()

	def _on_connected(self, *args):
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

		# connect
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)
		self.genre_list.connect_after("item-selected", self._refresh)

	def _refresh(self, *args):
		genre=self.genre_list.get_item_selected()
		if genre is None:
			artists=self._client.list("albumartistsort", "group", "albumartist")
		else:
			artists=self._client.list("albumartistsort", "genre", genre, "group", "albumartist")
		filtered_artists=[]
		for name, artist in itertools.groupby(((artist["albumartist"], artist["albumartistsort"]) for artist in artists), key=lambda x: x[0]):
			filtered_artists.append(next(artist))
			# ignore multiple albumartistsort values
			if next(artist, None) is not None:
				filtered_artists[-1]=(name, name)
		self.set_items(filtered_artists)
		if genre is not None:
			self.select_all()
		elif (song:=self._client.currentsong()):
			artist=song["albumartist"][0]
			self.select(artist)
		elif self.length() > 0:
			self.select_path(Gtk.TreePath(1))
		else:
			self.select_path(Gtk.TreePath(0))
		self.scroll_to_selected()

	def get_artist_at_path(self, path):
		genre=self.genre_list.get_item_selected()
		artist=self.get_item_at_path(path)
		return (artist, genre)

	def get_artist_selected(self):
		return self.get_artist_at_path(self.get_path_selected())

	def _on_disconnected(self, *args):
		self.set_sensitive(False)
		self.clear()

	def _on_connected(self, *args):
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
		@main_thread_function
		def client_list(*args):
			if self._stop_flag:
				raise ValueError("Stop requested")
			else:
				return self._client.list(*args)
		for albumartist in self._artists:
			try:
				albums=client_list("albumsort", "albumartist", albumartist, *self._genre_filter, "group", "date", "group", "album")
			except ValueError:
				break
			for _, album in itertools.groupby(albums, key=lambda x: (x["album"], x["date"])):
				tmp=next(album)
				# ignore multiple albumsort values
				if next(album, None) is None:
					yield (albumartist, tmp["album"], tmp["date"], tmp["albumsort"])
				else:
					yield (albumartist, tmp["album"], tmp["date"], tmp["album"])

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
			self._artists=self._client.comp_list("albumartist", *self._genre_filter)
		else:
			self._artists=[self._artist]
		super().start()

	def run(self):
		# temporarily display all albums with fallback cover
		fallback_cover=GdkPixbuf.Pixbuf.new_from_file_at_size(FALLBACK_COVER, self._cover_size, self._cover_size)
		add=main_thread_function(self._store.append)
		for i, (albumartist, album, date, albumsort) in enumerate(self._get_albums()):
			# album label
			if date:
				display_label=f"<b>{GLib.markup_escape_text(album)}</b> ({GLib.markup_escape_text(date)})"
			else:
				display_label=f"<b>{GLib.markup_escape_text(album)}</b>"
			display_label_artist=f"{display_label}\n{GLib.markup_escape_text(albumartist)}"
			# add album
			add([fallback_cover, display_label, display_label_artist, albumartist, album, date, albumsort])
			if i%10 == 0:
				if self._stop_flag:
					self._exit()
					return
				idle_add(self._progress_bar.pulse)
		if self._stop_flag:
			self._exit()
			return
		# sort model
		if main_thread_function(self._settings.get_boolean)("sort-albums-by-year"):
			main_thread_function(self._store.set_sort_column_id)(5, Gtk.SortType.ASCENDING)
		else:
			main_thread_function(self._store.set_sort_column_id)(6, Gtk.SortType.ASCENDING)
		idle_add(self._iconview.set_model, self._store)
		# select album
		@main_thread_function
		def get_current_album_path():
			if self._stop_flag:
				raise ValueError("Stop requested")
			else:
				return self._iconview.get_current_album_path()
		try:
			path=get_current_album_path()
		except ValueError:
			self._exit()
			return
		if path is None:
			path=Gtk.TreePath(0)
		idle_add(self._iconview.set_cursor, path, None, False)
		idle_add(self._iconview.select_path, path)
		idle_add(self._iconview.scroll_to_path, path, True, 0.25, 0)
		# load covers
		total=2*len(self._store)
		@main_thread_function
		def get_cover(row):
			if self._stop_flag:
				raise ValueError("Stop requested")
			else:
				self._client.restrict_tagtypes("albumartist", "album")
				song=self._client.find("albumartist", row[3], "album", row[4], "date", row[5], "window", "0:1")[0]
				self._client.tagtypes("all")
				return self._client.get_cover(song)
		covers=[]
		for i, row in enumerate(self._store):
			try:
				cover=get_cover(row)
			except ValueError:
				self._exit()
				return
			covers.append(cover)
			idle_add(self._progress_bar.set_fraction, (i+1)/total)
		treeiter=self._store.get_iter_first()
		i=0
		def set_cover(treeiter, cover):
			if self._store.iter_is_valid(treeiter):
				self._store.set_value(treeiter, 0, cover)
		while treeiter is not None:
			if self._stop_flag:
				self._exit()
				return
			if covers[i] is not None:
				cover=covers[i].get_pixbuf(self._cover_size)
				idle_add(set_cover, treeiter, cover)
			idle_add(self._progress_bar.set_fraction, 0.5+(i+1)/total)
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
		idle_add(callback)

class AlbumList(Gtk.IconView):
	__gsignals__={"album-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,str,str,))}
	def __init__(self, client, settings, artist_list):
		super().__init__(item_width=0,pixbuf_column=0,markup_column=1,activate_on_single_click=True,selection_mode=Gtk.SelectionMode.BROWSE)
		self._settings=settings
		self._client=client
		self._artist_list=artist_list

		# cover, display_label, display_label_artist, albumartist, album, date, albumsort
		self._store=Gtk.ListStore(GdkPixbuf.Pixbuf, str, str, str, str, str, str)
		self._store.set_default_sort_func(lambda *args: 0)
		self.set_model(self._store)

		# progress bar
		self.progress_bar=Gtk.ProgressBar(no_show_all=True, valign=Gtk.Align.END, vexpand=False)
		self.progress_bar.get_style_context().add_class("osd")

		# cover thread
		self._cover_thread=AlbumLoadingThread(self._client, self._settings, self.progress_bar, self, self._store, None, None)

		# connect
		self.connect("item-activated", self._on_item_activated)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)
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
			self._workaround_clear()
		if self._cover_thread.is_alive():
			self._cover_thread.set_callback(callback)
			self._cover_thread.stop()
		else:
			callback()

	def get_current_album_path(self):
		if (song:=self._client.currentsong()):
			album=[song["albumartist"][0], song["album"][0], song["date"][0]]
			row_num=len(self._store)
			for i in range(0, row_num):
				path=Gtk.TreePath(i)
				if self._store[path][3:6] == album:
					return path
			return None
		else:
			return None

	def scroll_to_current_album(self):
		def callback():
			if (path:=self.get_current_album_path()) is not None:
				self.set_cursor(path, None, False)
				self.select_path(path)
				self.scroll_to_path(path, True, 0.25, 0)
		if self._cover_thread.is_alive():
			self._cover_thread.set_callback(callback)
		else:
			callback()

	def _sort_settings(self, *args):
		if not self._cover_thread.is_alive():
			if self._settings.get_boolean("sort-albums-by-year"):
				self._store.set_sort_column_id(5, Gtk.SortType.ASCENDING)
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

	def _on_item_activated(self, widget, path):
		tags=self._store[path][3:6]
		self.emit("album-selected", *tags)

	def _on_disconnected(self, *args):
		self.set_sensitive(False)

	def _on_connected(self, *args):
		self.set_sensitive(True)

	def _on_cover_size_changed(self, *args):
		if self._client.connected():
			self._refresh()

class AlbumView(Gtk.Box):
	__gsignals__={"close": (GObject.SignalFlags.RUN_FIRST, None, ())}
	def __init__(self, client, settings):
		super().__init__(orientation=Gtk.Orientation.VERTICAL)
		self._client=client
		self._settings=settings
		self._tag_filter=()

		# songs list
		self.songs_list=SongsList(self._client)
		self.songs_list.set_enable_search(True)
		scroll=Gtk.ScrolledWindow(child=self.songs_list)
		scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

		# buttons
		self._buttons=Gtk.ButtonBox(layout_style=Gtk.ButtonBoxStyle.EXPAND, halign=Gtk.Align.END)
		data=((_("Append"), "list-add-symbolic", "append"),
			(_("Play"), "media-playback-start-symbolic", "play")
		)
		for tooltip, icon, mode in data:
			button=Gtk.Button(image=Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
			button.set_tooltip_text(tooltip)
			button.connect("clicked", self._on_button_clicked, mode)
			self._buttons.pack_start(button, True, True, 0)

		# cover
		self._cover=Gtk.Image()
		size=self._settings.get_int("album-cover")*1.5
		pixbuf=GdkPixbuf.Pixbuf.new_from_file_at_size(FALLBACK_COVER, size, size)
		self._cover.set_from_pixbuf(pixbuf)

		# labels
		self._title=Gtk.Label(margin_start=12, margin_end=12, xalign=0)
		self._title.set_line_wrap(True)  # wrap=True is not working
		self._duration=Gtk.Label(xalign=1, ellipsize=Pango.EllipsizeMode.END)

		# event box
		event_box=Gtk.EventBox()

		# connect
		self.connect("hide", lambda *args: print("test"))
		event_box.connect("button-release-event", self._on_button_release_event)

		# packing
		event_box.add(self._cover)
		hbox=Gtk.Box(spacing=12)
		hbox.pack_end(self._buttons, False, False, 0)
		hbox.pack_end(self._duration, False, False, 0)
		vbox=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, border_width=6)
		vbox.set_center_widget(self._title)
		vbox.pack_end(hbox, False, False, 0)
		header=Gtk.Box()
		header.pack_start(event_box, False, False, 0)
		header.pack_start(Gtk.Separator(), False, False, 0)
		header.pack_start(vbox, True, True, 0)
		self.pack_start(header, False, False, 0)
		self.pack_start(Gtk.Separator(), False, False, 0)
		self.pack_start(scroll, True, True, 0)

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
		for song in songs:
			# only show artists =/= albumartist
			try:
				song["artist"].remove(albumartist)
			except ValueError:
				pass
			artist=str(song['artist'])
			if artist == albumartist or not artist:
				title_artist=f"<b>{GLib.markup_escape_text(song['title'][0])}</b>"
			else:
				title_artist=f"<b>{GLib.markup_escape_text(song['title'][0])}</b> • {GLib.markup_escape_text(artist)}"
			self.songs_list.append(song["track"][0], title_artist, str(song["duration"]), song["file"], song["title"][0])
		self.songs_list.save_set_cursor(Gtk.TreePath(0), None, False)
		self.songs_list.columns_autosize()
		if (cover:=self._client.get_cover({"file": songs[0]["file"], "albumartist": albumartist, "album": album})) is None:
			size=self._settings.get_int("album-cover")*1.5
			pixbuf=GdkPixbuf.Pixbuf.new_from_file_at_size(FALLBACK_COVER, size, size)
			self._cover.set_from_pixbuf(pixbuf)
		else:
			size=self._settings.get_int("album-cover")*1.5
			self._cover.set_from_pixbuf(cover.get_pixbuf(size))

	def _on_button_release_event(self, widget, event):
		if event.button == 1:
			if 0 <= event.x <= widget.get_allocated_width() and 0 <= event.y <= widget.get_allocated_height():
				self.emit("close")

	def _on_button_clicked(self, widget, mode):
		self._client.filter_to_playlist(self._tag_filter, mode)

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
		self._album_view=AlbumView(self._client, self._settings)

		# album overlay
		album_overlay=Gtk.Overlay(child=album_window)
		album_overlay.add_overlay(self._album_list.progress_bar)

		# album stack
		self._album_stack=Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT, homogeneous=False)
		self._album_stack.add_named(album_overlay, "album_list")
		self._album_stack.add_named(self._album_view, "album_view")

		# hide/show genre filter
		self._genre_list.set_property("visible", True)
		self._settings.bind("genre-filter", genre_window, "no-show-all", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)
		self._settings.bind("genre-filter", genre_window, "visible", Gio.SettingsBindFlags.GET)
		self._settings.connect("changed::genre-filter", self._on_genre_filter_changed)

		# connect
		self._album_list.connect("album-selected", self._on_album_list_show_info)
		self._album_view.connect("close", lambda *args: self._album_stack.set_visible_child_name("album_list"))
		self._artist_list.connect("item-selected", lambda *args: self._album_stack.set_visible_child_name("album_list"))
		self._artist_list.connect("item-reselected", lambda *args: self._album_stack.set_visible_child_name("album_list"))
		self._client.emitter.connect("disconnected", lambda *args: self._album_stack.set_visible_child_name("album_list"))
		self._settings.connect("changed::album-cover", lambda *args: self._album_stack.set_visible_child_name("album_list"))

		# packing
		self.paned1=Gtk.Paned()
		self.paned1.pack1(artist_window, False, False)
		self.paned1.pack2(self._album_stack, True, False)
		self.pack1(genre_window, False, False)
		self.pack2(self.paned1, True, False)

	def back(self):
		if self._album_stack.get_visible_child_name() == "album_view":
			self._album_stack.set_visible_child_name("album_list")
		else:
			if (song:=self._client.currentsong()):
				self._to_album(song)

	def _to_album(self, song):
		artist,genre=self._artist_list.get_artist_selected()
		if genre is None or song["genre"][0] == genre:
			if artist is None or song["albumartist"][0] == artist:
				self._album_list.scroll_to_current_album()
			else:
				self._artist_list.select(song["albumartist"][0])
			self._artist_list.scroll_to_selected()
		else:
			self._genre_list.select_all()
		self._genre_list.scroll_to_selected()

	def _on_genre_filter_changed(self, settings, key):
		if self._client.connected():
			if not settings.get_boolean(key):
				self._genre_list.select_all()

	def _on_album_list_show_info(self, widget, *tags):
		self._album_view.display(*tags)
		self._album_stack.set_visible_child_name("album_view")
		GLib.idle_add(self._album_view.songs_list.grab_focus)

############
# playlist #
############

class PlaylistView(TreeView):
	selected_path=GObject.Property(type=Gtk.TreePath, default=None)  # currently marked song
	def __init__(self, client, settings):
		super().__init__(activate_on_single_click=True, reorderable=True, search_column=4, headers_visible=False)
		self._client=client
		self._settings=settings
		self._playlist_version=None
		self._inserted_path=None  # needed for drag and drop

		# selection
		self._selection=self.get_selection()
		self._selection.set_select_function(self._select_function)

		# store
		# (track, title, duration, file, search)
		self._store=Gtk.ListStore(str, str, str, str, str)
		self.set_model(self._store)

		# columns
		renderer_text=Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END, ellipsize_set=True)
		attrs=Pango.AttrList()
		attrs.insert(Pango.AttrFontFeatures.new("tnum 1"))
		renderer_text_ralign_tnum=Gtk.CellRendererText(xalign=1, attributes=attrs)
		renderer_text_centered_tnum=Gtk.CellRendererText(xalign=0.5, attributes=attrs)
		columns=(
			Gtk.TreeViewColumn(_("No"), renderer_text_centered_tnum, text=0),
			Gtk.TreeViewColumn(_("Title"), renderer_text, markup=1),
			Gtk.TreeViewColumn(_("Length"), renderer_text_ralign_tnum, text=2)
		)
		for column in columns:
			column.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
			column.set_property("resizable", False)
			self.append_column(column)
		self._column_title=columns[1]
		self._column_title.set_property("expand", True)

		# menu
		action_group=Gio.SimpleActionGroup()
		action=Gio.SimpleAction.new("remove", None)
		action.connect("activate", lambda *args: self._store.remove(self._store.get_iter(self.get_cursor()[0])))
		action_group.add_action(action)
		self._show_action=Gio.SimpleAction.new("show", None)
		self._show_action.connect("activate", lambda *args: self._client.show_in_file_manager(self._store[self.get_cursor()[0]][3]))
		action_group.add_action(self._show_action)
		self.insert_action_group("menu", action_group)
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
		self._menu=Gtk.Popover.new_from_model(self, menu)
		self._menu.set_position(Gtk.PositionType.BOTTOM)

		# connect
		self.connect("row-activated", self._on_row_activated)
		self.connect("button-press-event", self._on_button_press_event)
		self.connect("key-press-event", self._on_key_press_event)
		self._row_deleted=self._store.connect("row-deleted", self._on_row_deleted)
		self._row_inserted=self._store.connect("row-inserted", self._on_row_inserted)
		self._client.emitter.connect("playlist", self._on_playlist_changed)
		self._client.emitter.connect("current_song", self._on_song_changed)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)

	def scroll_to_selected_title(self):
		if (path:=self.get_property("selected-path")) is not None:
			self._scroll_to_path(path)

	def _open_menu(self, uri, x, y):
		rect=Gdk.Rectangle()
		rect.x,rect.y=x,y
		self._menu.set_pointing_to(rect)
		self._show_action.set_enabled(self._client.can_show_in_file_manager(uri))
		self._menu.popup()

	def _clear(self, *args):
		self._menu.popdown()
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
			self.set_property("selected-path", path)
			self._selection.select_path(path)
		except IndexError:  # invalid path
			pass

	def _unselect(self):
		if (path:=self.get_property("selected-path")) is not None:
			self.set_property("selected-path", None)
			try:
				self._selection.unselect_path(path)
			except IndexError:  # invalid path
				pass

	def _delete(self, path):
		if path == self.get_property("selected-path"):
			self._client.tidy_playlist()
		else:
			self._store.remove(self._store.get_iter(path))

	def _scroll_to_path(self, path):
		self.set_cursor(path, None, False)
		self.save_scroll_to_cell(path, None, True, 0.25)

	def _refresh_selection(self):
		song=self._client.status().get("song")
		if song is None:
			self._unselect()
		else:
			path=Gtk.TreePath(int(song))
			self._select(path)

	def _on_button_press_event(self, widget, event):
		if (path_re:=widget.get_path_at_pos(int(event.x), int(event.y))) is not None:
			path=path_re[0]
			if event.button == 2 and event.type == Gdk.EventType.BUTTON_PRESS:
				self._delete(path)
			elif event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
				point=self.convert_bin_window_to_widget_coords(event.x,event.y)
				self._open_menu(self._store[path][3], *point)

	def _on_key_press_event(self, widget, event):
		if event.keyval == Gdk.keyval_from_name("Delete"):
			if (path:=self.get_cursor()[0]) is not None:
				self._delete(path)
		elif event.keyval == Gdk.keyval_from_name("Menu"):
			if (path:=self.get_cursor()[0]) is not None:
				self._open_menu(self._store[path][3], *self.get_popover_point(path))

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
		except CommandError as e:
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
		self._menu.popdown()
		self._unselect()
		self._client.restrict_tagtypes("track", "title", "artist", "album", "date")
		songs=[]
		if self._playlist_version is not None:
			songs=self._client.plchanges(self._playlist_version)
		else:
			songs=self._client.playlistinfo()
		self._client.tagtypes("all")
		if songs:
			self.freeze_child_notify()
			for song in songs:
				title=song.get_markup()
				try:
					treeiter=self._store.get_iter(song["pos"])
				except ValueError:
					self._store.insert_with_valuesv(-1, range(5),
						[song["track"][0], title, str(song["duration"]), song["file"], song["title"][0]]
					)
				else:
					self._store.set(treeiter,
						0, song["track"][0], 1, title, 2, str(song["duration"]), 3, song["file"], 4, song["title"][0]
					)
			self.thaw_child_notify()
		for i in reversed(range(int(self._client.status()["playlistlength"]), len(self._store))):
			treeiter=self._store.get_iter(i)
			self._store.remove(treeiter)
		self._refresh_selection()
		if (path:=self.get_property("selected-path")) is None:
			if len(self._store) > 0:
				self._scroll_to_path(Gtk.TreePath(0))
		else:
			self._scroll_to_path(path)
		self._playlist_version=version
		self._store.handler_unblock(self._row_inserted)
		self._store.handler_unblock(self._row_deleted)

	def _on_song_changed(self, *args):
		self._refresh_selection()
		if self._client.status()["state"] == "play":
			self._scroll_to_path(self.get_property("selected-path"))

	def _on_disconnected(self, *args):
		self.set_sensitive(False)
		self._clear()

	def _on_connected(self, *args):
		self.set_sensitive(True)

	def _select_function(self, selection, model, path, path_currently_selected):
		return (path == self.get_property("selected-path")) == (not path_currently_selected)

class PlaylistWindow(Gtk.Overlay):
	def __init__(self, client, settings):
		super().__init__()
		self._back_button_icon=Gtk.Image.new_from_icon_name("go-down-symbolic", Gtk.IconSize.BUTTON)
		self._back_to_current_song_button=Gtk.Button(image=self._back_button_icon, tooltip_text=_("Scroll to current song"), can_focus=False)
		self._back_to_current_song_button.get_style_context().add_class("osd")
		self._back_button_revealer=Gtk.Revealer(
			child=self._back_to_current_song_button, transition_duration=0,
			margin_bottom=6, margin_top=6, halign=Gtk.Align.CENTER, valign=Gtk.Align.END
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
		def callback():
			visible_range=self._treeview.get_visible_range()  # not always accurate possibly due to a bug in Gtk
			if visible_range is None or self._treeview.get_property("selected-path") is None:
				self._back_button_revealer.set_reveal_child(False)
			else:
				if visible_range[0] > self._treeview.get_property("selected-path"):  # current song is above upper edge
					self._back_button_icon.set_property("icon-name", "go-up-symbolic")
					self._back_button_revealer.set_valign(Gtk.Align.START)
					self._back_button_revealer.set_reveal_child(True)
				elif self._treeview.get_property("selected-path") > visible_range[1]:  # current song is below lower edge
					self._back_button_icon.set_property("icon-name", "go-down-symbolic")
					self._back_button_revealer.set_valign(Gtk.Align.END)
					self._back_button_revealer.set_reveal_child(True)
				else:  # current song is visible
					self._back_button_revealer.set_reveal_child(False)
		GLib.idle_add(callback)  # workaround for the Gtk bug from above

	def _on_back_to_current_song_button_clicked(self, *args):
		self._treeview.scroll_to_selected_title()

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

class LyricsWindow(Gtk.ScrolledWindow):
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

		# css zoom
		self._scale=100
		self._provider=Gtk.CssProvider()
		self._text_view.get_style_context().add_provider(self._provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

		# connect
		self._text_view.connect("scroll-event", self._on_scroll_event)
		self._text_view.connect("key-press-event", self._on_key_press_event)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._song_changed=self._client.emitter.connect("current_song", self._refresh)
		self._client.emitter.handler_block(self._song_changed)

		# packing
		self.add(self._text_view)

	def enable(self, *args):
		if (song:=self._client.currentsong()):
			if song["file"] != self._displayed_song_file:
				self._refresh()
		else:
			if self._displayed_song_file is not None:
				self._refresh()
		self._client.emitter.handler_unblock(self._song_changed)
		idle_add(self._text_view.grab_focus)  # focus textview

	def disable(self, *args):
		self._client.emitter.handler_block(self._song_changed)

	def _zoom(self, scale):
		if 30 <= scale <= 500:
			self._provider.load_from_data(bytes(f"textview{{font-size: {scale}%}}", "utf-8"))
			self._scale=scale

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

	def _on_scroll_event(self, widget, event):
		if event.state & Gdk.ModifierType.CONTROL_MASK:
			if event.delta_y < 0:
				self._zoom(self._scale+10)
			elif event.delta_y > 0:
				self._zoom(self._scale-10)
			return True
		else:
			return False

	def _on_key_press_event(self, widget, event):
		if event.state & Gdk.ModifierType.CONTROL_MASK:
			if event.keyval == Gdk.keyval_from_name("plus"):
				self._zoom(self._scale+10)
			elif event.keyval == Gdk.keyval_from_name("minus"):
				self._zoom(self._scale-10)
			elif event.keyval == Gdk.keyval_from_name("0"):
				self._zoom(100)

	def _on_disconnected(self, *args):
		self._displayed_song_file=None
		self._text_buffer.set_text("", -1)

class CoverEventBox(Gtk.EventBox):
	def __init__(self, client, settings):
		super().__init__()
		self._client=client
		self._settings=settings
		self._click_pos=()
		self.set_events(Gdk.EventMask.POINTER_MOTION_MASK)
		# connect
		self.connect("button-press-event", self._on_button_press_event)
		self.connect("button-release-event", self._on_button_release_event)
		self.connect("motion-notify-event", self._on_motion_notify_event)

	def _on_button_press_event(self, widget, event):
		if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
			self._click_pos=(event.x, event.y)

	def _on_button_release_event(self, widget, event):
		if event.button == 1 and not self._settings.get_boolean("mini-player") and self._client.connected():
			if (song:=self._client.currentsong()):
				tags=(song["albumartist"][0], song["album"][0], song["date"][0])
				self._client.album_to_playlist(*tags, "enqueue")
		self._click_pos=()

	def _on_motion_notify_event(self, widget, event):
		if self._click_pos:
			# gtk-double-click-distance seems to be the right threshold for this
			# according to: https://gitlab.gnome.org/GNOME/gtk/-/merge_requests/1839
			# I verified this via manipulating gtk-double-click-distance.
			pointer_travel=max(abs(self._click_pos[0]-event.x), abs(self._click_pos[1]-event.y))
			if pointer_travel > Gtk.Settings.get_default().get_property("gtk-double-click-distance"):
				window=self.get_toplevel()
				window.begin_move_drag(1, event.x_root, event.y_root, Gdk.CURRENT_TIME)
				self._click_pos=()

class MainCover(Gtk.DrawingArea):
	def __init__(self, client):
		super().__init__()
		self._client=client
		self._fallback=True

		# connect
		self._client.emitter.connect("current_song", self._refresh)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)

	def _clear(self):
		self._fallback=True
		self.queue_draw()

	def _refresh(self, *args):
		if self._client.current_cover is None:
			self._clear()
		else:
			self._pixbuf=self._client.current_cover.get_pixbuf()
			self._surface=Gdk.cairo_surface_create_from_pixbuf(self._pixbuf, 0, None)
			self._fallback=False
			self.queue_draw()

	def _on_disconnected(self, *args):
		self.set_sensitive(False)
		self._clear()

	def _on_connected(self, *args):
		self.set_sensitive(True)

	def do_draw(self, context):
		if self._fallback:
			size=min(self.get_allocated_height(), self.get_allocated_width())
			self._pixbuf=GdkPixbuf.Pixbuf.new_from_file_at_size(FALLBACK_COVER, size, size)
			self._surface=Gdk.cairo_surface_create_from_pixbuf(self._pixbuf, 0, None)
			scale_factor=1
		else:
			scale_factor=min(self.get_allocated_width()/self._pixbuf.get_width(), self.get_allocated_height()/self._pixbuf.get_height())
		context.scale(scale_factor, scale_factor)
		x=((self.get_allocated_width()/scale_factor)-self._pixbuf.get_width())/2
		y=((self.get_allocated_height()/scale_factor)-self._pixbuf.get_height())/2
		context.set_source_surface(self._surface, x, y)
		context.paint()

class CoverLyricsWindow(Gtk.Overlay):
	def __init__(self, client, settings):
		super().__init__()
		self._client=client
		self._settings=settings

		# cover
		main_cover=MainCover(self._client)
		self._cover_event_box=CoverEventBox(self._client, self._settings)
		self._cover_event_box.add(Gtk.AspectFrame(child=main_cover, shadow_type=Gtk.ShadowType.NONE))

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
		self._stack=Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
		self._stack.add_named(self._cover_event_box, "cover")
		self._stack.add_named(self._lyrics_window, "lyrics")
		self._stack.set_visible_child(self._cover_event_box)

		# connect
		self.lyrics_button.connect("toggled", self._on_lyrics_toggled)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)

		# packing
		self.add(self._stack)
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
		self._play_button=Gtk.Button(
			image=self._play_button_icon, action_name="mpd.toggle-play", tooltip_text=_("Play"), can_focus=False)
		self._stop_button=Gtk.Button(
			image=AutoSizedIcon("media-playback-stop-symbolic", "icon-size", self._settings), tooltip_text=_("Stop"),
			action_name="mpd.stop", can_focus=False, no_show_all=True)
		self._prev_button=Gtk.Button(
			image=AutoSizedIcon("media-skip-backward-symbolic", "icon-size", self._settings),
			tooltip_text=_("Previous title"), action_name="mpd.prev", can_focus=False)
		self._next_button=Gtk.Button(
			image=AutoSizedIcon("media-skip-forward-symbolic", "icon-size", self._settings),
			tooltip_text=_("Next title"), action_name="mpd.next", can_focus=False)

		# connect
		self._settings.connect("changed::mini-player", self._mini_player)
		self._settings.connect("changed::show-stop", self._mini_player)
		self._client.emitter.connect("state", self._on_state)

		# packing
		self.pack_start(self._prev_button, True, True, 0)
		self.pack_start(self._play_button, True, True, 0)
		self.pack_start(self._stop_button, True, True, 0)
		self.pack_start(self._next_button, True, True, 0)
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
		super().__init__(hexpand=True, margin_start=6, margin_right=6)
		self._client=client
		self._update=True
		self._first_mark=None
		self._second_mark=None

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
		elapsed_dict={1: Gtk.ScrollType.STEP_BACKWARD, 3: Gtk.ScrollType.STEP_FORWARD}
		rest_dict={1: Gtk.ScrollType.STEP_FORWARD, 3: Gtk.ScrollType.STEP_BACKWARD}
		elapsed_event_box.connect("button-release-event", self._on_label_button_release_event, elapsed_dict)
		elapsed_event_box.connect("button-press-event", self._on_label_button_press_event)
		rest_event_box.connect("button-release-event", self._on_label_button_release_event, rest_dict)
		rest_event_box.connect("button-press-event", self._on_label_button_press_event)
		self._scale.connect("change-value", self._on_change_value)
		self._scale.connect("scroll-event", lambda *args: True)  # disable mouse wheel
		self._scale.connect("button-press-event", self._on_scale_button_press_event)
		self._scale.connect("button-release-event", self._on_scale_button_release_event)
		self._adjustment.connect("notify::value", self._update_labels)
		self._adjustment.connect("notify::upper", self._update_labels)
		self._adjustment.connect("notify::upper", self._clear_marks)
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
			self._adjustment.set_upper(duration)
			if self._update:
				if self._second_mark is not None:
					if elapsed > self._second_mark:
						self._client.seekcur(self._first_mark)
						return
				self._scale.set_value(elapsed)
			self._scale.set_fill_level(elapsed)
		else:
			self._disable()
			self._elapsed.set_text(str(Duration(elapsed)))

	def _update_labels(self, *args):
		duration=self._adjustment.get_upper()
		value=self._scale.get_value()
		if value > duration:  # fix display error
			elapsed=duration
		else:
			elapsed=value
		if duration > 0:
			self._elapsed.set_text(str(Duration(elapsed)))
			self._rest.set_text(str(Duration(duration-elapsed)))
		else:
			self._elapsed.set_text("")
			self._rest.set_text("")

	def _disable(self, *args):
		self.set_sensitive(False)
		self._scale.set_fill_level(0)
		self._scale.set_range(0, 0)
		self._clear_marks()

	def _clear_marks(self, *args):
		self._first_mark=None
		self._second_mark=None
		self._scale.clear_marks()

	def _on_scale_button_press_event(self, widget, event):
		if (event.button == 1 or  event.button == 3) and event.type == Gdk.EventType.BUTTON_PRESS:
			self._update=False

	def _on_scale_button_release_event(self, widget, event):
		if event.button == 1 or  event.button == 3:
			self._update=True
			self._client.seekcur(self._scale.get_value())

	def _on_change_value(self, scale, scroll, value):
		if scroll in (Gtk.ScrollType.STEP_BACKWARD, Gtk.ScrollType.STEP_FORWARD , Gtk.ScrollType.PAGE_BACKWARD, Gtk.ScrollType.PAGE_FORWARD):
			self._client.seekcur(value)

	def _on_label_button_release_event(self, widget, event, scroll_type):
		if 0 <= event.x <= widget.get_allocated_width() and 0 <= event.y <= widget.get_allocated_height():
			self._scale.emit("move-slider", scroll_type.get(event.button, Gtk.ScrollType.NONE))

	def _on_label_button_press_event(self, widget, event):
		if event.button == 2 and event.type == Gdk.EventType.BUTTON_PRESS:
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
		hbox.pack_start(self._brate_label, False, False, 0)
		hbox.pack_start(self._separator_label, False, False, 0)
		hbox.pack_start(self._file_type_label, False, False, 0)
		self.pack_start(hbox, False, False, 0)
		self.pack_start(self._format_label, False, False, 0)
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

class PlaybackOptions(Gtk.ButtonBox):
	def __init__(self, client, settings):
		super().__init__(layout_style=Gtk.ButtonBoxStyle.EXPAND, homogeneous=False)
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
		self._provider.load_from_data(b"image {color: @error_color;}")  # red icon

		# connect
		for name in ("repeat", "random", "consume"):
			self._client.emitter.connect(name, self._button_refresh, name)
		self._client.emitter.connect("single", self._single_refresh)
		self._buttons["single"][0].connect("button-press-event", self._on_single_button_press_event)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)
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
			self._buttons["single"][0].get_image().get_style_context().add_provider(
				self._provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
		else:
			self._buttons["single"][0].get_image().get_style_context().remove_provider(self._provider)
		self._buttons["single"][0].handler_unblock(self._buttons["single"][1])

	def _on_single_button_press_event(self, widget, event):
		if event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
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
		super().__init__(orientation=Gtk.Orientation.HORIZONTAL, use_symbolic=True, can_focus=False)
		self._client=client
		self._adj=self.get_adjustment()
		self._adj.set_step_increment(5)
		self._adj.set_page_increment(10)
		self._adj.set_upper(0)  # do not allow volume change by user when MPD has not yet reported volume (no output enabled/avail)
		settings.bind("icon-size", self.get_child(), "pixel-size", Gio.SettingsBindFlags.GET)

		# output plugins
		self._output_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=10, margin_end=10, margin_bottom=10)

		# popover
		popover=self.get_popup()
		scale_box=popover.get_child()
		scale_box.get_children()[1].set_hexpand(True)  # expand scale
		popover.remove(scale_box)
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		box.pack_start(scale_box, False, False, 0)
		box.pack_start(self._output_box, False, False, 0)
		popover.add(box)
		box.show_all()

		# connect
		popover.connect("show", self._on_show)
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

	def _on_show(self, *args):
		for button in self._output_box.get_children():
			self._output_box.remove(button)
		for output in self._client.outputs():
			button=Gtk.ModelButton(label=f"{output['outputname']} ({output['plugin']})", role=Gtk.ButtonRole.CHECK, visible=True)
			button.get_child().set_property("xalign", 0)
			if output["outputenabled"] == "1":
				button.set_property("active", True)
			button.connect("clicked", self._on_button_clicked, output["outputid"])
			self._output_box.pack_start(button, False, False, 0)

	def _on_button_clicked(self, button, out_id):
		if button.get_property("active"):
			self._client.disableoutput(out_id)
			button.set_property("active", False)
		else:
			self._client.enableoutput(out_id)
			button.set_property("active", True)

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
		self._disable_on_stop_data=("next","prev","seek-forward","seek-backward","tidy","enqueue")
		self._enable_on_reconnect_data=("toggle-play","stop","clear","update","repeat","random","single","consume","single-oneshot")
		self._data=self._disable_on_stop_data+self._enable_on_reconnect_data
		for name in self._data:
			action=Gio.SimpleAction.new(name, None)
			action.connect("activate", getattr(self, ("_on_"+name.replace("-","_"))))
			self.add_action(action)

		# connect
		self._client.emitter.connect("state", self._on_state)
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
		settings_button=Gtk.Button(label=_("Preferences"), action_name="win.connection-settings")

		# connect
		connect_button.connect("clicked", self._on_connect_button_clicked)
		self._client.emitter.connect("connection_error", self._on_connection_error)
		self._client.emitter.connect("connected", self._on_connected)

		# packing
		box=Gtk.Box(spacing=12)
		box.get_style_context().add_class("app-notification")
		box.pack_start(self._label, False, True, 6)
		box.pack_end(connect_button, False, True, 0)
		box.pack_end(settings_button, False, True, 0)
		self.add(box)

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
		super().__init__(title=("mpdevil"), icon_name="org.mpdevil.mpdevil", **kwargs)
		self.set_default_icon_name("org.mpdevil.mpdevil")
		self._client=client
		self._settings=settings
		self._use_csd=self._settings.get_boolean("use-csd")
		self._size=None  # needed for window size saving

		# actions
		simple_actions_data=("settings","connection-settings","stats","help","menu","toggle-lyrics","back","toggle-search")
		for name in simple_actions_data:
			action=Gio.SimpleAction.new(name, None)
			action.connect("activate", getattr(self, ("_on_"+name.replace("-","_"))))
			self.add_action(action)
		self.add_action(self._settings.create_action("mini-player"))
		self.add_action(self._settings.create_action("genre-filter"))

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
		back_button=Gtk.Button(
			image=icon("go-previous-symbolic"), tooltip_text=_("Back"),
			action_name="win.back", can_focus=False, no_show_all=True)
		self._settings.bind("mini-player", back_button, "visible", Gio.SettingsBindFlags.INVERT_BOOLEAN|Gio.SettingsBindFlags.GET)

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
		menu=Gio.Menu()
		menu.append(_("Mini Player"), "win.mini-player")
		menu.append(_("Genre Filter"), "win.genre-filter")
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
		self._settings.connect_after("changed::mini-player", self._mini_player)
		self._settings.connect_after("notify::cursor-watch", self._on_cursor_watch)
		self._settings.connect("changed::playlist-right", self._on_playlist_pos_changed)
		self._client.emitter.connect("current_song", self._on_song_changed)
		self._client.emitter.connect("connected", self._on_connected)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connecting", self._on_connecting)
		self._client.emitter.connect("connection_error", self._on_connection_error)
		# auto save window state and size
		self.connect("size-allocate", self._on_size_allocate)

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
			self._header_bar.pack_start(back_button)
			self._header_bar.pack_end(self._menu_button)
			self._header_bar.pack_end(self._search_button)
		else:
			action_bar.pack_start(back_button)
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

	def open(self):
		# bring player in consistent state
		self._client.emitter.emit("disconnected")
		# set default window size
		if self._settings.get_boolean("mini-player"):
			self.set_default_size(self._settings.get_int("mini-player-width"), self._settings.get_int("mini-player-height"))
		else:
			self.set_default_size(self._settings.get_int("width"), self._settings.get_int("height"))
			if self._settings.get_boolean("maximize"):
				self.maximize()  # request maximize
		self.show_all()
		while Gtk.events_pending():  # ensure window is visible
			Gtk.main_iteration_do(True)
		if not self._settings.get_boolean("mini-player"):
			self._bind_paned_settings()  # restore paned settings when window is visible (fixes a bug when window is maximized)
		self._settings.bind("maximize", self, "is-maximized", Gio.SettingsBindFlags.SET)  # same problem as one line above
		self._client.start()

	def _clear_title(self):
		self.set_title("mpdevil")
		if self._use_csd:
			self._header_bar.set_subtitle("")

	def _bind_paned_settings(self):
		self._settings.bind("paned0", self._paned0, "position", Gio.SettingsBindFlags.DEFAULT)
		self._settings.bind("paned1", self._browser.paned1, "position", Gio.SettingsBindFlags.DEFAULT)
		self._settings.bind("paned2", self._paned2, "position", Gio.SettingsBindFlags.DEFAULT)
		self._settings.bind("paned3", self._browser, "position", Gio.SettingsBindFlags.DEFAULT)

	def _unbind_paned_settings(self):
		self._settings.unbind(self._paned0, "position")
		self._settings.unbind(self._browser.paned1, "position")
		self._settings.unbind(self._paned2, "position")
		self._settings.unbind(self._browser, "position")

	def _mini_player(self, *args):
		if self.is_maximized():
			self.unmaximize()
		if self._settings.get_boolean("mini-player"):
			self._unbind_paned_settings()
			self.resize(self._settings.get_int("mini-player-width"), self._settings.get_int("mini-player-height"))
		else:
			self.resize(self._settings.get_int("width"), self._settings.get_int("height"))
			while Gtk.events_pending():  # ensure window is resized
				Gtk.main_iteration_do(True)
			self._bind_paned_settings()
			self.show_all()  # show hidden gui elements

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
		settings.run()
		settings.destroy()

	def _on_connection_settings(self, action, param):
		settings=SettingsDialog(self, self._client, self._settings, "connection")
		settings.run()
		settings.destroy()

	def _on_stats(self, action, param):
		stats=ServerStats(self, self._client, self._settings)
		stats.destroy()

	def _on_help(self, action, param):
		Gtk.show_uri_on_window(self, "https://github.com/SoongNoonien/mpdevil/wiki/Usage", Gdk.CURRENT_TIME)

	def _on_menu(self, action, param):
		self._menu_button.emit("clicked")

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
				self._header_bar.set_subtitle(album)
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
			self._header_bar.set_subtitle(_("connecting…"))
		else:
			self.set_title("mpdevil "+_("connecting…"))

	def _on_connection_error(self, *args):
		self._clear_title()

	def _on_size_allocate(self, widget, rect):
		if not self.is_maximized():
			if (size:=self.get_size()) != self._size:  # prevent unneeded write operations
				if self._settings.get_boolean("mini-player"):
					self._settings.set_int("mini-player-width", size[0])
					self._settings.set_int("mini-player-height", size[1])
				else:
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

	def do_startup(self):
		Gtk.Application.do_startup(self)
		self._settings=Settings()
		self._client=Client(self._settings)
		self._window=MainWindow(self._client, self._settings, application=self)
		self._window.connect("delete-event", self._on_quit)
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
			("app.quit", ["<Control>q"]),("win.mini-player", ["<Control>m"]),("win.help", ["F1"]),("win.menu", ["F10"]),
			("win.show-help-overlay", ["<Control>question"]),("win.toggle-lyrics", ["<Control>l"]),
			("win.genre-filter", ["<Control>g"]),("win.back", ["Escape"]),("win.toggle-search", ["<Control>f"]),
			("mpd.update", ["F5"]),("mpd.clear", ["<Shift>Delete"]),("mpd.toggle-play", ["space"]),("mpd.stop", ["<Shift>space"]),
			("mpd.next", ["<Alt>Down", "KP_Add"]),("mpd.prev", ["<Alt>Up", "KP_Subtract"]),("mpd.repeat", ["<Control>r"]),
			("mpd.random", ["<Control>n"]),("mpd.single", ["<Control>s"]),("mpd.consume", ["<Control>o"]),
			("mpd.single-oneshot", ["<Shift><Control>s"]),
			("mpd.seek-forward", ["<Alt>Right", "KP_Multiply"]),("mpd.seek-backward", ["<Alt>Left", "KP_Divide"])
		)
		for action, accels in action_accels:
			self.set_accels_for_action(action, accels)
		# disable item activation on space key pressed in treeviews
		Gtk.binding_entry_remove(Gtk.binding_set_find('GtkTreeView'), Gdk.keyval_from_name("space"), Gdk.ModifierType.MOD2_MASK)

	def do_activate(self):
		try:
			self._window.present()
		except:  # failed to show window so the user can't see anything
			self.quit()

	def do_shutdown(self):
		Gtk.Application.do_shutdown(self)
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
		dialog.run()
		dialog.destroy()

	def _on_quit(self, *args):
		self.quit()

if __name__ == "__main__":
	app=mpdevil()
	signal.signal(signal.SIGINT, signal.SIG_DFL)  # allow using ctrl-c to terminate
	app.run(sys.argv)
