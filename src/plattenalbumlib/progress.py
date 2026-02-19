import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


class PlaylistProgress(Gtk.Label):
    def __init__(self, client):
        super().__init__(xalign=0, single_line_mode=True, css_classes=["caption", "dimmed"])
        self._client=client
        self._length=0

        # connect
        self._client.emitter.connect("current-song", self._on_song_changed)
        self._client.emitter.connect("playlist", self._on_playlist_changed)
        self._client.emitter.connect("disconnected", self._on_disconnected)

    def _clear(self):
        self._length=0
        self.set_text("")

    def _refresh(self, song):
        if song is None:
            self.set_text("")
        else:
            self.set_text(f"{int(song)+1}/{self._length}")

    def _on_song_changed(self, emitter, song, songpos, songid, state):
        self._refresh(songpos)

    def _on_playlist_changed(self, emitter, version, length, songpos):
        self._length=length
        self._refresh(songpos)

    def _on_disconnected(self, *args):
        self._clear()