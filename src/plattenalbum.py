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
		self._playback_mapping={"play": "Playing", "pause": "Paused", "stop": "Stopped"}

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
				"CanGoNext": (self._get_can_next_prev_seek, None),
				"CanGoPrevious": (self._get_can_next_prev_seek, None),
				"CanPlay": (self._get_can_play_pause, None),
				"CanPause": (self._get_can_play_pause, None),
				"CanSeek": (self._get_can_next_prev_seek, None),
				"CanControl": (GLib.Variant("b", True), None)},
		}

		# connect
		self._handlers.append(self._client.emitter.connect("state", self._on_state_changed))
		self._handlers.append(self._client.emitter.connect("current-song", self._on_song_changed))
		self._handlers.append(self._client.emitter.connect("playlist", self._on_playlist_changed))
		self._handlers.append(self._client.emitter.connect("volume", self._on_volume_changed))
		self._handlers.append(self._client.emitter.connect("repeat", self._on_loop_changed))
		self._handlers.append(self._client.emitter.connect("single", self._on_loop_changed))
		self._handlers.append(self._client.emitter.connect("random", self._on_random_changed))
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
			return GLib.Variant("s", self._playback_mapping[self._client.status()["state"]])
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
				return GLib.Variant("s", "Track")
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
			return GLib.Variant("b", self._client.status()["random"] == "1")
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
			return GLib.Variant("x", float(self._client.status().get("elapsed", 0))*1000000)
		return GLib.Variant("x", 0)

	def _get_can_next_prev_seek(self):
		if self._client.connected():
			return GLib.Variant("b", self._client.status()["state"] != "stop")
		return GLib.Variant("b", False)

	def _get_can_play_pause(self):
		if self._client.connected():
			return GLib.Variant("b", int(self._client.status()["playlistlength"]) > 0)
		return GLib.Variant("b", False)

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

	def _set_property(self, interface_name, prop, value):
		self.PropertiesChanged(interface_name, {prop: value}, [])

	def _update_property(self, interface_name, prop):
		getter, setter=self._prop_mapping[interface_name][prop]
		if callable(getter):
			value=getter()
		else:
			value=getter
		self._set_property(interface_name, prop, value)

	def _on_state_changed(self, emitter, state):
		value=GLib.Variant("b", state != "stop")
		self._set_property(self._MPRIS_PLAYER_IFACE, "CanGoNext", value)
		self._set_property(self._MPRIS_PLAYER_IFACE, "CanGoPrevious", value)
		self._set_property(self._MPRIS_PLAYER_IFACE, "CanSeek", value)
		self._set_property(self._MPRIS_PLAYER_IFACE, "PlaybackStatus", GLib.Variant("s", self._playback_mapping[state]))

	def _on_song_changed(self, *args):
		self._update_metadata()
		self._update_property(self._MPRIS_PLAYER_IFACE, "Metadata")

	def _on_playlist_changed(self, emitter, version, length, song_pos):
		value=GLib.Variant("b", length > 0)
		self._set_property(self._MPRIS_PLAYER_IFACE, "CanPlay", value)
		self._set_property(self._MPRIS_PLAYER_IFACE, "CanPause", value)

	def _on_volume_changed(self, emitter, volume):
		if volume < 0:
			self._set_property(self._MPRIS_PLAYER_IFACE, "Volume", GLib.Variant("d", 0.0))
		else:
			self._set_property(self._MPRIS_PLAYER_IFACE, "Volume", GLib.Variant("d", volume/100))

	def _on_loop_changed(self, *args):
		self._update_property(self._MPRIS_PLAYER_IFACE, "LoopStatus")

	def _on_random_changed(self, emitter, state):
		self._set_property(self._MPRIS_PLAYER_IFACE, "Shuffle", GLib.Variant("b", state))

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
			for prop in ("PlaybackStatus", "Metadata", "Volume", "LoopStatus", "CanGoNext",
					"CanGoPrevious", "CanPlay", "CanPause", "CanSeek", "Shuffle"):
				self._update_property(self._MPRIS_PLAYER_IFACE, prop)
		else:
			self._disable()

	def _on_disconnected(self, *args):
		self._metadata={}
		self._set_property(self._MPRIS_PLAYER_IFACE, "PlaybackStatus", GLib.Variant("s", "Stopped"))
		self._set_property(self._MPRIS_PLAYER_IFACE, "Metadata", GLib.Variant("a{sv}", self._metadata))
		self._set_property(self._MPRIS_PLAYER_IFACE, "Volume", GLib.Variant("d", 0))
		self._set_property(self._MPRIS_PLAYER_IFACE, "LoopStatus", GLib.Variant("s", "None"))
		for prop in ("CanGoNext","CanGoPrevious","CanPlay","CanPause","CanSeek","Shuffle"):
			self._set_property(self._MPRIS_PLAYER_IFACE, prop, GLib.Variant("b", False))

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
		elif key in ("range", "file", "pos", "id", "format", "last-modified"):
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

	def get_markup(self):
		if "artist" in self:
			title=f"<b>{GLib.markup_escape_text(self['title'][0])}</b> • {GLib.markup_escape_text(str(self['artist']))}"
		else:
			title=f"<b>{GLib.markup_escape_text(self['title'][0])}</b>"
		return (title, " • ".join(filter(None, (str(self["album"]), str(self["date"])))))

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
		"bitrate": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
		"a-b-loop": (GObject.SignalFlags.RUN_FIRST, None, (float,float)),
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
		self._first_mark=None
		self._second_mark=None
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

	def try_connect(self, remote):
		self.emitter.emit("connecting")
		def callback():
			# connect
			if remote:
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
					self.disconnect()
					self.emitter.emit("connection_error")
					self._start_idle_id=None
					return False
			# connected
			commands=self.commands()
			if remote:
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
			# connect successful
			self._settings.set_boolean("remote-connection", remote)
			self._start_idle_id=None
			return False
		self._start_idle_id=GLib.idle_add(callback)

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

	def a_b_loop(self):
		value=float(self.status()["elapsed"])
		if self._first_mark is None:
			self._first_mark=value
			self.emitter.emit("a-b-loop", value, -1.0)
		elif self._second_mark is None:
			if value < self._first_mark:
				self._second_mark=self._first_mark
				self._first_mark=value
			else:
				self._second_mark=value
			self.emitter.emit("a-b-loop", self._first_mark, self._second_mark)
		else:
			self._clear_marks()

	def _clear_marks(self):
		if self._first_mark is not None:
			self.emitter.emit("a-b-loop", -1.0, -1.0)
		self._first_mark=None
		self._second_mark=None

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
				self._clear_marks()
			if "elapsed" in diff:
				elapsed=float(diff["elapsed"])
				self.emitter.emit("elapsed", elapsed, float(status.get("duration", 0.0)))
				if self._second_mark is not None:
					if elapsed > self._second_mark:
						self.seekcur(self._first_mark)
			if "bitrate" in diff:
				if diff["bitrate"] == "0":
					self.emitter.emit("bitrate", None)
				else:
					self.emitter.emit("bitrate", diff["bitrate"])
			if "volume" in diff:
				self.emitter.emit("volume", float(diff["volume"]))
			if "state" in diff:
				self.emitter.emit("state", diff["state"])
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
					self._clear_marks()
				elif "volume" == key:
					self.emitter.emit("volume", -1)
				elif "updating_db" == key:
					self.emitter.emit("updated-db", self._database_is_empty())
				elif "bitrate" == key:
					self.emitter.emit("bitrate", None)
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

