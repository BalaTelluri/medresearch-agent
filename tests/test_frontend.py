"""Front-end routing: home page, chat page and the shared top nav."""
import unittest
from fastapi.testclient import TestClient
from serve.api import app

PAGES = {"/": "Home", "/chat": "Chat", "/genomics": "Genomics", "/pharmacovigilance": "Pharmacovigilance"}


class FrontendTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_every_page_loads_with_shared_nav(self):
        for path in PAGES:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            for target in PAGES:
                self.assertIn(f'href="{target}"', r.text, f"{path} nav missing {target}")

    def test_home_links_to_all_three_tools(self):
        html = self.client.get("/").text
        for target in ("/chat", "/genomics", "/pharmacovigilance"):
            self.assertIn(f'class="tool', html)
            self.assertIn(f'href="{target}"', html)

    def test_chat_page_keeps_stream_endpoint(self):
        self.assertIn("/api/ask/stream", self.client.get("/chat").text)


if __name__ == "__main__":
    unittest.main()
