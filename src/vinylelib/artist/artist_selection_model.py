from ..models import SelectionModel
from .artist import Artist


class ArtistSelectionModel(SelectionModel):
    def __init__(self):
        super().__init__(Artist)
