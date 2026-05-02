import re
import requests

HEAD_SCRIPT_TEMPLATE = """\
<!-- Google Tag Manager -->
<script>(function(w,d,s,l,i){{w[l]=w[l]||[];w[l].push({{'gtm.start':
new Date().getTime(),event:'gtm.js'}});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
}})(window,document,'script','dataLayer','{gtm_id}');</script>
<!-- End Google Tag Manager -->"""

BODY_SCRIPT_TEMPLATE = """\
<!-- Google Tag Manager (noscript) -->
<noscript><iframe src="https://www.googletagmanager.com/ns.html?id={gtm_id}"
height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
<!-- End Google Tag Manager (noscript) -->"""

# PHP snippet used when WPCode is absent but Code Snippets plugin is present
CODE_SNIPPETS_PHP_TEMPLATE = """\
add_action( 'wp_head', function() {{
?>
<!-- Google Tag Manager -->
<script>(function(w,d,s,l,i){{w[l]=w[l]||[];w[l].push({{'gtm.start':
new Date().getTime(),event:'gtm.js'}});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
}})(window,document,'script','dataLayer','{gtm_id}');</script>
<!-- End Google Tag Manager -->
<?php
}}, 1 );

add_action( 'wp_body_open', function() {{
?>
<!-- Google Tag Manager (noscript) -->
<noscript><iframe src="https://www.googletagmanager.com/ns.html?id={gtm_id}"
height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
<!-- End Google Tag Manager (noscript) -->
<?php
}}, 1 );"""


class InjectionError(Exception):
    pass


def fetch_settings_nonce(session: requests.Session, domain: str) -> str:
    """Fetch nonce from the WPCode headers/footers settings page."""
    url = f"https://{domain}/wp-admin/admin.php"
    resp = session.get(url, params={"page": "wpcode-headers-footers"}, timeout=30)
    resp.raise_for_status()

    # WPCode Lite uses its own nonce field (not _wpnonce)
    match = re.search(r'name="insert-headers-and-footers_nonce"\s+value="([^"]+)"', resp.text)
    if not match:
        match = re.search(r'name="insert-headers-and-footers_nonce"[^>]*value="([^"]+)"', resp.text)
    if not match:
        raise InjectionError(f"Could not extract settings nonce from {domain}")

    return match.group(1)


def has_wpcode(session: requests.Session, domain: str) -> bool:
    """Return True if the WPCode headers/footers admin page is accessible."""
    resp = session.get(
        f"https://{domain}/wp-admin/admin.php",
        params={"page": "wpcode-headers-footers"},
        timeout=30,
        allow_redirects=True,
    )
    return resp.status_code == 200


def has_code_snippets_api(session: requests.Session, domain: str, rest_nonce: str) -> bool:
    """Return True if the Code Snippets REST API is accessible."""
    resp = session.get(
        f"https://{domain}/wp-json/code-snippets/v1/snippets",
        headers={"X-WP-Nonce": rest_nonce},
        timeout=30,
    )
    return resp.status_code == 200


def inject_gtm_via_wpcode(session: requests.Session, domain: str, gtm_id: str) -> None:
    """Write GTM head and body scripts via WPCode headers/footers page POST."""
    nonce = fetch_settings_nonce(session, domain)

    head_script = HEAD_SCRIPT_TEMPLATE.format(gtm_id=gtm_id)
    body_script = BODY_SCRIPT_TEMPLATE.format(gtm_id=gtm_id)

    payload = {
        "insert-headers-and-footers_nonce": nonce,
        "_wp_http_referer": "/wp-admin/admin.php?page=wpcode-headers-footers",
        "ihaf_insert_header": head_script,
        "ihaf_insert_body": body_script,
        "ihaf_insert_footer": "",
    }

    resp = session.post(
        f"https://{domain}/wp-admin/admin.php",
        params={"page": "wpcode-headers-footers"},
        data=payload,
        allow_redirects=True,
        timeout=30,
    )

    if resp.status_code >= 400:
        raise InjectionError(
            f"WPCode headers/footers POST failed for {domain}: {resp.status_code}"
        )


def inject_gtm_via_code_snippets(
    session: requests.Session, domain: str, gtm_id: str, rest_nonce: str
) -> None:
    """Create an active PHP snippet via the Code Snippets REST API."""
    # Check for an existing GTM snippet to avoid duplicates
    existing = session.get(
        f"https://{domain}/wp-json/code-snippets/v1/snippets",
        headers={"X-WP-Nonce": rest_nonce},
        timeout=30,
    ).json()

    for snippet in existing:
        if gtm_id in snippet.get("code", ""):
            raise InjectionError(
                f"GTM snippet for {gtm_id} already exists on {domain} (id={snippet['id']})"
            )

    php_code = CODE_SNIPPETS_PHP_TEMPLATE.format(gtm_id=gtm_id)

    resp = session.post(
        f"https://{domain}/wp-json/code-snippets/v1/snippets",
        headers={"X-WP-Nonce": rest_nonce, "Content-Type": "application/json"},
        json={
            "name": f"Google Tag Manager – {gtm_id}",
            "desc": "GTM head + body snippets injected by LNM automation.",
            "code": php_code,
            "scope": "front-end",
            "active": True,
        },
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        raise InjectionError(
            f"Code Snippets REST POST failed for {domain}: {resp.status_code} {resp.text[:200]}"
        )


def inject_gtm(
    session: requests.Session,
    domain: str,
    gtm_id: str,
    rest_nonce: str = "",
) -> str:
    """
    Inject GTM using whichever plugin is available.
    Returns the method used: 'wpcode' or 'code-snippets'.
    Raises InjectionError if neither method works.
    """
    if has_wpcode(session, domain):
        inject_gtm_via_wpcode(session, domain, gtm_id)
        return "wpcode"

    if rest_nonce and has_code_snippets_api(session, domain, rest_nonce):
        inject_gtm_via_code_snippets(session, domain, gtm_id, rest_nonce)
        return "code-snippets"

    raise InjectionError(
        f"Neither WPCode nor Code Snippets REST API is available on {domain}"
    )