###########
# dialogs #
###########

class ViewSettings(Adw.PreferencesGroup):
	def __init__(self, settings):
		super().__init__(title=_("View"))
		toggle_data=(
			(_("_Show Bit Rate"), "show-bit-rate", ""),
		)
		for title, key, subtitle in toggle_data:
			row=Adw.SwitchRow(title=title, subtitle=subtitle, use_underline=True)
			settings.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
			self.add(row)

class BehaviorSettings(Adw.PreferencesGroup):
	def __init__(self, settings):
		super().__init__(title=_("Behavior"))
		toggle_data=(
			(_("Send _Notification on Title Change"), "send-notify", ""),
			(_("Re_wind via Previous Button"), "rewind-mode", ""),
			(_("Stop _Playback on Quit"), "stop-on-quit", ""),
			(_("Support “_MPRIS”"), "mpris", _("Disable if “MPRIS” is supported by another client")),
		)
		for title, key, subtitle in toggle_data:
			row=Adw.SwitchRow(title=title, subtitle=subtitle, use_underline=True)
			settings.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
			self.add(row)

class SettingsDialog(Adw.PreferencesDialog):
	def __init__(self, client, settings):
		super().__init__()
		page=Adw.PreferencesPage()
		page.add(ViewSettings(settings))
		page.add(BehaviorSettings(settings))
		self.add(page)

class ConnectDialog(Adw.Dialog):
	def __init__(self, title, target):
		super().__init__(title=title, width_request=360, follows_content_size=True)
		self._clamp=Adw.Clamp()
		button=Gtk.Button(label=_("_Connect"), use_underline=True, halign=Gtk.Align.CENTER, action_name="mpd.connect", action_target=target)
		button.set_css_classes(["pill", "suggested-action"])
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24, margin_top=12, margin_bottom=18, margin_start=18, margin_end=18)
		box.append(self._clamp)
		box.append(button)
		scroll=Gtk.ScrolledWindow(child=box, propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
		toolbar_view=Adw.ToolbarView(content=scroll)
		toolbar_view.add_top_bar(Adw.HeaderBar())
		self._connection_toast=Adw.Toast(title=_("Connection failed"))
		self._toast_overlay=Adw.ToastOverlay(child=toolbar_view)
		self.set_child(self._toast_overlay)
		self.set_default_widget(button)
		self.set_focus(button)

	def set_content(self, widget):
		self._clamp.set_child(widget)

	def connection_error(self):
		self._toast_overlay.add_toast(self._connection_toast)

class LocalConnectDialog(ConnectDialog):
	def __init__(self, settings):
		super().__init__(_("Local Connection"), GLib.Variant("b", False))
		list_box=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
		list_box.add_css_class("boxed-list")
		password_row=Adw.PasswordEntryRow(title=_("Password (optional)"))
		settings.bind("password", password_row, "text", Gio.SettingsBindFlags.DEFAULT)
		list_box.append(password_row)
		self.set_content(list_box)

class RemoteConnectDialog(ConnectDialog):
	def __init__(self, settings):
		super().__init__(_("Remote Connection"), GLib.Variant("b", True))
		list_box=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
		list_box.add_css_class("boxed-list")
		hostname_row=Adw.EntryRow(title=_("Host Name"))
		settings.bind("host", hostname_row, "text", Gio.SettingsBindFlags.DEFAULT)
		list_box.append(hostname_row)
		port_row=Adw.SpinRow.new_with_range(0, 65535, 1)
		port_row.set_title(_("Port"))
		settings.bind("port", port_row, "value", Gio.SettingsBindFlags.DEFAULT)
		list_box.append(port_row)
		password_row=Adw.PasswordEntryRow(title=_("Password (optional)"))
		settings.bind("password", password_row, "text", Gio.SettingsBindFlags.DEFAULT)
		list_box.append(password_row)
		self.set_content(list_box)

class CommandLabel(Gtk.Box):
	def __init__(self, text):
		super().__init__(css_classes=["card"])
		label=Gtk.Label(selectable=True, xalign=0, hexpand=True, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, css_classes=["monospace"])
		label.set_margin_start(12)
		label.set_margin_end(12)
		label.set_margin_top(9)
		label.set_margin_bottom(9)
		label.set_text(text)
		self.append(label)

class SetupDialog(ConnectDialog):
	def __init__(self):
		super().__init__(_("Setup"), GLib.Variant("b", False))
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
		box.append(Gtk.Label(label=_("To get started, install the Music Player Daemon (<tt>mpd</tt>) with your system package manager, and run the following commands"\
			" to configure and initialize a basic local instance. After that, Plattenalbum should be able to seamlessly connect to it."), use_markup=True, xalign=0, wrap=True))
		box.append(CommandLabel("mkdir -p ~/.mpd"))
		box.append(CommandLabel('cat << EOF > ~/.mpd/mpd.conf\ndb_file\t\t"~/.mpd/database"\nstate_file\t"~/.mpd/state"\n\n'\
			'audio_output {\n\ttype\t"pulse"\n\tname\t"Music"\n}\nEOF'))
		box.append(CommandLabel("systemctl --user enable --now mpd.socket"))
		self.set_content(box)

class ServerStats(Adw.Dialog):
	def __init__(self, client, settings):
		super().__init__(title=_("Server Statistics"), width_request=360, follows_content_size=True)

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
		clamp=Adw.Clamp(child=list_box, margin_top=12, margin_bottom=18, margin_start=12, margin_end=12)
		scroll=Gtk.ScrolledWindow(child=clamp, propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
		toolbar_view=Adw.ToolbarView(content=scroll)
		toolbar_view.add_top_bar(Adw.HeaderBar())
		self.set_child(toolbar_view)

###########################
# general purpose widgets #
###########################

class SongRow(Gtk.Box):
	def __init__(self, show_track=True, **kwargs):
		super().__init__( **kwargs)

		# labels
		self._track=Gtk.Label(xalign=1, single_line_mode=True, width_chars=3, visible=show_track, css_classes=["numeric"])
		self._title=Gtk.Label(xalign=0, single_line_mode=True, ellipsize=Pango.EllipsizeMode.END)
		self._subtitle=Gtk.Label(xalign=0, single_line_mode=True, ellipsize=Pango.EllipsizeMode.END, css_classes=["dim-label", "caption"])
		self._length=Gtk.Label(xalign=1, single_line_mode=True, css_classes=["numeric"])

		# packing
		self.append(self._track)
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
		box.append(self._title)
		box.append(self._subtitle)
		self.append(box)
		self.append(self._length)

	def set_song(self, song):
		self._track.set_text(song["track"][0])
		title,subtitle=song.get_markup()
		self._title.set_markup(title)
		self._subtitle.set_visible(bool(subtitle))
		self._subtitle.set_text(subtitle)
		self._length.set_text(str(song["duration"]))

	def unset_song(self):
		self._track.set_text("")
		self._title.set_text("")
		self._subtitle.set_text("")
		self._length.set_text("")

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

class SelectionModel(ListModel, Gtk.SelectionModel):
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
	def do_get_selection_in_range(self, position, n_items): return False

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

class SongListRow(SongRow):
	position=GObject.Property(type=int, default=-1)
	def __init__(self):
		super().__init__(can_target=False)  # can_target=False is needed to use Gtk.Widget.pick() in Gtk.ListView

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
		if item is self or item is None:
			return None
		return item.get_first_child().get_property("position")

	def get_song(self, position):
		return self.get_model().get_item(position)

class BrowserSongRow(SongRow):
	def __init__(self, song, **kwargs):
		super().__init__(**kwargs)
		self.song=song
		self.set_song(song)

class BrowserSongList(Gtk.ListBox):
	def __init__(self, client):
		super().__init__(selection_mode=Gtk.SelectionMode.NONE, valign=Gtk.Align.START)
		self._client=client
		self._activate_on_release=False

		# menu
		self._menu=SongMenu(client)

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
		self.connect("row-activated", self._on_row_activated)
		button_controller.connect("pressed", self._on_button_pressed)
		long_press_controller.connect("pressed", self._on_long_pressed)
		drag_source.connect("prepare", self._on_drag_prepare)

	def _open_menu(self, row, x, y):
		self._menu.unparent()
		self._menu.set_parent(row)
		point=Graphene.Point.zero()
		point.x,point.y=x,y
		computed_point,point=self.compute_point(row, point)
		if computed_point:
			self._menu.open(row.get_child().song["file"], point.x, point.y)

	def _on_row_activated(self, list_box, row):
		self._client.file_to_playlist(row.get_child().song["file"], "play")

	def _on_button_pressed(self, controller, n_press, x, y):
		if (row:=self.get_row_at_y(y)) is not None:
			if controller.get_current_button() == 2 and n_press == 1:
				self._client.file_to_playlist(row.get_child().song["file"], "append")
			elif controller.get_current_button() == 3 and n_press == 1:
				self._open_menu(row, x, y)

	def _on_long_pressed(self, controller, x, y):
		if (row:=self.get_row_at_y(y)) is not None:
			self._open_menu(row, x, y)

	def _on_menu(self, action, state):
		row=self.get_focus_child()
		self._menu.unparent()
		self._menu.set_parent(row)
		self._menu.open(row.get_child().song["file"], 0, 0)

	def _on_drag_prepare(self, drag_source, x, y):
		if (row:=self.get_row_at_y(y)) is not None:
			return Gdk.ContentProvider.new_for_value(row.get_child().song)

###########
# browser #
###########

class SearchView(Gtk.Stack):
	__gsignals__={"artist-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
			"song-selected": (GObject.SignalFlags.RUN_FIRST, None, (Song,))}
	def __init__(self, client):
		super().__init__()
		self._client=client

		# artist list
		self._artist_list=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, valign=Gtk.Align.START)
		self._artist_list.add_css_class("rich-list")
		self._artist_list.add_css_class("boxed-list")

		# song list
		self._song_list=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, valign=Gtk.Align.START)
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
		self.add_named(status_page, "no-results")
		self.add_named(Gtk.ScrolledWindow(child=Adw.Clamp(child=box)), "results")

	def clear(self):
		self._artist_list.remove_all()
		self._song_list.remove_all()
		self.set_visible_child_name("no-results")

	def search(self, search_text, artists):
		self.clear()
		if (keywords:=search_text.split()):
			self._client.restrict_tagtypes("title", "artist", "albumartist", "album", "date")
			expressions=" AND ".join((f"(any contains '{keyword}')" for keyword in keywords))
			songs=self._client.search(f"({expressions})", "window", "0:20")  # TODO adjust number of results
			self._client.tagtypes("all")
			for song in songs:
				row=BrowserSongRow(song, show_track=False)
				self._song_list.append(row)
			if songs:
				self.set_visible_child_name("results")
				artists=filter(lambda x: all(keyword.casefold() in x.name.casefold() for keyword in keywords), artists)
				for artist in itertools.islice(artists, 20):  # TODO adjust number of results
					label=Gtk.Label(xalign=0, single_line_mode=True, ellipsize=Pango.EllipsizeMode.END, label=artist.name)
					self._artist_list.append(label)
				self._artist_box.set_visible(self._artist_list.get_first_child() is not None)

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
		super().__init__(orientation=Gtk.Orientation.VERTICAL)
		self._client=client
		self._cover=Gtk.Picture(margin_bottom=3)
		square_container=SquareContainer(self._cover)
		square_container.set_valign(Gtk.Align.START)
		self._title=Gtk.Label(single_line_mode=True, ellipsize=Pango.EllipsizeMode.END, css_classes=["heading"])
		self._date=Gtk.Label(single_line_mode=True, css_classes=["dim-label", "caption"])
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

