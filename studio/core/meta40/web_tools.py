"""Compatibility adapter for older META imports. Prefer web_research directly."""
from .web_research import WebError, web_search
from .web_research import web_fetch as _web_fetch


def web_fetch(url, approved_urls=None):
    if approved_urls is not None and url not in approved_urls:
        raise WebError('URL must be present in search results from this task')
    return _web_fetch(url)
