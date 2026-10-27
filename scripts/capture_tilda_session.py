"""Run on your trusted workstation, never on an unattended Actions runner.

User enters login/MFA into the real browser UI. No credential CLI parameters.
This tool does not create/edit/publish pages or click any Tilda controls.
"""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project-url', required=True, help='Exact existing project dashboard URL')
    parser.add_argument('--state', type=Path, default=Path('.auth/tilda-state.json'))
    args = parser.parse_args()
    url = urlsplit(args.project_url)
    if url.scheme != 'https' or url.hostname != 'tilda.cc' or url.username or url.password:
        parser.error('Expected HTTPS tilda.cc URL without credentials')
    if args.state.parent.resolve() != Path('.auth').resolve():
        parser.error('State must be stored directly inside ignored .auth/')
    os.umask(0o077)
    args.state.parent.mkdir(mode=0o700, exist_ok=True)
    if args.state.exists():
        parser.error('State already exists; securely rotate the previous session first')
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto('https://tilda.cc/login/', wait_until='domcontentloaded')
        input('Log in manually in the browser, including MFA. Then press Enter here. ')
        page.goto(args.project_url, wait_until='domcontentloaded')
        input('Verify account, project VericoMedia, and access in the browser. Press Enter to continue. ')
        if page.url.rstrip('/') != args.project_url.rstrip('/'):
            raise RuntimeError('Unexpected page or login redirect; session not saved')
        confirm = input('Type SAVE SESSION to store sensitive state locally: ')
        if confirm != 'SAVE SESSION':
            raise RuntimeError('Cancelled')
        state = context.storage_state(indexed_db=True)
        # Drop unrelated domains from the reusable state.
        state['cookies'] = [c for c in state['cookies'] if c['domain'].lstrip('.') == 'tilda.cc'
                            or c['domain'].endswith('.tilda.cc')]
        state['origins'] = [o for o in state['origins']
                            if urlsplit(o['origin']).hostname == 'tilda.cc']
        fd = os.open(args.state, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(state, output)
        context.close()
        browser.close()
    print('Session saved locally with mode 0600. Never upload it as a workflow artifact.')


if __name__ == '__main__':
    main()
