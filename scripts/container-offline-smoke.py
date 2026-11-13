"""Trusted packaging check; no network, user profile, or model API is involved."""
import hashlib,json,os
from playwright.sync_api import sync_playwright
assert os.getuid()==10001
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page();page.set_content('<h1>HoundBrowser controlled fixture</h1><input aria-label="Note"><button onclick="document.querySelector(\'h1\').textContent=\'Updated\'">Update</button>')
    page.get_by_label('Note').fill('synthetic data');page.get_by_role('button',name='Update').click();assert page.locator('h1').inner_text()=='Updated'
    image=page.screenshot();assert len(image)>100
    browser.close()
print(json.dumps({'offlineChromiumPassed':True,'nonRootUid':os.getuid(),'screenshotSha256':hashlib.sha256(image).hexdigest()}))
