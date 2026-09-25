// End-to-end scenarios against a WordPress running the plugin + tests/fixture-wms-test-site.php.
// Usage: BASE=http://127.0.0.1:9400 node tests/e2e.mjs
import { chromium } from 'playwright';
import assert from 'node:assert/strict';

const BASE = process.env.BASE || 'http://127.0.0.1:9400';
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
let failed = 0;

async function rows() { return (await fetch(`${BASE}/wp-json/wmstest/v1/rows`)).json(); }
async function reset() { await fetch(`${BASE}/wp-json/wmstest/v1/reset`); }
async function waitRows(n) {
  for (let i = 0; i < 40; i++) { const r = await rows(); if (r.length >= n) return r; await new Promise(s => setTimeout(s, 250)); }
  return rows();
}

/** Fresh visitor. External WhatsApp/GHL navigations are captured instead of loaded. */
async function visitor() {
  const ctx = await browser.newContext();
  const external = [];
  await ctx.route(/wa\.me|whatsapp\.com|leadconnectorhq\.com|msgsndr\.com/, route => {
    external.push(route.request().url());
    route.fulfill({ status: 200, contentType: 'text/html', body: 'external' });
  });
  const page = await ctx.newPage();
  return { ctx, page, external };
}

async function scenario(name, fn) {
  await reset();
  try { await fn(); console.log(`PASS  ${name}`); }
  catch (e) { failed++; console.log(`FAIL  ${name}\n      ${e.message.split('\n').join('\n      ')}`); }
}

const cookieOf = async ctx => {
  const c = (await ctx.cookies()).find(c => c.name === 'wms_attr');
  return c ? JSON.parse(decodeURIComponent(c.value)) : null;
};

/* 1 ─ /might → home → speakers → get-ticket → HRD form */
await scenario('Affiliate /might survives browsing and reaches the HRD Corp form', async () => {
  const { ctx, page } = await visitor();
  await page.goto(`${BASE}/might`);
  await page.goto(`${BASE}/`);
  await page.goto(`${BASE}/speakers`);
  await page.goto(`${BASE}/get-ticket`);
  const hidden = await page.$eval('#hrd-form', f => Object.fromEntries(new FormData(f)));
  assert.equal(hidden.affiliate, 'MIGHT');
  assert.equal(hidden.utm_source, 'affiliate');
  assert.match(hidden.wms_ref, /^WMS-[A-Z2-9]{6}$/);
  assert.equal(hidden.wms_route, '*/might > / > /speakers > /get-ticket');
  await page.fill('#hrd-form [name=full_name]', 'Aminah Test');
  await page.fill('#hrd-form [name=email]', 'aminah@example.com');
  await page.fill('#hrd-form [name=phone]', '0123000111');
  await page.click('#hrd-form button');
  const [r] = await waitRows(1);
  assert.equal(r.type, 'form_submit');
  assert.equal(r.label, 'HRD Corp Form');
  assert.equal(r.affiliate, 'MIGHT');
  assert.equal(r.source, 'affiliate');
  assert.equal(r.contact_email, 'aminah@example.com');
  assert.equal(r.contact_phone, '0123000111');
  assert.equal(r.contact_name, 'Aminah Test');
  assert.equal(r.route, '*/might > / > /speakers > /get-ticket');
  console.log('      row:', { affiliate: r.affiliate, source: r.source, route: r.route, ref: r.visitor_ref });
  await ctx.close();
});

/* 2 ─ /might?utm_source=facebook&utm_campaign=might_ads → WhatsApp admin */
await scenario('Affiliate + UTM kept separately on a WhatsApp Contact Admin click', async () => {
  const { ctx, page, external } = await visitor();
  await page.goto(`${BASE}/might?utm_source=facebook&utm_medium=paid_social&utm_campaign=might_ads`);
  await page.goto(`${BASE}/speakers`);
  await page.click('#wa-admin');
  const [r] = await waitRows(1);
  assert.equal(r.type, 'whatsapp');
  assert.equal(r.label, 'Contact Admin');
  assert.equal(r.affiliate, 'MIGHT');
  assert.equal(r.source, 'facebook');
  assert.equal(r.campaign, 'might_ads');
  assert.equal(r.location, '#contact');
  await page.waitForTimeout(300);
  const text = new URL(external.find(u => u.includes('wa.me'))).searchParams.get('text');
  assert.match(text, /^Hi admin, saya nak tanya WMS\n\n\[Ref WMS-[A-Z2-9]{6} · MIGHT · facebook\/might_ads\]$/);
  console.log('      WhatsApp text:', JSON.stringify(text));
  await ctx.close();
});