class AlbumsPage(Adw.NavigationPage):
	__gsignals__={"album-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,str,str,))}
	def __init__(self, client, settings):
		super().__init__(title=_("Albums"), tag="album_list")
		self._settings=settings
		self._client=client

		# grid view
		self.grid_view=Gtk.GridView(tab_behavior=Gtk.ListTabBehavior.ITEM, single_click_activate=True, vexpand=True, max_columns=2)
		self.grid_view.add_css_class("navigation-sidebar")
		self._selection_model=SelectionModel(Album)
		self.grid_view.set_model(self._selection_model)

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
		self.grid_view.set_factory(factory)

		# breakpoint bin
		breakpoint_bin=Adw.BreakpointBin(width_request=320, height_request=336)  # TODO height_request
		for width, columns in ((500,3), (850,4), (1200,5), (1500,6)):
			break_point=Adw.Breakpoint()
			break_point.set_condition(Adw.BreakpointCondition.parse(f"min-width: {width}sp"))
			break_point.add_setter(self.grid_view, "max-columns", columns)
			breakpoint_bin.add_breakpoint(break_point)
		breakpoint_bin.set_child(Gtk.ScrolledWindow(child=self.grid_view, hscrollbar_policy=Gtk.PolicyType.NEVER))

		# connect
		self.grid_view.connect("activate", self._on_activate)

		# packing
		toolbar_view=Adw.ToolbarView(content=breakpoint_bin)
		toolbar_view.add_top_bar(Adw.HeaderBar())
		self.set_child(toolbar_view)

	def clear(self, *args):
		self._selection_model.clear()
		self.set_title(_("Albums"))

	def _get_albums(self, artist):
		albums=self._client.list("albumsort", "albumartist", artist, "group", "date", "group", "album")
		for _, album in itertools.groupby(albums, key=lambda x: (x["album"], x["date"])):
			tmp=next(album)
			# ignore multiple albumsort values
			if next(album, None) is None:
				yield Album(artist, tmp["album"], tmp["albumsort"], tmp["date"])
			else:
				yield Album(artist, tmp["album"], tmp["album"], tmp["date"])

	def display(self, artist):
		self._settings.set_property("cursor-watch", True)
		self._selection_model.clear()
		self.set_title(artist)
		# ensure list is empty
		main=GLib.main_context_default()
		while main.pending():
			main.iteration()
		self.update_property([Gtk.AccessibleProperty.LABEL], [_("Albums of {artist}").format(artist=artist)])
		self._selection_model.append(sorted(self._get_albums(artist), key=lambda item: item.date))
		self._settings.set_property("cursor-watch", False)

	def _on_activate(self, widget, pos):
		album=self._selection_model.get_item(pos)
		self.emit("album-selected", album.artist, album.name, album.date)

class AlbumPage(Adw.NavigationPage):
	def __init__(self, client, albumartist, album, date, file=None):
		super().__init__()
		tag_filter=("albumartist", albumartist, "album", album, "date", date)

		# songs list
		song_list=BrowserSongList(client)
		song_list.add_css_class("rich-list")
		song_list.add_css_class("boxed-list")

		# header bar
		header_bar=Adw.HeaderBar()
		window_title=Adw.WindowTitle()
		header_bar.set_title_widget(window_title)

		# buttons
		data=((_("Play"), "media-playback-start-symbolic", "play"),
			(_("Append"), "list-add-symbolic", "append")
		)
		for tooltip, icon_name, mode in data:
			button=Gtk.Button(icon_name=icon_name, tooltip_text=tooltip)
			button.connect("clicked", lambda widget, mode: client.filter_to_playlist(tag_filter, mode), mode)
			header_bar.pack_end(button)

		# cover
		album_cover=Gtk.Image(width_request=200, height_request=200)

		# packing
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=30, margin_start=12, margin_end=12, margin_top=24, margin_bottom=24)
		box.append(album_cover)
		box.append(Adw.Clamp(child=song_list))
		self._scroll=Gtk.ScrolledWindow(child=box)#, vexpand=True)
		self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
		toolbar_view=Adw.ToolbarView(content=self._scroll)
		toolbar_view.add_top_bar(header_bar)
		self.set_child(toolbar_view)

		# populate
		if album:
			self.set_title(album)
			window_title.set_title(album)
			album_cover.update_property([Gtk.AccessibleProperty.LABEL], [_("Album cover of {album}").format(album=album)])
		else:
			self.set_title(_("Unknown Album"))
			window_title.set_title(_("Unknown Album"))
			album_cover.update_property([Gtk.AccessibleProperty.LABEL], [_("Album cover of an unknown album")])
		window_title.set_subtitle(" • ".join(filter(None, (date, str(Duration(client.count(*tag_filter)["playtime"]))))))
		client.restrict_tagtypes("track", "title", "artist")
		songs=client.find(*tag_filter)
		client.tagtypes("all")
		if (cover:=client.get_cover(songs[0]["file"])) is None:
			album_cover.set_from_paintable(lookup_icon(FALLBACK_COVER, 1024))
		else:
			album_cover.set_from_paintable(cover.get_paintable())
		for song in songs:
			row=BrowserSongRow(song)
			song_list.append(row)

		# scroll to file
		if file is not None:
			for i, song in enumerate(songs):
				if song["file"] == file:
					row=song_list.get_row_at_index(i)
					GLib.idle_add(self._scroll_to, row)
					break

	def _scroll_to(self, row):
		row.grab_focus()
		computed_point,point=row.compute_point(self._scroll.get_child(), Graphene.Point.zero())
		if computed_point:
			adj=self._scroll.get_vadjustment()
			value=point.y-self._scroll.get_height()*0.4
			if value >= adj.get_value():
				adj.set_value(value)
		return False

