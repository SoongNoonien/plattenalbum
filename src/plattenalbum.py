#!@PYTHON@
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Plattenalbum - MPD Client.
# Copyright (C) 2020-2026 Martin Wagner <martin.wagner.dev@gmail.com>
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
from html.parser import HTMLParser
import urllib.request
import urllib.parse
import urllib.error
import socket
import threading
import collections
import sys
import signal
import re
import locale
import gettext

locale.bindtextdomain("de.wagnermartin.Plattenalbum", "@LOCALE_DIR@")
locale.textdomain("de.wagnermartin.Plattenalbum")
gettext.install("de.wagnermartin.Plattenalbum", "@LOCALE_DIR@", names=["ngettext"])
Gio.Resource._register(Gio.resource_load(GLib.build_filenamev(["@RESOURCES_DIR@", "de.wagnermartin.Plattenalbum.gresource"])))
signal.signal(signal.SIGINT, signal.SIG_DFL)  # allow using ctrl-c to terminate

##################################
# global constants and functions #
##################################

FALLBACK_COVER=Gdk.Paintable.new_empty(1, 1)
CONNECTION_TIMEOUT=30
MINIMUM_MPD_VERSION="0.24.0"

def idle_add(*args, **kwargs):
	GLib.idle_add(*args, priority=GLib.PRIORITY_DEFAULT, **kwargs)

def lookup_icon(icon_name, size, scale=1):
	return Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).lookup_icon(
			icon_name, None, size, scale, Gtk.TextDirection.NONE, Gtk.IconLookupFlags.FORCE_REGULAR)

#########
# MPRIS #
#########

class MPRISInterface:
	"""
	based on 'Lollypop' (master 22.12.2020) by Cedric Bellegarde <cedric.bellegarde@adishatz.org>
	and 'mpDris2' (master 19.03.2020) by Jean-Philippe Braun <eon@patapon.info>, Mantas Mikulėnas <grawity@gmail.com>
	"""
	_MPRIS_IFACE="org.mpris.MediaPlayer2"
	_MPRIS_PLAYER_IFACE="org.mpris.MediaPlayer2.Player"
	_MPRIS_NAME="org.mpris.MediaPlayer2.de.wagnermartin.Plattenalbum"
	_MPRIS_PATH="/org/mpris/MediaPlayer2"
	_INTERFACES_XML=Gio.resources_lookup_data("/de/wagnermartin/Plattenalbum/mpris.xml", Gio.ResourceLookupFlags.NONE).get_data().decode("utf-8")
	_NODE_INFO=Gio.DBusNodeInfo.new_for_xml(_INTERFACES_XML)
	_PLAYBACK_MAPPING={"play": GLib.Variant("s", "Playing"), "pause": GLib.Variant("s", "Paused"), "stop": GLib.Variant("s", "Stopped")}
	def __init__(self, window, client, settings):
		self._window=window
		self._client=client
		self._settings=settings
		self._bus=self._window.get_application().get_dbus_connection()
		self._metadata={}
		self._object_ids=[]
		self._name_id=None

		# MPRIS property mappings
		self._prop_mapping={
			self._MPRIS_IFACE:
				{"CanQuit": (GLib.Variant("b", False), None, None),
				"CanRaise": (GLib.Variant("b", True), None, None),
				"HasTrackList": (GLib.Variant("b", False), None, None),
				"Identity": (GLib.Variant("s", "Plattenalbum"), None, None),
				"DesktopEntry": (GLib.Variant("s", "de.wagnermartin.Plattenalbum"), None, None),
				"SupportedUriSchemes": (GLib.Variant("as", []), None, None),
				"SupportedMimeTypes": (GLib.Variant("as", []), None, None)},
			self._MPRIS_PLAYER_IFACE:
				{"PlaybackStatus": (GLib.Variant("s", "Stopped"), self._get_playback_status, None),
				"LoopStatus": (GLib.Variant("s", "None"), self._get_loop_status, self._set_loop_status),
				"Rate": (GLib.Variant("d", 1.0), None, None),
				"Shuffle": (GLib.Variant("b", False), self._get_shuffle, self._set_shuffle),
				"Metadata": (GLib.Variant("a{sv}", {}), self._get_metadata, None),
				"Volume": (GLib.Variant("d", 0.0), self._get_volume, self._set_volume),
				"Position": (GLib.Variant("x", 0), self._get_position, None),
				"MinimumRate": (GLib.Variant("d", 1.0), None, None),
				"MaximumRate": (GLib.Variant("d", 1.0), None, None),
				"CanGoNext": (GLib.Variant("b", False), self._get_can_next_prev, None),
				"CanGoPrevious": (GLib.Variant("b", False), self._get_can_next_prev, None),
				"CanPlay": (GLib.Variant("b", False), self._get_can_play_pause, None),
				"CanPause": (GLib.Variant("b", False), self._get_can_play_pause, None),
				"CanSeek": (GLib.Variant("b", False), self._get_can_seek, None),
				"CanControl": (GLib.Variant("b", True), None, None)},
		}

		# connect
		self._settings.connect("changed::mpris", self._on_mpris_changed)
		self._client.connect("songid", self._on_songid_changed)
		self._client.connect("metadata", self._on_metadata_changed)
		self._client.connect("disconnected", self._on_disconnected)
		self._client.connect("connected", self._on_connected)
		self._handlers=(self._client.connect("state", self._on_state_changed),
			self._client.connect("playlist", self._on_playlist_changed),
			self._client.connect("volume", self._on_volume_changed),
			self._client.connect("repeat", self._on_loop_changed),
			self._client.connect("single", self._on_loop_changed),
			self._client.connect("consume", self._on_loop_changed),
			self._client.connect("random", self._on_random_changed),
			self._client.connect("seeked", self._on_seeked))
		for handler in self._handlers:
			self._client.handler_block(handler)

	def _handle_method_call(self, connection, sender, object_path, interface_name, method_name, parameters, invocation):
		result=getattr(self, method_name)(*parameters.unpack())
		if out_args:=self._NODE_INFO.lookup_interface(interface_name).lookup_method(method_name).out_args:
			variant=GLib.Variant(f"({out_args[0].signature})", (result,))
			invocation.return_value(variant)
		else:
			invocation.return_value(None)

	# setter and getter
	def _get_playback_status(self): return self._PLAYBACK_MAPPING[self._client.get_state()]
	def _set_shuffle(self, value): self._client.random(int(value))
	def _get_shuffle(self): return GLib.Variant("b", self._client.get_random())
	def _get_metadata(self): return GLib.Variant("a{sv}", self._metadata)
	def _get_volume(self): return GLib.Variant("d", self._client.get_volume()/100)
	def _set_volume(self, value): self._client.setvol(int(max(value, 0.0)*100))
	def _get_position(self): return GLib.Variant("x", self._client.get_elapsed()*1000000)
	def _get_can_seek(self): return GLib.Variant("b", "mpris:length" in self._metadata)
	def _get_can_next_prev(self): return GLib.Variant("b", self._client.get_state() != "stop")
	def _get_can_play_pause(self): return GLib.Variant("b", self._client.get_playlistlength() > 0)

	def _set_loop_status(self, value):
		self._client.repeat(int(value != "None"))
		self._client.single(int(value == "Track"))
		if value == "Track":
			self._client.consume(0)

	def _get_loop_status(self):
		if self._client.get_repeat():
			if self._client.get_single() and not self._client.get_consume():
				return GLib.Variant("s", "Track")
			return GLib.Variant("s", "Playlist")
		return GLib.Variant("s", "None")

	# introspect methods
	def Introspect(self): return self._INTERFACES_XML

	# property methods
	def Get(self, interface_name, prop):
		default, getter, setter=self._prop_mapping[interface_name][prop]
		if getter is not None:
			return getter()
		return default

	def Set(self, interface_name, prop, value):
		default, getter, setter=self._prop_mapping[interface_name][prop]
		if setter is not None:
			setter(value)

	def GetAll(self, interface_name):
		try:
			props=self._prop_mapping[interface_name]
		except KeyError:  # interface has no properties
			return {}
		read_props={}
		for prop in props:
			read_props[prop]=self.Get(interface_name, prop)
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
	def Raise(self): self._window.present()
	def Quit(self): self._window.get_application().quit()

	# player methods
	def Next(self): self._client.next()
	def Previous(self): self._client.previous()
	def Pause(self): self._client.pause(1)
	def PlayPause(self): self._client.toggle_play()
	def Stop(self): self._client.stop()
	def Play(self): self._client.play()
	def Seek(self, offset): self._client.seekcur((offset>0)*"+"+str(offset/1000000))
	def OpenUri(self, uri): pass

	def SetPosition(self, trackid, position):
		if trackid == self._metadata["mpris:trackid"].unpack() and 0 <= position <= self._metadata["mpris:length"].unpack():
			self._client.seekcur(str(position/1000000))

	def Seeked(self, position):
		self._bus.emit_signal(
			None, self._MPRIS_PATH, self._MPRIS_PLAYER_IFACE, "Seeked",
			GLib.Variant.new_tuple(GLib.Variant("x", position))
		)

	# other methods
	def _convert_metadata(self, song):
		"""
		Translate metadata returned by MPD to the MPRIS v2 syntax.
		http://www.freedesktop.org/wiki/Specifications/mpris-spec/metadata
		"""
		metadata_map={}
		for tag, xesam_tag in (("album","album"),("title","title"),("date","contentCreated")):
			if tag in song:
				metadata_map[f"xesam:{xesam_tag}"]=GLib.Variant("s", song[tag][0])
		for tag, xesam_tag in (("albumartist","albumArtist"),("artist","artist")):
			if tag in song:
				metadata_map[f"xesam:{xesam_tag}"]=GLib.Variant("as", song[tag])
		if "track" in song:
			metadata_map["xesam:trackNumber"]=GLib.Variant("i", int(song["track"][0]))
		if "id" in song:
			metadata_map["mpris:trackid"]=GLib.Variant("o", f"{self._MPRIS_PATH}/Track/{song['id']}")
		if "duration" in song:
			metadata_map["mpris:length"]=GLib.Variant("x", float(song["duration"])*1000000)
		if "file" in song:
			if "://" in (song_file:=song["file"]):  # remote file
				metadata_map["xesam:url"]=GLib.Variant("s", song_file)
			elif (song_path:=self._client.get_absolute_path(song)) is not None:
				metadata_map["xesam:url"]=GLib.Variant("s", Gio.File.new_for_path(song_path).get_uri())
		return metadata_map

	def _set_property(self, interface_name, prop, value):
		self.PropertiesChanged(interface_name, {prop: value}, [])

	def _update_property(self, interface_name, prop):
		self._set_property(interface_name, prop, self.Get(interface_name, prop))

	def _on_state_changed(self, client, state):
		value=GLib.Variant("b", state != "stop")
		self._set_property(self._MPRIS_PLAYER_IFACE, "CanGoNext", value)
		self._set_property(self._MPRIS_PLAYER_IFACE, "CanGoPrevious", value)
		self._set_property(self._MPRIS_PLAYER_IFACE, "PlaybackStatus", self._PLAYBACK_MAPPING[state])

	def _on_songid_changed(self, client, song, cover, cover_path, songpos, songid, state):
		self._metadata=self._convert_metadata(song)
		if cover_path is not None:
			self._metadata["mpris:artUrl"]=GLib.Variant("s", Gio.File.new_for_path(cover_path).get_uri())
		if self._name_id is not None:
			self._update_property(self._MPRIS_PLAYER_IFACE, "CanSeek")
			self._update_property(self._MPRIS_PLAYER_IFACE, "Metadata")

	def _on_metadata_changed(self, client, song):
		cover=self._metadata.get("mpris:artUrl")
		self._metadata=self._convert_metadata(song)
		if cover is not None:
			self._metadata["mpris:artUrl"]=cover
		if self._name_id is not None:
			self._update_property(self._MPRIS_PLAYER_IFACE, "Metadata")

	def _on_playlist_changed(self, client, version, length, songpos):
		value=GLib.Variant("b", length > 0)
		self._set_property(self._MPRIS_PLAYER_IFACE, "CanPlay", value)
		self._set_property(self._MPRIS_PLAYER_IFACE, "CanPause", value)

	def _on_volume_changed(self, client, volume):
		self._set_property(self._MPRIS_PLAYER_IFACE, "Volume", GLib.Variant("d", max(volume, 0)/100))

	def _on_loop_changed(self, *args):
		self._update_property(self._MPRIS_PLAYER_IFACE, "LoopStatus")

	def _on_random_changed(self, client, state):
		self._set_property(self._MPRIS_PLAYER_IFACE, "Shuffle", GLib.Variant("b", state))

	def _on_seeked(self, client, position):
		self.Seeked(position*1000000)

	def _enable(self):
		self._name_id=Gio.bus_own_name_on_connection(self._bus, self._MPRIS_NAME, Gio.BusNameOwnerFlags.NONE, None, None)
		for interface in self._NODE_INFO.interfaces:
			self._object_ids.append(self._bus.register_object(self._MPRIS_PATH, interface, self._handle_method_call, None, None))
		for handler in self._handlers:
			self._client.handler_unblock(handler)

	def _disable(self):
		for object_id in self._object_ids:
			self._bus.unregister_object(object_id)
		self._object_ids=[]
		Gio.bus_unown_name(self._name_id)
		self._name_id=None
		for handler in self._handlers:
			self._client.handler_block(handler)

	def _on_mpris_changed(self, settings, key):
		if settings.get_boolean(key) and self._client.connected():
			self._enable()
		elif self._name_id is not None:
			self._disable()

	def _on_disconnected(self, *args):
		if self._name_id is not None:
			self._disable()

	def _on_connected(self, *args):
		if self._settings.get_boolean("mpris"):
			self._enable()

##############
# MPD client #
##############

class Version(tuple):
	def __new__(cls, version):
		return super().__new__(cls, map(int, version.split(".")))

