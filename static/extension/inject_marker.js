/**
 * AISBF OAuth2 Relay - Main-world marker injection
 *
 * Runs in the page's main JavaScript world (world: "MAIN") at document_start,
 * before any page scripts execute. Sets window.aisbfOAuth2Extension so the
 * AISBF dashboard can detect the extension with a simple synchronous check.
 *
 * This file must NOT use any chrome.* APIs — those are only available in the
 * isolated world. All extension API calls live in content.js instead.
 *
 * Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>
 * Licensed under GPL-3.0
 */
window.aisbfOAuth2Extension = true;
