import re
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib
from mpd import MPDClient, CommandError, ConnectionError
from .event_emitter import EventEmitter
from .cover import FallbackCover, FileCover, BinaryCover
from .song import Song

class Client(MPDClient):
	def __init__(self, settings):
		super().__init__()
		self.add_command("config", MPDClient._parse_object)  # Work around https://github.com/Mic92/python-mpd2/issues/244
		self._settings=settings
		self.emitter=EventEmitter()
		self._last_status={}
		self._main_timeout_id=None
		self._start_idle_id=None
		self._music_directory=None
		self.current_cover=FallbackCover()
		self._first_mark=None
		self._second_mark=None
		self._cover_regex=re.compile(r"^\.?(album|cover|folder|front).*\.(gif|jpeg|jpg|png)$", flags=re.IGNORECASE)
		self._socket_path=GLib.build_filenamev([GLib.get_user_runtime_dir(), "mpd", "socket"])
		self._bus=Gio.bus_get_sync(Gio.BusType.SESSION, None)  # used for "show in file manager"
		self.server=""

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

	def try_connect(self, manual):
		self.emitter.emit("connecting")
		def callback():
			# connect
			if manual:
				try:
					self.connect(self._settings.get_string("host"), self._settings.get_int("port"))
					self.server=f'{self._settings.get_string("host")}:{self._settings.get_int("port")}'
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
			else:
				host=GLib.getenv("MPD_HOST")
				port=GLib.getenv("MPD_PORT")
				if host is not None or port is not None:
					if host is None:
						host="localhost"
					if port is None:
						port=6600
					try:
						self.connect(host, port)
						self.server=f"{host}:{port}"
					except:
						pass
				if not self.connected():
					try:
						self.connect(self._socket_path, None)
						self.server=self._socket_path
					except:
						try:
							self.connect("/run/mpd/socket", None)
							self.server="/run/mpd/socket"
						except:
							self.emitter.emit("connection_error")
							self._start_idle_id=None
							return False
			# connected
			commands=self.commands()
			try:
				self._music_directory=self.config()["music_directory"]
			except:
				self._music_directory=None
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
			self._settings.set_boolean("manual-connection", manual)
			self._start_idle_id=None
			return False
		self._start_idle_id=GLib.idle_add(callback)

	def disconnect(self):
		super().disconnect()
		self._last_status={}
		self._music_directory=None
		self.server=""
		self.current_cover=FallbackCover()
		self.emitter.emit("disconnected")

	def connected(self):
		try:
			self.ping()
			return True
		except:
			return False

	def tidy_playlist(self):
		status=self.status()
		if (songid:=status.get("songid")) is None:
			self.clear()
		else:
			self.moveid(songid, 0)
			if int(status["playlistlength"]) > 1:
				self.delete((1,))

	def file_to_playlist(self, file, mode):  # modes: play, append, as-next
		if mode == "append":
			self.add(file)
		elif mode == "play":
			self.clear()
			self.add(file)
			self.play()
		elif mode == "as-next":
			try:
				self.add(file, "+0")
			except CommandError:
				self.add(file, "0")
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
			song_dir=GLib.build_filenamev([self._music_directory, GLib.path_get_dirname(uri)])
			if uri.lower().endswith(".cue"):
				song_dir=GLib.path_get_dirname(song_dir)  # get actual directory of .cue file
			if GLib.file_test(song_dir, GLib.FileTest.IS_DIR):
				directory=GLib.Dir.open(song_dir, 0)
				while (f:=directory.read_name()) is not None:
					if self._cover_regex.match(f):
						return GLib.build_filenamev([song_dir, f])
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
			return FallbackCover()

	def get_absolute_path(self, uri):
		stripped_uri=re.sub(r"(.*\.cue)\/track\d+$", r"\1", uri, flags=re.IGNORECASE)
		if GLib.file_test(stripped_uri, GLib.FileTest.IS_REGULAR):
			return stripped_uri
		elif self._music_directory is not None:
			absolute_path=GLib.build_filenamev([self._music_directory, stripped_uri])
			if GLib.file_test(absolute_path, GLib.FileTest.IS_REGULAR):
				return absolute_path
		return None

	def can_show_file(self, uri):
		has_owner,=self._bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
			GLib.Variant("(s)",("org.freedesktop.portal.Desktop",)), GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE, -1, None)
		activatable,=self._bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListActivatableNames",
			None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE, -1, None)
		return (has_owner or "org.freedesktop.portal.Desktop" in activatable) and self.get_absolute_path(uri) is not None

	def show_file(self, uri):
		with open(self.get_absolute_path(uri)) as f:
			fd_list=Gio.UnixFDList()
			self._bus.call_with_unix_fd_list_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
				"org.freedesktop.portal.OpenURI", "OpenDirectory", GLib.Variant("(sha{sv})", ("", fd_list.append(f.fileno()), {})),
				None, Gio.DBusCallFlags.NONE, -1, fd_list)

	def can_show_album(self, uri):
		self.tagtypes("clear")
		songs=self.find("file", uri)
		self.tagtypes("all")
		return bool(songs)

	def show_album(self, uri):
		self.restrict_tagtypes("album", "albumartist", "artist", "date")
		song=self.lsinfo(uri)[0]
		self.tagtypes("all")
		self.emitter.emit("show-album", song["album"][0], song["albumartist"][0], song["date"][0])

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

	def get_search_expression(self, tags, keywords):
		return "("+(" AND ".join("(!("+(" AND ".join(f"({tag} !contains_ci '{keyword}')" for tag in tags))+"))" for keyword in keywords))+")"

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
				song=self.currentsong()
				self.current_cover=self.get_cover(song["file"])
				self.emitter.emit("current-song", song, status["song"], status["songid"], status["state"])
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
					self.current_cover=FallbackCover()
					self.emitter.emit("current-song", Song({}), None, None, status["state"])
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
