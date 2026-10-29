"""Entry URLs independent of Telegram's launch-data fragment."""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def miniapp_entry_url(base_url: str, section: str = 'catalog') -> str:
    if section not in {'catalog', 'suppliers'}:
        raise ValueError('Unknown Mini App section')
    parts = urlsplit(base_url)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != 'section']
    query.append(('section', section))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))
