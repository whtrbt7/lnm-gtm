import re


def clean_url(url):
    """Strip protocol and trailing slash from a URL for use as a GTM container name."""
    if not url:
        return ''
    return re.sub(r'^https?://', '', str(url)).rstrip('/')
