"""Conservative read-only HTTP for public manufacturer catalogs."""
import asyncio
import logging
import re
from time import monotonic
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)


class CatalogFetchError(RuntimeError):
    pass


class CatalogHTTPError(CatalogFetchError):
    def __init__(self, status_code, url):
        self.status_code, self.url = status_code, url
        super().__init__(f'HTTP {status_code}: {url}')


class RobotsRules:
    def __init__(self, text: str, user_agent: str = 'patternhubbot'):
        groups, agents, rules = [], [], []
        for line in text.lstrip('\ufeff').splitlines() + ['User-agent: end']:
            line = line.split('#', 1)[0].strip()
            if ':' not in line:
                continue
            key, value = (part.strip() for part in line.split(':', 1))
            key = key.casefold()
            if key == 'user-agent':
                if rules:
                    groups.append((agents or ['*'], rules))
                    agents, rules = [], []
                agents.append(value.casefold())
            elif key in {'allow', 'disallow'} and value:
                rules.append((key, value))
        # Some public CDN robots omit User-agent but explicitly disallow all.
        if rules and not groups:
            groups.append((agents or ['*'], rules))
        matched = [(max((len(a) for a in names if a != '*' and a in user_agent), default=0), entries)
                   for names, entries in groups if '*' in names or any(a in user_agent for a in names)]
        specificity = max((score for score, _ in matched), default=-1)
        self.rules = [rule for score, entries in matched if score == specificity for rule in entries]

    def allows(self, url: str) -> bool:
        parts = urlsplit(url)
        path = parts.path or '/'
        if parts.query:
            path += '?' + parts.query
        matched = []
        for kind, value in self.rules:
            pattern = '^' + re.escape(value).replace(r'\*', '.*').replace(r'\$', '$')
            if re.search(pattern, path):
                matched.append((len(value.replace('*', '')), kind == 'allow'))
        return not matched or max(matched)[1]


class PublicCatalogHTTP:
    def __init__(self, base_url: str, *, timeout=30, retries=3, transport=None, robots_allow=()):
        origin = urlsplit(base_url)
        host = origin.hostname.removeprefix('www.')
        self.hosts = {host, 'www.' + host}
        self.origin = f'{origin.scheme}://{origin.netloc}'
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=min(timeout, 10)),
            trust_env=False, follow_redirects=False, transport=transport,
            headers={'User-Agent':'Mozilla/5.0 (compatible; PatternHubBot/1.0)', 'Accept-Language':'ru-RU,ru;q=0.9'})
        self.retries = max(1, retries)
        self.requests_made = self.retries_made = 0
        self.robots = None
        self.last_request = 0
        # Operator-reviewed public storefront routes, authorized by the owner.
        # Defaults remain strict; never broaden to admin/account/cart endpoints.
        self.robots_allow = tuple(re.compile(pattern) for pattern in robots_allow)

    def allows(self, url):
        path = urlsplit(url).path or '/'
        if urlsplit(url).query:
            path += '?' + urlsplit(url).query
        return bool(self.robots and self.robots.allows(url)) or any(p.fullmatch(path) for p in self.robots_allow)

    async def __aenter__(self):
        try:
            response = await self._request(self.origin + '/robots.txt')
        except BaseException:
            await self.client.aclose()
            raise
        if response.status_code == 404:
            self.robots = RobotsRules('')
        elif response.status_code == 200:
            self.robots = RobotsRules(response.text)
        else:
            await self.client.aclose()
            raise CatalogFetchError('Robots unavailable')
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def get(self, url: str):
        if self.robots is None or not self.allows(url):
            raise CatalogFetchError('Robots disallows ' + url)
        response = await self._request(url)
        if response.status_code != 200:
            raise CatalogHTTPError(response.status_code, url)
        return response

    async def read_catalog_post(self, url, data):
        """POST used by an audited public listing's search/load-more form only."""
        if self.robots is None or not self.allows(url):
            raise CatalogFetchError('Robots disallows ' + url)
        response = await self._request(url, method='POST', data=data,
                                       headers={'X-Requested-With':'XMLHttpRequest'})
        if response.status_code != 200:
            raise CatalogHTTPError(response.status_code, url)
        return response

    async def _request(self, url: str, *, method='GET', data=None, headers=None):
        for redirect in range(6):
            parts = urlsplit(url)
            if parts.scheme not in {'http','https'} or parts.hostname not in self.hosts or parts.username or parts.password:
                raise CatalogFetchError('Catalog URL changed origin')
            if redirect and self.robots and not self.allows(url):
                raise CatalogFetchError('Robots disallows redirect')
            for attempt in range(self.retries):
                await asyncio.sleep(max(0, .2 - (monotonic() - self.last_request)))
                self.last_request = monotonic()
                self.requests_made += 1
                try:
                    response = await self.client.request(method, url, data=data, headers=headers)
                    if response.status_code != 429 and response.status_code < 500:
                        break
                    if attempt == self.retries - 1:
                        break
                except httpx.HTTPError as error:
                    if attempt == self.retries - 1:
                        raise CatalogFetchError(f'{type(error).__name__}: {url}') from error
                self.retries_made += 1
                await asyncio.sleep(min(2 ** attempt, 8))
            if response.status_code not in {301,302,303,307,308}:
                return response
            from urllib.parse import urljoin
            if response.status_code == 303 or (method == 'POST' and response.status_code in {301,302}):
                method, data = 'GET', None
            url = urljoin(url, response.headers.get('location', ''))
        raise CatalogFetchError('Redirect limit')