class SearchFilter():
	def __init__(self, tags, keywords):
		self._tags=tags
		self._keywords=keywords

	def __str__(self):
		return '"('+" AND ".join(self._filter(keyword) for keyword in self._keywords)+')"'

	def _filter(self, keyword):
		return "(!("+" AND ".join(f'({tag} !contains_ci \\"{self._escape(keyword)}\\")' for tag in self._tags)+"))"

	def _escape(self, keyword):
		return keyword.replace("\\", "\\\\\\\\").replace("'", "\\\\'").replace("\"", "\\\\\\\"")

class TagFilter():
	def __init__(self, **kwargs):
		self.filter=kwargs

	def __str__(self):
		return " ".join((f"{tag} {self._quote(value)}" for tag, value in self.filter.items()))

	def __add__(self, other):
		return TagFilter(**self.filter, **other.filter)

	def _quote(self, value):
		return f'"{value.replace("\"","\\\"")}"'

class Duration():
	def __init__(self, seconds=None):
		if seconds is None:
			self._seconds=None
		else:
			self._seconds=float(seconds)

	def __str__(self):
		if self._seconds is None:
			return ""
		seconds=int(self._seconds)
		days,seconds=divmod(seconds, 86400) # 86400 seconds make a day
		hours,seconds=divmod(seconds, 3600) # 3600 seconds make an hour
		minutes,seconds=divmod(seconds, 60)
		if days > 0:
			days_string=ngettext("{days} day", "{days} days", days).format(days=days)
			return f"{days_string}, {hours:02d}:{minutes:02d}:{seconds:02d}"
		if hours > 0:
			return f"{hours}:{minutes:02d}:{seconds:02d}"
		return f"{minutes:02d}:{seconds:02d}"

	def __float__(self):
		return self._seconds

class MultiTag(list):
	def __str__(self):
		return ", ".join(self)

class SongMetaclass(type(GObject.Object), type(collections.UserDict)): pass
class Song(collections.UserDict, GObject.Object, metaclass=SongMetaclass):
	def __init__(self):
		collections.UserDict.__init__(self)
		GObject.Object.__init__(self)
	def __setitem__(self, key, value):
		if key == "duration":
			super().__setitem__(key, Duration(value))
		elif key in ("file", "pos", "id"):
			super().__setitem__(key, value)
		elif key in ("track", "title", "artist", "album", "albumartist", "albumartistsort", "date"):
			if key in self.data:
				self.data[key].append(value)
			else:
				super().__setitem__(key, MultiTag([value]))

	def __missing__(self, key):
		if self.data:
			if key == "albumartist":
				return self["artist"]
			elif key == "albumartistsort":
				return self["albumartist"]
			elif key == "title":
				return MultiTag([GLib.path_get_basename(self.data["file"])])
			elif key == "duration":
				return Duration()
			elif key in ("track", "artist", "album", "date"):
				return MultiTag([""])

	def get_album_artist(self):
		return Artist(self["albumartist"][0], self["albumartistsort"][0])

	def get_album(self):
		return Album(self.get_album_artist(), self["album"][0], self["date"][0])

	def get_quoted_file(self):
		return f'"{self["file"].replace("\"", "\\\"")}"'

class Album(GObject.Object):
	def __init__(self, artist, name, date):
		GObject.Object.__init__(self)
		self.artist=artist
		self.name=name
		self.date=date
		self.cover=None

	def tag_filter(self):
		return self.artist.tag_filter()+TagFilter(album=self.name, date=self.date)

class Artist(GObject.Object):
	def __init__(self, name, sortname):
		GObject.Object.__init__(self)
		self.name=name
		self.sortname=sortname

	def __eq__(self, other):
		return (self.name == other.name) and (self.sortname == other.sortname)

	def tag_filter(self):
		return TagFilter(albumartist=self.name, albumartistsort=self.sortname)

class CommandError(Exception): pass
class Client(GObject.Object):
	__gsignals__={
		"updating-db": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"updated-db": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
		"disconnected": (GObject.SignalFlags.RUN_FIRST, None, ()),
		"connected": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
		"server-error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
		"songid": (GObject.SignalFlags.RUN_FIRST, None, (Song,Gdk.Paintable,str,str,str,str,)),
		"metadata": (GObject.SignalFlags.RUN_FIRST, None, (Song,)),
		"state": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
		"elapsed": (GObject.SignalFlags.RUN_FIRST, None, (float,float,)),
		"volume": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
		"playlist": (GObject.SignalFlags.RUN_FIRST, None, (int,int,str,)),
		"repeat": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
		"random": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
		"single": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
		"consume": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
		"bitrate": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
		"show-album": (GObject.SignalFlags.RUN_FIRST, None, (Album,)),
		"seeked": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
	}
	_COVER_REGEX=re.compile(r"^\.?(album|cover|folder|front).*\.(gif|jpeg|jpg|png)$", flags=re.IGNORECASE)
	_SOCKET_PATH=GLib.build_filenamev([GLib.get_user_runtime_dir(), "mpd", "socket"])
	_BUS=Gio.bus_get_sync(Gio.BusType.SESSION, None)  # used for "show in file manager"
	def __init__(self, settings):
		super().__init__()
		self._settings=settings
		self._cached_status={}

	def _post_connect(self):
		self._socket.settimeout(None)
		self._read_file=self._socket.makefile("rb")
		self._write_file=self._socket.makefile("w", encoding='utf-8')
		self.protocol_version=self._read_file.readline().decode('utf-8')[7:-1]

	def _connect_tcp(self, host, port):
		try:
			addrinfo=socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
		except OSError:
			return False
		for af, socktype, proto, canonname, sa in addrinfo:
			try:
				self._socket=socket.socket(af, socktype, proto)
			except OSError:
				continue
			try:
				self._socket.connect(sa)
			except OSError:
				self._socket.close()
				continue
			break
		else:
			return False
		self.server=f"{host}:{port}"
		self._post_connect()
		return True

	def _connect_unix(self, socket_path):
		self._socket=socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		self.server=socket_path
		if socket_path[0] == "@":
			socket_path="\0"+socket_path[1:]
		try:
			self._socket.connect(socket_path)
		except OSError:
			return False
		self._post_connect()
		return True

	def _connect(self, host, port):
		if host[0] == "@" or host[0] == "/":
			return self._connect_unix(host)
		return self._connect_tcp(host, port)

	def _parse_line(self):
		line=self._read_file.readline().decode('utf-8')
		if not line.endswith("\n"):
			raise CommandError
		line=line[:-1]
		if line.startswith("ACK"):
			if "you don't have permission" in line:
				self.emit("server-error", _("No permission"))
				return None
			raise CommandError(line)
		if line == "OK":
			return None
		return line

	def _parse_pairs(self):
		while (line:=self._parse_line()) is not None:
			key,value=line.split(": ", 1)
			yield (key.lower(), value)

	def _parse_dict(self):
		response={}
		for key, value in self._parse_pairs():
			response[key]=value
		return response

	def _parse_songs(self):
		song=Song()
		for key, value in self._parse_pairs():
			if key == "file" and song:
				yield song
				song=Song()
			song[key]=value
		if song:
			yield song

	def _parse_song(self):
		song=Song()
		for song in self._parse_songs():
			continue
		return song

	def _send_command(self, command):
		self._write_file.write(command+"\n")
		self._write_file.flush()

	def _clear_response(self):
		while self._parse_line() is not None:
			continue

	def _run_command(self, command):
		self._send_command(command)
		self._clear_response()

	def update(self):
		self._send_command("update")
		# This is a rather ugly workaround for database updates that are quicker
		# than around a tenth of a second and therefore can't be detected by _main_loop.
		self._cached_status["updating_db"]=self._parse_dict()["updating_db"]
		self.emit("updating-db")

	def open_connection(self, manual):
		def callback():
			if manual:
				socket.setdefaulttimeout(CONNECTION_TIMEOUT)
				password=self._settings.get_string("password")
				success=self._connect(self._settings.get_string("host"), self._settings.get_int("port"))
			else:
				if (timeout:=GLib.getenv("MPD_TIMEOUT")) is None:
					socket.setdefaulttimeout(CONNECTION_TIMEOUT)
				else:
					socket.setdefaulttimeout(int(timeout))
				password=""
				host=GLib.getenv("MPD_HOST")
				port=GLib.getenv("MPD_PORT")
				if host is None and port is None:
					success=self._connect_unix(self._SOCKET_PATH)
					if not success:
						success=self._connect_unix("/run/mpd/socket")
				else:
					if host is None:
						host="localhost"
					elif "@" in host and host[0] != "@":
						password,host=host.split("@", 1)
					if port is None:
						port=6600
					success=self._connect(host, port)
			if not success:
				self.emit("disconnected")
				return False
			# check MPD version
			if Version(self.protocol_version) < Version(MINIMUM_MPD_VERSION):
				self.close_connection()
				self.emit("server-error", _("Server version older than {version}").format(version=MINIMUM_MPD_VERSION))
				return False
			# set password
			if password:
				try:
					self._run_command(f"password {password}")
				except CommandError:
					self.close_connection()
					self.emit("server-error", _("Incorrect password"))
					return False
			# connected
			self._send_command("commands")
			commands=[command for _, command in self._parse_pairs()]
			self._music_directory=None
			if "config" in commands:
				try:
					self._music_directory=self.config().get("music_directory")
				except CommandError:
					pass
			if "tagtypes" not in commands or "status" not in commands:
				self.close_connection()
				self.emit("server-error", _("Not enough permissions"))
				return False
			self._set_default_tagtypes()
			self._settings.set_boolean("manual-connection", manual)
			self.emit("connected", self._database_is_empty())
			GLib.timeout_add(100, self._main_loop)
			return False
		GLib.idle_add(callback)

	def close_connection(self):
		self._socket.close()
		self._read_file.close()
		try:
			self._write_file.close()
		except BrokenPipeError:
			pass
		self._cached_status={}
		self.emit("disconnected")

	def connected(self):
		try:
			self._run_command("ping")
			return True
		except:
			return False

	def delete_song(self, song):
		self._run_command(f'deleteid {song["id"]}')

	def add_song(self, song, position):
		self._run_command(f"add {song.get_quoted_file()} {position}")

	def append_song(self, song):
		self._run_command(f"add {song.get_quoted_file()}")

	def play_song(self, song):
		self.clear()
		self.append_song(song)
		self.play()

	def add_as_next_song(self, song):
		try:
			self.add_song(song, "+0")
		except CommandError:
			self.add_song(song, "0")

	def move_as_next_song(self, song):
		self._run_command(f'moveid {song["id"]} +0')

	def append_album(self, album):
		self._run_command(f"findadd {album.tag_filter()}")

	def play_album(self, album):
		self.clear()
		self.append_album(album)
		self.play()

	def enqueue(self):
		song=self.currentsong()
		songid=self.get_songid()
		self._run_command(f'moveid {songid} 0')
		if self.get_playlistlength() > 1:
			self._run_command("delete 1:")
		self.append_album(song.get_album())
		self._send_command(f"playlistfind file {song.get_quoted_file()}")
		if duplicate:=self._parse_song():
			self._run_command(f'swapid {songid} {duplicate["id"]}')
			self._run_command(f'deleteid {duplicate["id"]}')

	def tidy_playlist(self):
		if (songid:=self.get_songid()) is None:
			self.clear()
		else:
			self._run_command(f"moveid {songid} 0")
			if self.get_playlistlength() > 1:
				self._run_command("delete 1:")

	def search_songs(self, keywords, num):
		tags=("title", "artist", "album", "date")
		self._send_command(f"search {SearchFilter(tags, keywords)} window 0:{num}")
		return self._parse_songs()

	def search_albums(self, keywords, num):
		tags=("album", "albumartist", "albumartistsort", "date")
		self._send_command(f"list album {SearchFilter(tags, keywords)} group date group albumartist group albumartistsort")
		for key, value in self._parse_pairs():
			if key == "date":
				date=value
			elif key == "albumartist":
				albumartist=value
			elif key == "albumartistsort":
				albumartistsort=value
			elif num > 0:
				yield Album(Artist(albumartist, albumartistsort), value, date)
				num-=1

	def search_artists(self, keywords, num):
		tags=("albumartist", "albumartistsort")
		self._send_command(f"list albumartist {SearchFilter(tags, keywords)} group albumartistsort")
		for key, value in self._parse_pairs():
			if key == "albumartistsort":
				sortname=value
			elif num > 0:
				yield Artist(value, sortname)
				num-=1

	def get_songs(self, album):
		self._send_command(f"find {album.tag_filter()}")
		return self._parse_songs()

	def get_albums(self, artist):
		self._send_command(f"list album {artist.tag_filter()} group date")
		for key, value in self._parse_pairs():
			if key == "date":
				date=value
			else:
				yield Album(artist, value, date)

	def get_artists(self):
		self._send_command(f"list albumartist group albumartistsort")
		for key, value in self._parse_pairs():
			if key == "albumartistsort":
				sortname=value
			else:
				yield Artist(value, sortname)

	def get_cover(self, album):
		self._clear_tagtypes()
		self._send_command(f"find {album.tag_filter()} window 0:1")
		song=self._parse_song()
		self._set_default_tagtypes()
		return self._get_cover(song)

	def get_duration(self, album):
		self._send_command(f"count {album.tag_filter()}")
		return Duration(self._parse_dict()["playtime"])

	def get_playlist_changes(self, version):
		if version is None:
			self._send_command("playlistinfo")
		else:
			self._send_command(f"plchanges {version}")
		for song in self._parse_songs():
			yield song

	def get_absolute_path(self, song):
		stripped_uri=re.sub(r"(.*\.cue)\/track\d+$", r"\1", song["file"], flags=re.IGNORECASE)
		if GLib.file_test(stripped_uri, GLib.FileTest.IS_REGULAR):
			return stripped_uri
		elif self._music_directory is not None:
			absolute_path=GLib.build_filenamev([self._music_directory, stripped_uri])
			if GLib.file_test(absolute_path, GLib.FileTest.IS_REGULAR):
				return absolute_path

	def can_show_file(self, song):
		has_owner,=self._BUS.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
			GLib.Variant("(s)",("org.freedesktop.portal.Desktop",)), GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE, -1, None)
		activatable,=self._BUS.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListActivatableNames",
			None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE, -1, None)
		return (has_owner or "org.freedesktop.portal.Desktop" in activatable) and self.get_absolute_path(song) is not None

	def show_file(self, song):
		with open(self.get_absolute_path(song)) as f:
			fd_list=Gio.UnixFDList()
			self._BUS.call_with_unix_fd_list_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
				"org.freedesktop.portal.OpenURI", "OpenDirectory", GLib.Variant("(sha{sv})", ("", fd_list.append(f.fileno()), {})),
				None, Gio.DBusCallFlags.NONE, -1, fd_list)

	def can_show_album(self, song):
		self._clear_tagtypes()
		self._send_command(f"find file {song.get_quoted_file()}")
		song=self._parse_song()
		self._set_default_tagtypes()
		return bool(song)

	def show_album(self, song):
		self.emit("show-album", song.get_album())

	def toggle_play(self):
		if self.get_state() == "stop":
			self.play()
		else:
			self.pause(int(self.get_state() == "play"))

	def get_state(self): return self._cached_status.get("state", "stop")
	def get_volume(self): return int(self._cached_status.get("volume", "0"))
	def get_elapsed(self): return float(self._cached_status.get("elapsed", "0"))
	def get_playlistlength(self): return int(self._cached_status.get("playlistlength", "0"))
	def get_songid(self): return self._cached_status.get("songid")
	def get_random(self): return self._cached_status.get("random", "0") != "0"
	def get_repeat(self): return self._cached_status.get("repeat", "0") != "0"
	def get_single(self): return self._cached_status.get("single", "0") != "0"
	def get_consume(self): return self._cached_status.get("consume", "0") != "0"

	def _get_cover_path(self, uri):
		if self._music_directory is None:
			return None
		song_dir=GLib.build_filenamev([self._music_directory, GLib.path_get_dirname(uri)])
		if uri.lower().endswith(".cue"):
			song_dir=GLib.path_get_dirname(song_dir)  # get actual directory of .cue file
		if GLib.file_test(song_dir, GLib.FileTest.IS_DIR):
			directory=GLib.Dir.open(song_dir, 0)
			while (f:=directory.read_name()) is not None:
				if self._COVER_REGEX.match(f):
					return GLib.build_filenamev([song_dir, f])

	def _cover_fetch_loop(self, command, quoted_file):
		offset=0
		chunk_size=-1
		data=bytearray()
		while chunk_size != 0:
			self._send_command(f'{command} {quoted_file} {offset}')
			for key, value in self._parse_pairs():
				if key == "binary":
					chunk_size=int(value)
					break
			else:
				break
			chunk=self._read_file.read(chunk_size)
			data.extend(chunk)
			offset+=chunk_size
			self._clear_response()
		if not data:
			return FALLBACK_COVER
		try:
			return Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
		except GLib.Error:  # cover can't be loaded
			return FALLBACK_COVER

	def _get_binary_cover(self, quoted_file):
		try:
			return self._cover_fetch_loop("albumart", quoted_file)
		except CommandError:
			return self._cover_fetch_loop("readpicture", quoted_file)

	def _get_cover_with_path(self, song):
		if (cover_path:=self._get_cover_path(song["file"])) is None:
			return self._get_binary_cover(song.get_quoted_file()), None
		try:
			return Gdk.Texture.new_from_filename(cover_path), cover_path
		except GLib.Error:  # cover can't be loaded
			return self._get_binary_cover(song.get_quoted_file()), None

	def _get_cover(self, song):
		return self._get_cover_with_path(song)[0]

	def _set_default_tagtypes(self):
		self._run_command("tagtypes reset track title artist album albumartist albumartistsort date")

	def _clear_tagtypes(self):
		self._run_command("tagtypes clear")

	def _database_is_empty(self):
		return self.stats().get("songs", "0") == "0"

	def _main_loop(self, *args):
		try:
			song=None
			last_status=self._cached_status
			self._cached_status=self.status()
			diff=dict(set(self._cached_status.items())-set(last_status.items()))
			if "updating_db" in diff:
				self.emit("updating-db")
			if (playlist:=diff.get("playlist")) is not None:
				self.emit("playlist", int(playlist), int(self._cached_status["playlistlength"]), self._cached_status.get("song"))
				song=self.currentsong()
			if (songid:=diff.get("songid")) is not None:
				if song is None:
					song=self.currentsong()
				cover,cover_path=self._get_cover_with_path(song)
				self.emit("songid", song, cover, cover_path, self._cached_status["song"], songid, self._cached_status["state"])
			elif song is not None:
				self.emit("metadata", song)
			if (elapsed:=diff.get("elapsed")) is not None:
				elapsed=float(elapsed)
				self.emit("elapsed", elapsed, float(self._cached_status.get("duration", 0.0)))
				# check if playback position has changed by more than two times the polling interval which indicates a seek event
				if (last_elapsed:=last_status.get("elapsed")) is not None and abs(elapsed-float(last_elapsed)) > 0.2:
					self.emit("seeked", elapsed)
			if (bitrate:=diff.get("bitrate")) is not None:
				if bitrate == "0":
					self.emit("bitrate", None)
				else:
					self.emit("bitrate", bitrate)
			if (volume:=diff.get("volume")) is not None:
				self.emit("volume", int(volume))
			for key in ("state", "single", "consume"):
				if (val:=diff.get(key)) is not None:
					self.emit(key, val)
			for key in ("repeat", "random"):
				if (val:=diff.get(key)) is not None:
					self.emit(key, val != "0")
			diff=set(last_status)-set(self._cached_status)
			for key in diff:
				if "songid" == key:
					self.emit("songid", Song(), FALLBACK_COVER, None, None, None, self._cached_status["state"])
				elif "volume" == key:
					self.emit("volume", -1)
				elif "updating_db" == key:
					self.emit("updated-db", self._database_is_empty())
				elif "bitrate" == key:
					self.emit("bitrate", None)
			return True
		except (BrokenPipeError, ConnectionResetError, CommandError):  # Server offline or connection lost
			self.close_connection()
			return False
		except ValueError:  # Connection closed by user
			return False

	def currentsong(self):
		self._send_command("currentsong")
		return self._parse_song()

	def status(self):
		self._send_command("status")
		return self._parse_dict()

	def config(self):
		self._send_command("config")
		return self._parse_dict()

	def stats(self):
		self._send_command("stats")
		return self._parse_dict()

	def pause(self, state=""): self._run_command(f"pause {state}")
	def play(self, pos=""): self._run_command(f"play {pos}")
	def move(self, from_pos, to_pos): self._run_command(f"move {from_pos} {to_pos}")
	def seekcur(self, time): self._run_command(f"seekcur {time}")
	def setvol(self, vol): self._run_command(f"setvol {vol}")
	def stop(self): self._run_command("stop")
	def next(self): self._run_command("next")
	def previous(self): self._run_command("previous")
	def clear(self): self._run_command("clear")
	def single(self, state): self._run_command(f"single {state}")
	def consume(self, state): self._run_command(f"consume {state}")
	def random(self, state): self._run_command(f"random {state}")
	def repeat(self, state): self._run_command(f"repeat {state}")

