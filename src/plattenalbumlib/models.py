from gi.repository import Gtk, GObject, Gio
import locale


class ListModel(GObject.Object, Gio.ListModel):
    def __init__(self, item_type):
        super().__init__()
        self.data=[]
        self._item_type=item_type

    def do_get_item(self, position):
        try:
            return self.data[position]
        except IndexError:
            return None

    def do_get_item_type(self):
        return self._item_type

    def do_get_n_items(self):
        return len(self.data)

class SelectionModel(ListModel, Gtk.SelectionModel):
    __gsignals__={"selected": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
            "reselected": (GObject.SignalFlags.RUN_FIRST, None, ()),
            "clear": (GObject.SignalFlags.RUN_FIRST, None, ())}
    def __init__(self, item_type):
        super().__init__(item_type)
        self._selected=None

    def clear(self, position=0):
        n=self.get_n_items()-position
        self.data=self.data[:position]
        if self._selected is not None:
            if self._selected >= self.get_n_items():
                self._selected=None
        self.items_changed(position, n, 0)
        if position == 0:
            self.emit("clear")

    def append(self, data):
        n=self.get_n_items()
        self.data.extend(data)
        self.items_changed(n, 0, self.get_n_items())

    def get_selected(self):
        return self._selected

    def set(self, position, item):
        if position < len(self.data):
            self.data[position]=item
            self.items_changed(position, 1, 1)
        else:
            self.data.append(item)
            self.items_changed(position, 0, 1)

    def select(self, position):
        if position == self._selected:
            self.emit("reselected")
        else:
            old_selected=self._selected
            self._selected=position
            if old_selected is not None:
                self.selection_changed(old_selected, 1)
            self.selection_changed(position, 1)
            self.emit("selected", position)

    def unselect(self):
        old_selected=self._selected
        self._selected=None
        if old_selected is not None:
            self.selection_changed(old_selected, 1)

    def do_select_item(self, position, unselect_rest): return False
    def do_select_all(self): return False
    def do_select_range(self, position, n_items, unselect_rest): return False
    def do_set_selection(self, selected, mask): return False
    def do_unselect_all(self): return False
    def do_unselect_item(self, position): return False
    def do_unselect_range(self, position, n_items): return False
    def do_get_selection_in_range(self, position, n_items): return False

    def do_is_selected(self, position):
        return position == self._selected

    def set_list(self, items):
        self.clear()
        self.append((self.do_get_item_type()(item[0], item[2]) for item in sorted(items, key=lambda item: locale.strxfrm(item[1]))))

    def select_item(self, name):
        for i, item in enumerate(self.data):
            if item.name == name:
                self.select(i)
                return

    def get_item_name(self, position):
        return self.get_item(position).name

    def get_selected_item(self):
        if (selected:=self.get_selected()) is None:
            return None
        else:
            return self.get_item_name(selected)