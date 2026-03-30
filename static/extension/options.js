/**
 * AISBF OAuth2 Relay - Options Page Script
 * 
 * Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>
 * Licensed under GPL-3.0
 */

document.addEventListener('DOMContentLoaded', async () => {
  const statusBar = document.getElementById('statusBar');
  const enabledEl = document.getElementById('enabled');
  const remoteServerEl = document.getElementById('remoteServer');
  const portsEl = document.getElementById('ports');
  const pathsEl = document.getElementById('paths');
  const saveBtn = document.getElementById('saveBtn');
  const resetBtn = document.getElementById('resetBtn');
  
  // Default configuration
  const DEFAULT_CONFIG = {
    enabled: true,
    remoteServer: '',
    ports: [54545],
    paths: ['/callback', '/oauth/callback', '/auth/callback']
  };
  
  // Show status message
  function showStatus(message, isError = false) {
    statusBar.textContent = message;
    statusBar.className = 'status-bar ' + (isError ? 'error' : 'success');
    
    setTimeout(() => {
      statusBar.className = 'status-bar';
    }, 3000);
  }
  
  // Load current configuration
  async function loadConfig() {
    try {
      const response = await chrome.runtime.sendMessage({ type: 'GET_CONFIG' });
      
      if (response.success) {
        const config = response.config;
        
        enabledEl.checked = config.enabled;
        remoteServerEl.value = config.remoteServer || '';
        portsEl.value = (config.ports || DEFAULT_CONFIG.ports).join(', ');
        pathsEl.value = (config.paths || DEFAULT_CONFIG.paths).join('\n');
      }
    } catch (error) {
      showStatus('Failed to load configuration: ' + error.message, true);
    }
  }
  
  // Save configuration
  async function saveConfig() {
    const ports = portsEl.value
      .split(/[,\s]+/)
      .map(p => parseInt(p.trim(), 10))
      .filter(p => !isNaN(p) && p > 0 && p < 65536);
    
    const paths = pathsEl.value
      .split('\n')
      .map(p => p.trim())
      .filter(p => p.length > 0);
    
    if (!remoteServerEl.value) {
      showStatus('Please enter a remote server URL', true);
      remoteServerEl.focus();
      return;
    }
    
    if (ports.length === 0) {
      showStatus('Please enter at least one valid port', true);
      portsEl.focus();
      return;
    }
    
    if (paths.length === 0) {
      showStatus('Please enter at least one callback path', true);
      pathsEl.focus();
      return;
    }
    
    const config = {
      enabled: enabledEl.checked,
      remoteServer: remoteServerEl.value.replace(/\/$/, ''),
      ports: ports,
      paths: paths
    };
    
    try {
      const response = await chrome.runtime.sendMessage({
        type: 'SET_CONFIG',
        config: config
      });
      
      if (response.success) {
        showStatus('Configuration saved successfully!');
      } else {
        showStatus('Failed to save configuration', true);
      }
    } catch (error) {
      showStatus('Error: ' + error.message, true);
    }
  }
  
  // Reset to defaults
  async function resetConfig() {
    if (!confirm('Reset all settings to defaults?')) {
      return;
    }
    
    enabledEl.checked = DEFAULT_CONFIG.enabled;
    remoteServerEl.value = '';
    portsEl.value = DEFAULT_CONFIG.ports.join(', ');
    pathsEl.value = DEFAULT_CONFIG.paths.join('\n');
    
    try {
      const response = await chrome.runtime.sendMessage({
        type: 'SET_CONFIG',
        config: { ...DEFAULT_CONFIG, remoteServer: '' }
      });
      
      if (response.success) {
        showStatus('Configuration reset to defaults');
      }
    } catch (error) {
      showStatus('Error: ' + error.message, true);
    }
  }
  
  // Event listeners
  saveBtn.addEventListener('click', saveConfig);
  resetBtn.addEventListener('click', resetConfig);
  
  // Save on Enter in text fields
  remoteServerEl.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      saveConfig();
    }
  });
  
  portsEl.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      saveConfig();
    }
  });
  
  // Load initial config
  await loadConfig();
});
