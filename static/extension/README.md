# AISBF OAuth2 Relay Extension

A Chrome extension that intercepts localhost OAuth2 callbacks and redirects them to your remote AISBF server.

## Why This Extension?

Many OAuth2 providers (like Claude/Anthropic) lock their redirect URIs to `localhost` or `127.0.0.1`. When AISBF runs on a remote server, it cannot receive these localhost callbacks directly. This extension solves that problem by intercepting the OAuth2 callback in your browser and redirecting it to your remote AISBF server.

## Features

- **Automatic Redirect**: Intercepts `http://localhost:*` and `http://127.0.0.1:*` OAuth2 callbacks
- **Configurable**: Set your remote AISBF server URL, ports, and callback paths
- **Secure**: Only redirects specific OAuth2 callback paths, not all localhost traffic
- **Easy Setup**: Auto-configuration from AISBF dashboard
- **Visual Status**: Badge shows when relay is active

## Installation

### From AISBF Dashboard (Recommended)

1. Open your AISBF dashboard
2. Go to Providers page
3. When configuring a Claude provider, you'll see an extension installation prompt
4. Click "Download Extension" to get the extension files
5. Follow the installation instructions shown in the dashboard

### Manual Installation

1. Download or clone this extension directory
2. Open Chrome and go to `chrome://extensions/`
3. Enable "Developer mode" (toggle in top right)
4. Click "Load unpacked"
5. Select the `static/extension` directory
6. The extension icon should appear in your toolbar

## Configuration

### Automatic Configuration (Recommended)

1. Install the extension
2. Open your AISBF dashboard
3. The dashboard will automatically detect and configure the extension
4. Click "Configure Extension" when prompted

### Manual Configuration

1. Click the extension icon in your toolbar
2. Click "Configure Server"
3. Enter your AISBF server URL (e.g., `https://192.168.1.100:17765`)
4. The extension will automatically intercept OAuth2 callbacks

### Advanced Options

Click the extension icon → "Advanced Options" to configure:

- **Ports to Intercept**: Comma-separated list (default: `54545`)
- **Callback Paths**: One per line (default: `/callback`, `/oauth/callback`, `/auth/callback`)

## How It Works

1. OAuth2 provider redirects to `http://localhost:54545/callback?code=...`
2. Extension intercepts this request before it fails
3. Extension redirects to `https://your-server.com/dashboard/oauth2/callback?code=...`
4. AISBF receives the callback and completes authentication

## Supported Providers

- Claude (Anthropic) - Port 54545
- Any OAuth2 provider that requires localhost redirect URIs

## Security

- Extension only intercepts specific callback paths, not all localhost traffic
- Only accepts configuration from HTTPS sites or localhost
- No data is stored or transmitted except the OAuth2 callback redirect
- Open source - review the code yourself

## Troubleshooting

### Extension Not Working

1. Check that the extension is enabled in `chrome://extensions/`
2. Verify the remote server URL is correct (click extension icon)
3. Check that the port matches your OAuth2 provider (default: 54545)
4. Look for errors in the extension console (chrome://extensions/ → Details → Inspect views: service worker)

### OAuth2 Still Failing

1. Ensure the extension badge shows "ON" (click extension icon)
2. Verify the callback path is in the configured paths
3. Check AISBF server logs for incoming requests
4. Try disabling and re-enabling the extension

### Configuration Not Saving

1. Check Chrome sync is enabled (extension uses chrome.storage.sync)
2. Try using chrome.storage.local instead (modify background.js)
3. Check browser console for errors

## Development

### File Structure

```
static/extension/
├── manifest.json          # Extension manifest (v3)
├── background.js          # Service worker with redirect logic
├── popup.html            # Extension popup UI
├── popup.js              # Popup logic
├── options.html          # Options page UI
├── options.js            # Options page logic
├── icons/                # Extension icons
│   ├── icon16.svg
│   ├── icon48.svg
│   └── icon128.svg
└── README.md            # This file
```

### Testing

1. Load extension in developer mode
2. Configure with your AISBF server URL
3. Try authenticating with a Claude provider
4. Check extension console for logs (look for `[AISBF]` prefix)

### Debugging

Enable verbose logging:
1. Open `chrome://extensions/`
2. Find "AISBF OAuth2 Relay"
3. Click "Inspect views: service worker"
4. Console will show all intercepted requests

## License

Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

## Support

For issues or questions:
- Check AISBF documentation
- Review extension console logs
- Open an issue on the AISBF repository
