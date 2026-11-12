import { spawn } from 'node:child_process';
import { writeFileSync, mkdirSync, existsSync, readFileSync } from 'node:fs';
import { setTimeout as sleep } from 'node:timers/promises';

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PROFILE = 'C:/Users/DELL/AppData/Local/Temp/chrome-cdp-huashu-' + Date.now();
const PAGE_URL = process.env.DISPATCH_URL || 'file:///E:/ops-conductor/design/cross-border-dispatch/index.html';
const OUT = 'E:/ops-conductor/design/cross-border-dispatch/screenshots';
mkdirSync(OUT, { recursive: true });

const chrome = spawn(CHROME, [
  '--headless=new',
  '--disable-gpu',
  '--no-first-run',
  '--no-default-browser-check',
  '--remote-debugging-port=0',
  `--user-data-dir=${PROFILE}`,
  '--hide-scrollbars',
  'about:blank'
], { stdio: 'ignore' });

async function waitForDevtools() {
  for (let i = 0; i < 100; i++) {
    try {
      const file = `${PROFILE}/DevToolsActivePort`;
      if (existsSync(file)) {
        const text = readFileSync(file, 'utf8').trim();
        const port = text.split(String.fromCharCode(10))[0];
        const res = await fetch(`http://127.0.0.1:${port}/json/list`);
        if (res.ok) return await res.json();
      }
    } catch {}
    await sleep(150);
  }
  throw new Error('DevTools endpoint not ready');
}

const targets = await waitForDevtools();
const page = targets.find(t => t.type === 'page');
if (!page) throw new Error('No page target');

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  ws.addEventListener('open', resolve, { once: true });
  ws.addEventListener('error', reject, { once: true });
});

let seq = 0;
const pending = new Map();
const consoleErrors = [];
ws.addEventListener('message', event => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(new Error(JSON.stringify(msg.error)));
    else resolve(msg.result);
    return;
  }
  if (msg.method === 'Runtime.exceptionThrown') {
    consoleErrors.push(msg.params.exceptionDetails?.text || 'exception');
  }
  if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
    consoleErrors.push(msg.params.args.map(a => a.value ?? a.description).join(' '));
  }
});
function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression) {
  const out = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  return out.result?.value;
}
async function shot(name) {
  const data = (await send('Page.captureScreenshot', { format: 'png', fromSurface: true })).data;
  writeFileSync(`${OUT}/${name}.png`, Buffer.from(data, 'base64'));
}
async function fullShot(name, width = 375) {
  const height = await evaluate('Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)');
  const data = (await send('Page.captureScreenshot', {
    format: 'png',
    fromSurface: true,
    captureBeyondViewport: true,
    clip: { x: 0, y: 0, width, height, scale: 1 }
  })).data;
  writeFileSync(`${OUT}/${name}.png`, Buffer.from(data, 'base64'));
}

await send('Page.enable');
await send('Runtime.enable');
await send('Emulation.setDeviceMetricsOverride', {
  width: 375, height: 812, deviceScaleFactor: 2, mobile: true,
  screenWidth: 375, screenHeight: 812
});
await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
await send('Page.navigate', { url: PAGE_URL });
await sleep(2200);

const metrics = await evaluate(`({
  vw: innerWidth,
  vh: innerHeight,
  scrollWidth: document.documentElement.scrollWidth,
  bodyScrollWidth: document.body.scrollWidth,
  scrollHeight: document.documentElement.scrollHeight,
  title: document.title,
  flowNote: document.querySelector('#flowNote')?.textContent,
  apiStatus: document.querySelector('#apiStatus')?.textContent,
  apiStatusClass: document.querySelector('#apiStatus')?.className,
  approvalCount: document.querySelector('#approvalCount')?.textContent,
  stageDetail: document.querySelector('#stageDetail h3')?.textContent.trim()
})`);

await shot('mobile-375x812');
await fullShot('mobile-full', 375);

// click settlement stage
await evaluate(`document.querySelector('.stage[data-stage="settlement"]').click()`);
await sleep(250);
const stageAfterClick = await evaluate(`document.querySelector('#stageDetail h3')?.textContent.trim()`);

// approve budget
await evaluate(`document.querySelector('.approval[data-id="budget"] button[data-decision="approve"]').click()`);
await sleep(250);
const approvalAfter = await evaluate(`({
  count: document.querySelector('#approvalCount')?.textContent,
  decided: document.querySelector('.approval[data-id="budget"]')?.className,
  stamp: document.querySelector('.approval[data-id="budget"] .stamp')?.textContent
})`);

// open exception drawer
await evaluate(`document.querySelector('[data-exception="ORD-01"]').click()`);
await sleep(600);
const drawerAfter = await evaluate(`({
  hidden: document.querySelector('#drawer')?.hidden,
  open: document.querySelector('#drawer')?.className,
  title: document.querySelector('#drawerTitle')?.textContent,
  phases: document.querySelectorAll('#drawerBody .drawer-phase').length
})`);
await shot('mobile-drawer');

// close drawer
await evaluate(`document.querySelector('#drawerClose').click()`);
await sleep(400);

// reset approvals
await evaluate(`document.querySelector('#resetApprovals').click()`);
await sleep(250);
const approvalReset = await evaluate(`({
  count: document.querySelector('#approvalCount')?.textContent,
  decided: document.querySelectorAll('.approval.decided').length,
  flowNote: document.querySelector('#flowNote')?.textContent
})`);

// clean mobile drawer on a fresh load
await send('Page.navigate', { url: PAGE_URL });
await sleep(2200);
await evaluate(`document.querySelector('[data-exception="ORD-01"]').click()`);
await sleep(600);
await shot('mobile-drawer');
await evaluate(`document.querySelector('#drawerClose').click()`);
await sleep(400);

// desktop viewport screenshots via emulation, fresh load
await send('Emulation.setDeviceMetricsOverride', {
  width: 1440, height: 900, deviceScaleFactor: 1, mobile: false,
  screenWidth: 1440, screenHeight: 900
});
await send('Page.navigate', { url: PAGE_URL });
await sleep(2200);
await shot('desktop-1440x900');
await fullShot('desktop-full', 1440);

// reopen drawer at desktop
await evaluate(`document.querySelector('[data-exception="ORD-01"]').click()`);
await sleep(600);
await shot('drawer-ord01');
await evaluate(`document.querySelector('#drawerClose').click()`);
await sleep(300);

console.log(JSON.stringify({
  metrics,
  stageAfterClick,
  approvalAfter,
  drawerAfter,
  approvalReset,
  consoleErrors
}, null, 2));

ws.close();
chrome.kill();
process.exit(0);
