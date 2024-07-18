#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Plattenalbum - MPD Client.
# Copyright (C) 2020-2024 Martin Wagner <martin.wagner.dev@gmail.com>
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
from gi.repository import Gtk, Adw, Gio, Gdk, Pango, GObject, GLib, Graphene
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
locale.bindtextdomain("de.wagnermartin.Plattenalbum", "@LOCALE_DIR@")
locale.textdomain("de.wagnermartin.Plattenalbum")
bindtextdomain("de.wagnermartin.Plattenalbum", localedir="@LOCALE_DIR@")
textdomain("de.wagnermartin.Plattenalbum")
Gio.Resource._register(Gio.resource_load(os.path.join("@RESOURCES_DIR@", "de.wagnermartin.Plattenalbum.gresource")))

FALLBACK_COVER="media-optical"

############################
# decorators and functions #
############################

def idle_add(*args, **kwargs):
	GLib.idle_add(*args, priority=GLib.PRIORITY_DEFAULT, **kwargs)

def lookup_icon(icon_name, size, scale=1):
	return Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).lookup_icon(
			icon_name, None, size, scale, Gtk.TextDirection.NONE, Gtk.IconLookupFlags.FORCE_REGULAR)

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
	_MPRIS_NAME="org.mpris.MediaPlayer2.de.wagnermartin.Plattenalbum"
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
		self._bus=Gio.bus_get_sync(Gio.BusType.SESSION, None)
		self._node_info=Gio.DBusNodeInfo.new_for_xml(self._INTERFACES_XML)
		self._metadata={}
		self._handlers=[]
		self._object_ids=[]
		self._name_id=None

		# MPRIS property mappings
		self._prop_mapping={
			self._MPRIS_IFACE:
				{"CanQuit": (GLib.Variant("b", False), None),
				"CanRaise": (GLib.Variant("b", True), None),
				"HasTrackList": (GLib.Variant("b", False), None),
				"Identity": (GLib.Variant("s", "Plattenalbum"), None),
				"DesktopEntry": (GLib.Variant("s", "de.wagnermartin.Plattenalbum"), None),
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

		# connect
		self._handlers.append(self._client.emitter.connect("state", self._on_state_changed))
		self._handlers.append(self._client.emitter.connect("current-song", self._on_song_changed))
		self._handlers.append(self._client.emitter.connect("volume", self._on_volume_changed))
		self._handlers.append(self._client.emitter.connect("repeat", self._on_loop_changed))
		self._handlers.append(self._client.emitter.connect("single", self._on_loop_changed))
		self._handlers.append(self._client.emitter.connect("random", self._on_random_changed))
		self._handlers.append(self._client.emitter.connect("connected", self._on_connected))
		self._handlers.append(self._client.emitter.connect("disconnected", self._on_disconnected))
		for handler in self._handlers:
			self._client.emitter.handler_block(handler)

		# enable/disable
		settings.connect("changed::mpris", self._on_mpris_changed)
		if settings.get_boolean("mpris"):
			self._enable()

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

	def _enable(self):
		self._name_id=Gio.bus_own_name_on_connection(self._bus, self._MPRIS_NAME, Gio.BusNameOwnerFlags.NONE, None, None)
		for interface in self._node_info.interfaces:
			self._object_ids.append(self._bus.register_object(self._MPRIS_PATH, interface, self._handle_method_call, None, None))
		for handler in self._handlers:
			self._client.emitter.handler_unblock(handler)

	def _disable(self):
		for object_id in self._object_ids:
			self._bus.unregister_object(object_id)
		self._object_ids=[]
		Gio.bus_unown_name(self._name_id)
		self._name_id=None
		for handler in self._handlers:
			self._client.emitter.handler_block(handler)

	def _on_mpris_changed(self, settings, key):
		if settings.get_boolean(key):
			self._enable()
			self._update_metadata()
			for p in ("PlaybackStatus","CanGoNext","CanGoPrevious","Metadata","Volume","LoopStatus","Shuffle"):
				self._update_property(self._MPRIS_PLAYER_IFACE, p)
		else:
			self._disable()

	def _on_connected(self, *args):
		for p in ("CanPlay","CanPause","CanSeek"):
			self._update_property(self._MPRIS_PLAYER_IFACE, p)

	def _on_disconnected(self, *args):
		self._metadata={}
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
		"updating-db": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"updated-db": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
		"disconnected": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"connected": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
		"connecting": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"connection_error": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"current-song": (GObject.SignalFlags.RUN_FIRST, None, (str,str,str,)),
		"state": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
		"elapsed": (GObject.SignalFlags.RUN_FIRST, None, (float,float,)),
		"volume": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
		"playlist": (GObject.SignalFlags.RUN_FIRST, None, (int,int,str)),
		"repeat": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
		"random": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
		"single": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
		"single-oneshot": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
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
		self._main_timeout_id=None
		self._start_idle_id=None
		self._music_directory=None
		self.current_cover=None
		self._cover_regex=re.compile(r"^\.?(album|cover|folder|front).*\.(gif|jpeg|jpg|png)$", flags=re.IGNORECASE)
		self._socket_path=os.path.join(GLib.get_user_runtime_dir(), "mpd/socket")
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
	def update(self):
		# This is a rather ugly workaround for database updates that are quicker
		# than around a tenth of a second and therefore can't be detected by _main_loop.
		job_id=super().update()
		self._last_status["updating_db"]=job_id
		self.emitter.emit("updating-db")
		return job_id

	def start(self):
		self.emitter.emit("connecting")
		def callback():
			# connect
			if self._settings.get_boolean("remote-connection"):
				try:
					self.connect(self._settings.get_string("host"), self._settings.get_int("port"))
				except:
					self.emitter.emit("connection_error")
					self._start_idle_id=None
					return False
			else:
				try:
					self.connect(self._socket_path, None)
				except:
					try:
						self.connect("/run/mpd/socket", None)
					except:
						self.emitter.emit("connection_error")
						self._start_idle_id=None
						return False
			# set password
			if password:=self._settings.get_string("password"):
				try:
					self.password(password)
				except:
					self.emitter.emit("connection_error")
					self._start_idle_id=None
					return False
			# connect successful
			commands=self.commands()
			if self._settings.get_boolean("remote-connection"):
				self._music_directory=None
			elif "config" in commands:
				self._music_directory=self.config()
			if "outputs" in commands and "enableoutput" in commands:
				if len(self.outputs()) == 1:
					self.enableoutput(0)
			if "status" in commands:
				self.emitter.emit("connected", self._database_is_empty())
				self._main_timeout_id=GLib.timeout_add(100, self._main_loop)
			else:
				self.disconnect()
				self.emitter.emit("connection_error")
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
		self._music_directory=None
		self.current_cover=None
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

	def get_cover_path(self, uri):
		if self._music_directory is not None:
			song_dir=os.path.join(self._music_directory, os.path.dirname(uri))
			if uri.lower().endswith(".cue"):
				song_dir=os.path.dirname(song_dir)  # get actual directory of .cue file
			if os.path.isdir(song_dir):
				for f in os.listdir(song_dir):
					if self._cover_regex.match(f):
						return os.path.join(song_dir, f)
		return None

	def get_cover_binary(self, uri):
		try:
			binary=self.albumart(uri)["binary"]
		except:
			try:
				binary=self.readpicture(uri)["binary"]
			except:
				binary=None
		return binary

	def get_cover(self, uri):
		if (cover_path:=self.get_cover_path(uri)) is not None:
			return FileCover(cover_path)
		elif (cover_binary:=self.get_cover_binary(uri)) is not None:
			return BinaryCover(cover_binary)
		else:
			return None

	def get_absolute_path(self, uri):
		if self._music_directory is not None:
			path=re.sub(r"(.*\.cue)\/track\d+$", r"\1", os.path.join(self._music_directory, uri), flags=re.IGNORECASE)
			if os.path.isfile(path):
				return path
			else:
				return None
		else:
			return None

	def can_show_in_file_manager(self, uri):
		has_owner,=self._bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
			GLib.Variant("(s)",("org.freedesktop.FileManager1",)), GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE, -1, None)
		activatable,=self._bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListActivatableNames",
			None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE, -1, None)
		return (has_owner or "org.freedesktop.FileManager1" in activatable) and self.get_absolute_path(uri) is not None

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

	def _database_is_empty(self):
		return self.stats().get("songs", "0") == "0"

	def _main_loop(self, *args):
		try:
			status=self.status()
			diff=dict(set(status.items())-set(self._last_status.items()))
			if "updating_db" in diff:
				self.emitter.emit("updating-db")
			if "playlist" in diff:
				self.emitter.emit("playlist", int(diff["playlist"]), int(status["playlistlength"]), status.get("song"))
			if "songid" in diff:
				self.current_cover=self.get_cover(self.currentsong()["file"])
				self.emitter.emit("current-song", status["song"], status["songid"], status["state"])
			if "elapsed" in diff:
				self.emitter.emit("elapsed", float(diff["elapsed"]), float(status.get("duration", 0.0)))
			if "bitrate" in diff:
				if diff["bitrate"] == "0":
					self.emitter.emit("bitrate", None)
				else:
					self.emitter.emit("bitrate", diff["bitrate"])
			if "volume" in diff:
				self.emitter.emit("volume", float(diff["volume"]))
			for key in ("state", "audio"):
				if key in diff:
					self.emitter.emit(key, diff[key])
			if "single" in diff:
				self.emitter.emit("single", diff["single"] == "1")
				self.emitter.emit("single-oneshot", diff["single"] == "oneshot")
			for key in ("repeat", "random", "consume"):
				if key in diff:
					self.emitter.emit(key, diff[key] == "1")
			diff=set(self._last_status)-set(status)
			for key in diff:
				if "songid" == key:
					self.current_cover=None
					self.emitter.emit("current-song", None, None, status["state"])
				elif "volume" == key:
					self.emitter.emit("volume", -1)
				elif "updating_db" == key:
					self.emitter.emit("updated-db", self._database_is_empty())
				elif "bitrate" == key:
					self.emitter.emit("bitrate", None)
				elif "audio" == key:
					self.emitter.emit("audio", None)
			self._last_status=status
		except (ConnectionError, ConnectionResetError) as e:
			self.disconnect()
			self.emitter.emit("connection_error")
			self._main_timeout_id=None
			return False
		return True