/* 3 ─ direct visitor → Contact Salesperson (no text prefill) */
await scenario('Direct visitor is recorded as "direct", never blank', async () => {
  const { ctx, page, external } = await visitor();
  await page.goto(`${BASE}/`);
  await page.click('#wa-sales');
  const [r] = await waitRows(1);
  assert.equal(r.type, 'whatsapp');
  assert.equal(r.label, 'Contact Salesperson');
  assert.equal(r.affiliate, '');
  assert.equal(r.source, 'direct');
  await page.waitForTimeout(300);
  const u = new URL(external.find(u => u.includes('whatsapp.com')));
  assert.equal(u.searchParams.get('phone'), '60198765432');
  assert.match(u.searchParams.get('text'), /^\[Ref WMS-[A-Z2-9]{6} · direct\]$/);
  await ctx.close();
});

/* 4 ─ /ibuhanim is a server redirect to home → VIP ticket CTA */
await scenario('Redirecting affiliate link /ibuhanim still credits Ibu Hanim (VIP ticket CTA)', async () => {
  const { ctx, page } = await visitor();
  const resp = await page.goto(`${BASE}/ibuhanim`);
  assert.equal(new URL(resp.url()).pathname, '/');          // existing redirect still works
  await page.goto(`${BASE}/get-ticket`);
  await page.click('text=VIP Ticket');
  const [r] = await waitRows(1);
  assert.equal(r.type, 'add_to_cart');
  assert.equal(r.label, 'VIP Ticket');
  assert.equal(r.affiliate, 'Ibu Hanim');
  assert.equal(r.source, 'affiliate');
  assert.equal(r.route, '*/ibuhanim > / > /get-ticket');
  await ctx.close();
});

/* 5 ─ later UTM visit must not overwrite the affiliate */
await scenario('A later Google UTM visit changes source but keeps affiliate MIGHT', async () => {
  const { ctx, page } = await visitor();
  await page.goto(`${BASE}/might`);
  await page.goto(`${BASE}/?utm_source=google&utm_medium=cpc&utm_campaign=wms_search`);
  const c = await cookieOf(ctx);
  assert.equal(c.an, 'MIGHT');
  assert.equal(c.s, 'google');
  assert.equal(c.c, 'wms_search');
  assert.equal(c.f.s, 'affiliate');                          // first touch preserved
  await page.click('text=Standard Ticket');
  const [r] = await waitRows(1);
  assert.equal(r.affiliate, 'MIGHT');
  assert.equal(r.source, 'google');
  assert.equal(r.first_touch, 'MIGHT / affiliate');
  await ctx.close();
});

/* 6 ─ GHL iframe/link, Elementor hidden field, search form untouched */
await scenario('GHL iframe + link carry attribution; Elementor field filled; search form untouched', async () => {
  const { ctx, page } = await visitor();
  await page.goto(`${BASE}/might?utm_source=instagram&utm_campaign=story`);
  const src = await page.getAttribute('#ghl-frame', 'data-src');
  const u = new URL(src);
  assert.equal(u.searchParams.get('affiliate'), 'MIGHT');
  assert.equal(u.searchParams.get('utm_source'), 'instagram');
  assert.equal(u.searchParams.get('utm_campaign'), 'story');
  assert.equal(u.searchParams.get('notrack'), '1');            // existing params kept
  assert.match(u.searchParams.get('wms_ref'), /^WMS-/);
  const link = new URL(await page.getAttribute('#ghl-link', 'href'));
  assert.equal(link.searchParams.get('affiliate'), 'MIGHT');
  assert.equal(await page.inputValue('#corp-form [name="form_fields[affiliate]"]'), 'MIGHT');
  assert.equal(await page.$$eval('#search input[type=hidden]', e => e.length), 0);
  await page.click('#ghl-link');
  const [r] = await waitRows(1);
  assert.equal(r.type, 'cta_click');
  assert.equal(r.label, 'Student enquiry form');
  assert.equal(r.affiliate, 'MIGHT');
  await ctx.close();
});

/* 7 ─ chat widget opening WhatsApp via window.open */
await scenario('WhatsApp opened by a chat widget (window.open) is logged and referenced', async () => {
  const { ctx, page, external } = await visitor();
  await page.goto(`${BASE}/?ref=peoplelogy&utm_source=linkedin`);
  const [popup] = await Promise.all([ctx.waitForEvent('page'), page.click('#wa-widget')]);
  await popup.waitForLoadState();
  const [r] = await waitRows(1);
  assert.equal(r.type, 'whatsapp');
  assert.equal(r.affiliate, 'Peoplelogy');
  assert.equal(r.source, 'linkedin');
  assert.match(new URL(external.find(u => u.includes('60111111111'))).searchParams.get('text'), /^Hello\n\n\[Ref WMS-.{6} · Peoplelogy · linkedin\]$/);
  await ctx.close();
});

