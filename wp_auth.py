import re
import requests


class WPAuthError(Exception):
    pass


def wp_login(domain: str, username: str, password: str) -> requests.Session:
    """
    Log into WP admin via wp-login.php. Returns an authenticated Session.
    Raises WPAuthError if login fails.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; GTMInjector/1.0)"})

    login_url = f"https://{domain}/wp-login.php"

    # WP requires the test cookie to be present
    session.cookies.set("wordpress_test_cookie", "WP Cookie check", domain=domain)

    payload = {
        "log": username,
        "pwd": password,
        "wp-submit": "Log In",
        "redirect_to": "/wp-admin/",
        "testcookie": "1",
    }

    resp = session.post(login_url, data=payload, allow_redirects=True, timeout=30)

    # Login success: final URL must contain /wp-admin/
    if "/wp-admin/" not in resp.url:
        raise WPAuthError(f"Login failed for {domain}: ended at {resp.url}")

    return session


def fetch_rest_nonce(session: requests.Session, domain: str) -> str:
    """
    Fetch the WP REST API nonce from the admin dashboard.
    WP injects it as wpApiSettings.nonce in every admin page.
    Raises WPAuthError if nonce cannot be found.
    """
    resp = session.get(f"https://{domain}/wp-admin/", timeout=30)
    resp.raise_for_status()

    # Target wpApiSettings specifically — other plugins also inject "nonce" keys earlier on the page
    match = re.search(r'wpApiSettings\s*=\s*\{[^}]*"nonce"\s*:\s*"([a-z0-9]+)"', resp.text)
    if not match:
        # Fallback: last resort generic match
        match = re.search(r'"nonce"\s*:\s*"([a-z0-9]+)"', resp.text)
    if not match:
        raise WPAuthError(f"Could not extract REST nonce from {domain}/wp-admin/")

    return match.group(1)
