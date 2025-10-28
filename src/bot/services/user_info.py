import http.client
import json
from html.parser import HTMLParser
from typing import Dict, Iterable, Optional


class _CsrfTokenParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._token: Optional[str] = None

    @property
    def token(self) -> Optional[str]:
        return self._token

    def handle_starttag(self, tag: str, attrs: Iterable[tuple[str, Optional[str]]]) -> None:
        if tag != 'meta':
            return
        attributes: Dict[str, Optional[str]] = dict(attrs)
        if attributes.get('name') == 'csrf-token':
            self._token = attributes.get('content')


class UserInfoSource:
    HOST = 'tg-user.id'
    API_PATH = '/api/get-userid'
    PROFILE_PATH_TEMPLATE = '/from/username/{username}'
    USER_AGENT = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/141.0.0.0 Safari/537.36'
    )
    ACCEPT_HTML = (
        'text/html,application/xhtml+xml,application/xml;q=0.9,'
        'image/avif,image/webp,image/apng,*/*;q=0.8,'
        'application/signed-exchange;v=b3;q=0.7'
    )
    ACCEPT_JSON = '*/*'
    ACCEPT_LANGUAGE = 'en-GB,en-US;q=0.9,en;q=0.8,ru;q=0.7'
    ORIGIN = 'https://tg-user.id'
    TIMEOUT = 10

    def get_user_info(self, user_tag: str) -> dict:
        profile_path = self.PROFILE_PATH_TEMPLATE.format(username=user_tag)
        page_body, set_cookies = self._fetch_profile_page(profile_path)
        csrf_token = self._extract_csrf_token(page_body)
        if not csrf_token:
            raise RuntimeError('Could not find CSRF token on tg-user.id profile page')
        headers = self._build_post_headers(user_tag, csrf_token, set_cookies)
        payload = json.dumps({'username': user_tag})
        return self._perform_post(self.API_PATH, payload, headers)

    def _fetch_profile_page(self, path: str) -> tuple[str, str]:
        connection = http.client.HTTPSConnection(self.HOST, timeout=self.TIMEOUT)
        headers = {
            'Accept': self.ACCEPT_HTML,
            'Accept-Language': self.ACCEPT_LANGUAGE,
            'DNT': '1',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.USER_AGENT,
        }
        connection.request('GET', path, headers=headers)
        response = connection.getresponse()
        body_bytes = response.read()
        set_cookie_header = self._collect_set_cookie_header(response.getheaders())
        connection.close()
        if response.status != 200:
            raise RuntimeError(f'tg-user.id profile page request failed: {response.status}')
        return body_bytes.decode('utf-8'), set_cookie_header

    def _perform_post(self, path: str, payload: str, headers: Dict[str, str]) -> dict:
        connection = http.client.HTTPSConnection(self.HOST, timeout=self.TIMEOUT)
        connection.request('POST', path, body=payload, headers=headers)
        response = connection.getresponse()
        body_bytes = response.read()
        connection.close()
        if response.status != 200:
            raise RuntimeError(f'tg-user.id API request failed: {response.status}')
        return json.loads(body_bytes)

    def _build_post_headers(self, username: str, csrf_token: str, cookies: str) -> Dict[str, str]:
        headers = {
            'Accept': self.ACCEPT_JSON,
            'Accept-Language': self.ACCEPT_LANGUAGE,
            'Content-Type': 'application/json',
            'DNT': '1',
            'Origin': self.ORIGIN,
            'Referer': f'{self.ORIGIN}/from/username/{username}',
            'Sec-CH-UA': '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
            'Sec-CH-UA-Mobile': '?0',
            'Sec-CH-UA-Platform': '"macOS"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': self.USER_AGENT,
            'X-CSRF-Token': csrf_token,
        }
        if cookies:
            headers['Cookie'] = cookies
        return headers

    @staticmethod
    def _extract_csrf_token(page_body: str) -> Optional[str]:
        parser = _CsrfTokenParser()
        parser.feed(page_body)
        return parser.token

    @staticmethod
    def _collect_set_cookie_header(headers: Iterable[tuple[str, str]]) -> str:
        cookies = []
        for name, value in headers:
            if name.lower() == 'set-cookie' and value:
                cookies.append(value.split(';', 1)[0])
        return '; '.join(cookies)
