/**
 * AISBF OAuth2 Relay - Content Script
 * 
 * This content script bridges communication between the AISBF dashboard
 * and the extension's background service worker.
 * 
 * Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>
 * Licensed under GPL-3.0
 */

// Inject marker to indicate extension is installed
window.aisbfOAuth2Extension = true;

// Listen for messages from the web page
window.addEventListener('message', async (event) => {
  // Only accept messages from the same window
  if (event.source !== window) {
    return;
  }
  
  const message = event.data;
  
  // Handle ping request
  if (message.type === 'aisbf-extension-ping') {
    window.postMessage({ type: 'aisbf-extension-pong' }, '*');
    return;
  }
  
  // Handle configuration request
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
  
  // Handle status request
  if (message.type === 'aisbf-extension-status') {
    try {
      const response = await chrome.runtime.sendMessage({
        type: 'GET_STATUS'
      });
      
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

// Notify that content script is ready
console.log('[AISBF Content] Extension content script loaded');
