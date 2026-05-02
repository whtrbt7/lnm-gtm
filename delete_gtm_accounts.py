"""
delete_gtm_accounts.py — Delete ALL GTM accounts visible to the logged-in Google user.

Requires Chrome running with remote debugging on port 9222, logged into achiu@leadsnearme.com.

Usage:
  python delete_gtm_accounts.py --dry-run  # list only, no changes
  python delete_gtm_accounts.py --yes      # delete without prompt
  python delete_gtm_accounts.py            # list then confirm
"""

import re
import time
import argparse

CDP_URL  = 'http://localhost:9222'
GTM_HOME = 'https://tagmanager.google.com/#/home'
GTM_BASE = 'https://tagmanager.google.com/'


def collect_accounts(context):
    """Scroll the GTM home page to force all account cards to render, collect account+container IDs."""
    page = context.new_page()
    try:
        print('Loading GTM home...')
        page.goto(GTM_HOME, wait_until='networkidle', timeout=60000)
        time.sleep(3)

        if 'accounts.google.com' in page.url:
            raise SystemExit('Not logged in. Log in to achiu@leadsnearme.com in the Chrome window.')

        # Scroll to the bottom incrementally to trigger lazy rendering
        prev_count = 0
        for _ in range(30):
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            time.sleep(0.8)
            links = page.query_selector_all('a[href*="/container/accounts/"]')
            if len(links) == prev_count and len(links) > 0:
                break
            prev_count = len(links)

        # Collect account_id → (name, container_id)
        links = page.query_selector_all('a[href*="/container/accounts/"]')
        seen = {}
        for link in links:
            href = link.get_attribute('href') or ''
            m = re.search(r'/container/accounts/(\d+)/containers/(\d+)', href)
            if not m:
                continue
            acct_id, ctr_id = m.group(1), m.group(2)
            if acct_id in seen:
                continue
            name = link.inner_text().strip().splitlines()[0].strip()
            if name:
                seen[acct_id] = (name, ctr_id)

        return [(aid, name, ctr_id) for aid, (name, ctr_id) in seen.items()]
    finally:
        page.close()