########################
# gio settings wrapper #
########################

class Settings(Gio.Settings):
	cursor_watch=GObject.Property(type=bool, default=False)
	def __init__(self):
		super().__init__(schema="de.wagnermartin.Plattenalbum")

###########
# dialogs #
###########

@Gtk.Template(resource_path="/de/wagnermartin/Plattenalbum/preferences-dialog.ui")
class PreferencesDialog(Adw.PreferencesDialog):
	__gtype_name__="PreferencesDialog"
	show_bit_rate=Gtk.Template.Child()
	send_notify=Gtk.Template.Child()
	stop_on_quit=Gtk.Template.Child()
	mpris=Gtk.Template.Child()
	def __init__(self, settings):
		super().__init__()
		settings.bind("show-bit-rate", self.show_bit_rate, "active", Gio.SettingsBindFlags.DEFAULT)
		settings.bind("send-notify", self.send_notify, "active", Gio.SettingsBindFlags.DEFAULT)
		settings.bind("stop-on-quit", self.stop_on_quit, "active", Gio.SettingsBindFlags.DEFAULT)
		settings.bind("mpris", self.mpris, "active", Gio.SettingsBindFlags.DEFAULT)

class ConnectDialog(Adw.Dialog):
	def __init__(self, settings):
		super().__init__(title=_("Manual Connection"), width_request=360, follows_content_size=True)

		# list_box
		list_box=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
		list_box.add_css_class("boxed-list")
		hostname_row=Adw.EntryRow(title=_("Host"))
		settings.bind("host", hostname_row, "text", Gio.SettingsBindFlags.DEFAULT)
		list_box.append(hostname_row)
		port_row=Adw.SpinRow.new_with_range(0, 65535, 1)
		port_row.set_title(_("Port"))
		settings.bind("port", port_row, "value", Gio.SettingsBindFlags.DEFAULT)
		list_box.append(port_row)
		password_row=Adw.PasswordEntryRow(title=_("Password (optional)"))
		settings.bind("password", password_row, "text", Gio.SettingsBindFlags.DEFAULT)
		list_box.append(password_row)

		# button
		connect_button=Gtk.Button(label=_("_Connect"), use_underline=True, action_name="app.connect", action_target=GLib.Variant("b", True),
			halign=Gtk.Align.CENTER, css_classes=["suggested-action", "pill"])

		# packing
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
		box.append(list_box)
		box.append(connect_button)
		clamp=Adw.Clamp(child=box, margin_start=12, margin_end=12, margin_top=24, margin_bottom=24)
		scroll=Gtk.ScrolledWindow(child=clamp, propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
		toolbar_view=Adw.ToolbarView(content=scroll)
		toolbar_view.add_top_bar(Adw.HeaderBar())
		self._connection_toast=Adw.Toast(title=_("Connection failed"))
		self._toast_overlay=Adw.ToastOverlay(child=toolbar_view)
		self.set_child(self._toast_overlay)

	def connection_failed(self):
		self._toast_overlay.add_toast(self._connection_toast)

class CommandLabel(Gtk.Label):
	def __init__(self, **kwargs):
		super().__init__(selectable=True, xalign=0, hexpand=True, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
			css_classes=["command-label", "view", "card", "monospace"], **kwargs)

class SetupDialog(Adw.Dialog):
	def __init__(self):
		super().__init__(title=_("Setup"), width_request=360, follows_content_size=True)
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
		box.append(Gtk.Label(label=_("To get started, install the Music Player Daemon (<tt>mpd</tt>) with your system package manager, and"\
			" run the following commands to configure and initialize a basic local instance. After that, Plattenalbum should be able to"\
			" seamlessly connect to it."), use_markup=True, xalign=0, wrap=True))
		box.append(CommandLabel(label="mkdir ~/.mpd"))
		box.append(CommandLabel(label='cat << EOF > ~/.mpd/mpd.conf\ndb_file\t\t"~/.mpd/database"\nstate_file\t"~/.mpd/state"\n\n'\
			'audio_output {\n\ttype\t"pulse"\n\tname\t"Music"\n}\nEOF'))
		box.append(CommandLabel(label="systemctl --user enable --now mpd.socket"))

		# packing
		clamp=Adw.Clamp(child=box, margin_start=12, margin_end=12, margin_top=24, margin_bottom=24)
		scroll=Gtk.ScrolledWindow(child=clamp, propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
		toolbar_view=Adw.ToolbarView(content=scroll)
		toolbar_view.add_top_bar(Adw.HeaderBar())
		self.set_child(toolbar_view)

class PropertyRow(Adw.ActionRow):
	def __init__(self, **kwargs):
		super().__init__(activatable=False, selectable=False, css_classes=["property"], **kwargs)

class ServerInfo(Adw.Dialog):
	def __init__(self, client):
		super().__init__(title=_("Information"), width_request=360, follows_content_size=True)

		# lists
		server_list=Gtk.ListBox()
		server_list.add_css_class("boxed-list")
		database_list=Gtk.ListBox()
		database_list.add_css_class("boxed-list")

		# boxes
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=30)
		box.append(HeadingBox(_("Server"), server_list))
		box.append(HeadingBox(_("Database"), database_list))

		# populate
		stats=client.stats()
		server_list.append(PropertyRow(title=_("Address"), subtitle=client.server, subtitle_selectable=True))
		server_list.append(PropertyRow(title=_("Protocol"), subtitle=client.protocol_version))
		database_list.append(PropertyRow(title=_("Songs"), subtitle=stats["songs"]))
		database_list.append(PropertyRow(title=_("Total Playtime"), subtitle=str(Duration(stats["db_playtime"]))))
		last_update=GLib.DateTime.new_from_unix_local(int(stats["db_update"])).format("%x, %X")
		database_list.append(PropertyRow(title=_("Last Update"), subtitle=last_update))

		# packing
		clamp=Adw.Clamp(child=box, margin_start=12, margin_end=12, margin_top=24, margin_bottom=24)
		scroll=Gtk.ScrolledWindow(child=clamp, propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
		toolbar_view=Adw.ToolbarView(content=scroll)
		toolbar_view.add_top_bar(Adw.HeaderBar())
		self.set_child(toolbar_view)

###########################
# general purpose widgets #
###########################

class HeadingBox(Gtk.Box):
	def __init__(self, heading, widget):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
		self.append(Gtk.Label(label=heading, xalign=0, css_classes=["heading"]))
		self.append(widget)

class SelectionModel(GObject.Object, Gio.ListModel, Gtk.SelectionModel):
	show_selection=GObject.Property(type=bool, default=True)
	def __init__(self, item_type):
		super().__init__()
		self._item_type=item_type
		self._data=[]
		self._selected=None

		# connect
		self.connect("notify::show-selection", self._on_show_selection)

	def clear(self, position=0):
		n=self.get_n_items()-position
		self._data=self._data[:position]
		if self._selected is not None and self._selected >= self.get_n_items():
			self._selected=None
		self.items_changed(position, n, 0)

	def append(self, data):
		n=self.get_n_items()
		self._data.extend(data)
		self.items_changed(n, 0, self.get_n_items())

	def get_selected(self):
		return self._selected

	def set(self, position, item):
		if position < len(self._data):
			self._data[position]=item
			self.items_changed(position, 1, 1)
		else:
			self._data.append(item)
			self.items_changed(position, 0, 1)

	def select(self, position):
		if position != self._selected:
			self.unselect()
			self._selected=position
			self.selection_changed(self._selected, 1)

	def unselect(self):
		old_selected=self._selected
		self._selected=None
		if old_selected is not None:
			self.selection_changed(old_selected, 1)

	def _on_show_selection(self, *args):
		if self._selected is not None:
			self.selection_changed(self._selected, 1)

	# Gio.ListModel methods
	def do_get_item(self, position):
		try:
			return self._data[position]
		except IndexError:
			return None

	def do_get_item_type(self): return self._item_type
	def do_get_n_items(self): return len(self._data)

	# Gtk.SelectionModel methods
	def do_select_item(self, position, unselect_rest): return False
	def do_select_all(self): return False
	def do_select_range(self, position, n_items, unselect_rest): return False
	def do_set_selection(self, selected, mask): return False
	def do_unselect_all(self): return False
	def do_unselect_item(self, position): return False
	def do_unselect_range(self, position, n_items): return False
	def do_get_selection_in_range(self, position, n_items): return False
	def do_is_selected(self, position): return position == self._selected and self.get_property("show-selection")

class SongMenu(Gtk.PopoverMenu):
	def __init__(self, client, show_album=False):
		super().__init__(has_arrow=False, halign=Gtk.Align.START)
		self.update_property([Gtk.AccessibleProperty.LABEL], [_("Context menu")])
		self._client=client
		self._song=None

		# action group
		action_group=Gio.SimpleActionGroup()
		action=Gio.SimpleAction.new("append", None)
		action.connect("activate", lambda *args: self._client.append_song(self._song))
		action_group.add_action(action)
		action=Gio.SimpleAction.new("as-next", None)
		action.connect("activate", lambda *args: self._client.add_as_next_song(self._song))
		action_group.add_action(action)
		if show_album:
			action=Gio.SimpleAction.new("show-album", None)
			action.connect("activate", lambda *args: self._client.show_album(self._song))
			action_group.add_action(action)
		self._show_file_action=Gio.SimpleAction.new("show-file", None)
		self._show_file_action.connect("activate", lambda *args: self._client.show_file(self._song))
		action_group.add_action(self._show_file_action)
		self.insert_action_group("menu", action_group)

		# menu model
		menu=Gio.Menu()
		menu.append(_("_Append"), "menu.append")
		menu.append(_("As _Next"), "menu.as-next")
		subsection=Gio.Menu()
		if show_album:
			subsection.append(_("Show Al_bum"), "menu.show-album")
		subsection.append(_("Show _File"), "menu.show-file")
		menu.append_section(None, subsection)
		self.set_menu_model(menu)

	def open(self, song, x, y):
		self._song=song
		rect=Gdk.Rectangle()
		rect.x,rect.y=x,y
		self.set_pointing_to(rect)
		self._show_file_action.set_enabled(self._client.can_show_file(self._song))
		self.popup()

class SongActionRow(Adw.ActionRow):
	def __init__(self, song, show_track=True, hide_artist="", **kwargs):
		super().__init__(use_markup=False, activatable=True, **kwargs)
		self.song=song

		# populate
		self.set_title(song["title"][0])
		if subtitle:=", ".join(artist for artist in song["artist"] if artist != hide_artist):
			self.set_subtitle(subtitle)
		length=Gtk.Label(label=str(song["duration"]), xalign=1, single_line_mode=True, css_classes=["numeric", "dimmed"])
		self.add_suffix(length)
		if show_track:
			track=Gtk.Label(label=song["track"][0], xalign=1, single_line_mode=True, width_chars=3, css_classes=["numeric", "dimmed"])
			self.add_prefix(track)

class SongList(Gtk.ListBox):
	def __init__(self, client, show_album=False):
		super().__init__(selection_mode=Gtk.SelectionMode.NONE, tab_behavior=Gtk.ListTabBehavior.ITEM, valign=Gtk.Align.START)
		self._client=client

		# menu
		self._menu=SongMenu(client, show_album=show_album)

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
		long_press_controller=Gtk.GestureLongPress()
		self.add_controller(long_press_controller)
		drag_source=Gtk.DragSource()
		drag_source.set_icon(lookup_icon("audio-x-generic", 32, self.get_scale_factor()), 0, 0)
		self.add_controller(drag_source)

		# connect
		self.connect("row-activated", self._on_row_activated)
		self.connect("keynav-failed", self._on_keynav_failed)
		button_controller.connect("pressed", self._on_button_pressed)
		long_press_controller.connect("pressed", self._on_long_pressed)
		drag_source.connect("prepare", self._on_drag_prepare)

	def remove_all(self):
		self._menu.unparent()
		super().remove_all()

	def _open_menu(self, row, x, y):
		self._menu.unparent()
		self._menu.set_parent(row)
		point=Graphene.Point.zero()
		point.x,point.y=x,y
		computed_point,point=self.compute_point(row, point)
		if computed_point:
			self._menu.open(row.song, point.x, point.y)

	def _on_row_activated(self, list_box, row):
		self._client.play_song(row.song)

	def _on_keynav_failed(self, list_box, direction):
		if (root:=list_box.get_root()) is not None and direction == Gtk.DirectionType.UP:
			root.child_focus(Gtk.DirectionType.TAB_BACKWARD)

	def _on_button_pressed(self, controller, n_press, x, y):
		if (row:=self.get_row_at_y(y)) is not None:
			if controller.get_current_button() == 2 and n_press == 1:
				self._client.append_song(row.song)
			elif controller.get_current_button() == 3 and n_press == 1:
				self._open_menu(row, x, y)

	def _on_long_pressed(self, controller, x, y):
		if (row:=self.get_row_at_y(y)) is not None:
			self._open_menu(row, x, y)

	def _on_menu(self, action, state):
		row=self.get_focus_child()
		self._menu.unparent()
		self._menu.set_parent(row)
		self._menu.open(row.song, 0, 0)

	def _on_drag_prepare(self, drag_source, x, y):
		if (row:=self.get_row_at_y(y)) is not None:
			return Gdk.ContentProvider.new_for_value(row.song)

class AlbumCover(Gtk.Widget):
	def __init__(self, **kwargs):
		super().__init__(hexpand=True, **kwargs)
		self._picture=Gtk.Picture(css_classes=["cover"], accessible_role=Gtk.AccessibleRole.PRESENTATION)
		self._picture.set_parent(self)
		self.connect("destroy", lambda *args: self._picture.unparent())

	def do_get_request_mode(self):
		return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

	def do_size_allocate(self, width, height, baseline):
		self._picture.allocate(width, height, baseline, None)

	def do_measure(self, orientation, for_size):
		return (for_size, for_size, -1, -1)

	def set_paintable(self, paintable):
		if paintable.get_intrinsic_width()/paintable.get_intrinsic_height() >= 1:
			self._picture.set_halign(Gtk.Align.FILL)
			self._picture.set_valign(Gtk.Align.CENTER)
		else:
			self._picture.set_halign(Gtk.Align.CENTER)
			self._picture.set_valign(Gtk.Align.FILL)
		self._picture.set_paintable(paintable)

	def set_alternative_text(self, alt_text):
		self._picture.set_alternative_text(alt_text)

###########
# browser #
###########

class AlbumActionRow(Adw.ActionRow):
	def __init__(self, album):
		super().__init__(use_markup=False, activatable=True, css_classes=["property"])
		self.album=album
		self.set_title(album.artist.name)
		self.set_subtitle(album.name)
		self.add_suffix(Gtk.Label(label=album.date, use_markup=False, xalign=1, single_line_mode=True, css_classes=["numeric", "dimmed"]))
		self.add_suffix(Gtk.Image(icon_name="go-next-symbolic", accessible_role=Gtk.AccessibleRole.PRESENTATION))

class ArtistActionRow(Adw.ActionRow):
	def __init__(self, artist):
		super().__init__(use_markup=False, activatable=True)
		self.artist=artist
		self.set_title(artist.name)
		self.add_suffix(Gtk.Image(icon_name="go-next-symbolic", accessible_role=Gtk.AccessibleRole.PRESENTATION))

class SearchView(Gtk.Stack):
	__gsignals__={"artist-selected": (GObject.SignalFlags.RUN_FIRST, None, (Artist,)),
			"album-selected": (GObject.SignalFlags.RUN_FIRST, None, (Album,))}
	def __init__(self, client):
		super().__init__()
		self._client=client
		self._results=20  # TODO adjust number of results

		# artist list
		self._artist_list=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, tab_behavior=Gtk.ListTabBehavior.ITEM, valign=Gtk.Align.START)
		self._artist_list.add_css_class("boxed-list")

		# album list
		self._album_list=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, tab_behavior=Gtk.ListTabBehavior.ITEM, valign=Gtk.Align.START)
		self._album_list.add_css_class("boxed-list")

		# song list
		self._song_list=SongList(client, show_album=True)
		self._song_list.add_css_class("boxed-list")

		# boxes
		self._artist_box=HeadingBox(_("Artists"), self._artist_list)
		self._album_box=HeadingBox(_("Albums"), self._album_list)
		self._song_box=HeadingBox(_("Songs"), self._song_list)
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=30, margin_start=12, margin_end=12, margin_top=24, margin_bottom=24)
		box.append(self._artist_box)
		box.append(self._album_box)
		box.append(self._song_box)

		# scroll
		scroll=Gtk.ScrolledWindow(child=Adw.Clamp(child=box))
		self._adj=scroll.get_vadjustment()

		# status page
		status_page=Adw.StatusPage(icon_name="edit-find-symbolic", title=_("No Results"), description=_("Try a different search"))

		# connect
		self._artist_list.connect("row-activated", self._on_artist_activate)
		self._artist_list.connect("keynav-failed", self._on_keynav_failed)
		self._album_list.connect("row-activated", self._on_album_activate)
		self._album_list.connect("keynav-failed", self._on_keynav_failed)

		# packing
		self.add_named(status_page, "no-results")
		self.add_named(scroll, "results")

	def clear(self):
		self._artist_list.remove_all()
		self._album_list.remove_all()
		self._song_list.remove_all()
		self._adj.set_value(0.0)
		self.set_visible_child_name("no-results")

	def search(self, search_text):
		self.clear()
		if (keywords:=search_text.split()):
			for song in self._client.search_songs(keywords, self._results):
				self._song_list.append(SongActionRow(song, show_track=False))
			self._song_box.set_visible(self._song_list.get_first_child() is not None)
			for album in self._client.search_albums(keywords, self._results):
				self._album_list.append(AlbumActionRow(album))
			self._album_box.set_visible(self._album_list.get_first_child() is not None)
			for artist in self._client.search_artists(keywords, self._results):
				self._artist_list.append(ArtistActionRow(artist))
			self._artist_box.set_visible(self._artist_list.get_first_child() is not None)
			if self._song_box.get_visible() or self._album_box.get_visible() or self._artist_box.get_visible():
				self.set_visible_child_name("results")

	def _on_artist_activate(self, list_box, row):
		self.emit("artist-selected", row.artist)

	def _on_album_activate(self, list_box, row):
		self.emit("album-selected", row.album)

	def _on_keynav_failed(self, list_box, direction):
		if (root:=list_box.get_root()) is not None:
			if direction == Gtk.DirectionType.UP:
				root.child_focus(Gtk.DirectionType.TAB_BACKWARD)
			elif direction == Gtk.DirectionType.DOWN:
				root.child_focus(Gtk.DirectionType.TAB_FORWARD)

