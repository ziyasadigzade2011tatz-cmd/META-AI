import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.debug_state import render,key

class DebugTests(unittest.TestCase):
    def test_private_details_never_rendered(self):
        result=render({'private':True,'normalized':'скрыто'},None,None,None)
        self.assertNotIn('скрыто',result)
    def test_session_keys_are_separate(self):self.assertNotEqual(key('first'),key('second'))

if __name__=='__main__':unittest.main()