########################
# gio settings wrapper #
########################

class Settings(Gio.Settings):
	BASE_KEY="de.wagnermartin.Plattenalbum"
	# temp settings
	cursor_watch=GObject.Property(type=bool, default=False)
	def __init__(self):
		super().__init__(schema=self.BASE_KEY)

###################
# settings dialog #
###################

class ViewSettings(Adw.PreferencesGroup):
	def __init__(self, settings):
		super().__init__(title=_("View"))
		toggle_data=(
			(_("Show _Stop Button"), "show-stop", ""),
			(_("Show Audio _Format"), "show-audio-format", ""),
		)
		for title, key, subtitle in toggle_data:
			row=Adw.SwitchRow(title=title, subtitle=subtitle, use_underline=True)
			settings.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
			self.add(row)

class BehaviorSettings(Adw.PreferencesGroup):
	def __init__(self, settings):
		super().__init__(title=_("Behavior"))
		toggle_data=(
			(_("Support “_MPRIS”"), "mpris", ""),
			(_("Sort _Albums by Year"), "sort-albums-by-year", ""),
			(_("Send _Notification on Title Change"), "send-notify", ""),
			(_("Re_wind via Previous Button"), "rewind-mode", ""),
			(_("Stop _Playback on Quit"), "stop-on-quit", ""),
		)
		for title, key, subtitle in toggle_data:
			row=Adw.SwitchRow(title=title, subtitle=subtitle, use_underline=True)
			settings.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
			self.add(row)

class ConnectionSettings(Adw.PreferencesGroup):
	def __init__(self, client, settings):
		super().__init__(title=_("Connection"))
		remote_row=Adw.ExpanderRow(title=_("_Connect to Remote Server"), use_underline=True, show_enable_switch=True)
		settings.bind("remote-connection", remote_row, "enable-expansion", Gio.SettingsBindFlags.DEFAULT)
		self.add(remote_row)

		hostname_row=Adw.EntryRow(title=_("Host Name"))
		settings.bind("host", hostname_row, "text", Gio.SettingsBindFlags.DEFAULT)
		remote_row.add_row(hostname_row)

		port_row=Adw.SpinRow.new_with_range(0, 65535, 1)
		port_row.set_title(_("Port"))
		settings.bind("port", port_row, "value", Gio.SettingsBindFlags.DEFAULT)
		remote_row.add_row(port_row)

		password_row=Adw.PasswordEntryRow(title=_("Password"))
		settings.bind("password", password_row, "text", Gio.SettingsBindFlags.DEFAULT)
		self.add(password_row)

		# connect button
		reconnect_button_content=Adw.ButtonContent(icon_name="view-refresh-symbolic", label=_("_Reconnect"), use_underline=True)
		reconnect_button=Gtk.Button(child=reconnect_button_content, has_frame=False)
		reconnect_button.connect("clicked", lambda *args: client.reconnect())
		self.set_header_suffix(reconnect_button)

class SettingsDialog(Adw.PreferencesDialog):
	def __init__(self, client, settings):
		super().__init__()
		page=Adw.PreferencesPage()
		page.add(ConnectionSettings(client, settings))
		page.add(ViewSettings(settings))
		page.add(BehaviorSettings(settings))
		self.add(page)

#################
# other dialogs #
#################

class ServerStats(Adw.Dialog):
	def __init__(self, client, settings):
		super().__init__(title=_("Server Statistics"), content_width=360, width_request=360, height_request=294)

		# list box
		list_box=Gtk.ListBox(valign=Gtk.Align.START)
		list_box.add_css_class("boxed-list")

		# populate
		display_str={
			"protocol": _("Protocol"),
			"uptime": _("Uptime"),
			"playtime": _("Playtime"),
			"artists": _("Artists"),
			"albums": _("Albums"),
			"songs": _("Songs"),
			"db_playtime": _("Total Playtime"),
			"db_update": _("Database Update")
		}
		stats=client.stats()
		stats["protocol"]=str(client.mpd_version)
		for key in ("uptime","playtime","db_playtime"):
			stats[key]=str(Duration(stats[key]))
		stats["db_update"]=GLib.DateTime.new_from_unix_local(int(stats["db_update"])).format("%a %d %B %Y, %H∶%M")
		for key in ("protocol","uptime","playtime","db_update","db_playtime","artists","albums","songs"):
			row=Adw.ActionRow(activatable=False, selectable=False, subtitle_selectable=True, title=display_str[key], subtitle=stats[key])
			row.add_css_class("property")
			list_box.append(row)

		# packing
		clamp=Adw.Clamp(child=list_box, margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
		scroll=Gtk.ScrolledWindow(child=clamp, propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
		toolbar_view=Adw.ToolbarView(content=scroll)
		toolbar_view.add_top_bar(Adw.HeaderBar())
		self.set_child(toolbar_view)

###########################
# general purpose widgets #
###########################

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
	__gsignals__={"selected": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
			"reselected": (GObject.SignalFlags.RUN_FIRST, None, ()),
			"clear": (GObject.SignalFlags.RUN_FIRST, None, ())}
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
		if position == 0:
			self.emit("clear")

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

	def set(self, position, item):
		if position < len(self.data):
			self.data[position]=item
			self.items_changed(position, 1, 1)
		else:
			self.data.append(item)
			self.items_changed(position, 0, 1)

	def select(self, position):
		if position == self._selected:
			self.emit("reselected")
		else:
			old_selected=self._selected
			self._selected=position
			if old_selected is not None:
				self.selection_changed(old_selected, 1)
			self.selection_changed(position, 1)
			self.emit("selected", position)

	def unselect(self):
		old_selected=self._selected
		self._selected=None
		if old_selected is not None:
			self.selection_changed(old_selected, 1)

	def do_select_item(self, position, unselect_rest): return False
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

class SongMenu(Gtk.PopoverMenu):
	def __init__(self, client):
		super().__init__(has_arrow=False, halign=Gtk.Align.START)
		self.update_property([Gtk.AccessibleProperty.LABEL], [_("Context menu")])
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
		menu.append(_("_Append"), "menu.append")
		menu.append(_("As _Next"), "menu.as_next")
		menu.append(_("_Play"), "menu.play")
		subsection=Gio.Menu()
		subsection.append(_("_Show"), "menu.show")
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
		self._track=Gtk.Label(xalign=1, single_line_mode=True, width_chars=3, css_classes=["numeric"])
		self._title=Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, hexpand=True)
		self._length=Gtk.Label(xalign=1, single_line_mode=True, css_classes=["numeric"])

		# packing
		self.append(self._track)
		self.append(self._title)
		self.append(self._length)

	def set_song(self, song):
		self._track.set_text(song["track"][0])
		self._title.set_markup(song.get_markup())
		self._length.set_text(str(song["duration"]))

	def unset_song(self):
		self._track.set_text("")
		self._title.set_text("")
		self._length.set_text("")

class SongList(Gtk.ListView):
	def __init__(self):
		super().__init__(tab_behavior=Gtk.ListTabBehavior.ITEM, css_classes=["rich-list"])
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
		computed_point,point=self._get_focus_row().compute_point(self, Graphene.Point.zero())
		if computed_point:
			return (point.x, point.y)
		return (0, 0)

	def get_focus_position(self):
		return self._get_focus_row().get_property("position")

	def get_focus_song(self):
		return self.get_model().get_item(self.get_focus_position())

	def get_position(self, x, y):
		item=self.pick(x,y,Gtk.PickFlags.DEFAULT)
		if item is self:
			return None
		return item.get_first_child().get_property("position")

	def get_song(self, position):
		return self.get_model().get_item(position)

class BrowserSongList(SongList):
	def __init__(self, client):
		super().__init__()
		self._client=client
		self._activate_on_release=False

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
		long_press_controller=Gtk.GestureLongPress(touch_only=True)
		self.add_controller(long_press_controller)
		drag_source=Gtk.DragSource()
		drag_source.set_icon(lookup_icon("audio-x-generic", 32, self.get_scale_factor()), 0, 0)
		self.add_controller(drag_source)

		# connect
		self.connect("activate", self._on_activate)
		button_controller.connect("pressed", self._on_button_pressed)
		button_controller.connect("stopped", self._on_button_stopped)
		button_controller.connect("released", self._on_button_released)
		long_press_controller.connect("pressed", self._on_long_pressed)
		drag_source.connect("prepare", self._on_drag_prepare)

	def clear(self):
		self._menu.popdown()
		self.get_model().clear()

	def append(self, data):
		self.get_model().append(data)

	def _on_activate(self, listview, pos):
		self._client.file_to_playlist(self.get_model().get_item(pos)["file"], "play")

	def _on_button_pressed(self, controller, n_press, x, y):
		if (position:=self.get_position(x,y)) is not None:
			if controller.get_current_button() == 1 and n_press == 1:
				self._activate_on_release=True
			elif controller.get_current_button() == 2 and n_press == 1:
				self._client.file_to_playlist(self.get_song(position)["file"], "append")
			elif controller.get_current_button() == 3 and n_press == 1:
				self._menu.open(self.get_song(position)["file"], x, y)

	def _on_button_stopped(self, controller):
		self._activate_on_release=False

	def _on_button_released(self, controller, n_press, x, y):
		if self._activate_on_release and (position:=self.get_position(x,y)) is not None:
			self._client.file_to_playlist(self.get_song(position)["file"], "play")
		self._activate_on_release=False

	def _on_long_pressed(self, controller, x, y):
		if (position:=self.get_position(x,y)) is not None:
			self._menu.open(self.get_song(position)["file"], x, y)

	def _on_menu(self, action, state):
		self._menu.open(self.get_focus_song()["file"], *self.get_focus_popup_point())

	def _on_drag_prepare(self, drag_source, x, y):
		if (position:=self.get_position(x,y)) is not None:
			return Gdk.ContentProvider.new_for_value(self.get_model().get_item(position))

###########
# browser #
###########

class SearchSongRow(Gtk.Box):
	def __init__(self, song):
		super().__init__()
		self.song=song

		# labels
		title_label=Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, hexpand=True)
		title_label.set_markup(song.get_markup())
		length_label=Gtk.Label(xalign=1, single_line_mode=True, css_classes=["numeric"])
		length_label.set_text(str(song["duration"]))

		# packing
		self.append(title_label)
		self.append(length_label)