class ArtistList(Gtk.ListView):
	show_selection=GObject.Property(type=bool, default=True)
	__gsignals__={"artist-selected": (GObject.SignalFlags.RUN_FIRST, None, (Artist,)),
		"clear": (GObject.SignalFlags.RUN_FIRST, None, ())}
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

		# model
		self._selection_model=SelectionModel(Artist)
		self.set_model(self._selection_model)
		self.bind_property("show-selection", self._selection_model, "show-selection", GObject.BindingFlags.DEFAULT)

		# connect
		self.connect("activate", self._on_activate)
		self._client.connect("disconnected", self._on_disconnected)
		self._client.connect("connected", self._on_connected)
		self._client.connect("updated-db", self._on_updated_db)

	def select(self, artist):
		for i, item in enumerate(self._selection_model):
			if item == artist:
				self._selection_model.select(i)
				self.scroll_to(i, Gtk.ListScrollFlags.FOCUS, None)
				self.emit("artist-selected", artist)
				break

	def _clear(self):
		self._selection_model.clear()
		self.emit("clear")

	def _refresh(self):
		self._clear()
		self._selection_model.append(sorted(self._client.get_artists(), key=lambda item: locale.strxfrm(item.sortname)))

	def _on_activate(self, widget, pos):
		self._selection_model.select(pos)
		self.emit("artist-selected", self._selection_model.get_item(pos))

	def _on_disconnected(self, *args):
		self._clear()

	def _on_connected(self, client, database_is_empty):
		if not database_is_empty:
			self._refresh()
			if (song:=self._client.currentsong()):
				self.select(song.get_album_artist())

	def _on_updated_db(self, client, database_is_empty):
		if database_is_empty:
			self._clear()
		else:
			if (selected:=self._selection_model.get_selected()) is not None:
				artist=self._selection_model.get_item(selected)
				self._refresh()
				self.select(artist)

class AlbumRow(Gtk.Box):
	def __init__(self, client):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)
		self._client=client
		self._cover=AlbumCover()
		self._title=Gtk.Label(single_line_mode=True, ellipsize=Pango.EllipsizeMode.END, margin_top=3)
		self._date=Gtk.Label(single_line_mode=True, css_classes=["dimmed", "caption"])
		self.append(self._cover)
		self.append(self._title)
		self.append(self._date)

	def set_album(self, album):
		if album.name:
			self._title.set_text(album.name)
			self._cover.set_alternative_text(_("Album cover of {album}").format(album=album.name))
		else:
			self._title.set_markup(f'<i>{GLib.markup_escape_text(_("Unknown Album"))}</i>')
			self._cover.set_alternative_text(_("Album cover of an unknown album"))
		self._date.set_text(album.date)
		if album.cover is None:
			album.cover=self._client.get_cover(album)
		self._cover.set_paintable(album.cover)

