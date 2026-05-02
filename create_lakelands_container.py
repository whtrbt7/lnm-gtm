"""
One-off: Create GTM Account + Web container for Lakelands Tire & Auto.
Connects to Chrome via CDP on localhost:9222.
"""
import re
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

GTM_URL        = 'https://tagmanager.google.com/'
ACCOUNT_NAME   = 'Lakelands Tire & Auto'
CONTAINER_NAME = 'lakelandstire.com'
CDP_URL        = 'http://localhost:9222'


def create_gtm_account(context):
    page = context.new_page()
    try:
        print('Navigating to GTM home...')
        page.goto(f'{GTM_URL}#/home', wait_until='domcontentloaded', timeout=60000)
        time.sleep(2)

        print('Clicking Create Account...')
        page.get_by_role('button', name=re.compile('Create Account', re.I)).first.click(timeout=10000)
        page.wait_for_url(re.compile(r'admin/accounts/create'), timeout=10000)
        time.sleep(1)

        account_field = page.locator('input[name="form.account.properties.displayName"]')
        account_field.wait_for(timeout=10000)
        account_field.fill(ACCOUNT_NAME)

        container_field = page.locator('input[name="form.container.properties.displayName"]')
        container_field.fill(CONTAINER_NAME)

        page.locator('div.context-picker__row[title="Web"]').click(timeout=10000)
        time.sleep(1)

        print('Submitting...')
        page.get_by_role('button', name=re.compile(r'^Create$')).click(timeout=10000)

        pre_workspace_urls = {
            p.url for p in context.pages
            if re.search(r'tagmanager\.google\.com.*workspaces', p.url)
        }

        try:
            tos = page.get_by_role('button', name=re.compile('Yes|I agree|Accept', re.I))
            tos.wait_for(timeout=8000)
            tos.click()
            print('Accepted TOS.')
        except PlaywrightTimeoutError:
            pass

        workspace_page = None
        for _ in range(25):
            time.sleep(1)
            for p in context.pages:
                if re.search(r'tagmanager\.google\.com.*workspaces', p.url) and p.url not in pre_workspace_urls:
                    workspace_page = p
                    break
            if workspace_page:
                break

        if not workspace_page:
            try:
                page.wait_for_url(re.compile(r'tagmanager\.google\.com.*workspaces'), timeout=10000)
                if page.url not in pre_workspace_urls:
                    workspace_page = page
            except PlaywrightTimeoutError:
                pass

        if not workspace_page:
            print('ERROR: Could not find new workspace page.')
            return None

        time.sleep(2)
        workspace_url = workspace_page.url
        print(f'Workspace URL: {workspace_url}')

        gtm_id = None
        try:
            workspace_page.wait_for_load_state('networkidle', timeout=15000)
            gtm_id = workspace_page.evaluate(
                "() => { const m = document.body.innerText.match(/GTM-[A-Z0-9]{4,10}/); return m ? m[0] : null; }"
            )
            if not gtm_id:
                m = re.search(r'GTM-[A-Z0-9]{4,10}', workspace_page.content())
                if m:
                    gtm_id = m.group(0)
        except Exception as e:
            print(f'Page extract error: {e}')

        if not gtm_id:
            url_match = re.search(r'accounts/(\d+)/containers/(\d+)', workspace_url)
            if url_match:
                from create_accounts_api import get_gtm_service
                svc = get_gtm_service('token_analytics.json')
                container = svc.accounts().containers().get(
                    path=f'accounts/{url_match.group(1)}/containers/{url_match.group(2)}'
                ).execute()
                gtm_id = container.get('publicId')

        try:
            workspace_page.close()
        except Exception:
            pass

        return gtm_id

    finally:
        try:
            page.close()
        except Exception:
            pass


def main():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]

        check = context.new_page()
        check.goto(GTM_URL, wait_until='domcontentloaded', timeout=60000)
        if 'accounts.google.com' in check.url:
            print('Not logged in to Google. Log in manually in the Chrome window.')
            check.close()
            return
        check.close()

        print(f'Creating: "{ACCOUNT_NAME}" / "{CONTAINER_NAME}"')
        gtm_id = create_gtm_account(context)

        if gtm_id:
            print(f'\nSUCCESS: {gtm_id}')
        else:
            print('\nFAILED: could not capture GTM ID')


if __name__ == '__main__':
    main()
