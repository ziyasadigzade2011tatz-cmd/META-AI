import tempfile
import unittest
from pathlib import Path
from .engine import Workspace,tools_schema

class TestGuardrails(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.ws=Workspace(self.root,lambda a,d:True)
    def tearDown(self):self.tmp.cleanup()
    def test_read_before_edit(self):
        (self.root/'a.py').write_text('x = 1\n')
        with self.assertRaisesRegex(ValueError,'Read'):
            self.ws.edit('a.py','x = 1','x = 2')
        self.assertIn('1: x = 1',self.ws.read('a.py'))
        self.assertIn('Updated',self.ws.edit('a.py','x = 1','x = 2'))
        self.assertEqual((self.root/'a.py').read_text(),'x = 2\n')
    def test_escape_denied(self):
        with self.assertRaises(PermissionError):self.ws.read('../outside.txt')
        with self.assertRaises(PermissionError):self.ws.write('C:/Windows/a.py','bad')
    def test_overwrite_denied(self):
        self.ws.write('new.txt','hello')
        with self.assertRaises(FileExistsError):self.ws.write('new.txt','overwrite')
    def test_shell_restricted(self):
        with self.assertRaises(PermissionError):self.ws.bash('powershell -NoProfile -Command whoami')
        with self.assertRaises(PermissionError):self.ws.bash('git status && echo bad')
    def test_schema(self):self.assertEqual(len(tools_schema()),6)
if __name__=='__main__':unittest.main()
