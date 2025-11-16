#!/usr/bin/env python3
from __future__ import annotations
import re
import html
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests
import json
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta


_MOODLE_HOST = "moodle.innopolis.university"
_DEFAULT_WANTS_URL = "https://moodle.innopolis.university/my/"
_DEFAULT_AGENT = "innoauth-python/1.0"
_ACCEPT_HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


class AuthException(Exception):
    pass


class InnoAuthResult:
    def __init__(self, final_url, cookies):
        self.final_url = final_url
        self.cookies = cookies

    def cookie_header(self):
        return "; ".join(f"{c.name}={c.value}" for c in self.cookies)


class InnoAuthClient:
    def __init__(self, logger=print):
        self.session = requests.Session()
        self.logger = logger

        self.session.headers.update(
            {
                "User-Agent": _DEFAULT_AGENT,
                "Accept": _ACCEPT_HTML,
            }
        )

    def _log(self, msg):
        if self.logger:
            self.logger(msg)

    def _resolve(self, base, location):
        return urljoin(base, location)

    def _get_hidden(self, html_body, name):
        m = re.search(
            r'<input[^>]*name=["\']' + re.escape(name) + r'["\'][^>]*value=["\']([^"\']*)["\']',
            html_body,
            flags=re.IGNORECASE,
        )
        return html.unescape(m.group(1)) if m else None

    # ---------------------------
    #         MAIN LOGIN
    # ---------------------------
    def authorize(self, username, password, wants_url=None, keep_me_signed_in=True, timeout=30):
        wants = wants_url or _DEFAULT_WANTS_URL

        # --------------------------------------------------------
        # STEP 1: Load /login/index.php and extract OAuth2 link
        # --------------------------------------------------------
        login_page = f"https://{_MOODLE_HOST}/login/index.php"
        self._log("Loading Moodle login page...")
        r = self.session.get(login_page, timeout=timeout)
        r.raise_for_status()

        # Extract OAuth link automatically from login page
        # Example: <a href="/auth/oauth2/login.php?id=1&sesskey=XYZ123">Log in ...</a>
        m = re.search(r'<a[^>]+href="([^"]+/auth/oauth2/login[^"]+)"', r.text, re.IGNORECASE)
        if not m:
            raise AuthException("Cannot find OAuth2 login link on the login page.")

        oauth_url_raw = m.group(1)
        oauth_url_raw = html.unescape(oauth_url_raw)  # ← ВАЖНО: убираем &amp;

        oauth_url = self._resolve(login_page, oauth_url_raw)
        self._log(f"OAuth link found (decoded): {oauth_url}")

        # --------------------------------------------------------
        # STEP 2: Start OAuth (should redirect to ADFS)
        # --------------------------------------------------------
        resp = self.session.get(oauth_url, allow_redirects=False, timeout=timeout)

        if resp.status_code not in (301, 302, 303, 307, 308):
            raise AuthException("OAuth2 start failed: expected redirect to SSO.")

        sso_location = resp.headers.get("Location")
        if not sso_location:
            raise AuthException("OAuth2 start failed: Missing Location header.")

        sso_url = self._resolve(resp.url, sso_location)
        self._log(f"SSO redirect: {sso_url}")

        # --------------------------------------------------------
        # STEP 3: Load ADFS login form (username/password)
        # --------------------------------------------------------
        sso_form = self.session.get(sso_url, timeout=timeout)
        sso_form.raise_for_status()

        if "UserName" not in sso_form.text:
            raise AuthException("Unexpected SSO login page: no UserName field found")

        # --------------------------------------------------------
        # STEP 4: Submit credentials to ADFS
        # --------------------------------------------------------
        payload = {
            "UserName": username,
            "Password": password,
            "Kmsi": "true" if keep_me_signed_in else "false",
            "AuthMethod": "FormsAuthentication",
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": sso_url,
        }

        self._log("Submitting credentials to ADFS...")
        rpost = self.session.post(
            sso_url,
            data=payload,
            headers=headers,
            allow_redirects=True,
            timeout=timeout,
        )
        rpost.raise_for_status()

        # --------------------------------------------------------
        # STEP 5: Extract OAuth2 code + state returned from ADFS
        # --------------------------------------------------------
        code = self._get_hidden(rpost.text, "code")
        state = self._get_hidden(rpost.text, "state")

        if not code or not state:
            raise AuthException("Failed to extract authorization code/state – login failed.")

        # --------------------------------------------------------
        # STEP 6: Exchange code at Moodle callback
        # --------------------------------------------------------
        callback = f"https://{_MOODLE_HOST}/admin/oauth2callback.php"

        cb = self.session.post(
            callback,
            data={"code": code, "state": state},
            allow_redirects=True,
            timeout=timeout,
        )
        cb.raise_for_status()

        final_url = cb.url
        self._log(f"Final URL: {final_url}")

        return InnoAuthResult(final_url, self.session.cookies)


# --------------------------------------------------------
# CLI WRAPPER
# --------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--pass", required=True, dest="password")
    parser.add_argument("--last_event", required=True)
    args = parser.parse_args()

    client = InnoAuthClient(logger=print)
    try:
        result = client.authorize(args.user, args.password)
    except Exception as e:
        print("Auth failed:", e)
        exit(2)

    header_auth = {"Cookie": result.cookie_header()}

    sesskey_value = (
        BeautifulSoup(
            requests.get("https://moodle.innopolis.university/my/", headers=header_auth).text,
            "html.parser",
        )
        .find("input", {"type": "hidden", "name": "sesskey"})
        .get("value")
    )

    request_data = [
        {
            "index": 0,
            "methodname": "core_calendar_get_action_events_by_timesort",
            "args": {
                "aftereventid": int(args.last_event),
                "limitnum": 50,
                "timesortfrom": int(datetime.now(timezone.utc).timestamp()),
                "timesortto": int(
                    (datetime.now(timezone.utc) + relativedelta(months=2)).timestamp()
                ),
                "limittononsuspendedevents": True,
            },
        }
    ]

    data = requests.post(
        f"https://moodle.innopolis.university/lib/ajax/service.php?sesskey={sesskey_value}&info=core_calendar_get_action_events_by_timesort",
        headers=header_auth,
        json=request_data,
    ).json()[0]

    if data["error"]:
        raise Exception(json.dumps(data["exception"], indent=4, ensure_ascii=False))

    events = data["data"]["events"]
    allowed_keys = {"name", "activityname", "timestart", "course_name", "task_id"}
    deadlines = []
    for item in events:
        if not item["action"]["actionable"]:
            continue

        item["task_id"] = item["id"]
        item["course_name"] = item["course"]["fullname"]
        item = {key: item[key] for key in item if key in allowed_keys}
        deadlines.append(item)

    print("Deadlines:", deadlines, sep="")
