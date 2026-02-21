from ..album import Album


class ArtistAlbum(Album):
    def __init__(self, artist, role, name, date):
        super().__init__(name, date)
        self.artist=artist
        self.role=role