class SearchView(Gtk.Stack):
	__gsignals__={"artist-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
			"song-selected": (GObject.SignalFlags.RUN_FIRST, None, (Song,))}
	def __init__(self, client):
		super().__init__()
		self._client=client

		# artist list
		self._artist_list=Gtk.ListBox(activate_on_single_click=True, selection_mode=Gtk.SelectionMode.NONE, valign=Gtk.Align.START)
		self._artist_list.add_css_class("rich-list")
		self._artist_list.add_css_class("boxed-list")

		# song list
		self._song_list=Gtk.ListBox(activate_on_single_click=True, selection_mode=Gtk.SelectionMode.NONE, valign=Gtk.Align.START)
		self._song_list.add_css_class("rich-list")
		self._song_list.add_css_class("boxed-list")

		# boxes
		self._artist_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
		self._artist_box.append(Gtk.Label(label=_("Artists"), xalign=0, css_classes=["heading"]))
		self._artist_box.append(self._artist_list)
		song_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
		song_box.append(Gtk.Label(label=_("Songs"), xalign=0, css_classes=["heading"]))
		song_box.append(self._song_list)
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=30, margin_start=12, margin_end=12, margin_top=24, margin_bottom=24)
		box.append(self._artist_box)
		box.append(song_box)

		# status page
		status_page=Adw.StatusPage(icon_name="edit-find-symbolic", title=_("No Results Found"), description=_("Try a different search"))

		# connect
		self._artist_list.connect("row-activated", self._on_artist_activate)
		self._song_list.connect("row-activated", self._on_song_activate)

		# packing
		self.add_named(Gtk.ScrolledWindow(child=Adw.Clamp(child=box)), "results")
		self.add_named(status_page, "no-results")

	def clear(self):
		self._artist_list.remove_all()
		self._song_list.remove_all()
		self.set_visible_child_name("results")

	def search(self, search_text, artists):
		self.clear()
		if (keywords:=search_text.split()):
			self._client.restrict_tagtypes("track", "title", "artist", "albumartist", "album", "date")
			expressions=" AND ".join((f"(any contains '{keyword}')" for keyword in keywords))
			songs=self._client.search(f"({expressions})", "window", "0:20")  # TODO adjust number of results
			self._client.tagtypes("all")
			for song in songs:
				row=SearchSongRow(song)
				self._song_list.append(row)
			if songs:
				artists=filter(lambda x: all(keyword.casefold() in x.name.casefold() for keyword in keywords), artists)
				for artist in itertools.islice(artists, 20):  # TODO adjust number of results
					label=Gtk.Label(xalign=0, single_line_mode=True, ellipsize=Pango.EllipsizeMode.END, label=artist.name)
					self._artist_list.append(label)
				self._artist_box.set_visible(self._artist_list.get_first_child() is not None)
			else:  # if no songs were found there also won't be any artists matching the keywords
				self.set_visible_child_name("no-results")
		else:
			self.set_visible_child_name("no-results")

	def _on_artist_activate(self, list_box, row):
		self.emit("artist-selected", row.get_child().get_label())

	def _on_song_activate(self, list_box, row):
		self.emit("song-selected", row.get_child().song)

class Artist(GObject.Object):
	def __init__(self, name):
		GObject.Object.__init__(self)
		self.name=name

class ArtistSelectionModel(SelectionModel):  # TODO
	def __init__(self):
		super().__init__(Artist)

	def set_artists(self, artists):
		self.clear()
		self.append((Artist(item[0]) for item in sorted(artists, key=lambda item: locale.strxfrm(item[1]))))

	def select_artist(self, name):
		for i, artist in enumerate(self.data):
			if artist.name == name:
				self.select(i)
				return

	def get_artist(self, position):
		return self.get_item(position).name

	def get_selected_artist(self):
		if (selected:=self.get_selected()) is None:
			return None
		else:
			return self.get_artist(selected)

class ArtistList(Gtk.ListView):
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
				label.set_markup(f'<i>{GLib.markup_escape_text(_("Unknown Artist"))}</i>')
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
		self.artist_selection_model=ArtistSelectionModel()
		self.set_model(self.artist_selection_model)

		# connect
		self.connect("activate", self._on_activate)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)
		self._client.emitter.connect("updated-db", self._on_updated_db)

	def select(self, name):
		self.artist_selection_model.select_artist(name)
		if (selected:=self.artist_selection_model.get_selected()) is None:
			self.artist_selection_model.select(0)
			self.scroll_to(0, Gtk.ListScrollFlags.FOCUS, None)
		else:
			self.scroll_to(selected, Gtk.ListScrollFlags.FOCUS, None)

	def _refresh(self):
		artists=self._client.list("albumartistsort", "group", "albumartist")
		filtered_artists=[]
		for name, artist in itertools.groupby(((artist["albumartist"], artist["albumartistsort"]) for artist in artists), key=lambda x: x[0]):
			filtered_artists.append(next(artist))
			# ignore multiple albumartistsort values
			if next(artist, None) is not None:
				filtered_artists[-1]=(name, name)
		self.artist_selection_model.set_artists(filtered_artists)

	def _on_activate(self, widget, pos):
		self.artist_selection_model.select(pos)

	def _on_disconnected(self, *args):
		self.artist_selection_model.clear()

	def _on_connected(self, emitter, database_is_empty):
		if not database_is_empty:
			self._refresh()
			if (song:=self._client.currentsong()):
				artist=song["albumartist"][0]
				self.select(artist)
			else:
				self.artist_selection_model.select(0)
				self.scroll_to(0, Gtk.ListScrollFlags.FOCUS, None)

	def _on_updated_db(self, emitter, database_is_empty):
		if database_is_empty:
			self.artist_selection_model.clear()
		else:
			if (artist:=self.artist_selection_model.get_selected_artist()) is None:
				self._refresh()
				self.artist_selection_model.select(0)
				self.scroll_to(0, Gtk.ListScrollFlags.FOCUS, None)
			else:
				self._refresh()
				self.select(artist)

class Album(GObject.Object):
	def __init__(self, artist, name, sortname, date):
		GObject.Object.__init__(self)
		self.artist=artist
		self.name=name
		self.sortname=sortname
		self.date=date
		self.cover=None

class SquareContainer(Gtk.Widget):
	def __init__(self, child):
		super().__init__(hexpand=True)
		child.set_parent(self)
		self.connect("destroy", lambda *args: child.unparent())

	def do_get_request_mode(self):
		return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

	def do_size_allocate(self, width, height, baseline):
		self.get_first_child().allocate(width, height, baseline, None)

	def do_measure(self, orientation, for_size):
		return (for_size, for_size, -1, -1)

class AlbumListRow(Gtk.Box):
	def __init__(self, client):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6, margin_top=6, margin_bottom=6)
		self._client=client
		self._cover=Gtk.Picture(margin_bottom=3)
		square_container=SquareContainer(self._cover)
		square_container.set_valign(Gtk.Align.START)
		self._title=Gtk.Label(single_line_mode=True, ellipsize=Pango.EllipsizeMode.END, css_classes=["heading"])
		self._date=Gtk.Label(single_line_mode=True)
		self.append(square_container)
		self.append(self._title)
		self.append(self._date)

	def set_album(self, album):
		if album.name:
			self._title.set_text(album.name)
			self._cover.update_property([Gtk.AccessibleProperty.LABEL], [_("Album cover of {album}").format(album=album.name)])
		else:
			self._title.set_markup(f'<i>{GLib.markup_escape_text(_("Unknown Album"))}</i>')
			self._cover.update_property([Gtk.AccessibleProperty.LABEL], [_("Album cover of an unknown album")])
		self._date.set_text(album.date)
		if album.cover is None:
			self._client.tagtypes("clear")
			song=self._client.find("albumartist", album.artist, "album", album.name, "date", album.date, "window", "0:1")[0]
			self._client.tagtypes("all")
			if (cover:=self._client.get_cover(song["file"])) is None:
				album.cover=lookup_icon(FALLBACK_COVER, 1024)
			else:
				album.cover=cover.get_paintable()
		self._cover.set_paintable(album.cover)

