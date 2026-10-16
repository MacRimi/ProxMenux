// Render the real help component; only its translation provider is replaced.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const source = fs.readFileSync('AppImage/components/apprise-service-help.tsx', 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
const english = JSON.parse(fs.readFileSync('AppImage/messages/en/common.json'));
function resolve(catalog, key) { return key.split('.').reduce((value, part) => value?.[part], catalog); }
for (const locale of ['en', 'es', 'de', 'fr', 'it', 'pt', 'sk', 'sv', 'missing']) {
  const catalog = locale === 'missing' ? {} : JSON.parse(fs.readFileSync(`AppImage/messages/${locale}/common.json`));
  const context = { exports: {}, require: name => name === '../lib/i18n/provider' ? {
    useT: () => key => resolve(catalog, key) ?? resolve(english, key),
  } : require(name) };
  vm.runInNewContext(js, context);
  const html = renderToStaticMarkup(React.createElement(context.exports.AppriseServiceHelp));
  assert.ok(html.includes('https://hooks.slack.com/services/TOKEN_A/TOKEN_B/TOKEN_C'));
  assert.ok(html.includes('matrixs://USER:PASSWORD@matrix.example.com/!ROOM_ID:matrix.example.com'));
  assert.ok(html.includes('https://appriseit.com/services/slack/'));
  assert.ok(html.includes('https://appriseit.com/services/matrix/'));
  assert.ok(!html.includes('settings.notifications.'), `${locale}: no unresolved labels`);
}
for (const [, key] of source.matchAll(/t\("([^"]+)"\)/g)) assert.ok(resolve(english, key), key);
assert.ok(!source.includes('onChange') && !source.includes('fetch(') && !source.includes('updateChannel'));
const settings = fs.readFileSync('AppImage/components/notification-settings.tsx', 'utf8');
const section = settings.slice(settings.indexOf('<TabsContent value="apprise"'), settings.indexOf('</TabsContent>', settings.indexOf('<TabsContent value="apprise"')));
for (const part of ['<AppriseServiceHelp />', 'renderChannelCategories("apprise")', 'handleTest("apprise")']) assert.ok(section.includes(part));
console.log('PASS: real provider-help JSX, shipped locales and English fallback, no secret mutation, native category/test controls retained');