class MainMenuButton(Gtk.MenuButton):
	def __init__(self):
		super().__init__(icon_name="open-menu-symbolic", tooltip_text=_("Main Menu"), primary=True)
		app_section=Gio.Menu()
		app_section.append(_("_Preferences"), "win.settings")
		app_section.append(_("_Keyboard Shortcuts"), "win.show-help-overlay")
		app_section.append(_("_Help"), "win.help")
		app_section.append(_("_About Plattenalbum"), "app.about")
		menu=Gio.Menu()
		menu.append(_("_Disconnect"), "mpd.disconnect")
		menu.append(_("_Update Database"), "mpd.update")
		menu.append(_("_Server Statistics"), "win.stats")
		menu.append_section(None, app_section)
		self.set_menu_model(menu)

class Browser(Gtk.Stack):
	show_search=GObject.Property(type=bool, default=False)
	def __init__(self, client, settings):
		super().__init__()
		self._client=client

		# search
		self._search_view=SearchView(client)
		self.search_entry=Gtk.SearchEntry(placeholder_text=_("Search collection"), max_width_chars=25)
		self.search_entry.update_property([Gtk.AccessibleProperty.LABEL], [_("Search collection")])
		search_toolbar_view=Adw.ToolbarView(content=self._search_view)
		search_header_bar=Adw.HeaderBar(title_widget=self.search_entry)
		search_button=Gtk.ToggleButton(icon_name="system-search-symbolic", tooltip_text=_("Search"))
		search_button.bind_property("active", self, "show-search", GObject.BindingFlags.BIDIRECTIONAL)
		search_header_bar.pack_start(search_button)
		search_toolbar_view.add_top_bar(search_header_bar)
		search_toolbar_view.add_css_class("content-pane")

		# artist list
		self._artist_list=ArtistList(client)
		artist_window=Gtk.ScrolledWindow(child=self._artist_list)
		artist_header_bar=Adw.HeaderBar()
		search_button=Gtk.ToggleButton(icon_name="system-search-symbolic", tooltip_text=_("Search"))
		search_button.bind_property("active", self, "show-search", GObject.BindingFlags.BIDIRECTIONAL)
		artist_header_bar.pack_start(search_button)
		artist_header_bar.pack_end(MainMenuButton())
		artist_toolbar_view=Adw.ToolbarView(content=artist_window)
		artist_toolbar_view.add_top_bar(artist_header_bar)
		artist_page=Adw.NavigationPage(child=artist_toolbar_view, title=_("Artists"), tag="artists")

		# album list
		self._albums_page=AlbumsPage(client, settings)

		# navigation view
		self._album_navigation_view=Adw.NavigationView()
		self._album_navigation_view.add(self._albums_page)
		album_navigation_view_page=Adw.NavigationPage(child=self._album_navigation_view, title=_("Albums"), tag="albums")

		# split view
		self._navigation_split_view=Adw.NavigationSplitView(sidebar=artist_page, content=album_navigation_view_page)

		# breakpoint bin
		breakpoint_bin=Adw.BreakpointBin(width_request=320, height_request=336)  # TODO height_request
		break_point=Adw.Breakpoint()
		break_point.set_condition(Adw.BreakpointCondition.parse(f"max-width: 550sp"))
		break_point.add_setter(self._navigation_split_view, "collapsed", True)
		break_point.connect("apply", lambda *args: self._navigation_split_view.add_css_class("content-pane"))
		break_point.connect("unapply", lambda *args: self._navigation_split_view.remove_css_class("content-pane"))
		breakpoint_bin.add_breakpoint(break_point)
		breakpoint_bin.set_child(self._navigation_split_view)

		# status page
		status_page=Adw.StatusPage(title=_("Collection is Empty"), icon_name="folder-music-symbolic")
		status_page_header_bar=Adw.HeaderBar(show_title=False)
		status_page_header_bar.pack_end(MainMenuButton())
		status_page_toolbar_view=Adw.ToolbarView(content=status_page)
		status_page_toolbar_view.add_top_bar(status_page_header_bar)

		# navigation view
		self._stack=Gtk.Stack()
		self._stack.add_named(breakpoint_bin, "collection")
		self._stack.add_named(search_toolbar_view, "search")

		# connect
		self.connect("notify::show-search", self._on_search_toggled)
		self._albums_page.connect("album-selected", self._on_album_selected)
		self._artist_list.artist_selection_model.connect("selected", self._on_artist_selected)
		self._artist_list.artist_selection_model.connect("reselected", self._on_artist_reselected)
		self._artist_list.artist_selection_model.connect("clear", self._albums_page.clear)
		self._search_view.connect("artist-selected", self._on_search_artist_selected)
		self._search_view.connect("song-selected", self._on_search_song_selected)
		self.search_entry.connect("search-started", self._on_search_started)
		self.search_entry.connect("search-changed", self._on_search_changed)
		self.search_entry.connect("stop-search", self._on_search_stopped)
		client.emitter.connect("disconnected", self._on_disconnected)
		client.emitter.connect("connection-error", self._on_connection_error)
		client.emitter.connect("connected", self._on_connected_or_updated_db)
		client.emitter.connect("updated-db", self._on_connected_or_updated_db)

		# packing
		self.add_named(self._stack, "browser")
		self.add_named(status_page_toolbar_view, "empty-collection")

	def _on_search_toggled(self, *args):
		if self.get_property("show-search"):
			self._stack.set_visible_child_name("search")
			self.search_entry.grab_focus()
		else:
			self._stack.set_visible_child_name("collection")
			self.search_entry.set_text("")

	def _on_search_started(self, entry):
		self.set_property("show-search", True)

	def _on_search_changed(self, entry):
		if (search_text:=self.search_entry.get_text()):
			self.search_entry.grab_focus()
			self._search_view.search(search_text, self._artist_list.artist_selection_model)
		else:
			self._search_view.clear()

	def _on_search_stopped(self, widget):
		self.set_property("show-search", False)

	def _on_artist_selected(self, model, position):
		if self._navigation_split_view.get_collapsed():
			self._navigation_split_view.set_show_content(True)
		self._album_navigation_view.replace_with_tags(["album_list"])
		self._albums_page.display(model.get_artist(position))

	def _on_artist_reselected(self, model):
		if self._navigation_split_view.get_collapsed():
			self._navigation_split_view.set_show_content(True)
		self._album_navigation_view.pop_to_tag("album_list")

	def _on_album_selected(self, widget, *tags):
		self._album_navigation_view.push(AlbumPage(self._client, *tags))

	def _on_search_artist_selected(self, widget, artist):
		self._artist_list.select(artist)
		self.set_property("show-search", False)
		self._albums_page.grid_view.grab_focus()

	def _on_search_song_selected(self, widget, song):
		self._artist_list.select(song["albumartist"][0])
		album_page=AlbumPage(self._client, song["albumartist"][0], song["album"][0], song["date"][0], song["file"])
		self._album_navigation_view.replace([self._albums_page, album_page])
		self.set_property("show-search", False)
		# TODO https://lazka.github.io/pgi-docs/Gtk-4.0/classes/Window.html#Gtk.Window.set_focus_visible
		self.get_root().set_focus_visible(True)

	def _on_disconnected(self, *args):
		self._album_navigation_view.pop_to_tag("album_list")
		self.set_visible_child_name("browser")
		self.set_property("show-search", False)

	def _on_connection_error(self, *args):
		self.set_visible_child_name("empty-collection")

	def _on_connected_or_updated_db(self, emitter, database_is_empty):
		self.set_property("show-search", False)
		if database_is_empty:
			self.set_visible_child_name("empty-collection")
		else:
			self.set_visible_child_name("browser")

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
		self.add_css_class("background")

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

	def _on_drop(self, drop_target, value, x, y):
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
		self.scroll=Gtk.ScrolledWindow(child=self._playlist_view, hexpand=True, vexpand=True)
		self._adj=self.scroll.get_vadjustment()
		status_page=Adw.StatusPage(icon_name="view-list-symbolic", title=_("Playlist is Empty"))
		status_page.add_css_class("compact")

		# scroll button
		overlay=Gtk.Overlay(child=self.scroll)
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
			elif self._adj.get_value() < value-self.scroll.get_height():
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
	def __init__(self):
		super().__init__()

		# status pages
		no_lyrics_status_page=Adw.StatusPage(icon_name="lyrics-symbolic", title=_("No Lyrics Found"))
		no_lyrics_status_page.add_css_class("compact")
		connection_error_status_page=Adw.StatusPage(
			icon_name="network-wired-disconnected-symbolic", title=_("Connection Error"), description=_("Check your network connection"))
		connection_error_status_page.add_css_class("compact")
		searching_status_page=Adw.StatusPage(title=_("Searching…"))
		spinner=Adw.SpinnerPaintable(widget=searching_status_page)
		searching_status_page.set_paintable(spinner)

		# text view
		self._text_view=Gtk.TextView(
			editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD,
			justification=Gtk.Justification.CENTER,
			left_margin=12, right_margin=12, bottom_margin=9, top_margin=9
		)
		self._text_view.add_css_class("inline")

		# text buffer
		self._text_buffer=self._text_view.get_buffer()

		# packing
		scroll=Gtk.ScrolledWindow(child=self._text_view)
		self.add_named(scroll, "lyrics")
		self.add_named(no_lyrics_status_page, "no-lyrics")
		self.add_named(connection_error_status_page, "connection-error")
		self.add_named(searching_status_page, "searching")

	def clear(self):
		self.set_visible_child_name("no-lyrics")
		self._text_buffer.set_text("")
		self._text_view.update_property([Gtk.AccessibleProperty.LABEL], [_("Lyrics view")])

	def display(self, song):
		self.set_visible_child_name("searching")
		update_thread=threading.Thread(target=self._display_lyrics, kwargs={"song": song}, daemon=True)
		update_thread.start()

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
			idle_add(self._text_view.update_property, [Gtk.AccessibleProperty.LABEL], [_("Lyrics of {song}").format(song=song["title"])])
			idle_add(self.set_visible_child_name, "lyrics")
		except urllib.error.URLError:
			idle_add(self.set_visible_child_name, "connection-error")
		except ValueError:
			idle_add(self.set_visible_child_name, "no-lyrics")

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

