import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

@unittest.skipUnless(os.name=='nt','Windows instance gate')
class SingleInstanceTests(unittest.TestCase):
    def test_second_launch_exits_but_different_profile_can_open(self):
        core=str(Path(__file__).resolve().parents[1]/'core')
        script="import sys;sys.path.insert(0,sys.argv[1]);from meta_studio.single_instance import acquire;print(acquire(sys.argv[2]),flush=True);sys.stdin.readline()"
        with tempfile.TemporaryDirectory() as directory:
            first=subprocess.Popen([sys.executable,'-B','-c',script,core,directory],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                self.assertEqual(first.stdout.readline().strip(),'True')
                for target,expected in ((directory,'False'),(directory+'/other','True')):
                    result=subprocess.run([sys.executable,'-B','-c',script,core,target],input='\n',capture_output=True,text=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual(result.stdout.strip(),expected)
            finally:
                first.communicate('\n',timeout=10)

if __name__=='__main__':unittest.main()