class AlbumsPage(Adw.NavigationPage):
	__gsignals__={"album-selected": (GObject.SignalFlags.RUN_FIRST, None, (Album,))}
	def __init__(self, client, settings):
		super().__init__(title=_("Albums"), tag="album_list")
		self._settings=settings
		self._client=client
		self._artist=None

		# grid view
		self.grid_view=Gtk.GridView(tab_behavior=Gtk.ListTabBehavior.ITEM, single_click_activate=True, vexpand=True, max_columns=2)
		self.grid_view.add_css_class("navigation-sidebar")
		self.grid_view.add_css_class("albums-view")
		self._selection_model=SelectionModel(Album)
		self.grid_view.set_model(self._selection_model)

		# factory
		def setup(factory, item):
			row=AlbumRow(self._client)
			item.set_child(row)
		def bind(factory, item):
			row=item.get_child()
			row.set_album(item.get_item())
		factory=Gtk.SignalListItemFactory()
		factory.connect("setup", setup)
		factory.connect("bind", bind)
		self.grid_view.set_factory(factory)

		# breakpoint bin
		breakpoint_bin=Adw.BreakpointBin(width_request=320, height_request=200)
		for width, columns in ((500,3), (850,4), (1200,5), (1500,6)):
			break_point=Adw.Breakpoint()
			break_point.set_condition(Adw.BreakpointCondition.parse(f"min-width: {width}sp"))
			break_point.add_setter(self.grid_view, "max-columns", columns)
			breakpoint_bin.add_breakpoint(break_point)
		breakpoint_bin.set_child(Gtk.ScrolledWindow(child=self.grid_view))

		# status page
		status_page=Adw.StatusPage(icon_name="folder-music-symbolic", title=_("No Albums"), description=_("Select an artist"))

		# stack
		self._stack=Gtk.Stack()
		self._stack.add_named(breakpoint_bin, "albums")
		self._stack.add_named(status_page, "status-page")

		# connect
		self.grid_view.connect("activate", self._on_activate)
		self._client.connect("disconnected", self._on_disconnected)

		# packing
		toolbar_view=Adw.ToolbarView(content=self._stack)
		toolbar_view.add_top_bar(Adw.HeaderBar())
		self.set_child(toolbar_view)

	def clear(self, *args):
		self._selection_model.clear()
		self.set_title(_("Albums"))
		self._stack.set_visible_child_name("status-page")
		self._artist=None

	def display(self, artist):
		if artist != self._artist:
			self._settings.set_property("cursor-watch", True)
			self._artist=artist
			self._selection_model.clear()
			self.set_title(artist.name)
			self._stack.set_visible_child_name("albums")
			# ensure list is empty
			main=GLib.main_context_default()
			while main.pending():
				main.iteration()
			self.update_property([Gtk.AccessibleProperty.LABEL], [_("Albums of {artist}").format(artist=artist.name)])
			self._selection_model.append(sorted(self._client.get_albums(artist), key=lambda item: item.date))
			self._settings.set_property("cursor-watch", False)

	def _on_activate(self, widget, pos):
		self.emit("album-selected", self._selection_model.get_item(pos))

	def _on_disconnected(self, *args):
		self._stack.set_visible_child_name("albums")

class AlbumPage(Adw.NavigationPage):
	def __init__(self, client, album):
		super().__init__()

		# songs list
		song_list=SongList(client)
		song_list.add_css_class("boxed-list")

		# buttons
		self.play_button=Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text=_("Play"))
		self.play_button.connect("clicked", lambda *args: client.play_album(album))
		append_button=Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Append"))
		append_button.connect("clicked", lambda *args: client.append_album(album))

		# header bar
		header_bar=Adw.HeaderBar(show_title=False)
		header_bar.pack_end(self.play_button)
		header_bar.pack_end(append_button)

		# labels
		suptitle=Gtk.Label(single_line_mode=True, ellipsize=Pango.EllipsizeMode.END, css_classes=["dimmed", "caption"])
		title=Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, css_classes=["title-4"])
		subtitle=Gtk.Label(single_line_mode=True, ellipsize=Pango.EllipsizeMode.END, visible=bool(album.date))
		length=Gtk.Label(single_line_mode=True, css_classes=["numeric", "dimmed", "caption"])

		# label box
		label_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, margin_top=9, margin_bottom=18)
		label_box.append(suptitle)
		label_box.append(title)
		label_box.append(subtitle)
		label_box.append(length)

		# cover
		cover=AlbumCover()

		# packing
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=12, margin_end=12, margin_top=6, margin_bottom=24)
		box.append(Adw.Clamp(child=cover, maximum_size=200))
		box.append(label_box)
		box.append(Adw.Clamp(child=song_list))
		toolbar_view=Adw.ToolbarView(content=Gtk.ScrolledWindow(child=box))
		toolbar_view.add_top_bar(header_bar)
		self.set_child(toolbar_view)

		# populate
		if album.name:
			self.set_title(album.name)
			title.set_text(album.name)
		else:
			self.set_title(_("Unknown Album"))
			title.set_text(_("Unknown Album"))
		suptitle.set_text(album.artist.name)
		subtitle.set_text(album.date)
		length.set_text(str(client.get_duration(album)))
		cover.set_paintable(client.get_cover(album))
		for song in client.get_songs(album):
			row=SongActionRow(song, hide_artist=album.artist.name)
			song_list.append(row)

class MainMenuButton(Gtk.MenuButton):
	def __init__(self):
		super().__init__(icon_name="open-menu-symbolic", tooltip_text=_("Main Menu"), primary=True)
		app_section=Gio.Menu()
		app_section.append(_("_Preferences"), "win.preferences")
		app_section.append(_("_Keyboard Shortcuts"), "app.shortcuts")
		app_section.append(_("_About Plattenalbum"), "app.about")
		menu=Gio.Menu()
		menu.append(_("_Disconnect"), "app.disconnect")
		menu.append(_("_Update Database"), "app.update")
		menu.append(_("_Server Information"), "win.server-info")
		menu.append_section(None, app_section)
		self.set_menu_model(menu)

class Browser(Gtk.Stack):
	def __init__(self, client, settings):
		super().__init__()
		self._client=client

		# search
		self._search_view=SearchView(client)
		self.search_entry=Gtk.SearchEntry(placeholder_text=_("Search collection"), max_width_chars=25)
		self.search_entry.update_property([Gtk.AccessibleProperty.LABEL], [_("Search collection")])
		search_toolbar_view=Adw.ToolbarView(content=self._search_view)
		search_header_bar=Adw.HeaderBar(title_widget=self.search_entry)
		search_toolbar_view.add_top_bar(search_header_bar)
		search_toolbar_view.add_css_class("content-pane")

		# artist list
		self._artist_list=ArtistList(client)
		artist_header_bar=Adw.HeaderBar()
		search_button=Gtk.Button(icon_name="system-search-symbolic", tooltip_text=_("Search"))
		search_button.connect("clicked", lambda *args: self.search())
		artist_header_bar.pack_start(search_button)
		artist_header_bar.pack_end(MainMenuButton())
		artist_toolbar_view=Adw.ToolbarView(content=Gtk.ScrolledWindow(child=self._artist_list))
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
		breakpoint_bin=Adw.BreakpointBin(width_request=320, height_request=200)
		break_point=Adw.Breakpoint()
		break_point.set_condition(Adw.BreakpointCondition.parse(f"max-width: 550sp"))
		break_point.add_setter(self._navigation_split_view, "collapsed", True)
		break_point.add_setter(self._artist_list, "show-selection", False)
		breakpoint_bin.add_breakpoint(break_point)
		breakpoint_bin.set_child(self._navigation_split_view)

		# status page
		status_page=Adw.StatusPage(icon_name="folder-music-symbolic", title=_("Collection is Empty"))
		status_page_header_bar=Adw.HeaderBar(show_title=False)
		status_page_header_bar.pack_end(MainMenuButton())
		status_page_toolbar_view=Adw.ToolbarView(content=status_page)
		status_page_toolbar_view.add_top_bar(status_page_header_bar)

		# navigation view
		self._navigation_view=Adw.NavigationView()
		self._navigation_view.add(Adw.NavigationPage(child=breakpoint_bin, title=_("Collection"), tag="collection"))
		self._navigation_view.add(Adw.NavigationPage(child=search_toolbar_view, title=_("Search"), tag="search"))

		# connect
		self._albums_page.connect("album-selected", self._on_album_selected)
		self._artist_list.connect("artist-selected", self._on_artist_selected)
		self._artist_list.connect("clear", self._albums_page.clear)
		self._search_view.connect("artist-selected", self._on_search_artist_selected)
		self._search_view.connect("album-selected", lambda widget, album: self._show_album(album))
		self.search_entry.connect("search-changed", self._on_search_changed)
		self.search_entry.connect("stop-search", self._on_search_stopped)
		client.connect("disconnected", self._on_disconnected)
		client.connect("connected", self._on_connected_or_updated_db)
		client.connect("updated-db", self._on_connected_or_updated_db)
		client.connect("show-album", lambda widget, album: self._show_album(album))

		# packing
		self.add_named(self._navigation_view, "browser")
		self.add_named(status_page_toolbar_view, "empty-collection")

	def search(self):
		if self._navigation_view.get_visible_page_tag() != "search":
			self._navigation_view.push_by_tag("search")
		self.search_entry.select_region(0, -1)
		self.search_entry.grab_focus()

	def _on_search_changed(self, entry):
		if (search_text:=self.search_entry.get_text()):
			self._search_view.search(search_text)
		else:
			self._search_view.clear()

	def _on_search_stopped(self, widget):
		self._navigation_view.pop_to_tag("collection")

	def _on_artist_selected(self, widget, artist):
		self._navigation_split_view.set_show_content(True)
		self._album_navigation_view.replace_with_tags(["album_list"])
		self._albums_page.display(artist)

	def _on_album_selected(self, widget, album):
		album_page=AlbumPage(self._client, album)
		self._album_navigation_view.push(album_page)
		album_page.play_button.grab_focus()

	def _on_search_artist_selected(self, widget, artist):
		self._artist_list.select(artist)
		self.search_entry.emit("stop-search")
		self._albums_page.grid_view.grab_focus()

	def _show_album(self, album):
		self._artist_list.select(album.artist)
		album_page=AlbumPage(self._client, album)
		self._album_navigation_view.replace([self._albums_page, album_page])
		self.search_entry.emit("stop-search")
		album_page.play_button.grab_focus()

	def _on_disconnected(self, *args):
		self._album_navigation_view.pop_to_tag("album_list")
		self.set_visible_child_name("browser")
		self._navigation_split_view.set_show_content(False)
		self.search_entry.emit("stop-search")

	def _on_connected_or_updated_db(self, client, database_is_empty):
		self.search_entry.emit("stop-search")
		self.search_entry.set_text("")
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
		self._song=None

		# action group
		action_group=Gio.SimpleActionGroup()
		self._remove_action=Gio.SimpleAction.new("delete", None)
		self._remove_action.connect("activate", lambda *args: self._client.delete_song(self._song))
		action_group.add_action(self._remove_action)
		self._as_next_action=Gio.SimpleAction.new("as-next", None)
		self._as_next_action.connect("activate", lambda *args: self._client.move_as_next_song(self._song))
		action_group.add_action(self._as_next_action)
		self._show_album_action=Gio.SimpleAction.new("show-album", None)
		self._show_album_action.connect("activate", lambda *args: self._client.show_album(self._song))
		action_group.add_action(self._show_album_action)
		self._show_file_action=Gio.SimpleAction.new("show-file", None)
		self._show_file_action.connect("activate", lambda *args: self._client.show_file(self._song))
		action_group.add_action(self._show_file_action)
		self.insert_action_group("menu", action_group)

		# menu model
		menu=Gio.Menu()
		menu.append(_("_Remove"), "menu.delete")
		menu.append(_("As _Next"), "menu.as-next")
		show_section=Gio.Menu()
		show_section.append(_("Show Al_bum"), "menu.show-album")
		show_section.append(_("Show _File"), "menu.show-file")
		menu.append_section(None, show_section)
		mpd_section=Gio.Menu()
		mpd_section.append(_("_Enqueue Album"), "app.enqueue")
		mpd_section.append(_("_Tidy"), "app.tidy")
		mpd_section.append(_("_Clear"), "app.clear")
		menu.append_section(None, mpd_section)
		self.set_menu_model(menu)

	def open(self, song, songpos, x, y):
		self._song=song
		rect=Gdk.Rectangle()
		rect.x,rect.y=x,y
		self.set_pointing_to(rect)
		if song is None:
			self._remove_action.set_enabled(False)
			self._as_next_action.set_enabled(False)
			self._show_album_action.set_enabled(False)
			self._show_file_action.set_enabled(False)
		else:
			self._remove_action.set_enabled(True)
			self._as_next_action.set_enabled(songpos is not None and songpos != int(song["pos"]) != songpos+1)
			self._show_album_action.set_enabled(self._client.can_show_album(song))
			self._show_file_action.set_enabled(self._client.can_show_file(song))
		self.popup()

class SongRow(Gtk.Box):
	position=GObject.Property(type=int, default=-1)
	def __init__(self, show_track=True, **kwargs):
		# can_target=False is needed to use Gtk.Widget.pick() in Gtk.ListView
		super().__init__(can_target=False, **kwargs)

		# labels
		self._title=Gtk.Label(xalign=0, single_line_mode=True, ellipsize=Pango.EllipsizeMode.END)
		self._subtitle=Gtk.Label(xalign=0, single_line_mode=True, ellipsize=Pango.EllipsizeMode.END, css_classes=["dimmed", "caption"])
		self._length=Gtk.Label(xalign=1, single_line_mode=True, css_classes=["numeric", "dimmed"])

		# packing
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
		box.append(self._title)
		box.append(self._subtitle)
		self.append(box)
		self.append(self._length)

	def set_song(self, song):
		subtitle=str(song["artist"])
		self._title.set_text(song["title"][0])
		self._subtitle.set_visible(bool(subtitle))
		self._subtitle.set_text(subtitle)
		self._length.set_text(str(song["duration"]))

	def unset_song(self):
		self._title.set_text("")
		self._subtitle.set_text("")
		self._length.set_text("")

