import gettext
import locale
import os
from pathlib import Path

try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    pass
_translation = gettext.translation("desktop-studio", localedir=str(Path(__file__).parent / "locale"), fallback=True)


def _(message):
    # gettext reserves the empty message for catalog headers. Optional UI
    # descriptions and badges must remain empty in translated interfaces.
    return _translation.gettext(message) if message else ""


def n_(singular, plural, count):
    return _translation.ngettext(singular, plural, count)


def is_rtl():
    language = (os.environ.get("LANGUAGE") or os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "en").split(":")[0].split("_")[0].split(".")[0]
    return language in {"fa", "ar", "he", "ur", "ps", "dv", "yi"}