/* 8 ─ organic referral, then the same visitor comes back direct */
await scenario('Google organic referral is kept when the visitor returns directly', async () => {
  const { ctx, page } = await visitor();
  await page.goto(`${BASE}/speakers`, { referer: 'https://www.google.com/' });
  await page.goto(`${BASE}/`);                                // later direct visit
  let c = await cookieOf(ctx);
  assert.equal(c.s, 'google'); assert.equal(c.m, 'organic'); assert.equal(c.a, undefined);
  await page.click('#wa-float');
  const [r] = await waitRows(1);
  assert.equal(r.label, 'WhatsApp');                          // label from icon alt text
  assert.equal(r.source, 'google');
  assert.equal(r.medium, 'organic');
  await ctx.close();
});

/* 9 ─ a different affiliate link later replaces the earlier one */
await scenario('Latest affiliate link wins (/might then /annems)', async () => {
  const { ctx, page } = await visitor();
  await page.goto(`${BASE}/might`);
  await page.goto(`${BASE}/?ref=annems`);
  const c = await cookieOf(ctx);
  assert.equal(c.an, 'Annems');
  assert.equal(c.f.a, 'might');                               // first touch remembers MIGHT
  await ctx.close();
});

/* 10 ─ REST endpoint rejects junk */
await scenario('Event endpoint rejects unknown types (e.g. fake purchases)', async () => {
  const bad = await fetch(`${BASE}/wp-json/wms/v1/event`, { method: 'POST', body: JSON.stringify({ type: 'purchase', amount: 9999 }) });
  assert.equal(bad.status, 400);
  assert.equal((await rows()).length, 0);
});

/* 11 ─ WooCommerce order + Elementor + CF7 using the visitor's real cookie */
await scenario('WooCommerce order, Elementor corporate form and CF7 email carry the attribution', async () => {
  const { ctx, page } = await visitor();
  await page.goto(`${BASE}/ibuhanim?utm_source=facebook&utm_campaign=WMS%20September`);
  await page.goto(`${BASE}/get-ticket`);
  const resp = await page.request.get(`${BASE}/wp-json/wmstest/v1/integrations`);
  const out = await resp.json();
  assert.equal(out.order_meta._wms_affiliate, 'Ibu Hanim');
  assert.equal(out.order_meta._wms_source, 'facebook');
  assert.equal(out.order_meta._wms_campaign, 'WMS September');
  assert.equal(out.order_meta._wms_route, '*/ibuhanim > / > /get-ticket');
  assert.match(out.orders_column, /Ibu Hanim \| facebook \/ WMS September/);
  assert.equal(out.admin_email._wms_affiliate.value, 'Ibu Hanim');
  assert.equal(Array.isArray(out.customer_email) ? out.customer_email.length : Object.keys(out.customer_email).length, 0);
  assert.equal(out.elementor_fields.affiliate, 'Ibu Hanim');          // cookie beats a spoofed hidden value
  assert.equal(out.elementor_fields.utm_campaign, 'WMS September');
  assert.match(out.cf7_body, /Affiliate: Ibu Hanim\nSource: facebook/);
  const r = await rows();
  const purchases = r.filter(x => x.type === 'purchase');
  assert.equal(purchases.length, 1);                                   // processing + completed → logged once
  assert.equal(Number(purchases[0].amount), 1500);
  assert.equal(purchases[0].label, 'Order #1234 — 2× VIP Ticket');
  assert.equal(purchases[0].affiliate, 'Ibu Hanim');
  assert.equal(purchases[0].contact_phone, '0199998888');
  const form = r.find(x => x.type === 'form_submit');
  assert.equal(form.label, 'Corporate Bulk Form');
  assert.equal(form.contact_email, 'hr@company.my');
  assert.equal(form.contact_name, 'Encik Korporat');
  assert.equal(form.affiliate, 'Ibu Hanim');
  console.log('      meta box:\n        ' + out.meta_box.trim().split('\n').map(l => l.trim()).join('\n        '));
  await ctx.close();
});

/* 12 ─ no cookie at checkout, but the affiliate's coupon was used */
await scenario('Order with an affiliate coupon (no cookie) credits that affiliate', async () => {
  const out = await (await fetch(`${BASE}/wp-json/wmstest/v1/integrations?coupon=LINCGROUP`)).json();
  assert.equal(out.order_meta._wms_affiliate, 'Linc Group (coupon)');
  assert.equal(out.order_meta._wms_source, 'direct');
});

await browser.close();
console.log(failed ? `\n${failed} scenario(s) failed` : '\nAll scenarios passed');
process.exit(failed ? 1 : 0);
