// ==UserScript==
// @name         Twitch Drops Miner session sync
// @namespace    https://github.com/fireph/TwitchDropsMiner
// @version      1.1
// @description  Sends this browser's Twitch session (auth-token, X-Device-Id, Client-Integrity) to a Twitch Drops Miner webui, so the miner never needs the values pasted by hand.
// @match        https://www.twitch.tv/*
// @grant        GM_xmlhttpRequest
// @grant        unsafeWindow
// @connect      *
// @run-at       document-start
// ==/UserScript==

(function () {
  "use strict";

  // ---- configure ----------------------------------------------------------
  // Where the miner webui is reachable FROM THIS BROWSER (scheme, host, port).
  const MINER_URL = "http://127.0.0.1:5800";
  // Must equal the WEBUI_SESSION_KEY environment variable of the miner.
  const API_KEY = "";
  // -------------------------------------------------------------------------

  const PUSH_EVERY_MS = 5 * 60 * 1000;
  const GQL_URL = "https://gql.twitch.tv/gql";
  let latest = null;
  let lastPushed = "";
  let lastPushAt = 0;
  let seenGql = false;

  function log() {
    console.info.apply(console, ["[TDM sync]"].concat(Array.from(arguments)));
  }

  function capture(headers) {
    seenGql = true;
    const integrity = headers.get("client-integrity");
    if (!integrity) {
      return;
    }
    const auth = headers.get("authorization") || "";
    latest = {
      integrity: integrity,
      device_id: headers.get("x-device-id") || "",
      auth_token: auth.indexOf("OAuth ") === 0 ? auth.slice(6) : "",
    };
    push(false);
  }

  function push(force) {
    if (!latest || !API_KEY) {
      return;
    }
    const now = Date.now();
    if (!force && latest.integrity === lastPushed && now - lastPushAt < PUSH_EVERY_MS) {
      return;
    }
    lastPushed = latest.integrity;
    lastPushAt = now;
    log("pushing session to", MINER_URL, "(integrity ..." + latest.integrity.slice(-8) + ")");
    GM_xmlhttpRequest({
      method: "POST",
      url: MINER_URL.replace(/\/+$/, "") + "/api/session",
      headers: { "Content-Type": "application/json", "X-Api-Key": API_KEY },
      data: JSON.stringify(latest),
      onload: function (r) {
        log("miner answered", r.status, r.responseText);
      },
      onerror: function (e) {
        log("push FAILED (is MINER_URL reachable from this browser? did Tampermonkey ask to allow the connection?)", e);
      },
    });
  }

  function isGql(url) {
    return typeof url === "string" && url.indexOf(GQL_URL) === 0;
  }

  // Hook the page's fetch and XHR so the headers Twitch's own client sends to
  // GQL can be read; the requests themselves are passed through untouched.
  const w = typeof unsafeWindow !== "undefined" ? unsafeWindow : window;
  const origFetch = w.fetch;
  w.fetch = function (input, init) {
    try {
      const url = typeof input === "string" ? input : input && input.url;
      if (isGql(url)) {
        const source = (init && init.headers) || (input && input.headers) || undefined;
        capture(new Headers(source));
      }
    } catch (e) {
      // never interfere with the site
    }
    return origFetch.apply(this, arguments);
  };

  const xhrProto = w.XMLHttpRequest && w.XMLHttpRequest.prototype;
  if (xhrProto) {
    const origOpen = xhrProto.open;
    const origSetHeader = xhrProto.setRequestHeader;
    const origSend = xhrProto.send;
    xhrProto.open = function (method, url) {
      try {
        this.__tdmGql = isGql(String(url));
        this.__tdmHeaders = this.__tdmGql ? new Headers() : null;
      } catch (e) {}
      return origOpen.apply(this, arguments);
    };
    xhrProto.setRequestHeader = function (name, value) {
      try {
        if (this.__tdmHeaders) {
          this.__tdmHeaders.set(name, value);
        }
      } catch (e) {}
      return origSetHeader.apply(this, arguments);
    };
    xhrProto.send = function () {
      try {
        if (this.__tdmHeaders) {
          capture(this.__tdmHeaders);
        }
      } catch (e) {}
      return origSend.apply(this, arguments);
    };
  }

  setInterval(function () {
    push(true);
  }, PUSH_EVERY_MS);

  log("active; miner:", MINER_URL, API_KEY ? "" : "(API_KEY IS EMPTY - edit the script)");
  if (!API_KEY) {
    console.warn("[TDM sync] API_KEY is empty: edit the userscript and set MINER_URL / API_KEY.");
  }
  setTimeout(function () {
    if (!seenGql) {
      console.warn("[TDM sync] no GQL request seen in 60s - the hook isn't catching Twitch's requests on this page.");
    } else if (!latest) {
      console.warn("[TDM sync] GQL requests seen, but none carried Client-Integrity yet - open a stream page and wait.");
    }
  }, 60 * 1000);
})();
