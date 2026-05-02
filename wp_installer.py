import requests

PLUGIN_SLUG = "insert-headers-and-footers"


class PluginInstallError(Exception):
    pass


def _find_plugin(session: requests.Session, domain: str, nonce: str):
    """Return plugin data dict if installed (any status), or None if not found."""
    headers = {"X-WP-Nonce": nonce, "Content-Type": "application/json"}
    resp = session.get(
        f"https://{domain}/wp-json/wp/v2/plugins",
        headers=headers,
        timeout=30,
    )
    if resp.status_code != 200:
        return None
    plugins = resp.json()
    for plugin in plugins:
        # Match by slug — plugin dict has "plugin" key like "slug/slug.php"
        if plugin.get("textdomain") == PLUGIN_SLUG or PLUGIN_SLUG in plugin.get("plugin", ""):
            return plugin
    return None


def ensure_plugin_active(session: requests.Session, domain: str, nonce: str) -> None:
    """
    Ensure the Insert Headers and Footers plugin is installed and active.
    Raises PluginInstallError if install or activation fails.
    """
    headers = {"X-WP-Nonce": nonce, "Content-Type": "application/json"}
    base = f"https://{domain}/wp-json/wp/v2/plugins"

    plugin = _find_plugin(session, domain, nonce)

    if plugin is not None:
        if plugin.get("status") == "active":
            return  # already active

        # Installed but inactive — activate via PUT using the exact plugin path
        plugin_path = plugin["plugin"]
        put_resp = session.put(
            f"{base}/{plugin_path}",
            json={"status": "active"},
            headers=headers,
            timeout=30,
        )
        if put_resp.status_code != 200:
            raise PluginInstallError(
                f"Failed to activate {PLUGIN_SLUG} on {domain}: {put_resp.status_code} {put_resp.text[:200]}"
            )
        return

    # Not installed — install and activate in one call
    post_resp = session.post(
        base,
        json={"slug": PLUGIN_SLUG, "status": "active"},
        headers=headers,
        timeout=60,
    )
    if post_resp.status_code not in (200, 201):
        raise PluginInstallError(
            f"Failed to install {PLUGIN_SLUG} on {domain}: {post_resp.status_code} {post_resp.text[:200]}"
        )
