/**
 * AISBF OAuth2 Relay - Popup Script
 * 
 * Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>
 * Licensed under GPL-3.0
 */

document.addEventListener('DOMContentLoaded', async () => {
  const statusEl = document.getElementById('status');
  const toggleEl = document.getElementById('enableToggle');
  const configBtn = document.getElementById('configBtn');
  const optionsBtn = document.getElementById('optionsBtn');
  const rulesCountEl = document.getElementById('rulesCount');
  
  // Get current status
  async function updateStatus() {
    try {
      const response = await chrome.runtime.sendMessage({ type: 'GET_STATUS' });
      
      if (response.success) {
        toggleEl.checked = response.enabled;
        
        if (!response.remoteServer) {
          statusEl.className = 'status warning';
          statusEl.innerHTML = `
            <strong>Waiting for AISBF page</strong>
            <div class="server-info">Visit an AISBF providers page — the extension will auto-configure.</div>
          `;
        } else if (response.enabled && response.rulesCount > 0) {
          statusEl.className = 'status active';
          statusEl.innerHTML = `
            <strong>✓ Active</strong>
            <div class="server-info">Redirecting to: ${response.remoteServer}</div>
          `;
        } else if (response.enabled) {
          statusEl.className = 'status warning';
          statusEl.innerHTML = `
            <strong>⚠ Enabled but no rules</strong>
            <div class="server-info">Server: ${response.remoteServer}</div>
          `;
        } else {
          statusEl.className = 'status inactive';
          statusEl.innerHTML = `
            <strong>Disabled</strong>
            <div class="server-info">Server: ${response.remoteServer}</div>
          `;
        }
        
        rulesCountEl.textContent = `${response.rulesCount} redirect rules active`;
      }
    } catch (error) {
      statusEl.className = 'status inactive';
      statusEl.innerHTML = `<strong>Error:</strong> ${error.message}`;
    }
  }
  
  // Toggle enabled state
  toggleEl.addEventListener('change', async () => {
    try {
      const response = await chrome.runtime.sendMessage({ type: 'TOGGLE_ENABLED' });
      if (response.success) {
        await updateStatus();
      }
    } catch (error) {
      console.error('Failed to toggle:', error);
    }
  });
  
  // Configure server button
  configBtn.addEventListener('click', async () => {
    const serverUrl = prompt(
      'Enter your AISBF server URL:\n\n' +
      'Examples:\n' +
      '• http://192.168.1.100:17765\n' +
      '• https://aisbf.example.com\n' +
      '• https://example.com/aisbf'
    );
    
    if (serverUrl) {
      try {
        const response = await chrome.runtime.sendMessage({
          type: 'SET_CONFIG',
          config: {
            enabled: true,
            remoteServer: serverUrl.replace(/\/$/, '')
          }
        });
        
        if (response.success) {
          await updateStatus();
        } else {
          alert('Failed to save configuration');
        }
      } catch (error) {
        alert('Error: ' + error.message);
      }
    }
  });
  
  // Options button
  optionsBtn.addEventListener('click', () => {
    chrome.runtime.openOptionsPage();
  });
  
  // Initial status update
  await updateStatus();
});