class AlbumList(Gtk.GridView):
	__gsignals__={"album-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,str,str,))}
	def __init__(self, client, settings):
		super().__init__(tab_behavior=Gtk.ListTabBehavior.ITEM, single_click_activate=True, vexpand=True, max_columns=2)
		self._settings=settings
		self._client=client

		# factory
		def setup(factory, item):
			row=AlbumListRow(self._client)
			item.set_child(row)
		def bind(factory, item):
			row=item.get_child()
			row.set_album(item.get_item())
		factory=Gtk.SignalListItemFactory()
		factory.connect("setup", setup)
		factory.connect("bind", bind)
		self.set_factory(factory)

		# model
		self._selection_model=SelectionModel(Album)
		self.set_model(self._selection_model)

		# connect
		self.connect("activate", self._on_activate)
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
		self.update_property([Gtk.AccessibleProperty.LABEL], [_("Albums of {artist}").format(artist=artist)])
		if self._settings.get_boolean("sort-albums-by-year"):
			self._selection_model.append(sorted(self._get_albums(artist), key=lambda item: item.date))
		else:
			self._selection_model.append(sorted(self._get_albums(artist), key=lambda item: locale.strxfrm(item.sortname)))
		self._settings.set_property("cursor-watch", False)

	def select(self, name, date):
		for i, album in enumerate(self._selection_model):
			if album.name == name and album.date == date:
				self.scroll_to(i, Gtk.ListScrollFlags.FOCUS, None)
				self.emit("album-selected", album.artist, album.name, album.date)
				return

	def _on_activate(self, widget, pos):
		album=self._selection_model.get_item(pos)
		self.emit("album-selected", album.artist, album.name, album.date)

class AlbumView(Gtk.Box):
	__gsignals__={"close": (GObject.SignalFlags.RUN_FIRST, None, ())}
	def __init__(self, client):
		super().__init__(orientation=Gtk.Orientation.VERTICAL)
		self._client=client
		self._tag_filter=()

		# songs list
		self.song_list=BrowserSongList(self._client)
		clamp=Adw.ClampScrollable(child=self.song_list)
		clamp.add_css_class("view")
		scroll=Gtk.ScrolledWindow(child=clamp, vexpand=True)
		scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

		# buttons
		self._buttons=Gtk.Box(spacing=6)
		data=((_("Append"), "list-add-symbolic", "append"),
			(_("Play"), "media-playback-start-symbolic", "play")
		)
		for tooltip, icon_name, mode in data:
			button=Gtk.Button(icon_name=icon_name, tooltip_text=tooltip)
			button.add_css_class("circular")
			button.connect("clicked", self._on_button_clicked, mode)
			self._buttons.append(button)

		# cover
		self._cover=Gtk.Picture()

		# labels
		self._title=Gtk.Label(xalign=0, wrap=True, css_classes=["heading"])
		self._date=Gtk.Label(xalign=0, single_line_mode=True)
		self._duration=Gtk.Label(xalign=0, wrap=True)

		# event controller
		button1_controller=Gtk.GestureClick(button=1)
		self._cover.add_controller(button1_controller)

		# connect
		button1_controller.connect("released", self._on_button1_released)

		# packing
		title_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.START, margin_top=9)
		title_box.append(self._title)
		title_box.append(self._date)
		control_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.END, margin_bottom=9, spacing=6)
		control_box.append(self._duration)
		control_box.append(self._buttons)
		header=Gtk.Grid(column_homogeneous=True, column_spacing=12, margin_end=12)
		header.attach(self._cover, 0, 0, 1, 2)
		header.attach(title_box, 1, 0, 1, 1)
		header.attach(control_box, 1, 1, 1, 1)
		self.append(Adw.Clamp(child=header))
		self.append(Gtk.Separator())
		self.append(scroll)

	def display(self, albumartist, album, date):
		if album:
			self._title.set_text(album)
			self._cover.update_property([Gtk.AccessibleProperty.LABEL], [_("Album cover of {album}").format(album=album)])
		else:
			self._title.set_markup(f'<i>{GLib.markup_escape_text(_("Unknown Album"))}</i>')
			self._cover.update_property([Gtk.AccessibleProperty.LABEL], [_("Album cover of an unknown album")])
		self._date.set_text(date)
		self.song_list.clear()
		self._tag_filter=("albumartist", albumartist, "album", album, "date", date)
		count=self._client.count(*self._tag_filter)
		duration=str(Duration(count["playtime"]))
		length=int(count["songs"])
		text=ngettext("{number} song ({duration})", "{number} songs ({duration})", length).format(number=length, duration=duration)
		self._duration.set_text(text)
		self._client.restrict_tagtypes("track", "title", "artist")
		songs=self._client.find(*self._tag_filter)
		self._client.tagtypes("all")
		self.song_list.append(songs)
		self.song_list.scroll_to(0, Gtk.ListScrollFlags.NONE, None)
		if (cover:=self._client.get_cover(songs[0]["file"])) is None:
			self._cover.set_paintable(lookup_icon(FALLBACK_COVER, 1024))
		else:
			self._cover.set_paintable(cover.get_paintable())

	def select(self, file):
		for i, song in enumerate(self.song_list.get_model()):
			if song["file"] == file:
				self.song_list.scroll_to(i, Gtk.ListScrollFlags.FOCUS, None)

	def _on_button1_released(self, controller, n_press, x, y):
		if self._cover.contains(x, y):
			self.emit("close")

	def _on_button_clicked(self, widget, mode):
		self._client.filter_to_playlist(self._tag_filter, mode)

class BreakpointBin(Adw.BreakpointBin):
	def __init__(self, grid):
		super().__init__(width_request=320, height_request=336)  # TODO height_request
		for width, columns in ((500,3), (850,4), (1200,5), (1500,6)):
			break_point=Adw.Breakpoint()
			break_point.set_condition(Adw.BreakpointCondition.parse(f"min-width: {width}sp"))
			break_point.add_setter(grid, "max-columns", columns)
			self.add_breakpoint(break_point)

class Browser(Gtk.Box):
	__gsignals__={"stop-search": (GObject.SignalFlags.RUN_FIRST, None, ())}
	def __init__(self, client, settings):
		super().__init__(orientation=Gtk.Orientation.VERTICAL)

		# widgets
		self._artist_list=ArtistList(client)
		self._album_list=AlbumList(client, settings)
		artist_window=Gtk.ScrolledWindow(child=self._artist_list, hexpand=True)
		album_window=Gtk.ScrolledWindow(child=self._album_list, hscrollbar_policy=Gtk.PolicyType.NEVER)
		self._album_view=AlbumView(client)
		self._search_window=SearchView(client)

		# navigation view
		self._navigation_view=Adw.NavigationView()
		albums_page=Adw.NavigationPage(child=album_window, title="Album List", tag="album_list")  # TODO title
		self._navigation_view.add(albums_page)
		album_page=Adw.NavigationPage(child=self._album_view, title="Album View", tag="album_view")  # TODO title
		self._navigation_view.add(album_page)

		# album list breakpoint bin
		album_list_breakpoint_bin=BreakpointBin(self._album_list)
		album_list_breakpoint_bin.set_child(self._navigation_view)

		# split view
		self._overlay_split_view=Adw.OverlaySplitView(sidebar=artist_window, content=album_list_breakpoint_bin)
		sidebar_button=Gtk.ToggleButton(icon_name="sidebar-show-symbolic", tooltip_text=_("Artists"))
		sidebar_button.bind_property("active", self._overlay_split_view, "show-sidebar", GObject.BindingFlags.BIDIRECTIONAL)
		self.sidebar_button_revealer=Gtk.Revealer(reveal_child=True, visible=False, transition_type=Gtk.RevealerTransitionType.CROSSFADE)
		self.sidebar_button_revealer.set_child(sidebar_button)

		# breakpoint bin
		breakpoint_bin=Adw.BreakpointBin(width_request=320, height_request=336)  # TODO height_request
		break_point=Adw.Breakpoint()
		break_point.set_condition(Adw.BreakpointCondition.parse(f"max-width: 550sp"))
		break_point.add_setter(self._overlay_split_view, "collapsed", True)
		break_point.add_setter(self.sidebar_button_revealer, "visible", True)
		breakpoint_bin.add_breakpoint(break_point)
		breakpoint_bin.set_child(self._overlay_split_view)

		# status page
		status_page=Adw.StatusPage(title=_("Collection is Empty"), icon_name="folder-music-symbolic")

		# stacks
		# TODO names
		self._collection_stack=Gtk.Stack()
		self._collection_stack.add_named(breakpoint_bin, "browser")
		self._collection_stack.add_named(status_page, "empty-collection")
		self._main_stack=Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
		self._main_stack.add_named(self._collection_stack, "collection")
		self._main_stack.add_named(self._search_window, "search")

		# connect
		self._album_list.connect("album-selected", self._on_album_selected)
		self._album_view.connect("close", lambda *args: self._navigation_view.pop_to_tag("album_list"))
		self._artist_list.artist_selection_model.connect("selected", self._on_artist_selected)
		self._artist_list.artist_selection_model.connect("reselected", self._on_artist_reselected)
		self._artist_list.artist_selection_model.connect("clear", self._album_list.clear)
		self._search_window.connect("artist-selected", self._on_search_artist_selected)
		self._search_window.connect("song-selected", self._on_search_song_selected)
		client.emitter.connect("disconnected", self._on_disconnected)
		client.emitter.connect("connection-error", self._on_connection_error)
		client.emitter.connect("connected", self._on_connected_or_updated_db)
		client.emitter.connect("updated-db", self._on_connected_or_updated_db)

		# packing
		self.append(self._main_stack)

	def search(self, search_text):
		if search_text:
			self.sidebar_button_revealer.set_reveal_child(False)
			self._main_stack.set_visible_child_name("search")
			self._search_window.search(search_text, self._artist_list.artist_selection_model)
		else:
			self.sidebar_button_revealer.set_reveal_child(True)
			self._main_stack.set_visible_child_name("collection")
			self._search_window.clear()

	def _on_artist_selected(self, model, position):
		if self._overlay_split_view.get_collapsed():
			self._overlay_split_view.set_show_sidebar(False)
		self._navigation_view.pop_to_tag("album_list")
		self._album_list.display(model.get_artist(position))

	def _on_artist_reselected(self, model):
		if self._overlay_split_view.get_collapsed():
			self._overlay_split_view.set_show_sidebar(False)
		self._navigation_view.pop_to_tag("album_list")

	def _on_album_selected(self, widget, *tags):
		self._album_view.display(*tags)
		self._navigation_view.push_by_tag("album_view")
		self._album_view.song_list.grab_focus()

	def _on_search_artist_selected(self, widget, artist):
		self._artist_list.select(artist)
		self.emit("stop-search")
		self._main_stack.set_visible_child_name("collection")

	def _on_search_song_selected(self, widget, song):
		self._artist_list.select(song["albumartist"][0])
		self._album_list.select(song["album"][0], song["date"][0])
		self._album_view.select(song["file"])
		self.emit("stop-search")
		self._main_stack.set_visible_child_name("collection")
		# TODO https://lazka.github.io/pgi-docs/Gtk-4.0/classes/Window.html#Gtk.Window.set_focus_visible
		self.get_root().set_focus_visible(True)

	def _on_disconnected(self, *args):
		self._navigation_view.pop_to_tag("album_list")
		self._collection_stack.set_visible_child_name("browser")

	def _on_connection_error(self, *args):
		self._collection_stack.set_visible_child_name("empty-collection")

	def _on_connected_or_updated_db(self, emitter, database_is_empty):
		self.emit("stop-search")
		if database_is_empty:
			self._collection_stack.set_visible_child_name("empty-collection")
		else:
			self._collection_stack.set_visible_child_name("browser")

