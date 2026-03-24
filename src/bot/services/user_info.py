import json
from html.parser import HTMLParser
from typing import Dict, Iterable, Optional

import httpx


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
    BASE_URL = 'https://tg-user.id'
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
    TIMEOUT = 10

    async def get_user_info(self, user_tag: str) -> dict:
        profile_path = self.PROFILE_PATH_TEMPLATE.format(username=user_tag)
        async with httpx.AsyncClient(base_url=self.BASE_URL, timeout=self.TIMEOUT, follow_redirects=True) as client:
            # Step 1: fetch the profile page to get CSRF token and cookies
            resp = await client.get(
                profile_path,
                headers={
                    'Accept': self.ACCEPT_HTML,
                    'Accept-Language': self.ACCEPT_LANGUAGE,
                    'DNT': '1',
                    'Upgrade-Insecure-Requests': '1',
                    'User-Agent': self.USER_AGENT,
                },
            )
            if resp.status_code != 200:
                raise RuntimeError(f'tg-user.id profile page request failed: {resp.status_code}')

            csrf_token = self._extract_csrf_token(resp.text)
            if not csrf_token:
                raise RuntimeError('Could not find CSRF token on tg-user.id profile page')

            cookies = '; '.join(
                f'{name}={value}' for name, value in resp.cookies.items()
            )

            # Step 2: POST to the API to resolve user_id
            post_resp = await client.post(
                self.API_PATH,
                content=json.dumps({'username': user_tag}),
                headers={
                    'Accept': self.ACCEPT_JSON,
                    'Accept-Language': self.ACCEPT_LANGUAGE,
                    'Content-Type': 'application/json',
                    'DNT': '1',
                    'Origin': self.BASE_URL,
                    'Referer': f'{self.BASE_URL}/from/username/{user_tag}',
                    'Sec-CH-UA': '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
                    'Sec-CH-UA-Mobile': '?0',
                    'Sec-CH-UA-Platform': '"macOS"',
                    'Sec-Fetch-Dest': 'empty',
                    'Sec-Fetch-Mode': 'cors',
                    'Sec-Fetch-Site': 'same-origin',
                    'User-Agent': self.USER_AGENT,
                    'X-CSRF-Token': csrf_token,
                    'Cookie': cookies,
                },
            )
            if post_resp.status_code != 200:
                raise RuntimeError(f'tg-user.id API request failed: {post_resp.status_code}')
            return post_resp.json()

    @staticmethod
    def _extract_csrf_token(page_body: str) -> Optional[str]:
        parser = _CsrfTokenParser()
        parser.feed(page_body)
        return parser.token
