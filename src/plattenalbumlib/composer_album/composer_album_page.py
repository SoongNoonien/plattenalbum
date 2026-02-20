from ..album import AlbumPage
from ..browsersong import BrowserSongRow
from ..duration import Duration


class ComposerAlbumPage(AlbumPage):
    def __init__(self, client, albumcomposer, album, date):
        super().__init__(client, album, date)
        tag_filter = ("composer", albumcomposer, "album", album, "date", date)

        self.play_button.connect("clicked", lambda *args: client.filter_to_playlist(tag_filter, "play"))
        self.append_button.connect("clicked", lambda *args: client.filter_to_playlist(tag_filter, "append"))

        self.suptitle.set_text(albumcomposer)
        self.length.set_text(str(Duration(client.count(*tag_filter)["playtime"])))
        client.restrict_tagtypes("track", "title", "composer")
        songs = client.find(*tag_filter)
        client.tagtypes("all")
        self.album_cover.set_paintable(client.get_cover(songs[0]["file"]).get_paintable())
        for song in songs:
            row = BrowserSongRow(song, hide_composer=albumcomposer)
            self.song_list.append(row)