############
# playlist #
############

class PlaylistMenu(Gtk.PopoverMenu):
	def __init__(self, client):
		super().__init__(has_arrow=False, halign=Gtk.Align.START)
		self.update_property([Gtk.AccessibleProperty.LABEL], [_("Context menu")])
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
		menu.append(_("_Remove"), "menu.remove")
		menu.append(_("_Show"), "menu.show")
		current_song_section=Gio.Menu()
		current_song_section.append(_("_Enqueue Album"), "mpd.enqueue")
		current_song_section.append(_("_Tidy"), "mpd.tidy")
		subsection=Gio.Menu()
		subsection.append(_("_Clear"), "mpd.clear")
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
	def __init__(self, client):
		super().__init__()
		self._client=client
		self._playlist_version=None
		self._activate_on_release=False
		self._autoscroll=True

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
		long_press_controller=Gtk.GestureLongPress(touch_only=True)
		self.add_controller(long_press_controller)
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
		button_controller.connect("stopped", self._on_button_stopped)
		button_controller.connect("released", self._on_button_released)
		long_press_controller.connect("pressed", self._on_long_pressed)
		drag_source.connect("prepare", self._on_drag_prepare)
		drop_target.connect("drop", self._on_drop)
		self._client.emitter.connect("playlist", self._on_playlist_changed)
		self._client.emitter.connect("current-song", self._on_song_changed)
		self._client.emitter.connect("disconnected", self._on_disconnected)

	def _clear(self, *args):
		self._menu.popdown()
		self._playlist_version=None
		self.get_model().clear()

	def _delete(self, position):
		if position == self.get_model().get_selected():
			self._client.tidy_playlist()
		else:
			self._client.delete(position)

	def _refresh_selection(self, song):
		if song is None:
			self.get_model().unselect()
		else:
			self.get_model().select(int(song))

	def _on_button_pressed(self, controller, n_press, x, y):
		if (position:=self.get_position(x,y)) is None:
			if controller.get_current_button() == 3 and n_press == 1:
				self._menu.open(None, None, x, y)
		else:
			if controller.get_current_button() == 1 and n_press == 1:
				self._activate_on_release=True
			elif controller.get_current_button() == 2 and n_press == 1:
				self._delete(position)
			elif controller.get_current_button() == 3 and n_press == 1:
				self._menu.open(self.get_song(position)["file"], position, x, y)

	def _on_button_stopped(self, controller):
		self._activate_on_release=False

	def _on_button_released(self, controller, n_press, x, y):
		if self._activate_on_release and (position:=self.get_position(x,y)) is not None:
			self._autoscroll=False
			self._client.play(position)
		self._activate_on_release=False

	def _on_long_pressed(self, controller, x, y):
		if (position:=self.get_position(x,y)) is None:
			self._menu.open(None, None, x, y)
		else:
			self._menu.open(self.get_song(position)["file"], position, x, y)

	def _on_activate(self, listview, pos):
		self._autoscroll=False
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
		if self._playlist_version is None and (selected:=self.get_model().get_selected()) is not None:  # always scroll to song on startup
			self.scroll_to(selected, Gtk.ListScrollFlags.FOCUS, None)
		self._playlist_version=version

	def _on_song_changed(self, emitter, song, songid, state):
		self._refresh_selection(song)
		if self._autoscroll:
			if (selected:=self.get_model().get_selected()) is not None and state == "play":
				self.scroll_to(selected, Gtk.ListScrollFlags.FOCUS, None)
				adj=self.get_vadjustment()
				value=adj.get_upper()*selected/self.get_model().get_n_items()-self.get_parent().get_height()*0.3
				if value >= adj.get_value():
					adj.set_value(value)
		else:
			self._autoscroll=True

	def _on_menu(self, action, state):
		self._menu.open(self.get_focus_song()["file"], self.get_focus_position(), *self.get_focus_popup_point())

	def _on_delete(self, action, state):
		self._delete(self.get_focus_position())

	def _on_drag_prepare(self, drag_source, x, y):
		if (position:=self.get_position(x,y)) is not None:
			return Gdk.ContentProvider.new_for_value(position)

	def _point_in_upper_half(self, x, y, widget):
		point=Graphene.Point.zero()
		point.x,point.y=x,y
		computed_point,point=self.compute_point(widget, point)
		if computed_point:
			return point.y > widget.get_height()/2
		return False

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
				if self._point_in_upper_half(x, y, item):
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
				if self._point_in_upper_half(x, y, item):
					position+=1
			else:
				position=self.get_model().get_n_items()
			self._client.addid(value["file"], position)
			return True
		return False

	def _on_disconnected(self, *args):
		self._clear()

class PlaylistWindow(Gtk.Stack):
	def __init__(self, client):
		super().__init__(vhomogeneous=False)
		self._client=client

		# widgets
		self._playlist_view=PlaylistView(self._client)
		self._scroll=Gtk.ScrolledWindow(child=self._playlist_view, hexpand=True, vexpand=True)
		self._adj=self._scroll.get_vadjustment()
		status_page=Adw.StatusPage(icon_name="view-list-symbolic", title=_("Playlist is Empty"))
		status_page.add_css_class("compact")

		# scroll button
		overlay=Gtk.Overlay(child=self._scroll)
		self._scroll_button=Gtk.Button(css_classes=["osd", "circular"], tooltip_text=_("Scroll to Current Song"),
			margin_bottom=6, margin_top=6, halign=Gtk.Align.CENTER, visible=False)
		overlay.add_overlay(self._scroll_button)

		# event controller
		drop_target=Gtk.DropTarget()
		drop_target.set_actions(Gdk.DragAction.COPY)
		drop_target.set_gtypes((Song,))
		status_page.add_controller(drop_target)

		# connect
		drop_target.connect("drop", self._on_drop)
		self._scroll_button.connect("clicked", self._on_scroll_button_clicked)
		self._adj.connect("value-changed", self._update_scroll_button_visibility)
		self._playlist_view.get_model().connect("selection-changed", self._update_scroll_button_visibility)
		self._client.emitter.connect("playlist", self._on_playlist_changed)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connection-error", self._on_connection_error)

		# packing
		self.add_named(overlay, "playlist")
		self.add_named(status_page, "empty-playlist")

	def _on_drop(self, drop_target, value, x, y):
		if isinstance(value, Song):
			self._client.addid(value["file"])
			return True
		return False

	def _on_playlist_changed(self, emitter, version, length, song_pos):
		if length:
			self.set_visible_child_name("playlist")
		else:
			self.set_visible_child_name("empty-playlist")

	def _on_scroll_button_clicked(self, *args):
		if (selected:=self._playlist_view.get_model().get_selected()) is not None:
			self._playlist_view.scroll_to(selected, Gtk.ListScrollFlags.FOCUS, None)
		self._scroll_button.set_visible(False)

	def _update_scroll_button_visibility(self, *args):
		if (selected:=self._playlist_view.get_model().get_selected()) is None:
			self._scroll_button.set_visible(False)
		else:
			row_height=self._adj.get_upper()/self._playlist_view.get_model().get_n_items()
			value=self._adj.get_upper()*selected/self._playlist_view.get_model().get_n_items()+1/2*row_height
			if self._adj.get_value() > value:
				self._scroll_button.set_icon_name("go-up-symbolic")
				self._scroll_button.set_valign(Gtk.Align.START)
				self._scroll_button.set_visible(True)
			elif self._adj.get_value() < value-self._scroll.get_height():
				self._scroll_button.set_icon_name("go-down-symbolic")
				self._scroll_button.set_valign(Gtk.Align.END)
				self._scroll_button.set_visible(True)
			else:
				self._scroll_button.set_visible(False)

	def _on_disconnected(self, *args):
		self.set_visible_child_name("playlist")

	def _on_connection_error(self, *args):
		self.set_visible_child_name("empty-playlist")

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

