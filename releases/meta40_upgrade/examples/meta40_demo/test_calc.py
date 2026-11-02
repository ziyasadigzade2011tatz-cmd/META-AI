import unittest
from calc import add


class TestAdd(unittest.TestCase):
    def test_sum(self):
        self.assertEqual(add(2, 3), 5)