##########
# player #
##########

class PlayButton(Gtk.Button):
	def __init__(self, client):
		super().__init__(icon_name="media-playback-start-symbolic", action_name="mpd.toggle-play", tooltip_text=_("Play"))
		client.emitter.connect("state", self._on_state)

	def _on_state(self, emitter, state):
		if state == "play":
			self.set_property("icon-name", "media-playback-pause-symbolic")
			self.set_tooltip_text(_("Pause"))
		else:
			self.set_property("icon-name", "media-playback-start-symbolic")
			self.set_tooltip_text(_("Play"))

class BitRate(Gtk.Label):
	def __init__(self, client, settings):
		super().__init__(xalign=1, single_line_mode=True, css_classes=["caption", "numeric", "dim-label"])
		self._client=client
		settings.bind("show-bit-rate", self, "visible", Gio.SettingsBindFlags.GET)
		self._mask=_("{bitrate} kb/s")

		# connect
		self._client.emitter.connect("bitrate", self._on_bitrate)
		self._client.emitter.connect("disconnected", self._on_disconnected)

	def _on_bitrate(self, emitter, bitrate):
		# handle unknown bitrates: https://github.com/MusicPlayerDaemon/MPD/issues/428#issuecomment-442430365
		if bitrate is None:
			self.set_text("")
		else:
			self.set_text(self._mask.format(bitrate=bitrate))

	def _on_disconnected(self, *args):
		self.set_text("")

