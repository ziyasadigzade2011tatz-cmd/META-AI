import json,re,sys,unittest
from pathlib import Path
studio=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(studio/'core'))
from meta5 import VERSION as CORE_VERSION
from meta_studio import VERSION as DESKTOP_VERSION

class ReleaseVersionTests(unittest.TestCase):
    def test_core_desktop_frontend_and_setup_versions_match(self):
        self.assertEqual(CORE_VERSION,DESKTOP_VERSION)
        frontend=studio/'frontend/package.json';setup=studio/'build_tools/Installer.cs'
        if frontend.exists():self.assertEqual(CORE_VERSION,json.loads(frontend.read_text('utf-8'))['version'])
        if setup.exists():self.assertIn('Version="'+CORE_VERSION+'"',setup.read_text('utf-8-sig'))

if __name__=='__main__':unittest.main()
