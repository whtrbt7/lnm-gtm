import requests
import sys

def test_login(domain, username, password):
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; GTMInjector/1.0)"})
    login_url = f"https://{domain}/wp-login.php"
    session.cookies.set("wordpress_test_cookie", "WP Cookie check", domain=domain)
    payload = {
        "log": username,
        "pwd": password,
        "wp-submit": "Log In",
        "redirect_to": "/wp-admin/",
        "testcookie": "1",
    }
    print(f"Testing {username} / {password} on {domain}...")
    resp = session.post(login_url, data=payload, allow_redirects=True, timeout=30)
    if "/wp-admin/" in resp.url:
        print("SUCCESS")
    else:
        print(f"FAILED: ended at {resp.url}")

domain = 'autotronicspa.com'
test_login(domain, 'lnmdev', '1qv+4c15Zx;FV}O')
test_login(domain, 'lnm-dev', '1£qv+4c15Zx;FV}O')