class PlaybackControls(Gtk.Box):
	def __init__(self, client, settings):
		super().__init__(hexpand=True, orientation=Gtk.Orientation.VERTICAL)
		self.add_css_class("toolbar")
		self._client=client

		# buttons
		buttons=Gtk.Box(spacing=6)
		play_button=PlayButton(client)
		prev_button=Gtk.Button(icon_name="media-skip-backward-symbolic", tooltip_text=_("Previous"), action_name="mpd.prev")
		next_button=Gtk.Button(icon_name="media-skip-forward-symbolic", tooltip_text=_("Next"), action_name="mpd.next")
		buttons.append(prev_button)
		buttons.append(play_button)
		buttons.append(next_button)

		# labels
		self._elapsed=Gtk.Label(xalign=0, single_line_mode=True, valign=Gtk.Align.START, css_classes=["numeric"])
		self._rest=Gtk.Label(xalign=1, single_line_mode=True, valign=Gtk.Align.START, css_classes=["numeric"])

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

		# connect
		self._scale.connect("change-value", self._on_change_value)
		controller_motion.connect("motion", self._on_pointer_motion)
		controller_motion.connect("leave", self._on_pointer_leave)
		self._client.emitter.connect("disconnected", self._disable)
		self._client.emitter.connect("state", self._on_state)
		self._client.emitter.connect("elapsed", self._refresh)
		self._client.emitter.connect("current-song", self._on_song_changed)

		# packing
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		box.append(self._rest)
		box.append(BitRate(client, settings))
		center_box=Gtk.CenterBox(margin_start=6, margin_end=6)
		center_box.set_center_widget(buttons)
		center_box.set_start_widget(self._elapsed)
		center_box.set_end_widget(box)
		self.append(self._scale)
		self.append(center_box)

	def _refresh(self, emitter, elapsed, duration):
		self._scale.set_visible(True)
		if duration > 0:
			if elapsed > duration:  # fix display error
				elapsed=duration
			self._adjustment.set_upper(duration)
			self._scale.set_value(elapsed)
			self._elapsed.set_text(str(Duration(elapsed)))
			self._rest.set_text(str(Duration(duration-elapsed)))
		else:
			self._disable()
			self._elapsed.set_text(str(Duration(elapsed)))

	def _disable(self, *args):
		self._popover.popdown()
		self._scale.set_visible(False)
		self._scale.set_range(0, 0)
		self._elapsed.set_text("")
		self._rest.set_text("")

	def _on_change_value(self, range, scroll, value):  # value is inaccurate (can be above upper limit)
		if (scroll == Gtk.ScrollType.STEP_BACKWARD or scroll == Gtk.ScrollType.STEP_FORWARD or
			scroll == Gtk.ScrollType.PAGE_BACKWARD or scroll == Gtk.ScrollType.PAGE_FORWARD or
			scroll == Gtk.ScrollType.JUMP):
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
			if abs(current_pos-pos) > 1:
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

	def _on_state(self, emitter, state):
		if state == "stop":
			self._disable()

	def _on_song_changed(self, *args):
		self._popover.popdown()

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

class PlayerMenuButton(Gtk.MenuButton):
	def __init__(self, client):
		super().__init__(icon_name="view-more-symbolic", tooltip_text=_("Player Menu"))
		self._volume_visible=False

		# volume
		self._volume_control=VolumeControl(client)
		self._volume_item=Gio.MenuItem()
		self._volume_item.set_attribute_value("custom", GLib.Variant("s", "volume"))

		# menu model
		playback_section=Gio.Menu()
		playback_section.append(_("_Repeat Mode"), "mpd.repeat")
		playback_section.append(_("R_andom Mode"), "mpd.random")
		playback_section.append(_("_Single Mode"), "mpd.single")
		playback_section.append(_("_Pause After Song"), "mpd.single-oneshot")
		playback_section.append(_("_Consume Mode"), "mpd.consume")
		self._volume_section=Gio.Menu()
		menu=Gio.Menu()
		menu.append(_("_Lyrics"), "win.toggle-lyrics")
		menu.append_section(None, playback_section)
		menu.append_section(None, self._volume_section)

		# popover menu
		self._popover_menu=Gtk.PopoverMenu.new_from_model(menu)
		self.set_popover(self._popover_menu)

		# connect
		client.emitter.connect("volume", self._on_volume_changed)
		client.emitter.connect("disconnected", self._on_disconnected)

	def _on_volume_changed(self, emitter, volume):
		if volume < 0 and self._volume_visible:
			self._volume_section.remove(0)
			self._volume_visible=False
		elif volume >= 0 and not self._volume_visible:
			self._volume_section.append_item(self._volume_item)
			self._popover_menu.add_child(self._volume_control, "volume")
			self._volume_visible=True

	def _on_disconnected(self, *args):
		if self._volume_visible:
			self._volume_section.remove(0)
			self._volume_visible=False

class Player(Adw.Bin):
	show_lyrics=GObject.Property(type=bool, default=False)
	sheet_mode=GObject.Property(type=bool, default=False)
	def __init__(self, client, settings):
		super().__init__()
		self._client=client

		# widgets
		window_handle=Gtk.WindowHandle(child=MainCover(client))
		self._lyrics_window=LyricsWindow()
		playlist_window=PlaylistWindow(client)
		self.bind_property("sheet-mode", playlist_window.scroll, "propagate-natural-height", GObject.BindingFlags.DEFAULT)
		playback_controls=PlaybackControls(client, settings)

		# stack
		self._stack=Gtk.Stack()
		self._stack.add_named(window_handle, "cover")
		self._stack.add_named(self._lyrics_window, "lyrics")

		# header bar
		self._title=Adw.WindowTitle()
		header_bar=Adw.HeaderBar(title_widget=self._title)
		header_bar.pack_start(PlayerMenuButton(client))

		# connect
		self.connect("notify::show-lyrics", self._on_lyrics_toggled)
		self._client.emitter.connect("current-song", self._on_song_changed)
		self._client.emitter.connect("playlist", self._on_playlist_changed)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connected", self._on_connected)

		# packing
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		box.append(self._stack)
		box.append(playlist_window)
		self._toolbar_view=Adw.ToolbarView()
		self._toolbar_view.add_top_bar(header_bar)
		self._toolbar_view.set_content(box)
		self._toolbar_view.add_bottom_bar(playback_controls)
		self.set_child(self._toolbar_view)

	def _clear_title(self):
		self._title.set_title("")
		self._title.set_subtitle("")

	def _on_lyrics_toggled(self, *args):
		if self.get_property("show-lyrics"):
			self._stack.set_visible_child_name("lyrics")
			if self._client.connected() and (song:=self._client.currentsong()):
				self._lyrics_window.display(song)
		else:
			self._stack.set_visible_child_name("cover")
			self._lyrics_window.clear()

	def _on_song_changed(self, emitter, song, songid, state):
		if (song:=self._client.currentsong()):
			self._title.set_title(song["title"][0])
			self._title.set_subtitle(str(song["artist"]))
			if self.get_property("show-lyrics"):
				self._lyrics_window.display(song)
		else:
			self._clear_title()
			if self.get_property("show-lyrics"):
				self._lyrics_window.clear()

	def _on_playlist_changed(self, emitter, version, length, song_pos):
		self._toolbar_view.set_reveal_bottom_bars(length > 0)

	def _on_disconnected(self, *args):
		self._clear_title()
		self.set_property("show-lyrics", False)

	def _on_connected(self, *args):
		self.set_property("show-lyrics", False)

##############
# player bar #
##############

