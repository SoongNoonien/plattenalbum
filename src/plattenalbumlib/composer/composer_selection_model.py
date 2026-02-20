from ..models import SelectionModel
from .composer import Composer


class ComposerSelectionModel(SelectionModel):
    def __init__(self):
        super().__init__(Composer)