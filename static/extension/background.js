/**
 * AISBF OAuth2 Relay - Background Service Worker
 * 
 * This extension intercepts localhost OAuth2 callbacks and redirects them
 * to the remote AISBF server. This is necessary because many OAuth2 providers
 * (like Claude/Anthropic) lock their redirect URIs to localhost.
 * 
 * Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>
 * Licensed under GPL-3.0
 */

// Default configuration
const DEFAULT_CONFIG = {
  enabled: true,
  remoteServer: '',  // Will be set from AISBF dashboard
  ports: [54545],    // Default OAuth callback ports to intercept
  paths: ['/callback', '/oauth/callback', '/auth/callback'],
  forceInterception: false // Override for OAuth flows initiated from AISBF
};

// Current configuration
let config = { ...DEFAULT_CONFIG };

// Load configuration from storage
async function loadConfig() {
  try {
    const result = await chrome.storage.sync.get(['aisbfConfig']);
    if (result.aisbfConfig) {
      config = { ...DEFAULT_CONFIG, ...result.aisbfConfig };
    }
    console.log('[AISBF] Configuration loaded:', config);
    await updateRules();
  } catch (error) {
    console.error('[AISBF] Failed to load config:', error);
  }
}

// Save configuration to storage
async function saveConfig(newConfig) {
  config = { ...DEFAULT_CONFIG, ...newConfig };
  try {
    await chrome.storage.sync.set({ aisbfConfig: config });
    console.log('[AISBF] Configuration saved:', config);
    await updateRules();
    return true;
  } catch (error) {
    console.error('[AISBF] Failed to save config:', error);
    return false;
  }
}

// Generate declarativeNetRequest rules for interception
function generateRules() {
  const rules = [];
  let ruleId = 1;
  
  if (!config.enabled || !config.remoteServer) {
    return rules;
  }
  
  // Clean up remote server URL
  let remoteBase = config.remoteServer.replace(/\/$/, '');
  
  // Parse remote server URL to check if it's localhost
  let remoteUrl;
  try {
    remoteUrl = new URL(remoteBase);
  } catch (e) {
    console.error('[AISBF] Invalid remote server URL:', remoteBase);
    return rules;
  }
  
  // Check if remote server is localhost/127.0.0.1
  const isRemoteLocal = remoteUrl.hostname === 'localhost' ||
                        remoteUrl.hostname === '127.0.0.1' ||
                        remoteUrl.hostname === '::1';
  
  // If the remote server is on localhost, we don't need to intercept
  // The OAuth2 callback can go directly to localhost without redirection
  // EXCEPTION: If we have an ongoing OAuth flow initiated from AISBF (forceInterception flag)
  if (isRemoteLocal && !config.forceInterception) {
    console.log('[AISBF] Remote server is localhost - no interception needed');
    return rules;
  }
  
  if (isRemoteLocal && config.forceInterception) {
    console.log('[AISBF] Remote server is localhost but force interception is enabled for active OAuth flow');
  }
  
  for (const port of config.ports) {
    for (const path of config.paths) {
      // Rule for 127.0.0.1
      rules.push({
        id: ruleId++,
        priority: 1,
        action: {
          type: 'redirect',
          redirect: {
            regexSubstitution: `${remoteBase}/dashboard/oauth2/callback\\1`
          }
        },
        condition: {
          regexFilter: `^http://127\\.0\\.0\\.1:${port}${path.replace(/\//g, '\\/')}(.*)$`,
          resourceTypes: ['main_frame']
        }
      });
      
      // Rule for localhost
      rules.push({
        id: ruleId++,
        priority: 1,
        action: {
          type: 'redirect',
          redirect: {
            regexSubstitution: `${remoteBase}/dashboard/oauth2/callback\\1`
          }
        },
        condition: {
          regexFilter: `^http://localhost:${port}${path.replace(/\//g, '\\/')}(.*)$`,
          resourceTypes: ['main_frame']
        }
      });
    }
  }
  
  return rules;
}

