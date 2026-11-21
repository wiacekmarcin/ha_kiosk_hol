"""Okno potwierdzenia (np. przed przełączeniem chronionego włącznika)."""
from kivy.properties import ObjectProperty, StringProperty

from kiosk.widgets.dialog import KioskDialog


class ConfirmDialog(KioskDialog):
    title = StringProperty("")
    message = StringProperty("")
    confirm_text = StringProperty("Tak")
    # uwaga: nie "on_confirm" - Kivy traktuje argumenty on_* jako podpięcie zdarzeń
    action = ObjectProperty(None)

    def confirm(self):
        self.dismiss()
        if self.action:
            self.action()
