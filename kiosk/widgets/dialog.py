"""Bazowe okno dialogowe kiosku."""
from kivy.clock import Clock
from kivy.uix.modalview import ModalView

AUTO_CLOSE_SECONDS = 60     # kiosk: okno samo się zamknie po minucie bez dotyku


class KioskDialog(ModalView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._auto_close = Clock.create_trigger(lambda _dt: self.dismiss(),
                                                AUTO_CLOSE_SECONDS)

    def on_open(self):
        self._auto_close()

    def on_dismiss(self):
        self._auto_close.cancel()

    def on_touch_down(self, touch):
        self._auto_close.cancel()
        self._auto_close()
        return super().on_touch_down(touch)
