import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GObject, Gtk
from gettext import gettext as _
from html.parser import HTMLParser
import urllib.request
import urllib.parse
import urllib.error
import threading
from .functions import idle_add
from .song import Song


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
        self._text_view=Gtk.TextView(
            editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD,
            justification=Gtk.Justification.CENTER,
            left_margin=12, right_margin=12, bottom_margin=9, top_margin=9,
            pixels_above_lines=1, pixels_below_lines=2, pixels_inside_wrap=3
        )
        self._text_view.add_css_class("inline")
        self._text_view.update_property([Gtk.AccessibleProperty.LABEL], [_("Lyrics view")])

        # text buffer
        self._text_buffer=self._text_view.get_buffer()

        # scroll
        scroll=Gtk.ScrolledWindow(child=self._text_view, propagate_natural_height=True)
        self._adj=scroll.get_vadjustment()

        # connect
        self.connect("notify::song", self._on_song_changed)

        # packing
        self.add_named(scroll, "lyrics")
        self.add_named(no_lyrics_status_page, "no-lyrics")
        self.add_named(connection_error_status_page, "connection-error")
        self.add_named(searching_status_page, "searching")

    def load(self):
        if self.get_visible_child_name() != "lyrics" and (song:=self.get_property("song")) is not None:
            self.set_visible_child_name("searching")
            threading.Thread(target=self._display_lyrics, args=(song["title"][0], str(song["artist"])), daemon=True).start()

    def _on_song_changed(self, *args):
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
