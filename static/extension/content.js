/**
 * AISBF OAuth2 Relay - Content Script
 *
 * Bridges communication between the AISBF dashboard and the extension's
 * background service worker. Runs on all pages; auto-configures relay rules
 * only when an AISBF providers page is detected via window.AISBF_PROVIDERS_PAGE.
 *
 * Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>
 * Licensed under GPL-3.0
 */

// After the page scripts have run, check for the AISBF providers page marker
// and auto-configure redirect rules — no manual setup required.
document.addEventListener('DOMContentLoaded', () => {
  const pageInfo = window.AISBF_PROVIDERS_PAGE;
  if (!pageInfo) return;

  const serverUrl = (pageInfo && typeof pageInfo === 'object' && pageInfo.serverUrl)
    ? pageInfo.serverUrl
    : window.location.origin;

  console.log('[AISBF] Providers page detected, auto-configuring relay for:', serverUrl);

  chrome.runtime.sendMessage({
    type: 'SET_CONFIG',
    config: {
      enabled: true,
      remoteServer: serverUrl,
      ports: [54545],
      paths: ['/callback', '/oauth/callback', '/auth/callback']
    }
  }).then(response => {
    if (response && response.success) {
      console.log('[AISBF] Auto-configuration complete for:', serverUrl);
    }
  }).catch(err => {
    console.warn('[AISBF] Auto-configuration failed:', err);
  });
});

// Listen for messages from the web page
window.addEventListener('message', async (event) => {
  if (event.source !== window) return;

  const message = event.data;

  if (message.type === 'aisbf-extension-ping') {
    window.postMessage({ type: 'aisbf-extension-pong' }, '*');
    return;
  }

  if (message.type === 'aisbf-extension-configure') {
    try {
      const response = await chrome.runtime.sendMessage({
        type: 'SET_CONFIG',
        config: {
          enabled: true,
          remoteServer: message.serverUrl,
          ports: message.ports || [54545],
          paths: message.paths || ['/callback', '/oauth/callback', '/auth/callback']
        }
      });
      window.postMessage({
        type: 'aisbf-extension-configured',
        success: response.success
      }, '*');
    } catch (error) {
      console.error('[AISBF Content] Configuration error:', error);
      window.postMessage({
        type: 'aisbf-extension-configured',
        success: false,
        error: error.message
      }, '*');
    }
    return;
  }

  if (message.type === 'aisbf-extension-status') {
    try {
      const response = await chrome.runtime.sendMessage({ type: 'GET_STATUS' });
      window.postMessage({
        type: 'aisbf-extension-status-response',
        ...response
      }, '*');
    } catch (error) {
      console.error('[AISBF Content] Status error:', error);
      window.postMessage({
        type: 'aisbf-extension-status-response',
        success: false,
        error: error.message
      }, '*');
    }
    return;
  }
});

console.log('[AISBF] Extension content script loaded');