class ProgressBar(Gtk.ProgressBar):
	def __init__(self, client):
		super().__init__(valign=Gtk.Align.START, halign=Gtk.Align.FILL)
		self.add_css_class("osd")
		client.emitter.connect("state", self._on_state)
		client.emitter.connect("elapsed", self._on_elapsed)

	def _on_state(self, emitter, state):
		if state == "stop":
			self.set_visible(False)
			self.set_fraction(0.0)

	def _on_elapsed(self, emitter, elapsed, duration):
		if duration > 0:
			self.set_visible(True)
			self.set_fraction(elapsed/duration)
		else:
			self.set_visible(False)
			self.set_fraction(0.0)

class PlayerBar(Gtk.Overlay):
	def __init__(self, client):
		super().__init__()
		self._client=client

		# widgets
		progress_bar=ProgressBar(client)
		play_button=PlayButton(client)
		self._title=Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, css_classes=["heading"])
		self._subtitle=Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, css_classes=["dim-label", "caption"])

		# connect
		self._client.emitter.connect("current-song", self._on_song_changed)
		self._client.emitter.connect("disconnected", self._on_disconnected)

		# packing
		title_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
		title_box.append(self._title)
		title_box.append(self._subtitle)
		inner_box=Gtk.Box()
		inner_box.add_css_class("toolbar")
		inner_box.append(title_box)
		inner_box.append(play_button)
		outer_box=Gtk.Box()
		outer_box.append(MainCover(client))
		outer_box.append(inner_box)
		self.add_overlay(progress_bar)
		self.set_child(outer_box)

	def _clear_title(self):
		self._title.set_text("")
		self._subtitle.set_text("")

	def _on_song_changed(self, emitter, song, songid, state):
		if (song:=self._client.currentsong()):
			self._title.set_text(song["title"][0])
			self._subtitle.set_text(str(song["artist"]))
		else:
			self._clear_title()

	def _on_disconnected(self, *args):
		self._clear_title()

###################
# MPD gio actions #
###################

class MPDActionGroup(Gio.SimpleActionGroup):
	def __init__(self, client):
		super().__init__()
		self._client=client

		# actions
		self._disable_on_stop_data=["next","prev","seek-forward","seek-backward","a-b-loop"]
		self._disable_no_song=["tidy","enqueue"]
		self._enable_on_reconnect_data=["toggle-play","stop","clear","update","disconnect"]
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
		self._connect_action=Gio.SimpleAction.new("connect", GLib.VariantType.new("b"))
		self._connect_action.connect("activate", self._on_connect)
		self.add_action(self._connect_action)

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

	def _on_a_b_loop(self, action, param):
		self._client.a_b_loop()

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

	def _on_disconnect(self, action, param):
		self._client.disconnect()

	def _on_connect(self, action, param):
		self._client.try_connect(param.get_boolean())

	def _on_state(self, emitter, state):
		state_dict={"play": True, "pause": True, "stop": False}
		for action in self._disable_on_stop_data:
			self.lookup_action(action).set_enabled(state_dict[state])

	def _on_song_changed(self, emitter, song, songid, state):
		for action in self._disable_no_song:
			self.lookup_action(action).set_enabled(song is not None)

	def _on_disconnected(self, *args):
		self._connect_action.set_enabled(True)
		for action in self._data:
			self.lookup_action(action).set_enabled(False)

	def _on_connected(self, *args):
		self._connect_action.set_enabled(False)
		for action in self._enable_on_reconnect_data:
			self.lookup_action(action).set_enabled(True)

###############
# main window #
###############

