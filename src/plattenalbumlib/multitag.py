class MultiTag(list):
    def __str__(self):
        return ", ".join(self)