from ..album import Album


class ArtistAlbum(Album):
    def __init__(self, artist, name, date):
        super().__init__(name, date)
        self.artist=artist