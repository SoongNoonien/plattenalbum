from ..album import AlbumListRow


class ArtistAlbumListRow(AlbumListRow):
    def __init__(self, client):
        super().__init__(client)

    def set_album(self, album):
        super().set_album(album)
        if album.cover is None:
            self._client.tagtypes("clear")
            song=self._client.find("albumartist", album.artist, "album", album.name, "date", album.date, "window", "0:1")[0]
            self._client.tagtypes("all")
            album.cover=self._client.get_cover(song["file"]).get_paintable()
        self._cover.set_paintable(album.cover)