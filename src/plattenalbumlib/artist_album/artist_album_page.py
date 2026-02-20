from ..album import AlbumPage
from ..browsersong import BrowserSongRow
from ..duration import Duration


class ArtistAlbumPage(AlbumPage):
    def __init__(self, client, albumartist, album, date):
        super().__init__(client, album, date)
        tag_filter=("albumartist", albumartist, "album", album, "date", date)

        self.play_button.connect("clicked", lambda *args: client.filter_to_playlist(tag_filter, "play"))
        self.append_button.connect("clicked", lambda *args: client.filter_to_playlist(tag_filter, "append"))

        self.suptitle.set_text(albumartist)
        self.length.set_text(str(Duration(client.count(*tag_filter)["playtime"])))
        client.restrict_tagtypes("track", "title", "artist")
        songs=client.find(*tag_filter)
        client.tagtypes("all")
        self.album_cover.set_paintable(client.get_cover(songs[0]["file"]).get_paintable())
        for song in songs:
            row=BrowserSongRow(song, hide_artist=albumartist)
            self.song_list.append(row)