class LyricsWindow(Gtk.Stack):
	def __init__(self, client):
		super().__init__()
		self._client=client
		self._displayed_song_file=None

		# status pages
		no_lyrics_status_page=Adw.StatusPage(icon_name="lyrics-symbolic", title=_("No Lyrics Found"))
		no_lyrics_status_page.add_css_class("compact")
		connection_error_status_page=Adw.StatusPage(
			icon_name="network-wired-disconnected-symbolic", title=_("Connection Error"), description=_("Check your network connection"))
		connection_error_status_page.add_css_class("compact")

		# text view
		self._text_view=Gtk.TextView(
			editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD,
			justification=Gtk.Justification.CENTER,
			left_margin=12, right_margin=12, bottom_margin=9, top_margin=9
		)

		# text buffer
		self._text_buffer=self._text_view.get_buffer()

		# connect
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._song_changed=self._client.emitter.connect("current-song", self._refresh)
		self._client.emitter.handler_block(self._song_changed)

		# packing
		scroll=Gtk.ScrolledWindow(child=self._text_view)
		self.add_named(scroll, "lyrics")
		self.add_named(no_lyrics_status_page, "no-lyrics")
		self.add_named(connection_error_status_page, "connection-error")

	def enable(self, *args):
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
		try:
			text=self._get_lyrics(song["title"][0], song["artist"][0])
			idle_add(self._text_buffer.set_text, text)
		except urllib.error.URLError:
			idle_add(self.set_visible_child_name, "connection-error")
		except ValueError:
			idle_add(self.set_visible_child_name, "no-lyrics")

	def _refresh(self, *args):
		if self._client.connected() and (song:=self._client.currentsong()):
			self._text_view.update_property([Gtk.AccessibleProperty.LABEL], [_("Lyrics of {song}").format(song=song["title"])])
			self._text_buffer.set_text(_("searching…"))
			self.set_visible_child_name("lyrics")
			update_thread=threading.Thread(target=self._display_lyrics, kwargs={"song": song}, daemon=True)
			update_thread.start()
		else:
			self.set_visible_child_name("no-lyrics")
			self._text_buffer.set_text("")
			self._text_view.update_property([Gtk.AccessibleProperty.LABEL], [_("Lyrics view")])

	def _on_disconnected(self, *args):
		self.set_visible_child_name("no-lyrics")
		self._text_buffer.set_text("")
		self._text_view.update_property([Gtk.AccessibleProperty.LABEL], [_("Lyrics view")])

class MainCover(Gtk.Picture):
	def __init__(self, client):
		super().__init__()
		self.update_property([Gtk.AccessibleProperty.LABEL], [_("Current album cover")])
		self._client=client

		# connect
		self._client.emitter.connect("current-song", self._refresh)
		self._client.emitter.connect("disconnected", self._on_disconnected)

	def _clear(self):
		self.set_paintable(lookup_icon(FALLBACK_COVER, 1024))

	def _refresh(self, *args):
		if self._client.current_cover is None:
			self._clear()
		else:
			self.set_paintable(self._client.current_cover.get_paintable())

	def _on_disconnected(self, *args):
		self._clear()

class CoverLyricsWindow(Gtk.Stack):
	show_lyrics=GObject.Property(type=bool, default=False)
	def __init__(self, client):
		super().__init__(transition_type=Gtk.StackTransitionType.CROSSFADE)

		# cover
		main_cover=MainCover(client)
		window_handle=Gtk.WindowHandle(child=main_cover)

		# lyrics window
		self._lyrics_window=LyricsWindow(client)

		# connect
		self.connect("notify::show-lyrics", self._on_lyrics_toggled)

		# packing
		self.add_named(window_handle, "cover")
		self.add_named(self._lyrics_window, "lyrics")

	def _on_lyrics_toggled(self, *args):
		if self.get_property("show-lyrics"):
			self.set_visible_child_name("lyrics")
			self._lyrics_window.enable()
		else:
			self.set_visible_child_name("cover")
			self._lyrics_window.disable()

######################
# action bar widgets #
######################

class PlaybackControl(Gtk.Box):
	def __init__(self, client, settings):
		super().__init__(spacing=6)

		# widgets
		self._play_button=Gtk.Button(icon_name="media-playback-start-symbolic", action_name="mpd.toggle-play", tooltip_text=_("Play"))
		stop_button=Gtk.Button(icon_name="media-playback-stop-symbolic", tooltip_text=_("Stop"), action_name="mpd.stop")
		settings.bind("show-stop", stop_button, "visible", Gio.SettingsBindFlags.GET)
		prev_button=Gtk.Button(icon_name="media-skip-backward-symbolic", tooltip_text=_("Previous"), action_name="mpd.prev")
		next_button=Gtk.Button(icon_name="media-skip-forward-symbolic", tooltip_text=_("Next"), action_name="mpd.next")

		# connect
		client.emitter.connect("state", self._on_state)

		# packing
		self.append(prev_button)
		self.append(self._play_button)
		self.append(stop_button)
		self.append(next_button)

	def _on_state(self, emitter, state):
		if state == "play":
			self._play_button.set_property("icon-name", "media-playback-pause-symbolic")
			self._play_button.set_tooltip_text(_("Pause"))
		else:
			self._play_button.set_property("icon-name", "media-playback-start-symbolic")
			self._play_button.set_tooltip_text(_("Play"))

class SeekBar(Gtk.Box):
	def __init__(self, client):
		super().__init__(hexpand=True, margin_start=6, margin_end=6)
		self._client=client
		self._first_mark=None
		self._second_mark=None

		# labels
		self._elapsed=Gtk.Label(xalign=0, single_line_mode=True, css_classes=["numeric"])
		self._rest=Gtk.Label(xalign=1, single_line_mode=True, css_classes=["numeric"])

		# progress bar
		self._scale=Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, draw_value=False, hexpand=True)
		self._scale.set_increments(10, 10)
		self._scale.update_property([Gtk.AccessibleProperty.LABEL], [_("Progress bar")])
		self._adjustment=self._scale.get_adjustment()

		# popover
		self._popover=Gtk.Popover(autohide=False, has_arrow=False)
		self._time_label=Gtk.Label(single_line_mode=True, css_classes=["numeric"])
		self._popover.set_child(self._time_label)
		self._popover.set_parent(self)
		self._popover.set_position(Gtk.PositionType.TOP)

		# event controllers
		controller_motion=Gtk.EventControllerMotion()
		self._scale.add_controller(controller_motion)
		elapsed_button1_controller=Gtk.GestureClick(button=1)
		self._elapsed.add_controller(elapsed_button1_controller)
		rest_button1_controller=Gtk.GestureClick(button=1)
		self._rest.add_controller(rest_button1_controller)

		# connect
		self._scale.connect("change-value", self._on_change_value)
		controller_motion.connect("motion", self._on_pointer_motion)
		controller_motion.connect("leave", self._on_pointer_leave)
		elapsed_button1_controller.connect("released", self._on_label_button_released)
		rest_button1_controller.connect("released", self._on_label_button_released)
		self._client.emitter.connect("disconnected", self._disable)
		self._client.emitter.connect("state", self._on_state)
		self._client.emitter.connect("elapsed", self._refresh)
		self._client.emitter.connect("current-song", self._on_song_changed)

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
		point=Graphene.Point.zero()
		point.x=x
		computed_point,point=self._scale.compute_point(self, point)
		if computed_point:
			rect=Gdk.Rectangle()
			rect.x,rect.y=point.x,0
			self._popover.set_pointing_to(rect)
			self._popover.popup()

	def _on_pointer_leave(self, *args):
		self._popover.popdown()

	def _on_label_button_released(self, controller, n_press, x, y):
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
		super().__init__(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, margin_end=3)
		self._client=client
		settings.bind("show-audio-format", self, "visible", Gio.SettingsBindFlags.GET)

		# labels
		self._file_type_label=Gtk.Label(xalign=1, single_line_mode=True)
		self._separator_label=Gtk.Label(xalign=1, single_line_mode=True)
		self._brate_label=Gtk.Label(xalign=1, single_line_mode=True, width_chars=5, css_classes=["numeric"])
		self._format_label=Gtk.Label(single_line_mode=True, css_classes=["caption"])

		# connect
		self._client.emitter.connect("audio", self._on_audio)
		self._client.emitter.connect("bitrate", self._on_bitrate)
		self._client.emitter.connect("current-song", self._on_song_changed)
		self._client.emitter.connect("disconnected", self._on_disconnected)

		# packing
		hbox=Gtk.Box(halign=Gtk.Align.END)
		hbox.append(self._brate_label)
		hbox.append(self._separator_label)
		hbox.append(self._file_type_label)
		self.append(hbox)
		self.append(self._format_label)

	def _on_audio(self, emitter, audio_format):
		if audio_format is None:
			self._format_label.set_text("")
		else:
			self._format_label.set_text(str(Format(audio_format)))

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
			self._format_label.set_text("")

	def _on_disconnected(self, *args):
		self._brate_label.set_text("—")
		self._separator_label.set_text(" kb/s")
		self._file_type_label.set_text("")
		self._format_label.set_text("")