def delete_account(context, acct_id, name, ctr_id):
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    page = context.new_page()
    try:
        # Step 1: Load GTM home
        page.goto(GTM_HOME, wait_until='networkidle', timeout=60000)
        time.sleep(2)

        # Step 2: Find and click the three-dot (wd-account-dropdown) for this account.
        # The dropdown shows Account Settings with href="#/admin/accounts/{acct_id}".
        # We need to find the correct three-dot button by checking the dropdown links.
        clicked_settings = page.evaluate(f"""() => {{
            const dots = Array.from(document.querySelectorAll('.wd-account-dropdown:not(.admin-header-overflow)'));
            for (const dot of dots) {{
                // Peek at the dropdown menu for this dot to find the account ID
                const menu = dot.parentElement && dot.parentElement.querySelector
                    ? dot.parentElement.querySelector('.wd-account-dropdown-menu, .account-dropdown-menu')
                    : null;
                // Also check via Angular scope
                const scope = (typeof angular !== 'undefined' && angular.element(dot).scope());
                const scopeAcctId = scope && scope.account && scope.account.key;
                if (scopeAcctId == '{acct_id}') {{
                    dot.click();
                    return 'scope_match';
                }}
            }}
            // Fallback: click first dot, check href
            if (dots.length > 0) {{ dots[0].click(); return 'first_dot'; }}
            return 'no_dots';
        }}""")

        time.sleep(0.5)

        # Check if correct account's menu opened
        acct_settings_href = page.evaluate(f"""() => {{
            const items = document.querySelectorAll('.wd-account-dropdown-menu li, .account-dropdown-menu li');
            const el = Array.from(items).find(li => /account settings/i.test(li.innerText || ''));
            if (!el) return null;
            const a = el.querySelector('a');
            return a ? a.getAttribute('href') : null;
        }}""")

        if not acct_settings_href or acct_id not in (acct_settings_href or ''):
            # Wrong account opened — close and navigate directly
            page.keyboard.press('Escape')
            time.sleep(0.3)
            # Navigate directly to account settings URL (only works when Angular is initialized from home)
            page.evaluate(f'window.location.hash = "/admin/accounts/{acct_id}"')
            time.sleep(2)
        else:
            # Click Account Settings in the dropdown
            page.evaluate("""() => {
                const items = document.querySelectorAll('.wd-account-dropdown-menu li, .account-dropdown-menu li');
                const el = Array.from(items).find(li => /account settings/i.test(li.innerText || ''));
                if (el) el.click();
            }""")
            time.sleep(2)

        # Verify we're on the account settings page and read account name
        if acct_id not in page.url:
            print(f'  WARNING: Did not land on account {acct_id} settings. Got: {page.url}. Skipping.')
            return False

        try:
            name_input = page.locator('input[type="text"]').first
            name_input.wait_for(timeout=6000)
            gtm_name = name_input.input_value().strip() or name
        except PlaywrightTimeoutError:
            gtm_name = name

        # Step 3: Click the sheet header three-dot (admin-header-overflow)
        clicked = page.evaluate("""() => {
            const btn = document.querySelector('.admin-header-overflow');
            if (btn) { btn.click(); return true; }
            return false;
        }""")
        if not clicked:
            print(f'  WARNING: No sheet header overflow button for {name}. Skipping.')
            return False
        time.sleep(0.5)

        # Step 4: Click "Delete" from the editor dropdown menu
        clicked = page.evaluate("""() => {
            const menu = document.querySelector('.wd-account-editor-dropdown-menu');
            if (!menu) return false;
            const li = Array.from(menu.querySelectorAll('li')).find(li => /^delete$/i.test((li.innerText || '').trim()));
            if (li) { li.click(); return true; }
            return false;
        }""")
        if not clicked:
            print(f'  WARNING: No Delete option in editor menu for {name}. Skipping.')
            return False
        time.sleep(1)

        # Step 5: Confirmation dialog — type account name and confirm
        try:
            dialog_input = page.locator('input[type="text"]').last
            dialog_input.wait_for(timeout=6000)
            dialog_input.fill(gtm_name)
            time.sleep(0.5)
        except PlaywrightTimeoutError:
            print(f'  WARNING: No confirmation input for {name}. Skipping.')
            return False

        # Click the confirm Delete button
        page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button'));
            const el = btns.find(b => /^delete$/i.test((b.innerText || b.textContent || '').trim()));
            if (el) el.click();
        }""")

        time.sleep(2)
        print(f'  ✓ Deleted: {gtm_name} [{acct_id}]')
        return True

    except Exception as e:
        print(f'  ✗ Error on {name}: {e}')
        return False
    finally:
        try:
            page.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--yes',     action='store_true', help='Skip confirmation prompt')
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser  = p.chromium.connect_over_cdp(CDP_URL)
        context  = browser.contexts[0]
        accounts = collect_accounts(context)

        if not accounts:
            print('No GTM accounts found.')
            return

        print(f'\nFound {len(accounts)} account(s):\n')
        for acct_id, name, ctr_id in accounts:
            print(f'  [{acct_id}] ctr={ctr_id}  {name}')

        if args.dry_run:
            print('\n[DRY RUN] No changes made.')
            return

        if not args.yes:
            confirm = input(f'\nType "delete all" to permanently delete all {len(accounts)} accounts: ').strip()
            if confirm != 'delete all':
                print('Aborted.')
                return

        print()
        deleted = 0
        skipped = 0
        for acct_id, name, ctr_id in accounts:
            if delete_account(context, acct_id, name, ctr_id):
                deleted += 1
            else:
                skipped += 1
            time.sleep(0.5)

    print(f'\nDone. Deleted {deleted}/{len(accounts)} — {skipped} skipped.')


if __name__ == '__main__':
    main()
