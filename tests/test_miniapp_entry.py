import unittest
from app.miniapp import miniapp_entry_url
from app.handlers.catalog import create_main_keyboard

class MiniAppEntryTests(unittest.TestCase):
    def test_keyboard_uses_distinct_sections_not_launch_fragments(self):
        keyboard=create_main_keyboard(miniapp_url='https://example.com/')
        self.assertEqual(keyboard.keyboard[0][0].web_app.url,'https://example.com/?section=catalog')
        self.assertEqual(keyboard.keyboard[1][0].text,'Производители')
        self.assertEqual(keyboard.keyboard[1][0].web_app.url,'https://example.com/?section=suppliers')

    def test_existing_query_and_path_preserved_section_replaced(self):
        self.assertEqual(miniapp_entry_url('https://example.com/app/?ref=test&section=catalog#/product/42','suppliers'),
                         'https://example.com/app/?ref=test&section=suppliers')
        with self.assertRaises(ValueError):miniapp_entry_url('https://example.com/','invalid')