class VolumeControl(Gtk.Box):
	def __init__(self, client):
		super().__init__(orientation=Gtk.Orientation.HORIZONTAL, margin_start=12, margin_end=3)
		self._client=client

		# adjustment
		scale=Gtk.Scale(hexpand=True)
		scale.update_property([Gtk.AccessibleProperty.LABEL], [_("Volume control")])
		self._adjustment=scale.get_adjustment()
		self._adjustment.configure(0, 0, 100, 5, 5, 0)

		# connect
		scale.connect("change-value", self._on_change_value)
		self._client.emitter.connect("volume", self._refresh)

		# packing
		self.append(Gtk.Image(icon_name="audio-speakers-symbolic"))
		self.append(scale)

	def _on_change_value(self, scale, scroll, value):
		self._client.setvol(str(int(max(min(value, 100), 0))))

	def _refresh(self, emitter, volume):
		self._adjustment.set_value(max(volume, 0))

class MainMenuButton(Gtk.MenuButton):
	def __init__(self, client):
		super().__init__(icon_name="open-menu-symbolic", tooltip_text=_("Main Menu"), primary=True)
		self._volume_visible=False

		# volume
		self._volume_control=VolumeControl(client)
		self._volume_item=Gio.MenuItem()
		self._volume_item.set_attribute_value("custom", GLib.Variant("s", "volume"))

		# menu model
		app_section=Gio.Menu()
		app_section.append(_("_Preferences"), "win.settings")
		app_section.append(_("_Keyboard Shortcuts"), "win.show-help-overlay")
		app_section.append(_("_Help"), "win.help")
		app_section.append(_("_About Plattenalbum"), "app.about")
		mpd_section=Gio.Menu()
		mpd_section.append(_("_Reconnect"), "win.reconnect")
		mpd_section.append(_("_Update Database"), "mpd.update")
		mpd_section.append(_("_Server Statistics"), "win.stats")
		playback_section=Gio.Menu()
		playback_section.append(_("_Repeat Mode"), "mpd.repeat")
		playback_section.append(_("R_andom Mode"), "mpd.random")
		playback_section.append(_("_Single Mode"), "mpd.single")
		playback_section.append(_("_Pause After Song"), "mpd.single-oneshot")
		playback_section.append(_("_Consume Mode"), "mpd.consume")
		self._playback_submenu=Gio.Menu()
		self._playback_submenu.append_section(None, playback_section)
		menu=Gio.Menu()
		menu.append(_("_Lyrics"), "win.toggle-lyrics")
		menu.append_submenu(_("Play_back"), self._playback_submenu)
		menu.append_section(None, mpd_section)
		menu.append_section(None, app_section)

		# popover menu
		self._popover_menu=Gtk.PopoverMenu.new_from_model(menu)
		self.set_popover(self._popover_menu)

		# connect
		client.emitter.connect("volume", self._on_volume_changed)
		client.emitter.connect("disconnected", self._on_disconnected)

	def _on_volume_changed(self, emitter, volume):
		if volume < 0 and self._volume_visible:
			self._playback_submenu.remove(0)
			self._volume_visible=False
		elif volume >= 0 and not self._volume_visible:
			self._playback_submenu.prepend_item(self._volume_item)
			self._popover_menu.add_child(self._volume_control, "volume")
			self._volume_visible=True

	def _on_disconnected(self, *args):
		if self._volume_visible:
			self._playback_submenu.remove(0)
			self._volume_visible=False

