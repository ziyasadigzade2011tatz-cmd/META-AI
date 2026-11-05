import os
import sys
from pathlib import Path
root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))
sys.path.insert(0,str(root/'core'))
if len(sys.argv)>2 and sys.argv[1]=='--meta5-python':
    from meta5.python_child import dispatch
    raise SystemExit(dispatch(sys.argv[2:]))
if len(sys.argv)==3 and sys.argv[1]=='--studio-unittest':
    from meta_studio.runner import child
    raise SystemExit(child(sys.argv[2]))
from meta_studio.runtime import boot
boot(globals())