class PlaylistView(Gtk.ListView):
	def __init__(self, client):
		super().__init__(tab_behavior=Gtk.ListTabBehavior.ITEM)
		self._client=client
		self._playlist_version=None
		self._activate_on_release=False
		self._autoscroll=True
		self._highlighted_widget=None
		self.add_css_class("playlist")
		self.add_css_class("no-drop-highlight")

		# factory
		def setup(factory, item):
			item.set_child(SongRow())
		def bind(factory, item):
			row=item.get_child()
			song=item.get_item()
			row.set_song(song)
			row.set_property("position", item.get_position())
		def unbind(factory, item):
			row=item.get_child()
			song=item.get_item()
			row.unset_song()
			row.set_property("position", -1)
		factory=Gtk.SignalListItemFactory()
		factory.connect("setup", setup)
		factory.connect("bind", bind)
		factory.connect("unbind", unbind)
		self.set_factory(factory)

		# model
		self._selection_model=SelectionModel(Song)
		self.set_model(self._selection_model)

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
		long_press_controller=Gtk.GestureLongPress()
		self.add_controller(long_press_controller)
		drag_source=Gtk.DragSource()
		drag_source.set_icon(lookup_icon("audio-x-generic", 32, self.get_scale_factor()), 0, 0)
		drag_source.set_actions(Gdk.DragAction.MOVE)
		self.add_controller(drag_source)
		drop_target=Gtk.DropTarget()
		drop_target.set_actions(Gdk.DragAction.COPY|Gdk.DragAction.MOVE)
		drop_target.set_gtypes((int,Song,))
		self.add_controller(drop_target)
		drop_motion=Gtk.DropControllerMotion()
		self.add_controller(drop_motion)

		# connect
		self.connect("activate", self._on_activate)
		button_controller.connect("pressed", self._on_button_pressed)
		button_controller.connect("stopped", self._on_button_stopped)
		button_controller.connect("released", self._on_button_released)
		long_press_controller.connect("pressed", self._on_long_pressed)
		drag_source.connect("prepare", self._on_drag_prepare)
		drop_target.connect("drop", self._on_drop)
		drop_motion.connect("motion", self._on_drop_motion)
		drop_motion.connect("leave", self._on_drop_leave)
		self._client.connect("playlist", self._on_playlist_changed)
		self._client.connect("songid", self._on_songid_changed)
		self._client.connect("disconnected", self._on_disconnected)

	def _get_focus_row(self):
		return self.get_focus_child().get_first_child()

	def _get_position(self, x, y):
		item=self.pick(x,y,Gtk.PickFlags.DEFAULT)
		if item is self or item is None:
			return None
		return item.get_first_child().get_property("position")

	def _get_song(self, row):
		return self._selection_model.get_item(row.get_property("position"))

	def _clear(self, *args):
		self._menu.popdown()
		self._playlist_version=None
		self._selection_model.clear()

	def _refresh_selection(self, song):
		if song is None:
			self._selection_model.unselect()
		else:
			self._selection_model.select(int(song))

	def _on_button_pressed(self, controller, n_press, x, y):
		if (position:=self._get_position(x,y)) is None:
			if controller.get_current_button() == 3 and n_press == 1:
				self._menu.open(None, None, x, y)
		else:
			if controller.get_current_button() == 1 and n_press == 1:
				self._activate_on_release=True
			elif controller.get_current_button() == 2 and n_press == 1:
				self._client.delete_song(self._selection_model.get_item(position))
			elif controller.get_current_button() == 3 and n_press == 1:
				self._menu.open(self._selection_model.get_item(position), self._selection_model.get_selected(), x, y)

	def _on_button_stopped(self, controller):
		self._activate_on_release=False

	def _on_button_released(self, controller, n_press, x, y):
		if self._activate_on_release and (position:=self._get_position(x,y)) is not None:
			self._autoscroll=False
			self._client.play(position)
		self._activate_on_release=False

	def _on_long_pressed(self, controller, x, y):
		if (position:=self._get_position(x,y)) is None:
			self._menu.open(None, None, x, y)
		else:
			self._menu.open(self._selection_model.get_item(position), self._selection_model.get_selected(), x, y)

	def _on_activate(self, listview, pos):
		self._autoscroll=False
		self._client.play(pos)

	def _on_playlist_changed(self, client, version, length, songpos):
		self._menu.popdown()
		for song in self._client.get_playlist_changes(self._playlist_version):
			self._selection_model.set(int(song["pos"]), song)
		self._selection_model.clear(length)
		self._refresh_selection(songpos)
		if self._playlist_version is None and (selected:=self._selection_model.get_selected()) is not None:  # always scroll to song on startup
			self.scroll_to(selected, Gtk.ListScrollFlags.FOCUS, None)
		self._playlist_version=version

	def _on_songid_changed(self, client, song, cover, cover_path, songpos, songid, state):
		self._menu.popdown()
		self._refresh_selection(songpos)
		if self._autoscroll:
			if (selected:=self._selection_model.get_selected()) is not None and state == "play":
				idle_add(self.scroll_to, selected, Gtk.ListScrollFlags.FOCUS, None)
				adj=self.get_vadjustment()
				value=adj.get_upper()*selected/self._selection_model.get_n_items()-self.get_parent().get_height()*0.3
				if value >= adj.get_value():
					adj.set_value(value)
		else:
			self._autoscroll=True

	def _on_menu(self, action, state):
		row=self._get_focus_row()
		computed_point,point=row.compute_point(self, Graphene.Point.zero())
		if computed_point:
			self._menu.open(self._get_song(row), self._selection_model.get_selected(), point.x, point.y)
		else:
			self._menu.open(self._get_song(row), self._selection_model.get_selected(), 0, 0)

	def _on_delete(self, action, state):
		self._client.delete_song(self._get_song(self._get_focus_row()))

	def _on_drag_prepare(self, drag_source, x, y):
		if (position:=self._get_position(x,y)) is not None:
			return Gdk.ContentProvider.new_for_value(position)

	def _on_drop(self, drop_target, value, x, y):
		self._remove_highlight()
		item=self.pick(x,y,Gtk.PickFlags.DEFAULT)
		if isinstance(value, int):
			if item is self:
				position=self._selection_model.get_n_items()-1
			else:
				position=item.get_first_child().get_property("position")
			if value != position:
				self._client.move(value, position)
				return True
		elif isinstance(value, Song):
			if item is self:
				position=self._selection_model.get_n_items()
			else:
				position=item.get_first_child().get_property("position")
			self._client.add_song(value, position)
			return True
		return False

	def _remove_highlight(self):
		if self._highlighted_widget is not None:
			self._highlighted_widget.remove_css_class("drop-row")
		self._highlighted_widget=None

	def _on_drop_motion(self, drop_motion, x, y):
		self._remove_highlight()
		item=self.pick(x,y,Gtk.PickFlags.DEFAULT)
		if item is not self:
			item.add_css_class("drop-row")
			self._highlighted_widget=item

	def _on_drop_leave(self, drop_target):
		self._remove_highlight()

	def _on_disconnected(self, *args):
		self._clear()

class PlaylistWindow(Gtk.Stack):
	def __init__(self, client):
		super().__init__(vhomogeneous=False, vexpand=True)
		self._client=client

		# widgets
		playlist_view=PlaylistView(self._client)
		status_page=Adw.StatusPage(icon_name="view-playlist-symbolic", title=_("Playlist is Empty"))
		status_page.add_css_class("compact")
		status_page.add_css_class("no-drop-highlight")

		# event controller
		drop_target=Gtk.DropTarget()
		drop_target.set_actions(Gdk.DragAction.COPY)
		drop_target.set_gtypes((Song,))
		status_page.add_controller(drop_target)

		# connect
		drop_target.connect("drop", self._on_drop)
		self._client.connect("playlist", self._on_playlist_changed)
		self._client.connect("disconnected", self._on_disconnected)

		# packing
		self.add_named(Gtk.ScrolledWindow(child=playlist_view, propagate_natural_height=True), "playlist")
		self.add_named(status_page, "empty-playlist")

	def _on_drop(self, drop_target, value, x, y):
		if isinstance(value, Song):
			self._client.append_song(value)
			return True
		return False

	def _on_playlist_changed(self, client, version, length, songpos):
		if length:
			self.set_visible_child_name("playlist")
		else:
			self.set_visible_child_name("empty-playlist")

	def _on_disconnected(self, *args):
		self.set_visible_child_name("playlist")

##########
# lyrics #
##########

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
	song=GObject.Property(type=Song)
	def __init__(self):
		super().__init__(vhomogeneous=False, vexpand=True)

		# status pages
		no_lyrics_status_page=Adw.StatusPage(icon_name="view-lyrics-symbolic", title=_("No Lyrics"))
		no_lyrics_status_page.add_css_class("compact")
		connection_error_status_page=Adw.StatusPage(
			icon_name="network-wired-disconnected-symbolic", title=_("Connection Error"), description=_("Check your network connection"))
		connection_error_status_page.add_css_class("compact")
		searching_status_page=Adw.StatusPage(title=_("Searching…"))
		spinner=Adw.SpinnerPaintable(widget=searching_status_page)
		searching_status_page.set_paintable(spinner)

		# text view
		text_view=Gtk.TextView(
			editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD,
			justification=Gtk.Justification.CENTER,
			left_margin=12, right_margin=12, bottom_margin=9, top_margin=9,
			pixels_above_lines=1, pixels_below_lines=2, pixels_inside_wrap=3
		)
		text_view.add_css_class("inline")
		text_view.update_property([Gtk.AccessibleProperty.LABEL], [_("Lyrics view")])

		# text buffer
		self._text_buffer=text_view.get_buffer()

		# connect
		self.connect("notify::song", self._on_songid_changed)

		# packing
		self.add_named(Gtk.ScrolledWindow(child=text_view, propagate_natural_height=True), "lyrics")
		self.add_named(no_lyrics_status_page, "no-lyrics")
		self.add_named(connection_error_status_page, "connection-error")
		self.add_named(searching_status_page, "searching")

	def load(self):
		if self.get_visible_child_name() != "lyrics" and (song:=self.get_property("song")) is not None:
			self.set_visible_child_name("searching")
			threading.Thread(target=self._display_lyrics, args=(song["title"][0], str(song["artist"])), daemon=True).start()

	def _on_songid_changed(self, *args):
		self.set_visible_child_name("no-lyrics")
		self._text_buffer.delete(self._text_buffer.get_start_iter(), self._text_buffer.get_end_iter())

	def _get_lyrics(self, title, artist):
		title=urllib.parse.quote_plus(title)
		artist=urllib.parse.quote_plus(artist)
		parser=LetrasParser()
		with urllib.request.urlopen(f"https://www.letras.mus.br/winamp.php?musica={title}&artista={artist}") as response:
			parser.feed(response.read().decode("utf-8"))
		if text:=parser.text.strip("\n "):
			return text
		else:
			raise ValueError("Not found")

	def _display_lyrics(self, title, artist):
		try:
			idle_add(self._text_buffer.set_text, self._get_lyrics(title, artist))
			idle_add(self.set_visible_child_name, "lyrics")
		except urllib.error.URLError:
			idle_add(self.set_visible_child_name, "connection-error")
		except ValueError:
			idle_add(self.set_visible_child_name, "no-lyrics")

##########
# player #
##########

class PlayButton(Gtk.Button):
	def __init__(self, client):
		super().__init__(icon_name="media-playback-start-symbolic", action_name="app.toggle-play", tooltip_text=_("Play"))
		client.connect("state", self._on_state_changed)

	def _on_state_changed(self, client, state):
		if state == "play":
			self.set_property("icon-name", "media-playback-pause-symbolic")
			self.set_tooltip_text(_("Pause"))
		else:
			self.set_property("icon-name", "media-playback-start-symbolic")
			self.set_tooltip_text(_("Play"))

class MediaButtons(Gtk.Box):
	def __init__(self, client):
		super().__init__(spacing=6)
		self.append(Gtk.Button(icon_name="media-skip-backward-symbolic", tooltip_text=_("Previous"), action_name="app.previous"))
		self.append(PlayButton(client))
		self.append(Gtk.Button(icon_name="media-skip-forward-symbolic", tooltip_text=_("Next"), action_name="app.next"))

class BitRate(Gtk.Label):
	def __init__(self, client, settings):
		super().__init__(xalign=1, single_line_mode=True, css_classes=["caption", "numeric", "dimmed"])
		settings.bind("show-bit-rate", self, "visible", Gio.SettingsBindFlags.GET)
		self._mask=_("{bitrate} kb/s")

		# connect
		client.connect("bitrate", self._on_bitrate)
		client.connect("disconnected", self._on_disconnected)

	def _on_bitrate(self, client, bitrate):
		# handle unknown bitrates: https://github.com/MusicPlayerDaemon/MPD/issues/428#issuecomment-442430365
		if bitrate is None:
			self.set_text("")
		else:
			self.set_text(self._mask.format(bitrate=bitrate))

	def _on_disconnected(self, *args):
		self.set_text("")

class PlaylistProgress(Gtk.Label):
	def __init__(self, client):
		super().__init__(xalign=0, single_line_mode=True, css_classes=["caption", "dimmed"])
		self._length=0

		# connect
		client.connect("songid", self._on_songid_changed)
		client.connect("playlist", self._on_playlist_changed)
		client.connect("disconnected", self._on_disconnected)

	def _clear(self):
		self._length=0
		self.set_text("")

	def _refresh(self, song):
		if song is None:
			self.set_text("")
		else:
			self.set_text(f"{int(song)+1}/{self._length}")

	def _on_songid_changed(self, client, song, cover, cover_path, songpos, songid, state):
		self._refresh(songpos)

	def _on_playlist_changed(self, client, version, length, songpos):
		self._length=length
		self._refresh(songpos)

	def _on_disconnected(self, *args):
		self._clear()