// Update declarativeNetRequest rules
async function updateRules() {
  try {
    // Get existing rules
    const existingRules = await chrome.declarativeNetRequest.getDynamicRules();
    const existingRuleIds = existingRules.map(rule => rule.id);
    
    // Generate new rules
    const newRules = generateRules();
    
    // Update rules
    await chrome.declarativeNetRequest.updateDynamicRules({
      removeRuleIds: existingRuleIds,
      addRules: newRules
    });
    
    console.log('[AISBF] Rules updated:', newRules.length, 'rules active');
    
    // Update badge to show status
    updateBadge(config.enabled && newRules.length > 0);
    
  } catch (error) {
    console.error('[AISBF] Failed to update rules:', error);
  }
}

// Update extension badge
function updateBadge(active) {
  if (active) {
    chrome.action.setBadgeText({ text: 'ON' });
    chrome.action.setBadgeBackgroundColor({ color: '#4CAF50' });
  } else {
    chrome.action.setBadgeText({ text: 'OFF' });
    chrome.action.setBadgeBackgroundColor({ color: '#9E9E9E' });
  }
}

// Handle messages from popup and options page
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  console.log('[AISBF] Received message:', message);
  
  switch (message.type) {
    case 'GET_CONFIG':
      sendResponse({ success: true, config: config });
      break;
      
    case 'SET_CONFIG':
      saveConfig(message.config).then(success => {
        sendResponse({ success });
      });
      return true; // Will respond asynchronously
      
    case 'TOGGLE_ENABLED':
      config.enabled = !config.enabled;
      saveConfig(config).then(success => {
        sendResponse({ success, enabled: config.enabled });
      });
      return true;
      
    case 'GET_STATUS':
      chrome.declarativeNetRequest.getDynamicRules().then(rules => {
        sendResponse({
          success: true,
          enabled: config.enabled,
          rulesCount: rules.length,
          remoteServer: config.remoteServer
        });
      });
      return true;
      
    default:
      sendResponse({ success: false, error: 'Unknown message type' });
  }
});

// Handle external messages from AISBF dashboard
chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  console.log('[AISBF] External message from:', sender.url, message);
  
  // Security: Only accept messages from HTTPS sites or localhost
  const senderUrl = new URL(sender.url);
  const isSecure = senderUrl.protocol === 'https:' || 
                   senderUrl.hostname === 'localhost' || 
                   senderUrl.hostname === '127.0.0.1';
  
  if (!isSecure) {
    sendResponse({ success: false, error: 'Insecure origin' });
    return;
  }
  
  switch (message.type) {
    case 'CONFIGURE':
      // AISBF dashboard is setting up the extension
      const newConfig = {
        enabled: true,
        remoteServer: message.remoteServer || sender.url.replace(/\/dashboard.*$/, ''),
        ports: message.ports || config.ports,
        paths: message.paths || config.paths,
        forceInterception: message.forceInterception || false
      };
      saveConfig(newConfig).then(success => {
        sendResponse({ success, config: newConfig });
      });
      return true;
      
    case 'PING':
      sendResponse({ success: true, version: chrome.runtime.getManifest().version });
      break;
      
    case 'GET_STATUS':
      chrome.declarativeNetRequest.getDynamicRules().then(rules => {
        sendResponse({
          success: true,
          enabled: config.enabled,
          rulesCount: rules.length,
          remoteServer: config.remoteServer,
          version: chrome.runtime.getManifest().version
        });
      });
      return true;
      
    default:
      sendResponse({ success: false, error: 'Unknown message type' });
  }
});

// Initialize on install
chrome.runtime.onInstalled.addListener(async (details) => {
  console.log('[AISBF] Extension installed:', details.reason);
  await loadConfig();
  // No options page on install — extension auto-configures from AISBF providers pages.
});

// Initialize on startup
chrome.runtime.onStartup.addListener(async () => {
  console.log('[AISBF] Extension started');
  await loadConfig();
});

// Initial load
loadConfig();
