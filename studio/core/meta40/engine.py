"""Compatibility adapter for callers of the META 4 run interface."""
from meta5 import transport
from meta5.agent import execute
from meta5.tools import ToolContext
import uuid


class Ollama:
    def __init__(self,model,timeout=120):self.model=model;self.timeout=timeout
    def __call__(self,messages):return transport.complete(self.model,messages,timeout=self.timeout,json_mode=True)['message']['content']


def run(root,task,model,stage,emit,cancel=None,max_steps=24,seconds=900,allow_tests=False,memory='',history=None,allow_web=True,allow_self_inspect=True):
    ctx=ToolContext.create(root,uuid.uuid4().hex,allow_run=allow_tests,cancel=cancel,emit=emit)
    request={'task':task,'model':getattr(model,'model','auto'),'max_steps':max_steps,'seconds':seconds,
             'allow_tests':allow_tests,'history':history or [],'allow_web':allow_web,'allow_self_inspect':allow_self_inspect}
    return execute(ctx,request,model_client=model,stage_callback=stage)
