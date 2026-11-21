"""Pomocnicze funkcje UI."""
from kivy.factory import Factory


def make(cls_name: str, **props):
    """Tworzy klasę dynamiczną z .kv (<Nazwa@Baza>) i ustawia jej właściwości.

    Klasy dynamiczne nie przyjmują własnych właściwości w __init__.
    """
    widget = getattr(Factory, cls_name)()
    for key, value in props.items():
        setattr(widget, key, value)
    return widget