class PlaybackControls(Gtk.Box):
	def __init__(self, client, settings):
		super().__init__(hexpand=True, orientation=Gtk.Orientation.VERTICAL)
		self._client=client
		self._seeking=False

		# labels
		self._elapsed=Gtk.Label(xalign=0, single_line_mode=True, valign=Gtk.Align.START, css_classes=["numeric"])
		self._rest=Gtk.Label(xalign=1, single_line_mode=True, valign=Gtk.Align.START, css_classes=["numeric"])

		# progress bar
		self._scale=Gtk.Scale(restrict_to_fill_level=False, fill_level=0, visible=False)
		self._scale.set_increments(10, 10)
		self._scale.update_property([Gtk.AccessibleProperty.LABEL], [_("Progress bar")])
		self._adjustment=self._scale.get_adjustment()

		# event controllers
		key_controller=Gtk.EventControllerKey()
		self._scale.add_controller(key_controller)

		# connect
		self._scale.connect("change-value", self._on_change_value)
		self._scale.connect("value-changed", self._on_value_changed)
		self._scale.connect("notify::css-classes", self._on_css_classes)
		self._adjustment.connect("notify::upper", self._on_upper)
		key_controller.connect("key-pressed", self._on_key_pressed)
		self._client.connect("disconnected", self._on_disconnected)
		self._client.connect("state", self._on_state_changed)
		self._elapsed_handler=self._client.connect("elapsed", self._on_elapsed)
		self._client.connect("songid", self._on_songid_changed)

		# packing
		start_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.START)
		start_box.add_css_class("toolbar-text")
		start_box.append(self._elapsed)
		start_box.append(PlaylistProgress(client))
		end_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.START)
		end_box.add_css_class("toolbar-text")
		end_box.append(self._rest)
		end_box.append(BitRate(client, settings))
		center_box=Gtk.CenterBox(margin_start=6, margin_end=6)
		center_box.add_css_class("toolbar")
		center_box.set_center_widget(MediaButtons(client))
		center_box.set_start_widget(start_box)
		center_box.set_end_widget(end_box)
		self.append(self._scale)
		self.append(center_box)

	def _on_css_classes(self, *args):
		if not (seeking:=self._scale.has_css_class("dragging")) and self._seeking:
			pos=self._adjustment.get_value()
			try:
				self._client.seekcur(pos)
			except:
				pass
		self._seeking=seeking

	def _on_key_pressed(self, controller, keyval, keycode, state):
		if keyval == Gdk.KEY_Escape and self._seeking:
			self._seeking=False
			self._adjustment.set_value(self._scale.get_fill_level())

	def _on_elapsed(self, client, elapsed, duration):
		if duration > 0:
			elapsed=min(elapsed, duration)  # fix display error
			if not self._seeking:
				self._adjustment.set_upper(duration)
				self._adjustment.set_value(elapsed)
			self._scale.set_fill_level(elapsed)
		else:
			self._scale.set_range(0, 0)

	def _on_value_changed(self, scale):
		if (duration:=self._adjustment.get_upper()) > 0:
			self._scale.set_visible(True)
			elapsed=self._adjustment.get_value()
			self._elapsed.set_text(str(Duration(elapsed)))
			self._rest.set_text(str(Duration(duration-elapsed)))

	def _on_change_value(self, scale, scroll, value):  # value is inaccurate (can be above upper limit)
		if scroll == Gtk.ScrollType.JUMP:
			return False
		duration=self._adjustment.get_upper()
		pos=max(min(value, duration), 0)
		try:
			self._client.seekcur(pos)
		except:
			pass
		return True

	def _on_upper(self, *args):
		if self._adjustment.get_upper() == 0:
			self._scale.set_visible(False)
			self._scale.set_fill_level(0)
			self._elapsed.set_text("")
			self._rest.set_text("")

	def _on_state_changed(self, client, state):
		if state == "stop":
			self._scale.set_range(0, 0)

	def _on_songid_changed(self, *args):
		if self._seeking:
			self._seeking=False
			self._scale.set_sensitive(False)
			self._scale.set_sensitive(True)

	def _on_disconnected(self, *args):
		self._scale.set_range(0, 0)

class VolumeControl(Gtk.Box):
	def __init__(self, client):
		super().__init__(orientation=Gtk.Orientation.HORIZONTAL, margin_start=12)
		self._client=client

		# adjustment
		scale=Gtk.Scale(hexpand=True)
		scale.update_property([Gtk.AccessibleProperty.LABEL], [_("Volume control")])
		self._adjustment=scale.get_adjustment()
		self._adjustment.configure(0, 0, 100, 5, 5, 0)

		# event controllers
		key_controller=Gtk.EventControllerKey()
		scale.add_controller(key_controller)

		# connect
		scale.connect("change-value", self._on_change_value)
		key_controller.connect("key-pressed", self._on_key_pressed)
		self._client.connect("volume", self._refresh)

		# packing
		self.append(Gtk.Image(icon_name="audio-speakers-symbolic", accessible_role=Gtk.AccessibleRole.PRESENTATION))
		self.append(scale)

	def _on_change_value(self, scale, scroll, value):
		self._client.setvol(int(max(min(value, 100), 0)))

	def _refresh(self, client, volume):
		self._adjustment.set_value(max(volume, 0))

	def _on_key_pressed(self, controller, keyval, keycode, state):
		root=controller.get_widget().get_root()
		if keyval == Gdk.KEY_Up:
			root.child_focus(Gtk.DirectionType.TAB_BACKWARD)
			return True
		elif keyval == Gdk.KEY_Down:
			root.child_focus(Gtk.DirectionType.TAB_FORWARD)
			return True

class PlayerMenu(Gtk.PopoverMenu):
	def __init__(self, client):
		super().__init__()
		self._volume_visible=False

		# volume
		self._volume_control=VolumeControl(client)
		self._volume_item=Gio.MenuItem()
		self._volume_item.set_attribute_value("custom", GLib.Variant("s", "volume"))

		# menu model
		self._menu=Gio.Menu()
		playback=Gio.Menu()
		playback.append(_("_Continuous"), "app.single::0")
		playback.append(_("_Single Songs"), "app.single::1")
		playback.append(_("_Pause Next Song"), "app.single::oneshot")
		playback.append(_("_Repeat"), "app.repeat")
		self._menu.append_section(_("Playback"), playback)
		playlist=Gio.Menu()
		playlist.append(_("_Keep Songs"), "app.consume::0")
		playlist.append(_("Consu_me Songs"), "app.consume::1")
		playlist.append(_("Rem_ove Current Song"), "app.consume::oneshot")
		playlist.append(_("S_huffle"), "app.random")
		self._menu.append_section(_("Playlist"), playlist)
		self.set_menu_model(self._menu)

		# connect
		client.connect("volume", self._on_volume_changed)
		client.connect("disconnected", self._on_disconnected)

	def _on_volume_changed(self, client, volume):
		if volume < 0 and self._volume_visible:
			self._menu.remove(0)
			self._volume_visible=False
		elif volume >= 0 and not self._volume_visible:
			self._menu.prepend_item(self._volume_item)
			self.add_child(self._volume_control, "volume")
			self._volume_visible=True

	def _on_disconnected(self, *args):
		if self._volume_visible:
			self._menu.remove(0)
			self._volume_visible=False

class Player(Adw.Bin):
	def __init__(self, client, settings):
		super().__init__(width_request=300, height_request=200)

		# widgets
		self._cover=Gtk.Picture(css_classes=["cover"], accessible_role=Gtk.AccessibleRole.PRESENTATION,
			halign=Gtk.Align.CENTER, margin_start=12, margin_end=12, margin_bottom=6, visible=False)
		self._lyrics_window=LyricsWindow()
		playlist_window=PlaylistWindow(client)
		self._playback_controls=PlaybackControls(client, settings)
		self._playback_controls.set_visible(False)

		# box
		box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		box.append(Gtk.WindowHandle(child=self._cover))
		box.append(playlist_window)

		# stack
		self._stack=Adw.ViewStack(vhomogeneous=False, enable_transitions=True)
		self._stack.add_titled_with_icon(box, "playlist", _("Playlist"), "view-playlist-symbolic")
		self._stack.add_titled_with_icon(self._lyrics_window, "lyrics", _("Lyrics"), "view-lyrics-symbolic")

		# playlist page
		self._playlist_page=self._stack.get_page(box)

		# view switcher
		view_switcher=Adw.InlineViewSwitcher(stack=self._stack, display_mode=Adw.InlineViewSwitcherDisplayMode.ICONS)
		view_switcher.add_css_class("flat")

		# header bar
		header_bar=Adw.HeaderBar(show_title=False)
		header_bar.pack_start(view_switcher)
		header_bar.pack_end(Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text=_("Player Menu"), popover=PlayerMenu(client)))

		# connect
		self._stack.connect("notify::visible-child-name", self._on_visible_child_name)
		client.connect("songid", self._on_songid_changed)
		client.connect("playlist", self._on_playlist_changed)
		client.connect("disconnected", self._on_disconnected)
		client.connect("connected", self._on_connected)

		# packing
		toolbar_view=Adw.ToolbarView()
		toolbar_view.add_top_bar(header_bar)
		toolbar_view.set_content(self._stack)
		toolbar_view.add_bottom_bar(self._playback_controls)
		self.set_child(toolbar_view)

	def _on_visible_child_name(self, *args):
		if self._stack.get_visible_child_name() == "lyrics":
			self._lyrics_window.load()
		elif self._stack.get_visible_child_name() == "playlist":
			self._playlist_page.set_needs_attention(False)

	def _on_songid_changed(self, client, song, cover, cover_path, songpos, songid, state):
		if song:
			self._cover.set_paintable(cover)
			self._cover.set_visible(True)
			self._lyrics_window.set_property("song", song)
			if self._stack.get_visible_child_name() == "lyrics":
				self._lyrics_window.load()
		else:
			self._cover.set_visible(False)
			self._cover.set_paintable(FALLBACK_COVER)
			self._lyrics_window.set_property("song", None)

	def _on_playlist_changed(self, client, version, length, songpos):
		self._playback_controls.set_visible(length > 0)
		if self._stack.get_visible_child_name() != "playlist":
			self._playlist_page.set_needs_attention(True)

	def _on_disconnected(self, *args):
		self._cover.set_paintable(FALLBACK_COVER)
		self._cover.set_visible(False)
		self._lyrics_window.set_property("song", None)
		self._stack.set_visible_child_name("playlist")

	def _on_connected(self, *args):
		self._stack.set_visible_child_name("playlist")

##############
# player bar #
##############

class ProgressBar(Gtk.ProgressBar):
	def __init__(self, client):
		super().__init__(valign=Gtk.Align.START, halign=Gtk.Align.FILL)
		self.add_css_class("osd")
		client.connect("state", self._on_state_changed)
		client.connect("elapsed", self._on_elapsed)

	def _on_state_changed(self, client, state):
		if state == "stop":
			self.set_visible(False)
			self.set_fraction(0.0)

	def _on_elapsed(self, client, elapsed, duration):
		if duration > 0:
			self.set_visible(True)
			self.set_fraction(elapsed/duration)
		else:
			self.set_visible(False)
			self.set_fraction(0.0)

class PlayerBar(Gtk.Overlay):
	def __init__(self, client):
		super().__init__()

		# widgets
		self._cover=Gtk.Picture(css_classes=["cover"], accessible_role=Gtk.AccessibleRole.PRESENTATION, visible=False)
		progress_bar=ProgressBar(client)
		progress_bar.update_property([Gtk.AccessibleProperty.LABEL], [_("Progress bar")])
		self._title=Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
		self._subtitle=Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, css_classes=["dimmed", "caption"])

		# connect
		client.connect("songid", self._on_songid_changed)
		client.connect("disconnected", self._on_disconnected)

		# packing
		title_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
		title_box.add_css_class("toolbar-text")
		title_box.append(self._title)
		title_box.append(self._subtitle)
		box=Gtk.Box()
		box.add_css_class("toolbar")
		box.append(Adw.Clamp(orientation=Gtk.Orientation.VERTICAL, unit=Adw.LengthUnit.PX, maximum_size=34, child=self._cover))
		box.append(title_box)
		box.append(MediaButtons(client))
		self.add_overlay(progress_bar)
		self.set_child(box)

	def _clear(self):
		self._title.set_text("")
		self._subtitle.set_text("")
		self._cover.set_paintable(FALLBACK_COVER)
		self._cover.set_visible(False)

	def _on_songid_changed(self, client, song, cover, cover_path, songpos, songid, state):
		if song:
			self._cover.set_paintable(cover)
			self._cover.set_visible(True)
			self._title.set_text(song["title"][0])
			self._subtitle.set_text(str(song["artist"]))
		else:
			self._clear()

	def _on_disconnected(self, *args):
		self._clear()

###############
# main window #
###############

