// Isolated real-component browser fixture, not a Proxmox integration test.
// Requires AppImage dependencies, esbuild, playwright + Chromium, and a completed frontend build.
// Run: node tests/test_borg_ssh_browser.cjs /absolute/path/to/evidence-directory
// All navigation/assets/API requests are intercepted BEFORE navigation; nothing reaches a host.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createRequire } = require('node:module');
const app = path.resolve(__dirname, '../AppImage');
const req = createRequire(path.join(app, 'package.json'));
const { build } = req('esbuild');
const { chromium } = req('playwright');
const out = path.resolve(process.argv[2] || 'borg-browser-evidence');
fs.mkdirSync(out, { recursive: true });
const en = JSON.parse(fs.readFileSync(path.join(app, 'messages/en/common.json')));
const cssDir = process.env.BORG_SSH_CSS_DIR || path.join(app, 'out/_next/static/css');
const css = fs.readdirSync(cssDir).filter(p => p.endsWith('.css')).map(p => fs.readFileSync(path.join(cssDir, p), 'utf8')).join('\n');
const expanded = {
  sshUserHelpMessage: 'FIXTURE REMOTE ACCOUNT: the account on the remote repository host, not a local command.',
  sshKeyHelpMessage: '{action}: FIXTURE ACTION FIRST. Review the public-key line before adding it to the remote account authorized_keys file. The private key remains on this host.',
  sshKeySetupTitle: 'FIXTURE SSH key setup',
  sshKeySetupHelp: 'FIXTURE INITIAL: creates a missing local key, otherwise reads its public key. Nothing is installed on the remote host by this action.',
  sshAuthorizedKeyHelp: '{user}: FIXTURE USER FIRST. Review the following public-key line before manually adding it to the remote account ~/.ssh/authorized_keys.',
};
const records = [], unexpected = [], errors = [], requests = [];
(async () => {
  const bundle = await build({
    stdin: { contents: `import React from 'react';
import {createRoot} from 'react-dom/client';
import {I18nProvider} from './lib/i18n/provider';
import {BorgFixtureDialog} from './components/host-backup';
const editing = new URLSearchParams(location.search).has('new') ? null : {kind:'borg',name:'fixture',repository:'ssh://borg@backup.example.invalid/backup/repo',ssh_key_path:'/root/.ssh/proxmenux_borg',encrypt_mode:'none'};
createRoot(document.getElementById('root')).render(<I18nProvider><BorgFixtureDialog type="borg" editing={editing} onClose={()=>{}} onSaved={()=>{throw Error('Save must never be submitted')}} /></I18nProvider>);`,
      resolveDir: app, sourcefile: 'borg-fixture.tsx', loader: 'tsx' },
    bundle: true, write: false, outfile: 'fixture.js', format: 'iife', platform: 'browser', jsx: 'automatic',
    define: { 'process.env.NODE_ENV': '"development"', 'process.env.NEXT_PUBLIC_API_PORT': '"8008"' },
    plugins: [{ name: 'test-only-exports-and-synthetic-locale', setup(b) {
      b.onLoad({ filter: /host-backup\.tsx$/ }, args => ({ contents: fs.readFileSync(args.path, 'utf8') + '\nexport { AddDestinationDialog as BorgFixtureDialog };', loader: 'tsx' }));
      b.onLoad({ filter: /messages\/(de|it)\/common\.json$/ }, args => {
        const locale = JSON.parse(fs.readFileSync(args.path));
        if (args.path.endsWith('/de/common.json')) {
          Object.assign(locale.backup.destinations, expanded);
          locale.backup.actions.prepareSshKey = 'Prepare fixture key';
        } else {
          // Unconditional missing-key fixture survives future automated translations.
          for (const key of Object.keys(expanded)) delete locale.backup.destinations[key];
          delete locale.backup.actions.prepareSshKey;
        }
        return { contents: JSON.stringify(locale), loader: 'json' };
      });
    }}],
  });
  const javascript = bundle.outputFiles[0].text;
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      for (const theme of ['light', 'dark']) for (const language of ['en', 'it', 'de']) {
        const id = `${viewport.width}-${theme}-${language}`;
        const context = await browser.newContext({ viewport, colorScheme: theme, serviceWorkers: 'block' });
        const page = await context.newPage();
        page.on('pageerror', e => errors.push({ id, message: e.message }));
        let release = null, calls = 0;
        const fixtureLine = 'command="borg serve --restrict-to-path /backup/repo",restrict ssh-ed25519 AAAA-fixture-only <literal>\n';
        // No route.continue() exists: unexpected traffic is aborted and fails the test.
        await context.route('**/*', async route => {
          const request = route.request(), url = new URL(request.url());
          requests.push({ id, method: request.method(), url: request.url(), body: request.postData() });
          if (url.origin === 'https://borg.fixture.invalid' && request.method() === 'GET') {
            if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html class="${theme === 'dark' ? 'dark' : ''}" data-theme="${theme}"><head><link rel="stylesheet" href="/fixture.css"></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>` });
            if (url.pathname === '/fixture.js') return route.fulfill({ contentType: 'application/javascript', body: javascript });
            if (url.pathname === '/fixture.css') return route.fulfill({ contentType: 'text/css', body: css });
            if (url.pathname === '/api/host-backups/destinations') return route.fulfill({ json: { pbs: [], borg: [], local: { entries: [] } } });
            if (url.pathname === '/api/host-backups/usb-drives') return route.fulfill({ json: { drives: [] } });
          }
          if (url.origin === 'https://borg.fixture.invalid' && url.pathname === '/api/host-backups/ssh-keys/generate' && request.method() === 'POST') {
            calls++;
            const body = request.postDataJSON();
            records.push({ id, fixture: calls === 1 ? 'fresh-key' : calls === 2 ? 'existing-key' : 'error', body });
            await new Promise(resolve => { release = resolve; });
            release = null;
            if (calls === 3) return route.fulfill({ status: 500, json: { error: 'Fixture: public key unavailable' } });
            return route.fulfill({ json: { public_key: 'ssh-ed25519 AAAA-fixture-only', authorized_keys_line: fixtureLine } });
          }
          unexpected.push({ id, method: request.method(), url: request.url() });
          return route.abort('blockedbyclient');
        });
        await context.addInitScript(({ language }) => {
          localStorage.setItem('proxmenux-ui-language', language);
        }, { language });
        await page.goto('https://borg.fixture.invalid/');
        await page.waitForFunction(language => document.documentElement.lang === language, language);
        assert.equal(await page.evaluate(() => document.documentElement.classList.contains('dark')), theme === 'dark');
        await page.locator('#borgKeyPath').waitFor();
        const action = language === 'de' ? 'Prepare fixture key' : 'Prepare key';
        const button = page.getByRole('button', { name: action, exact: true });
        await button.waitFor();
        assert.equal(await page.locator('#borgKeyPath').inputValue(), '/root/.ssh/proxmenux_borg');
        assert.ok((await page.locator('[role=dialog]').innerText()).includes(language === 'de' ? 'FIXTURE INITIAL' : en.backup.destinations.sshKeySetupHelp));
        await button.evaluate(button => button.parentElement.parentElement.scrollIntoView({ block: 'center' }));
        assert.equal(await button.evaluate(button => {
          const panel = button.parentElement.parentElement;
          return [panel, ...panel.querySelectorAll('p, button, span')].every(e => e.scrollWidth <= e.clientWidth + 1 || getComputedStyle(e).display === 'inline');
        }), true, `${id}: initial setup guidance fits`);
        await page.screenshot({ animations: 'disabled', path: path.join(out, `${id}-initial.png`) });
        // Blank input remains disabled; no attempt is sent.
        await page.locator('#borgKeyPath').fill('');
        assert.equal(await button.isDisabled(), true);
        assert.equal(calls, 0);
        const longPath = '/fixture/long-local-private-key-directory/'.repeat(6) + 'key';
        await page.locator('#borgKeyPath').fill(longPath);
        await page.locator('#borgSshUser').fill('root');
        await button.click();
        await page.waitForFunction(() => document.querySelector('button svg.animate-spin'));
        assert.equal(await button.isDisabled(), true);
        assert.equal(await button.innerText(), action);
        assert.ok(release, 'intercepted mock POST is pending');
        release();
        await page.locator('textarea[readonly]').waitFor();
        assert.equal(await page.locator('textarea[readonly]').inputValue(), fixtureLine);
        assert.ok((await page.locator('[role=dialog]').innerText()).includes(language === 'de' ? 'root: FIXTURE USER FIRST' : 'for root on the remote host.'));
        // Changing input preserves the last response: characterize, do not change stale-response behavior.
        await page.locator('#borgKeyPath').fill('/fixture/already-existing-private-key');
        await page.locator('#borgSshUser').fill('<archive-user>');
        assert.equal(await page.locator('textarea[readonly]').inputValue(), fixtureLine);
        await button.click();
        await page.waitForFunction(() => document.querySelector('button svg.animate-spin'));
        assert.equal(await button.innerText(), action);
        release();
        await page.waitForFunction(() => !document.querySelector('button svg.animate-spin'));
        assert.equal(await page.locator('textarea[readonly]').inputValue(), fixtureLine);
        assert.equal(await page.locator('archive-user').count(), 0);
        assert.ok((await page.locator('[role=dialog]').innerText()).includes('<archive-user>'));
        await button.evaluate(button => button.parentElement.parentElement.scrollIntoView({ block: 'center' }));
        // Measure the changed guidance, its action, and result area, not unrelated whole-dialog layout.
        const layout = await button.evaluate(button => {
          const panel = button.parentElement.parentElement;
          const help = document.querySelector('#borgKeyPath').parentElement.querySelector('p');
          const userHelp = document.querySelector('#borgSshUser').parentElement.querySelector('p');
          const elements = [panel, button.parentElement, button, help, userHelp, panel.querySelector('p'), panel.querySelector('textarea')];
          return elements.map(e => {
            const r = e.getBoundingClientRect();
            return { tag: e.tagName, text: e.tagName === 'TEXTAREA' ? '[fixture public-key line]' : e.textContent, client: e.clientWidth, scroll: e.scrollWidth, left: r.left, right: r.right, viewport: innerWidth };
          });
        });
        for (const e of layout.filter(e => e.tag !== 'TEXTAREA')) {
          assert.ok(e.scroll <= e.client + 1, `${id}: guidance overflow ${JSON.stringify(e)}`);
          assert.ok(e.left >= 0 && e.right <= viewport.width + 1, `${id}: guidance outside viewport`);
        }
        await page.screenshot({ animations: 'disabled', path: path.join(out, `${id}-result.png`) });
        records.push({ id, fixture: 'layout', layout });
        await button.click();
        await page.waitForFunction(() => document.querySelector('button svg.animate-spin'));
        release();
        await page.getByText('Fixture: public key unavailable', { exact: true }).waitFor();
        assert.equal(await button.isEnabled(), true);
        assert.equal(await button.innerText(), action);
        assert.equal(await page.locator('textarea[readonly]').inputValue(), fixtureLine);
        assert.equal(calls, 3);
        assert.deepEqual(records.filter(r => r.id === id && r.body).map(r => r.body), [
          { key_path: longPath, remote_path: '/backup/repo' },
          { key_path: '/fixture/already-existing-private-key', remote_path: '/backup/repo' },
          { key_path: '/fixture/already-existing-private-key', remote_path: '/backup/repo' },
        ], 'real component submits the current path, not a fixed path or the previous response');
        await context.close();
      }
    }
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
    const posts = requests.filter(r => r.method === 'POST');
    assert.equal(posts.length, 36);
    assert.ok(posts.every(p => p.url.endsWith('/ssh-keys/generate')));
    console.log('PASS: 12 real-component/provider browser scenarios; desktop/mobile × light/dark × English/Italian fallback/synthetic expanded translation; 36 mocked POSTs, 0 real API calls.');
  } finally {
    fs.writeFileSync(path.join(out, 'browser-results.json'), JSON.stringify({ records, requests, unexpected, errors }, null, 2));
    await browser.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
