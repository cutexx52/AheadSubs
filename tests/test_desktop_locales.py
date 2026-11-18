import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


DESKTOP = Path(__file__).resolve().parents[1] / "desktop"
LOCALES = ("zh-CN", "zh-TW", "ja", "ko", "fr", "de", "es")


def catalog(path):
    entries = ET.parse(path).findall("data")
    result = {entry.attrib["name"]: entry.findtext("value") for entry in entries}
    if len(entries) != len(result):
        raise AssertionError(f"Duplicate resource key in {path.name}")
    return result


class DesktopLanguagesTest(unittest.TestCase):
    def test_each_interface_language_defines_every_message_and_format_argument(self):
        for neutral in DESKTOP.glob("*.resx"):
            if "." in neutral.stem:
                continue
            english = catalog(neutral)
            for locale in LOCALES:
                with self.subTest(group=neutral.stem, locale=locale):
                    path = neutral.with_suffix(f".{locale}.resx")
                    if locale == "zh-CN" and not path.exists():
                        path = neutral.with_suffix(".zh-Hans.resx")
                    strings = catalog(path)
                    self.assertEqual(strings.keys(), english.keys())
                    for key, value in strings.items():
                        self.assertTrue(value and value.strip(), key)
                        self.assertCountEqual(re.findall(r"\{\d+[^}]*\}", english[key]),
                                              re.findall(r"\{\d+[^}]*\}", value), key)