class MainWindow(Adw.ApplicationWindow):
	def __init__(self, client, settings, **kwargs):
		super().__init__(title="Plattenalbum", height_request=294, width_request=360, **kwargs)
		self._client=client
		self._settings=settings
		self._suspend_inhibit=0

		# MPRIS
		MPRISInterface(self, self._client, self._settings)

		# widgets
		self._browser=Browser(self._client, self._settings)
		player=Player(self._client, self._settings)

		# actions
		for name in ("close", "search", "preferences", "manual-connect", "server-info"):
			action=Gio.SimpleAction.new(name, None)
			action.connect("activate", getattr(self, ("_on_"+name.replace("-","_"))))
			self.add_action(action)

		# sidebar layout
		overlay_split_view=Adw.OverlaySplitView(
			sidebar_position=Gtk.PackType.END, min_sidebar_width=300, max_sidebar_width=500, sidebar_width_fraction=0.30)
		overlay_split_view.set_content(Adw.LayoutSlot(id="browser"))
		overlay_split_view.set_sidebar(Adw.LayoutSlot(id="player"))
		sidebar_layout=Adw.Layout(content=overlay_split_view, name="sidebar")

		# bottom sheet layout
		content_bin=Adw.Bin(child=Adw.LayoutSlot(id="browser"))
		self._bottom_sheet=Adw.BottomSheet(content=content_bin, sheet=Adw.LayoutSlot(id="player"), bottom_bar=PlayerBar(client))
		self._bottom_sheet.bind_property("bottom-bar-height", content_bin, "margin-bottom", GObject.BindingFlags.DEFAULT)
		bottom_sheet_layout=Adw.Layout(content=self._bottom_sheet, name="bottom-sheet")

		# multi layout view
		multi_layout_view=Adw.MultiLayoutView()
		multi_layout_view.add_layout(sidebar_layout)
		multi_layout_view.add_layout(bottom_sheet_layout)
		multi_layout_view.set_child("browser", self._browser)
		multi_layout_view.set_child("player", player)
		multi_layout_view.set_layout_name("sidebar")

		# breakpoint
		break_point=Adw.Breakpoint()
		break_point.set_condition(Adw.BreakpointCondition.parse(f"max-width: 620sp"))
		break_point.add_setter(multi_layout_view, "layout-name", "bottom-sheet")
		self.add_breakpoint(break_point)

		# status page
		status_page=Adw.StatusPage(icon_name="de.wagnermartin.Plattenalbum", title=_("Connect to Your Music"))
		status_page.set_description(_("To use Plattenalbum, an instance of the Music Player Daemon "\
			"needs to be set up and running on this device or another one on the network"))
		connect_button=Gtk.Button(label=_("_Connect"), use_underline=True, action_name="app.connect", action_target=GLib.Variant("b", False))
		connect_button.set_css_classes(["suggested-action", "pill"])
		manual_connect_button=Gtk.Button(label=_("Connect _Manually"), use_underline=True, action_name="win.manual-connect")
		manual_connect_button.add_css_class("pill")
		button_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, spacing=12)
		button_box.append(connect_button)
		button_box.append(manual_connect_button)
		status_page.set_child(button_box)
		menu=Gio.Menu()
		menu.append(_("_Preferences"), "win.preferences")
		menu.append(_("_Keyboard Shortcuts"), "app.shortcuts")
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
		self._browser.search_entry.add_controller(controller_focus)

		# connect
		multi_layout_view.connect("notify::layout-name", self._on_layout_name)
		controller_focus.connect("enter", self._on_search_entry_focus_event, True)
		controller_focus.connect("leave", self._on_search_entry_focus_event, False)
		self._settings.connect_after("notify::cursor-watch", self._on_cursor_watch)
		self._client.connect("songid", self._on_songid_or_metadata_changed)
		self._client.connect("metadata", self._on_songid_or_metadata_changed)
		self._client.connect("state", self._on_state_changed)
		self._client.connect("connected", self._on_connected)
		self._client.connect("disconnected", self._on_disconnected)
		self._client.connect("server-error", self._on_server_error)
		self._client.connect("updating-db", self._on_updating_db)
		self._client.connect("updated-db", self._on_updated_db)
		self._client.connect("show-album", lambda *args: self._bottom_sheet.set_open(False))

		# packing
		self._toast_overlay=Adw.ToastOverlay(child=self._status_page_stack)
		self.set_content(self._toast_overlay)

	def open(self):
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
		self._client.open_connection(self._settings.get_boolean("manual-connection"))

	def _clear_title(self):
		self.set_title("Plattenalbum")

	def _update_title(self, song):
		if song:
			self.set_title(song["title"][0])
		else:
			self._clear_title()

	def _on_close(self, action, param):
		if (dialog:=self.get_visible_dialog()) is None:
			self.close()
		else:
			dialog.close()

	def _on_search(self, action, param):
		self._browser.search()

	def _on_preferences(self, action, param):
		if self.get_visible_dialog() is None:
			PreferencesDialog(self._settings).present(self)

	def _on_manual_connect(self, action, param):
		if self.get_visible_dialog() is None:
			ConnectDialog(self._settings).present(self)

	def _on_server_info(self, action, param):
		if self.get_visible_dialog() is None:
			ServerInfo(self._client).present(self)

	def _on_search_entry_focus_event(self, controller, focus):
		if focus:
			self.get_application().set_accels_for_action("app.toggle-play", [])
		else:
			self.get_application().set_accels_for_action("app.toggle-play", ["space"])

	def _on_songid_or_metadata_changed(self, client, song, *args):
		self._update_title(song)

	def _on_state_changed(self, client, state):
		if state == "play":
			self._suspend_inhibit=self.get_application().inhibit(self, Gtk.ApplicationInhibitFlags.SUSPEND, _("Playing music"))
		elif self._suspend_inhibit:
			self.get_application().uninhibit(self._suspend_inhibit)
			self._suspend_inhibit=0

	def _on_connected(self, *args):
		self._toast_overlay.dismiss_all()
		if (dialog:=self.get_visible_dialog()) is not None:
			dialog.close()
		self.lookup_action("server-info").set_enabled(True)
		self._status_page_stack.set_visible_child_name("content")

	def _on_disconnected(self, *args):
		if self._status_page_stack.get_visible_child_name() == "status-page":  # already disconnected
			if (dialog:=self.get_visible_dialog()) is None:
				SetupDialog().present(self)
			elif isinstance(dialog, ConnectDialog):
				dialog.connection_failed()
		else:
			self._clear_title()
			self.lookup_action("server-info").set_enabled(False)
			self._toast_overlay.dismiss_all()
			if isinstance(dialog:=self.get_visible_dialog(), ServerInfo):
				dialog.close()
			if self._suspend_inhibit:
				self.get_application().uninhibit(self._suspend_inhibit)
				self._suspend_inhibit=0
			self._status_page_stack.set_visible_child_name("status-page")

	def _on_server_error(self, client, message):
		if (dialog:=self.get_visible_dialog()) is not None:
			dialog.close()
		self._toast_overlay.dismiss_all()
		self._toast_overlay.add_toast(Adw.Toast(title=message))

	def _on_updating_db(self, *args):
		self._toast_overlay.add_toast(Adw.Toast(title=_("Database is being updated"), timeout=0))

	def _on_updated_db(self, *args):
		self._toast_overlay.dismiss_all()
		if isinstance(dialog:=self.get_visible_dialog(), ServerInfo):
			dialog.close()
		self._toast_overlay.add_toast(Adw.Toast(title=_("Database updated")))

	def _on_cursor_watch(self, obj, typestring):
		if obj.get_property("cursor-watch"):
			self.set_cursor_from_name("progress")
		else:
			self.set_cursor_from_name(None)

	def _on_layout_name(self, obj, *args):
		if obj.get_layout_name() == "bottom-sheet":
			self._bottom_sheet.set_open(False)

###############
# application #
###############

class Plattenalbum(Adw.Application):
	def __init__(self):
		super().__init__(application_id="de.wagnermartin.Plattenalbum")
		self._settings=Settings()
		self._client=Client(self._settings)
		self._window=None

		# actions
		action=Gio.SimpleAction.new("about", None)
		action.connect("activate", self._on_about)
		self.add_action(action)
		action=Gio.SimpleAction.new("quit", None)
		action.connect("activate", self._on_quit)
		self.add_action(action)

		# mpd actions
		self._disable_on_stop_data=("next","previous","seek-forward","seek-backward")
		self._disable_no_song_data=("tidy","enqueue")
		self._enable_disable_on_playlist_data=("toggle-play","clear")
		self._enable_on_reconnect_data=("stop","update","disconnect")
		self._data=self._disable_on_stop_data+self._disable_no_song_data+self._enable_on_reconnect_data+self._enable_disable_on_playlist_data
		for name in self._data:
			action=Gio.SimpleAction.new(name, None)
			action.connect("activate", getattr(self, ("_on_"+name.replace("-","_"))))
			self.add_action(action)
		bool_mode_data=("repeat","random")
		self._enable_on_reconnect_data+=bool_mode_data
		self._data+=bool_mode_data
		for name in bool_mode_data:
			action=Gio.SimpleAction.new_stateful(name, None, GLib.Variant("b", False))
			action.connect("change-state", self._on_bool_mode_change, name)
			self.add_action(action)
			self._client.connect(name, self._update_bool_action, action)
		mode_data=("single","consume")
		self._enable_on_reconnect_data+=mode_data
		self._data+=mode_data
		for name in mode_data:
			action=Gio.SimpleAction.new_stateful(name, GLib.VariantType("s"), GLib.Variant("s", "0"))
			action.connect("change-state", self._on_mode_change, name)
			self.add_action(action)
			self._client.connect(name, self._update_action, action)
		self._connect_action=Gio.SimpleAction.new("connect", GLib.VariantType.new("b"))
		self._connect_action.connect("activate", self._on_connect)
		self.add_action(self._connect_action)

		# accelerators
		action_accels=(
			("app.quit", ["<Ctrl>q"]),("win.close", ["<Ctrl>w"]),("win.preferences", ["<Ctrl>comma"]),("win.search", ["<Ctrl>f"]),
			("win.server-info", ["<Ctrl>i"]),("app.disconnect", ["<Ctrl>d"]),("app.update", ["F5"]),("app.clear", ["<Shift>Delete"]),
			("app.toggle-play", ["space"]),("app.stop", ["<Ctrl>space"]),("app.next", ["<Ctrl>k"]),("app.previous", ["<Shift><Ctrl>k"]),
			("app.repeat", ["<Ctrl>r"]),("app.random", ["<Ctrl>h"]),("app.single::1", ["<Ctrl>s"]),("app.single::0", ["<Shift><Ctrl>s"]),
			("app.single::oneshot", ["<Ctrl>p"]),("app.consume::1", ["<Ctrl>m"]),("app.consume::0", ["<Shift><Ctrl>m"]),
			("app.consume::oneshot", ["<Ctrl>o"]),("app.seek-forward", ["<Ctrl>plus"]),("app.seek-backward", ["<Ctrl>minus"]),
			("app.enqueue", ["<Ctrl>e"]),("app.tidy", ["<Ctrl>t"]),("menu.delete", ["Delete"])
		)
		for action, accels in action_accels:
			self.set_accels_for_action(action, accels)

		# connect
		self._client.connect("state", self._on_state_changed)
		self._client.connect("songid", self._on_songid_changed)
		self._client.connect("playlist", self._on_playlist_changed)
		self._client.connect("disconnected", self._on_disconnected)
		self._client.connect("connected", self._on_connected)

	def do_activate(self):
		if self._window is None:
			self._window=MainWindow(self._client, self._settings, application=self)
			self._window.connect("close-request", self._on_quit)
			self._window.open()
		else:
			self._window.present()

	def do_shutdown(self):
		Adw.Application.do_shutdown(self)
		if self._settings.get_boolean("stop-on-quit") and self._client.connected():
			self._client.stop()
		self.withdraw_notification("title-change")

	def _on_about(self, *args):
		dialog=Adw.AboutDialog.new_from_appdata("/de/wagnermartin/Plattenalbum/de.wagnermartin.Plattenalbum.metainfo.xml")
		dialog.set_copyright("© 2020-2026 Martin Wagner")
		dialog.set_developers(["Martin Wagner <martin.wagner.dev@gmail.com>"])
		dialog.set_translator_credits(_("translator-credits"))
		dialog.present(self._window)

	def _on_quit(self, *args): self.quit()
	def _on_toggle_play(self, action, param): self._client.toggle_play()
	def _on_stop(self, action, param): self._client.stop()
	def _on_next(self, action, param): self._client.next()
	def _on_previous(self, action, param): self._client.previous()
	def _on_seek_forward(self, action, param): self._client.seekcur("+10")
	def _on_seek_backward(self, action, param): self._client.seekcur("-10")
	def _on_tidy(self, action, param): self._client.tidy_playlist()
	def _on_enqueue(self, action, param): self._client.enqueue()
	def _on_clear(self, action, param): self._client.clear()
	def _on_update(self, action, param): self._client.update()

	def _update_bool_action(self, client, value, action): action.set_state(GLib.Variant("b", value))
	def _update_action(self, client, value, action): action.set_state(GLib.Variant("s", value))
	def _on_bool_mode_change(self, action, value, name): getattr(self._client, name)("1" if value.unpack() else "0")
	def _on_mode_change(self, action, value, name): getattr(self._client, name)(value.unpack())

	def _on_disconnect(self, action, param):
		self._client.close_connection()

	def _on_connect(self, action, param):
		self._client.open_connection(param.get_boolean())

	def _on_state_changed(self, client, state):
		for action in self._disable_on_stop_data:
			self.lookup_action(action).set_enabled(state != "stop")

	def _on_songid_changed(self, client, song, cover, cover_path, songpos, songid, state):
		for action in self._disable_no_song_data:
			self.lookup_action(action).set_enabled(songpos is not None)
		if song:
			if self._settings.get_boolean("send-notify") and not self._window.is_active() and state == "play":
				notify=Gio.Notification()
				notify.set_title(_("Next Title is Playing"))
				if cover is not FALLBACK_COVER:
					notify.set_icon(cover)
				if artist:=song["artist"]:
					body=_("Now playing “{title}” by “{artist}”").format(title=song["title"][0], artist=str(artist))
				else:
					body=_("Now playing “{title}”").format(title=song["title"][0])
				notify.set_body(body)
				notify.add_button(_("Skip"), "app.next")
				self.send_notification("title-change", notify)
			else:
				self.withdraw_notification("title-change")
		else:
			if self._settings.get_boolean("send-notify") and not self._window.is_active():
				notify=Gio.Notification()
				notify.set_title(_("Playback Finished"))
				notify.set_body(_("The playlist is over"))
				self.send_notification("title-change", notify)
			else:
				self.withdraw_notification("title-change")

	def _on_playlist_changed(self, client, version, length, songpos):
		for action in self._enable_disable_on_playlist_data:
			self.lookup_action(action).set_enabled(length > 0)

	def _on_disconnected(self, *args):
		self._connect_action.set_enabled(True)
		for action in self._data:
			self.lookup_action(action).set_enabled(False)

	def _on_connected(self, *args):
		self._connect_action.set_enabled(False)
		for action in self._enable_on_reconnect_data:
			self.lookup_action(action).set_enabled(True)

if __name__ == "__main__":
	Plattenalbum().run(sys.argv)
