import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
from gettext import gettext as _


class ConnectDialog(Adw.Dialog):
    def __init__(self, title, target):
        super().__init__(title=title, width_request=360, follows_content_size=True)
        self._clamp=Adw.Clamp(margin_top=24, margin_bottom=24, margin_start=12, margin_end=12)
        connect_button=Gtk.Button(label=_("_Connect"), use_underline=True, action_name="app.connect", action_target=target)
        connect_button.set_css_classes(["suggested-action"])
        cancel_button=Gtk.Button(label=_("Ca_ncel"), use_underline=True)
        cancel_button.connect("clicked", lambda *args: self.close())
        scroll=Gtk.ScrolledWindow(child=self._clamp, propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        header_bar=Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header_bar.pack_start(cancel_button)
        header_bar.pack_end(connect_button)
        toolbar_view=Adw.ToolbarView(content=scroll)
        toolbar_view.add_top_bar(header_bar)
        self._connection_toast=Adw.Toast(title=_("Connection failed"))
        self._toast_overlay=Adw.ToastOverlay(child=toolbar_view)
        self.set_child(self._toast_overlay)
        self.set_default_widget(connect_button)
        self.set_focus(connect_button)

    def set_content(self, widget):
        self._clamp.set_child(widget)

    def connection_error(self):
        self._toast_overlay.add_toast(self._connection_toast)