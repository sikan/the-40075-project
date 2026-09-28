import re
from html.parser import HTMLParser
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class IDs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = set()
        self.scripts = []
        self.stylesheets = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.values.add(values["id"])
        if tag == "script" and "src" in values:
            self.scripts.append(values["src"])
        if tag == "link" and values.get("rel") == "stylesheet":
            self.stylesheets.append(values.get("href"))


class WebContractTests(unittest.TestCase):
    def setUp(self):
        self.javascript = (ROOT / "web/app.js").read_text(encoding="utf-8")
        self.parser = IDs()
        self.parser.feed((ROOT / "web/index.html").read_text(encoding="utf-8"))

    def test_every_javascript_dom_reference_exists(self):
        references = set(re.findall(r'\$\("([a-z0-9-]+)"\)', self.javascript))
        self.assertEqual(references - self.parser.values, set())

    def test_browser_assets_are_local(self):
        self.assertEqual(self.parser.scripts, ["./app.js"])
        self.assertEqual(self.parser.stylesheets, ["./style.css"])

    def test_browser_code_uses_safe_dom_writes_and_relative_data_fetches(self):
        self.assertNotIn("innerHTML", self.javascript)
        self.assertNotIn("eval(", self.javascript)
        fetches = re.findall(r'getJSON\((`[^`]+`|"[^"]+")\)', self.javascript)
        self.assertTrue(fetches)
        self.assertTrue(all("./data/" in value for value in fetches))


if __name__ == "__main__":
    unittest.main()