class MainWindow(Adw.ApplicationWindow):
	def __init__(self, client, settings, **kwargs):
		super().__init__(title="Plattenalbum", icon_name="de.wagnermartin.Plattenalbum", height_request=480, width_request=360, **kwargs)
		self.set_default_icon_name("de.wagnermartin.Plattenalbum")
		self._client=client
		self._settings=settings

		# shortcuts
		builder=Gtk.Builder()
		builder.add_from_resource("/de/wagnermartin/Plattenalbum/ShortcutsWindow.ui")
		self.set_help_overlay(builder.get_object("shortcuts_window"))

		# widgets
		browser=Browser(self._client, self._settings)
		player=Player(self._client, self._settings)
		self._updating_toast=Adw.Toast(title=_("Database is being updated"), timeout=0)
		self._updated_toast=Adw.Toast(title=_("Database updated"))
		self._a_b_loop_toast=Adw.Toast(priority=Adw.ToastPriority.HIGH)

		# actions
		simple_actions_data=("close", "settings","local-connect","remote-connect","setup","stats","help")
		for name in simple_actions_data:
			action=Gio.SimpleAction.new(name, None)
			action.connect("activate", getattr(self, ("_on_"+name.replace("-","_"))))
			self.add_action(action)
		self.add_action(Gio.PropertyAction.new("toggle-lyrics", player, "show-lyrics"))
		self.add_action(Gio.PropertyAction.new("toggle-search", browser, "show-search"))

		# sidebar layout
		overlay_split_view=Adw.OverlaySplitView(
			sidebar_position=Gtk.PackType.END, min_sidebar_width=300, max_sidebar_width=500, sidebar_width_fraction=0.30)
		overlay_split_view.set_content(Adw.LayoutSlot(id="browser"))
		overlay_split_view.set_sidebar(Adw.LayoutSlot(id="player"))
		overlay_split_view.get_content().get_parent().set_css_classes(["sidebar-pane"])
		overlay_split_view.get_sidebar().get_parent().set_css_classes(["content-pane"])
		sidebar_layout=Adw.Layout(content=overlay_split_view, name="sidebar")

		# bottom sheet layout
		content_bin=Adw.Bin(child=Adw.LayoutSlot(id="browser"))
		bottom_sheet=Adw.BottomSheet(
			content=content_bin, sheet=Adw.LayoutSlot(id="player"), bottom_bar=PlayerBar(client), show_drag_handle=False)
		bottom_sheet.bind_property("bottom-bar-height", content_bin, "margin-bottom", GObject.BindingFlags.DEFAULT)
		bottom_sheet_layout=Adw.Layout(content=bottom_sheet, name="bottom-sheet")

		# multi layout view
		multi_layout_view=Adw.MultiLayoutView()
		multi_layout_view.add_layout(sidebar_layout)
		multi_layout_view.add_layout(bottom_sheet_layout)
		multi_layout_view.set_child("browser", browser)
		multi_layout_view.set_child("player", player)
		multi_layout_view.set_layout_name("sidebar")

		# breakpoint
		break_point=Adw.Breakpoint()
		break_point.set_condition(Adw.BreakpointCondition.parse(f"max-width: 620sp"))
		break_point.add_setter(multi_layout_view, "layout-name", "bottom-sheet")
		break_point.add_setter(player, "sheet-mode", True)
		self.add_breakpoint(break_point)

		# status page
		status_page=Adw.StatusPage(icon_name="de.wagnermartin.Plattenalbum", title=_("Connect to Your Music"))
		status_page.set_description(_("To use Plattenalbum, an instance of the Music Player Daemon "\
			"needs to be set up and running on this device or another one on the network"))
		setup_button=Gtk.Button(label=_("_Set up Instance"), use_underline=True, action_name="win.setup")
		setup_button.set_css_classes(["suggested-action", "pill"])
		local_connect_button=Gtk.Button(label=_("Connect _Locally"), use_underline=True, action_name="win.local-connect")
		local_connect_button.add_css_class("pill")
		remote_connect_button=Gtk.Button(label=_("Connect _Remotely"), use_underline=True, action_name="win.remote-connect")
		remote_connect_button.add_css_class("pill")
		button_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, spacing=12)
		button_box.append(setup_button)
		button_box.append(local_connect_button)
		button_box.append(remote_connect_button)
		status_page.set_child(button_box)
		menu=Gio.Menu()
		menu.append(_("_Preferences"), "win.settings")
		menu.append(_("_Keyboard Shortcuts"), "win.show-help-overlay")
		menu.append(_("_Help"), "win.help")
		menu.append(_("_About Plattenalbum"), "app.about")
		menu_button=Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text=_("Main Menu"), primary=True, menu_model=menu)
		header_bar=Adw.HeaderBar()
		header_bar.pack_end(menu_button)
		status_page_toolbar_view=Adw.ToolbarView(content=status_page)
		status_page_toolbar_view.add_top_bar(header_bar)

		# stack
		self._status_page_stack=Gtk.Stack()
		self._status_page_stack.add_named(multi_layout_view, "content")
		self._status_page_stack.add_named(status_page_toolbar_view, "status-page")

		# event controller
		controller_focus=Gtk.EventControllerFocus()
		browser.search_entry.add_controller(controller_focus)

		# connect
		controller_focus.connect("enter", self._on_search_entry_focus_event, True)
		controller_focus.connect("leave", self._on_search_entry_focus_event, False)
		self._settings.connect_after("notify::cursor-watch", self._on_cursor_watch)
		self._client.emitter.connect("current-song", self._on_song_changed)
		self._client.emitter.connect("connected", self._on_connected)
		self._client.emitter.connect("disconnected", self._on_disconnected)
		self._client.emitter.connect("connection_error", self._on_connection_error)
		self._client.emitter.connect("updating-db", self._on_updating_db)
		self._client.emitter.connect("updated-db", self._on_updated_db)
		self._client.emitter.connect("a-b-loop", self._on_a_b_loop)

		# packing
		self._toast_overlay=Adw.ToastOverlay(child=self._status_page_stack)
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
		self._client.try_connect(self._settings.get_boolean("remote-connection"))

	def _clear_title(self):
		self.set_title("Plattenalbum")

	def _on_close(self, action, param):
		if (dialog:=self.get_visible_dialog()) is None:
			self.close()
		else:
			dialog.close()

	def _on_settings(self, action, param):
		if self.get_visible_dialog() is None:
			SettingsDialog(self._client, self._settings).present(self)

	def _on_local_connect(self, action, param):
		if self.get_visible_dialog() is None:
			LocalConnectDialog(self._settings).present(self)

	def _on_remote_connect(self, action, param):
		if self.get_visible_dialog() is None:
			RemoteConnectDialog(self._settings).present(self)

	def _on_setup(self, action, param):
		if self.get_visible_dialog() is None:
			SetupDialog().present(self)

	def _on_stats(self, action, param):
		if self.get_visible_dialog() is None:
			ServerStats(self._client, self._settings).present(self)

	def _on_help(self, action, param):
		Gtk.UriLauncher(uri="https://github.com/SoongNoonien/plattenalbum/wiki/Usage").launch(self, None, None, None)

	def _on_search_entry_focus_event(self, controller, focus):
		if focus:
			self.get_application().set_accels_for_action("mpd.toggle-play", [])
			self.get_application().set_accels_for_action("mpd.a-b-loop", [])
		else:
			self.get_application().set_accels_for_action("mpd.toggle-play", ["space"])
			self.get_application().set_accels_for_action("mpd.a-b-loop", ["l"])

	def _on_song_changed(self, emitter, song, songid, state):
		if (song:=self._client.currentsong()):
			self.set_title(song["title"][0])
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
		if (dialog:=self.get_visible_dialog()) is not None:
			dialog.close()
		self._status_page_stack.set_visible_child_name("content")
		self.lookup_action("stats").set_enabled(True)

	def _on_disconnected(self, *args):
		self._clear_title()
		self.lookup_action("stats").set_enabled(False)
		self._updating_toast.dismiss()

	def _on_connection_error(self, *args):
		self._status_page_stack.set_visible_child_name("status-page")
		if (dialog:=self.get_visible_dialog()) is not None:
			if isinstance(dialog, ConnectDialog):
				dialog.connection_error()

	def _on_updating_db(self, *args):
		self._toast_overlay.add_toast(self._updating_toast)

	def _on_updated_db(self, *args):
		self._updating_toast.dismiss()
		self._toast_overlay.add_toast(self._updated_toast)

	def _on_a_b_loop(self, emitter, first_mark, second_mark):
		if first_mark < 0.0:
			title=_("Cleared A‐B loop")
		else:
			if second_mark < 0.0:
				title=_("Started A‐B loop at {start}").format(start=Duration(first_mark))
			else:
				title=_("Activated A‐B loop from {start} to {end}").format(start=Duration(first_mark), end=Duration(second_mark))
		self._a_b_loop_toast.set_title(title)
		self._toast_overlay.add_toast(self._a_b_loop_toast)

	def _on_cursor_watch(self, obj, typestring):
		if obj.get_property("cursor-watch"):
			self.set_cursor_from_name("progress")
		else:
			self.set_cursor_from_name(None)

###############
# application #
###############

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
			("app.quit", ["<Ctrl>q"]),("win.close", ["<Ctrl>w"]),("win.help", ["F1"]),("win.settings", ["<Ctrl>comma"]),
			("win.show-help-overlay", ["<Ctrl>question"]),("win.toggle-lyrics", ["<Ctrl>l"]),("win.toggle-search", ["<Ctrl>f"]),
			("win.stats", ["<Ctrl>i"]),("mpd.disconnect", ["<Ctrl>d"]),("mpd.update", ["F5"]),("mpd.clear", ["<Shift>Delete"]),
			("mpd.toggle-play", ["space"]),("mpd.stop", ["<Ctrl>space"]),("mpd.next", ["<Ctrl>k"]),("mpd.prev", ["<Shift><Ctrl>k"]),
			("mpd.repeat", ["<Ctrl>r"]),("mpd.random", ["<Ctrl>n"]),("mpd.single", ["<Ctrl>s"]),("mpd.consume", ["<Ctrl>o"]),
			("mpd.single-oneshot", ["<Ctrl>p"]),("mpd.seek-forward", ["<Ctrl>plus"]),("mpd.seek-backward", ["<Ctrl>minus"]),
			("mpd.a-b-loop", ["l"]),("mpd.enqueue", ["<Ctrl>e"]),("mpd.tidy", ["<Ctrl>t"])
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
		dialog=Adw.AboutDialog.new_from_appdata("/de/wagnermartin/Plattenalbum/de.wagnermartin.Plattenalbum.metainfo.xml")
		dialog.set_copyright("© 2020-2024 Martin Wagner")
		dialog.set_developers(["Martin Wagner <martin.wagner.dev@gmail.com>"])
		dialog.set_translator_credits(_("translator-credits"))
		dialog.present(self._window)

	def _on_quit(self, *args):
		self.quit()

if __name__ == "__main__":
	app=Plattenalbum()
	signal.signal(signal.SIGINT, signal.SIG_DFL)  # allow using ctrl-c to terminate
	app.run(sys.argv)

