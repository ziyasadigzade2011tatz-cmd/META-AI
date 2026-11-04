"""Resolve the public thread executor explicitly on frozen Python runtimes."""
def prepare_thread_executor():
    import importlib
    futures=importlib.import_module('concurrent.futures')
    concrete=importlib.import_module('concurrent.futures.thread').ThreadPoolExecutor
    if futures.__dict__.get('ThreadPoolExecutor') is not concrete:
        futures.ThreadPoolExecutor=concrete
    return concrete