###################
# MPD gio actions #
###################
class MPDActionGroup(Gio.SimpleActionGroup):
	def __init__(self, client):
		super().__init__()
		self._client=client

		# actions
		self._disable_on_stop_data=["next","prev","seek-forward","seek-backward"]
		self._disable_no_song=["tidy","enqueue"]
		self._enable_on_reconnect_data=["toggle-play","stop","clear","update"]
		self._data=self._disable_on_stop_data+self._disable_no_song+self._enable_on_reconnect_data
		for name in self._data:
			action=Gio.SimpleAction.new(name, None)
			action.connect("activate", getattr(self, ("_on_"+name.replace("-","_"))))
			self.add_action(action)
		playback_data=["repeat","random","single","single-oneshot","consume"]
		self._enable_on_reconnect_data+=playback_data
		self._data+=playback_data
		for name in playback_data:
			action=Gio.SimpleAction.new_stateful(name , None, GLib.Variant("b", False))
			handler=action.connect("notify::state", self._on_mode_change, name)
			self.add_action(action)
			self._client.emitter.connect(name, self._update_action, action, handler)

		# connect
		self._client.emitter.connect("state", self._on_state)
		self._client.emitter.connect("current-song", self._on_song_changed)
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

	def _update_action(self, emitter, value, action, handler):
		action.handler_block(handler)
		action.set_state(GLib.Variant("b", value))
		action.handler_unblock(handler)

	def _on_mode_change(self, action, typestring, name):
		if name == "single-oneshot":
			self._client.single("oneshot" if action.get_state() else "0")
		else:
			getattr(self._client, name)("1" if action.get_state() else "0")

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
class MainWindow(Adw.ApplicationWindow):
	def __init__(self, client, settings, **kwargs):
		super().__init__(title="Plattenalbum", icon_name="de.wagnermartin.Plattenalbum", height_request=480, width_request=620, **kwargs)
		self.set_default_icon_name("de.wagnermartin.Plattenalbum")
		self._client=client
		self._settings=settings

		# shortcuts
		builder=Gtk.Builder()
		builder.add_from_resource("/de/wagnermartin/Plattenalbum/ShortcutsWindow.ui")
		self.set_help_overlay(builder.get_object("shortcuts_window"))

		# widgets
		cover_playlist_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self._browser=Browser(self._client, self._settings)
		cover_lyrics_window=CoverLyricsWindow(self._client)
		playlist_window=PlaylistWindow(self._client)
		playback_control=PlaybackControl(self._client, self._settings)
		seek_bar=SeekBar(self._client)
		audio=AudioFormat(self._client, self._settings)
		main_menu_button=MainMenuButton(self._client)
		self._updating_toast=Adw.Toast(title=_("Database is being updated"), timeout=0)
		self._updated_toast=Adw.Toast(title=_("Database updated"))

		# actions
		simple_actions_data=("close", "settings","reconnect","stats","help","toggle-search","toggle-artists")
		for name in simple_actions_data:
			action=Gio.SimpleAction.new(name, None)
			action.connect("activate", getattr(self, ("_on_"+name.replace("-","_"))))
			self.add_action(action)
		self.add_action(Gio.PropertyAction.new("toggle-lyrics", cover_lyrics_window, "show-lyrics"))

		# search
		self._search_button=Gtk.ToggleButton(icon_name="system-search-symbolic", tooltip_text=_("Search"))
		self._search_entry=Gtk.SearchEntry(placeholder_text=_("Search collection"))
		self._search_entry.update_property([Gtk.AccessibleProperty.LABEL], [_("Search collection")])
		self._search_entry.set_key_capture_widget(self)  # type to search

		# left button box
		self._left_button_box=Gtk.Box(spacing=6)
		self._left_button_box.append(self._search_button)
		self._left_button_box.append(self._browser.sidebar_button_revealer)

		# header bar
		self._title=Adw.WindowTitle()
		self._title_stack=Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, hexpand=True, hhomogeneous=False)
		self._title_stack.add_named(self._title, "title")
		self._title_stack.add_named(Adw.Clamp(child=self._search_entry, maximum_size=400), "search-entry")
		header_bar=Adw.HeaderBar(title_widget=self._title_stack)
		header_bar.pack_start(self._left_button_box)
		header_bar.pack_end(main_menu_button)

		# sidebar
		cover_playlist_box.append(cover_lyrics_window)
		cover_playlist_box.append(Gtk.Separator())
		cover_playlist_box.append(playlist_window)
		sidebar=Gtk.Box()
		sidebar.add_css_class("view")
		sidebar.append(Gtk.Separator())
		sidebar.append(cover_playlist_box)

		# split view
		overlay_split_view=Adw.OverlaySplitView(
			sidebar_position=Gtk.PackType.END, min_sidebar_width=300, max_sidebar_width=500, sidebar_width_fraction=0.30)
		overlay_split_view.set_content(self._browser)
		overlay_split_view.set_sidebar(sidebar)

		# status page
		status_page=Adw.StatusPage(icon_name="de.wagnermartin.Plattenalbum", title=_("Not Connected"))
		status_page.set_description(_("To use Plattenalbum an instance of the “Music Player Daemon” "\
			"needs to be set up and running on this or another device in the network"))
		reconnect_button=Gtk.Button(label=_("_Reconnect"), use_underline=True, action_name="win.reconnect")
		reconnect_button.set_css_classes(["suggested-action", "pill"])
		settings_button=Gtk.Button(label=_("_Preferences"), use_underline=True, action_name="win.settings")
		settings_button.add_css_class("pill")
		button_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, spacing=12)
		button_box.append(reconnect_button)
		button_box.append(settings_button)
		status_page.set_child(button_box)

		# stack
		self._status_page_stack=Gtk.Stack()
		self._status_page_stack.add_named(overlay_split_view, "content")
		self._status_page_stack.add_named(status_page, "status-page")

		# action bar
		self._action_bar=Gtk.Box()
		self._action_bar.add_css_class("toolbar")
		self._action_bar.append(playback_control)
		self._action_bar.append(seek_bar)
		self._action_bar.append(audio)

		# toolbar view
		self._toolbar_view=Adw.ToolbarView(top_bar_style=Adw.ToolbarStyle.RAISED_BORDER, bottom_bar_style=Adw.ToolbarStyle.RAISED_BORDER)
		self._toolbar_view.add_top_bar(header_bar)
		self._toolbar_view.add_bottom_bar(self._action_bar)
		self._toolbar_view.set_content(self._status_page_stack)

		# event controller
		controller_focus=Gtk.EventControllerFocus()
		self._search_entry.add_controller(controller_focus)

		# connect
		controller_focus.connect("enter", self._on_search_entry_focus_event, True)
		controller_focus.connect("leave", self._on_search_entry_focus_event, False)
		self._search_entry.connect("search-started", self._on_search_started)
		self._search_entry.connect("search-changed", self._on_search_changed)
		self._search_entry.connect("stop-search", self._on_search_stopped)
		self._browser.connect("stop-search", self._on_search_stopped)
		self._search_button.connect("clicked", self._on_search_button_clicked)
		self._settings.connect_after("notify::cursor-watch", self._on_cursor_watch)
		self._client.emitter.connect("current-song", self._on_song_changed)
		self._client.emitter.connect("connected", self._on_connected)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connecting", self._on_connecting)
		self._client.emitter.connect("connection_error", self._on_connection_error)
		self._client.emitter.connect("updating-db", self._on_updating_db)
		self._client.emitter.connect("updated-db", self._on_updated_db)

		# packing
		self._toast_overlay=Adw.ToastOverlay(child=self._toolbar_view)
		self.set_content(self._toast_overlay)

	def open(self):
		# bring player in consistent state
		self._client.emitter.emit("disconnected")
		self._client.emitter.emit("connecting")
		# set default window size
		self.set_default_size(self._settings.get_int("width"), self._settings.get_int("height"))
		self._settings.bind("width", self, "default-width", Gio.SettingsBindFlags.SET)
		self._settings.bind("height", self, "default-height", Gio.SettingsBindFlags.SET)
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
		self.set_title("Plattenalbum")
		self._title.set_title("Plattenalbum")
		self._title.set_subtitle("")

	def _on_toggle_search(self, action, param):
		self._search_button.emit("clicked")

	def _on_toggle_artists(self, action, param):
		revealer=self._browser.sidebar_button_revealer
		if revealer.get_visible() and revealer.get_reveal_child():
			revealer.get_child().grab_focus()
			revealer.get_child().emit("clicked")

	def _on_close(self, action, param):
		if (dialog:=self.get_visible_dialog()) is None:
			self.close()
		else:
			dialog.close()

	def _on_settings(self, action, param):
		settings=SettingsDialog(self._client, self._settings)
		settings.present(self)

	def _on_reconnect(self, action, param):
		self._client.reconnect()

	def _on_stats(self, action, param):
		stats=ServerStats(self._client, self._settings)
		stats.present(self)

	def _on_help(self, action, param):
		Gtk.UriLauncher(uri="https://github.com/SoongNoonien/plattenalbum/wiki/Usage").launch(self, None, None, None)

	def _on_search_started(self, entry):
		self._search_button.set_active(True)
		self._title_stack.set_visible_child_name("search-entry")
		self._search_entry.grab_focus()

	def _on_search_changed(self, entry):
		search_text=self._search_entry.get_text()
		if search_text:
			self._search_entry.grab_focus()
		self._browser.search(search_text)

	def _on_search_stopped(self, widget):
		self._search_button.set_active(False)
		self._title_stack.set_visible_child_name("title")
		self._search_entry.set_text("")

	def _on_search_button_clicked(self, button):
		if button.get_active():
			self._title_stack.set_visible_child_name("search-entry")
			self._search_entry.grab_focus()
		else:
			self._title_stack.set_visible_child_name("title")
			self._search_entry.set_text("")

	def _on_search_entry_focus_event(self, controller, focus):
		if focus:
			self.get_application().set_accels_for_action("mpd.toggle-play", [])
		else:
			self.get_application().set_accels_for_action("mpd.toggle-play", ["space"])

	def _on_song_changed(self, emitter, song, songid, state):
		if (song:=self._client.currentsong()):
			window_title=" • ".join(filter(None, (song["title"][0], str(song["artist"]))))
			self.set_title(window_title)
			self._title.set_title(window_title)
			self._title.set_subtitle(song.get_album_with_date())
			if self._settings.get_boolean("send-notify"):
				if not self.is_active() and state == "play":
					notify=Gio.Notification()
					notify.set_title(_("Next Title is Playing"))
					if artist:=song["artist"]:
						body=_("Now playing “{title}” by “{artist}”").format(title=song["title"][0], artist=str(artist))
					else:
						body=_("Now playing “{title}”").format(title=song["title"][0])
					notify.set_body(body)
					self.get_application().send_notification("title-change", notify)
				else:
					self.get_application().withdraw_notification("title-change")
		else:
			self._clear_title()
			self.get_application().withdraw_notification("title-change")

	def _on_connected(self, *args):
		self._clear_title()
		self._status_page_stack.set_visible_child_name("content")
		self._toolbar_view.set_reveal_bottom_bars(True)
		self._toolbar_view.set_top_bar_style(Adw.ToolbarStyle.RAISED_BORDER)
		self._left_button_box.set_visible(True)
		for action in ("stats","toggle-search"):
			self.lookup_action(action).set_enabled(True)
		self._search_button.set_sensitive(True)
		self._action_bar.set_sensitive(True)

	def _on_disconnected(self, *args):
		self._clear_title()
		for action in ("stats","toggle-search"):
			self.lookup_action(action).set_enabled(False)
		self._search_entry.emit("stop-search")
		self._search_button.set_sensitive(False)
		self._action_bar.set_sensitive(False)
		self._updating_toast.dismiss()

	def _on_connecting(self, *args):
		self._title.set_subtitle(_("connecting…"))

	def _on_connection_error(self, *args):
		self._clear_title()
		self._status_page_stack.set_visible_child_name("status-page")
		self._toolbar_view.set_reveal_bottom_bars(False)
		self._toolbar_view.set_top_bar_style(Adw.ToolbarStyle.FLAT)
		self._left_button_box.set_visible(False)

	def _on_updating_db(self, *args):
		self._toast_overlay.add_toast(self._updating_toast)

	def _on_updated_db(self, *args):
		self._updating_toast.dismiss()
		self._toast_overlay.add_toast(self._updated_toast)

	def _on_cursor_watch(self, obj, typestring):
		if obj.get_property("cursor-watch"):
			self.set_cursor_from_name("progress")
		else:
			self.set_cursor_from_name(None)

###################
# Gtk application #
###################

class Plattenalbum(Adw.Application):
	def __init__(self):
		super().__init__(application_id="de.wagnermartin.Plattenalbum", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
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
			("app.quit", ["<Control>q"]),("win.help", ["F1"]),("win.settings", ["<Control>comma"]),
			("win.show-help-overlay", ["<Control>question"]),("win.toggle-lyrics", ["<Control>l"]),
			("win.toggle-search", ["<Control>f"]),("win.toggle-artists", ["F9"]),("win.reconnect", ["<Shift>F5"]),
			("win.stats", ["<Control>i"]),("win.close", ["<Control>w"]),
			("mpd.update", ["F5"]),("mpd.clear", ["<Shift>Delete"]),("mpd.toggle-play", ["space"]),("mpd.stop", ["<Control>space"]),
			("mpd.next", ["KP_Add"]),("mpd.prev", ["KP_Subtract"]),("mpd.repeat", ["<Control>r"]),
			("mpd.random", ["<Control>n"]),("mpd.single", ["<Control>s"]),("mpd.consume", ["<Control>o"]),
			("mpd.single-oneshot", ["<Control>p"]),
			("mpd.seek-forward", ["KP_Multiply"]),("mpd.seek-backward", ["KP_Divide"]),
			("mpd.enqueue", ["<Control>e"]),("mpd.tidy", ["<Control>t"])
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
		builder.add_from_resource("/de/wagnermartin/Plattenalbum/AboutDialog.ui")
		dialog=builder.get_object("about_dialog")
		dialog.present(self._window)

	def _on_quit(self, *args):
		self.quit()

if __name__ == "__main__":
	app=Plattenalbum()
	signal.signal(signal.SIGINT, signal.SIG_DFL)  # allow using ctrl-c to terminate
	app.run(sys.argv)

