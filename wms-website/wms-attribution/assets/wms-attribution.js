/*!
 * WMS Attribution — one consistent source/affiliate tracker for every conversion.
 *
 * What it does on every page:
 *  1. Works out the visitor's affiliate (e.g. /might, ?ref=might) and traffic source (UTM,
 *     click IDs, referrer, else "direct") and keeps them in one first-party cookie (wms_attr).
 *  2. Records the page route (last pages visited) so every conversion carries its journey.
 *  3. Fills hidden attribution fields in every form (Elementor, CF7, WPForms, Fluent, Gravity,
 *     WooCommerce checkout, custom HTML forms).
 *  4. Appends attribution to GHL / LeadConnector iframes and links, so GHL contacts get it.
 *  5. Adds a short reference to WhatsApp messages and logs every WhatsApp / CTA click.
 *
 * Affiliate and traffic source are stored separately: UTM never overwrites the affiliate.
 */
(function (window, document) {
  'use strict';

  var CFG = window.WMS_ATTR_CFG || {};
  var COOKIE = CFG.cookie || 'wms_attr';
  var DAYS = parseInt(CFG.days, 10) || 90;
  var AFFILIATES = CFG.affiliates || {};            // { slug: "Display Name" }
  var AFF_PARAMS = CFG.affParams || ['ref', 'aff', 'affiliate', 'affid', 'reseller'];
  var ROUTE_MAX = 15;
  var GHL_HOSTS = ['leadconnectorhq.com', 'msgsndr.com', 'gohighlevel.com', 'highlevel.com']
    .concat(CFG.ghlHosts || []);
  var SITE_HOSTS = [location.hostname.replace(/^www\./, '')].concat(CFG.siteHosts || []);

  /* ------------------------------------------------------------------ helpers */

  function now() { return Math.floor(Date.now() / 1000); }

  function clip(s, n) { s = (s == null ? '' : String(s)).trim(); return s.length > n ? s.slice(0, n) : s; }

  function slugify(s) {
    return clip(s, 60).toLowerCase().replace(/[^a-z0-9_-]+/g, '');
  }

  function readCookie() {
    var m = document.cookie.match(new RegExp('(?:^|; )' + COOKIE + '=([^;]*)'));
    if (!m) return null;
    try {
      var v = JSON.parse(decodeURIComponent(m[1]));
      return v && typeof v === 'object' ? v : null;
    } catch (e) { return null; }
  }

  function writeCookie(data) {
    var val = encodeURIComponent(JSON.stringify(data));
    var exp = new Date(Date.now() + DAYS * 864e5).toUTCString();
    var domain = CFG.cookieDomain ? '; domain=' + CFG.cookieDomain : '';
    document.cookie = COOKIE + '=' + val + '; expires=' + exp + '; path=/' + domain + '; SameSite=Lax' +
      (location.protocol === 'https:' ? '; Secure' : '');
  }

  function newRef() {
    var chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789', out = '';
    var rnd = window.crypto && window.crypto.getRandomValues
      ? window.crypto.getRandomValues(new Uint8Array(6)) : null;
    for (var i = 0; i < 6; i++) {
      out += chars[(rnd ? rnd[i] : Math.floor(Math.random() * 256)) % chars.length];
    }
    return 'WMS-' + out;
  }

  function hostOf(url) {
    try { return new URL(url, location.href).hostname.replace(/^www\./, ''); } catch (e) { return ''; }
  }

  function isSiteHost(h) {
    return !h || SITE_HOSTS.some(function (s) { return h === s || h.slice(-(s.length + 1)) === '.' + s; });
  }

  function isGhlHost(h) {
    return !!h && GHL_HOSTS.some(function (s) { return h === s || h.slice(-(s.length + 1)) === '.' + s; });
  }

  function currentPath() { return clip(location.pathname + location.search, 200); }

  function shortPath() { return clip(location.pathname, 80) || '/'; }

  /** Referrer domain -> [source, medium] when there is no UTM. */
  function classifyReferrer(h) {
    var rules = [
      [/(^|\.)google\./, 'google', 'organic'],
      [/(^|\.)bing\.com$/, 'bing', 'organic'],
      [/(^|\.)yahoo\./, 'yahoo', 'organic'],
      [/(^|\.)duckduckgo\.com$/, 'duckduckgo', 'organic'],
      [/(^|\.)(facebook\.com|fb\.com|fb\.me|m\.facebook\.com|l\.facebook\.com)$/, 'facebook', 'social'],
      [/(^|\.)instagram\.com$/, 'instagram', 'social'],
      [/(^|\.)(linkedin\.com|lnkd\.in)$/, 'linkedin', 'social'],
      [/(^|\.)(t\.co|twitter\.com|x\.com)$/, 'x', 'social'],
      [/(^|\.)tiktok\.com$/, 'tiktok', 'social'],
      [/(^|\.)(youtube\.com|youtu\.be)$/, 'youtube', 'social'],
      [/(^|\.)(whatsapp\.com|wa\.me)$/, 'whatsapp', 'social'],
      [/(^|\.)t\.me$|(^|\.)telegram\.org$/, 'telegram', 'social']
    ];
    for (var i = 0; i < rules.length; i++) {
      if (rules[i][0].test(h)) return [rules[i][1], rules[i][2]];
    }
    return [h, 'referral'];
  }

  /* ------------------------------------------------------------ attribution */

  var params = new URLSearchParams(location.search);

  function detectAffiliate() {
    for (var i = 0; i < AFF_PARAMS.length; i++) {
      var v = slugify(params.get(AFF_PARAMS[i]));
      if (v) return v;
    }
    var first = slugify(location.pathname.split('/')[1] || '');
    if (first && Object.prototype.hasOwnProperty.call(AFFILIATES, first)) return first;
    return '';
  }

  function affName(slug) {
    return AFFILIATES[slug] || slug.toUpperCase();
  }

  function update() {
    var d = readCookie() || {};
    var t = now();
    if (!d.v) d.v = newRef();
    if (!d.t) d.t = t;

    // 1) Affiliate — kept separately. A new affiliate link replaces the old one; UTM never does.
    var aff = detectAffiliate();
    if (aff) { d.a = aff; d.an = affName(aff); d.at = t; }
    else if (d.a && !d.an) { d.an = affName(d.a); }

    // 2) Traffic source — last non-direct touch wins; direct visits keep the previous source.
    var utm = {
      s: clip(params.get('utm_source'), 100), m: clip(params.get('utm_medium'), 100),
      c: clip(params.get('utm_campaign'), 150), n: clip(params.get('utm_content'), 150),
      k: clip(params.get('utm_term'), 100)
    };
    var refHost = hostOf(document.referrer);
    var external = document.referrer && !isSiteHost(refHost) && !isGhlHost(refHost);
    var touch = null;
    // The server already recorded this arrival (e.g. /might redirected to the homepage).
    var serverFresh = d.ss && t - (d.st || 0) < 30;
    delete d.ss;

    if (serverFresh) {
      touch = null;
    } else if (utm.s || utm.c || utm.m) {
      touch = { s: utm.s || (external ? classifyReferrer(refHost)[0] : (aff ? 'affiliate' : 'direct')),
        m: utm.m, c: utm.c, n: utm.n, k: utm.k };
    } else if (params.get('gclid') || params.get('gbraid') || params.get('wbraid')) {
      touch = { s: 'google', m: 'cpc', c: '', n: '', k: '' };
    } else if (params.get('fbclid')) {
      touch = { s: 'facebook', m: 'social', c: '', n: '', k: '' };
    } else if (params.get('ttclid')) {
      touch = { s: 'tiktok', m: 'cpc', c: '', n: '', k: '' };
    } else if (external) {
      var cr = classifyReferrer(refHost);
      touch = { s: cr[0], m: cr[1], c: '', n: '', k: '' };
    } else if (aff) {
      touch = { s: 'affiliate', m: 'affiliate_link', c: '', n: '', k: '' };
    } else if (!d.s) {
      touch = { s: 'direct', m: '(none)', c: '', n: '', k: '' };
    }

    if (touch) {
      d.s = touch.s; d.m = touch.m; d.c = touch.c; d.n = touch.n; d.k = touch.k;
      d.lp = currentPath();
      d.r0 = external ? clip(refHost, 80) : '';
      d.st = t;
    }

    // First touch is written once and never changed.
    if (!d.f) d.f = { a: d.a || '', s: d.s, c: d.c || '', l: d.lp || currentPath(), t: d.t };

    // 3) Route — pages visited, most recent last.
    var r = Array.isArray(d.r) ? d.r : [];
    var p = shortPath();
    if (touch || aff) {                         // '*' marks a new arrival (new source / affiliate link)
      if (r[r.length - 1] !== '*' + p) r.push('*' + p);
    } else if (r[r.length - 1] !== p && r[r.length - 1] !== '*' + p) r.push(p);
    d.r = r.slice(-ROUTE_MAX);

    writeCookie(d);
    return d;
  }

  var A = update();

  /** Flat, human-readable attribution used everywhere (fields, URLs, events). */
  function fields() {
    return {
      affiliate: A.an || '',
      affiliate_code: A.a || '',
      utm_source: A.s || 'direct',
      utm_medium: A.m || '',
      utm_campaign: A.c || '',
      utm_content: A.n || '',
      utm_term: A.k || '',
      landing_page: A.lp || '',
      referrer: A.r0 || '',
      wms_ref: A.v,
      wms_route: (A.r || []).join(' > '),
      first_touch: A.f ? [A.f.a ? affName(A.f.a) : '', A.f.s, A.f.c].filter(Boolean).join(' / ') : ''
    };
  }

  /* --------------------------------------------------------------- logging */

  function send(payload) {
    if (!CFG.endpoint) return;
    var body = JSON.stringify(payload);
    try {
      if (navigator.sendBeacon && navigator.sendBeacon(CFG.endpoint, new Blob([body], { type: 'text/plain' }))) return;
    } catch (e) { /* fall through */ }
    try {
      fetch(CFG.endpoint, { method: 'POST', body: body, keepalive: true, credentials: 'same-origin',
        headers: { 'Content-Type': 'text/plain' } });
    } catch (e) { /* ignore */ }
  }

  function track(type, label, extra) {
    var f = fields();
    var payload = Object.assign({ type: type, label: clip(label, 120), page: currentPath() }, f, extra || {});
    send(payload);
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push(Object.assign({ event: 'wms_conversion', wms_type: type, wms_label: payload.label }, f));
    if (typeof window.gtag === 'function') {
      window.gtag('event', 'wms_' + type, { wms_label: payload.label, affiliate: f.affiliate,
        source: f.utm_source, campaign: f.utm_campaign, wms_ref: f.wms_ref });
    }
  }

  window.WMSAttribution = { get: fields, track: track, raw: function () { return A; } };

  /* ------------------------------------------------------------ labelling */

  function labelOf(el) {
    var l = el.getAttribute('data-wms-label') || el.getAttribute('aria-label') ||
      (el.innerText || el.textContent || '').replace(/\s+/g, ' ') || el.getAttribute('title') ||
      (el.querySelector && el.querySelector('img[alt]') ? el.querySelector('img[alt]').alt : '');
    return clip(l, 80);
  }

  /** Where on the page: nearest section id / heading, e.g. "#pricing" or "VIP Pass". */
  function locationOf(el) {
    var n = el.parentElement;
    while (n && n !== document.body) {
      if (n.id && !/^elementor-|^menu-item/.test(n.id)) return '#' + n.id;
      if (n.matches && n.matches('section, .elementor-section, .e-con, .elementor-widget-price-table, .wp-block-group, footer, header')) {
        var h = n.querySelector('h1, h2, h3, h4');
        if (h && h.textContent.trim()) return clip(h.textContent.replace(/\s+/g, ' '), 50);
        if (n.matches('footer')) return 'footer';
        if (n.matches('header')) return 'header';
      }
      n = n.parentElement;
    }
    return '';
  }

  /* --------------------------------------------------------------- forms */

  var FIELD_KEYS = ['affiliate', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term',
    'landing_page', 'referrer', 'wms_ref', 'wms_route', 'first_touch'];

  function isSkippableForm(form) {
    if (form.getAttribute('data-wms') === 'off') return true;
    if (form.getAttribute('role') === 'search' || form.classList.contains('search-form') ||
        form.querySelector('input[name="s"]:not([type=hidden])')) return true;
    if (form.id === 'loginform' || form.classList.contains('woocommerce-form-login') ||
        form.querySelector('input[type=password]')) return true;
    return false;
  }

  function findField(form, key) {
    var els = form.querySelectorAll('input, textarea');
    for (var i = 0; i < els.length; i++) {
      var e = els[i], nm = e.name || '';
      if (nm === key || nm.slice(-(key.length + 2)) === '[' + key + ']' ||
          e.getAttribute('data-wms') === key || e.id === key || e.id === 'form-field-' + key) {
        return e;
      }
    }
    return null;
  }

  function fillForm(form) {
    if (isSkippableForm(form)) return;
    var f = fields();
    FIELD_KEYS.forEach(function (key) {
      var el = findField(form, key);
      if (!el) {
        el = document.createElement('input');
        el.type = 'hidden'; el.name = key; el.setAttribute('data-wms', key);
        form.appendChild(el);
      }
      // Fill hidden fields always; visible fields only when the user left them empty.
      if (el.type === 'hidden' || !el.value) el.value = f[key] || '';
    });
  }

  function fillAllForms() {
    Array.prototype.forEach.call(document.querySelectorAll('form'), fillForm);
  }

  // Forms whose plugin reports the submission server-side (logged there, not here).
  var SERVER_LOGGED = '.elementor-form, .wpcf7-form, .wpforms-form, .frm-fluent-form, .fluent_form, ' +
    '[id^=gform_], form.checkout, form.woocommerce-checkout, form.cart, .wc-block-checkout';

  function contactFrom(form) {
    var out = {};
    Array.prototype.forEach.call(form.querySelectorAll('input, select, textarea'), function (e) {
      var k = ((e.name || '') + ' ' + (e.id || '') + ' ' + (e.type || '')).toLowerCase();
      var v = clip(e.value, 120);
      if (!v || e.type === 'hidden' || e.type === 'password') return;
      if (!out.email && (e.type === 'email' || /mail/.test(k))) out.email = v;
      else if (!out.phone && (e.type === 'tel' || /phone|tel|mobile|whatsapp|hp\b|telefon/.test(k))) out.phone = v;
      else if (!out.name && /name|nama/.test(k) && !/company|syarikat|organi/.test(k)) out.name = v;
      else if (!out.company && /company|syarikat|organi/.test(k)) out.company = v;
    });
    return out;
  }

  document.addEventListener('submit', function (ev) {
    var form = ev.target;
    if (!form || form.tagName !== 'FORM' || isSkippableForm(form)) return;
    fillForm(form);                               // make sure values are current at submit time
    if (form.matches(SERVER_LOGGED) || form.closest(SERVER_LOGGED)) return;
    var name = form.getAttribute('data-wms-label') || form.getAttribute('name') || form.id ||
      form.getAttribute('aria-label') || locationOf(form) || 'form';
    track('form_submit', name, { contact: contactFrom(form), location: locationOf(form) });
  }, true);

  /* ------------------------------------------------ GHL iframes and links */

  function ghlParams() {
    var f = fields();
    return {
      utm_source: f.utm_source, utm_medium: f.utm_medium, utm_campaign: f.utm_campaign,
      utm_content: f.utm_content, utm_term: f.utm_term, affiliate: f.affiliate,
      landing_page: f.landing_page, wms_ref: f.wms_ref, wms_route: f.wms_route
    };
  }

  function decorateUrl(url) {
    try {
      var u = new URL(url, location.href);
      var p = ghlParams();
      Object.keys(p).forEach(function (k) {
        if (p[k] && !u.searchParams.get(k)) u.searchParams.set(k, p[k]);
      });
      return u.toString();
    } catch (e) { return url; }
  }

  function decorateGhl(root) {
    var scope = root && root.querySelectorAll ? root : document;
    Array.prototype.forEach.call(scope.querySelectorAll('iframe'), function (fr) {
      ['data-src', 'src'].forEach(function (attr) {
        var v = fr.getAttribute(attr);
        if (v && isGhlHost(hostOf(v)) && v.indexOf('wms_ref=') === -1) fr.setAttribute(attr, decorateUrl(v));
      });
    });
    Array.prototype.forEach.call(scope.querySelectorAll('a[href]'), function (a) {
      var h = a.getAttribute('href');
      if (h && isGhlHost(hostOf(h)) && h.indexOf('wms_ref=') === -1) a.setAttribute('href', decorateUrl(h));
    });
  }

  // Best effort: GHL form embeds post messages to the parent page on submit.
  window.addEventListener('message', function (ev) {
    if (!isGhlHost(hostOf(ev.origin))) return;
    var s = '';
    try { s = typeof ev.data === 'string' ? ev.data : JSON.stringify(ev.data); } catch (e) { return; }
    if (/form[-_ ]?submit|submitted|survey[-_ ]?submit/i.test(s) && !/sticky|height|resize/i.test(s.slice(0, 40))) {
      track('ghl_form', 'GHL form', { location: '' });
    }
  });

  /* ---------------------------------------------------- WhatsApp and CTAs */

  function isWhatsApp(href) {
    return /^(https?:\/\/)?(wa\.me|api\.whatsapp\.com|web\.whatsapp\.com|chat\.whatsapp\.com|(www\.)?whatsapp\.com\/send)|^whatsapp:/i
      .test(href || '');
  }

  function waReference() {
    var f = fields();
    var bits = [f.wms_ref];
    if (f.affiliate) bits.push(f.affiliate);
    bits.push(f.utm_campaign ? f.utm_source + '/' + f.utm_campaign : f.utm_source);
    return '[Ref ' + bits.join(' · ') + ']';
  }

  function addWaRef(href) {
    if (CFG.waRef === false || /chat\.whatsapp\.com/i.test(href)) return href;   // group invites have no text
    try {
      var u = new URL(href, location.href);
      var text = u.searchParams.get('text') || '';
      if (text.indexOf('[Ref WMS-') !== -1) text = text.replace(/\s*\[Ref WMS-[^\]]*\]/, '');
      u.searchParams.set('text', (text ? text + '\n\n' : '') + waReference());
      return u.toString();
    } catch (e) { return href; }
  }

  var CTA_TEXT = /ticket|tiket|vip|standard|premium|early ?bird|hrd|corporate|korporat|bulk|group|student|pelajar|register|daftar|beli|buy|book|enquir|inquir|pertanyaan|contact|hubungi|sales|admin|quote|sebut ?harga|brochure|proposal|claim/i;

  function ctaType(el, href) {
    if (isWhatsApp(href)) return 'whatsapp';
    if (/^tel:/i.test(href)) return 'call';
    if (/^mailto:/i.test(href)) return 'email';
    if (el.classList.contains('add_to_cart_button') || /[?&]add-to-cart=/.test(href)) return 'add_to_cart';
    if (el.hasAttribute('data-wms-cta')) return 'cta_click';
    if (href && isGhlHost(hostOf(href))) return 'cta_click';
    if (/\/(checkout|cart|product|troli|bayar)\b/i.test(href || '')) return 'cta_click';
    if (el.closest('nav, .menu, .elementor-nav-menu, #wpadminbar')) return '';
    if (el.closest('.elementor-button-wrapper, .wp-block-button, .elementor-widget-button, .elementor-price-table, .button, .btn') ||
        el.matches('.button, .btn, .elementor-button, button, [role=button]')) {
      if (CTA_TEXT.test(labelOf(el))) return 'cta_click';
    }
    return '';
  }

  document.addEventListener('click', function (ev) {
    var el = ev.target && ev.target.closest ? ev.target.closest('a, button, [data-wms-cta], [role=button]') : null;
    if (!el || el.type === 'submit') return;
    var href = el.getAttribute('href') || el.getAttribute('data-href') || '';
    var type = ctaType(el, href);
    if (!type) return;
    var label = el.getAttribute('data-wms-cta') || labelOf(el) || type;
    if (type === 'whatsapp') {
      var dest = addWaRef(el.href || href);
      if (el.tagName === 'A') el.setAttribute('href', dest);
      var num = (dest.match(/wa\.me\/(\d+)|phone=(\d+)/) || []).slice(1).filter(Boolean)[0] || '';
      track('whatsapp', label, { location: locationOf(el), target: num });
    } else {
      track(type, label, { location: locationOf(el), target: clip(href, 200) });
    }
  }, true);

  // WhatsApp opened by script (window.open / chat widgets) also gets the reference.
  var nativeOpen = window.open;
  window.open = function (url) {
    if (typeof url === 'string' && isWhatsApp(url)) {
      arguments[0] = addWaRef(url);
      track('whatsapp', 'WhatsApp (widget)', { location: 'widget' });
    }
    return nativeOpen.apply(window, arguments);
  };

  /* ------------------------------------------------------------ plugin JS events */

  function onJq(evt, fn) {
    if (window.jQuery) window.jQuery(document).on(evt, fn);
  }
  // Popups and ajax content: keep forms and GHL iframes decorated.
  onJq('elementor/popup/show', function () { fillAllForms(); decorateGhl(document); });

  /* ------------------------------------------------------------------ boot */

  function boot() {
    fillAllForms();
    decorateGhl(document);
    if (window.MutationObserver) {
      var pending = false;
      new MutationObserver(function () {
        if (pending) return;
        pending = true;
        setTimeout(function () { pending = false; fillAllForms(); decorateGhl(document); }, 250);
      }).observe(document.body, { childList: true, subtree: true });
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})(window, document);
