# Claude OAuth2 Authentication Deep Dive

If you have ever typed `claude auth login` into a terminal and watched a browser tab pop open, you already know the surface-level experience. You sign in, something happens behind the scenes, and a moment later your terminal says you are authenticated. But what actually happened during those few seconds is a surprisingly detailed chain of cryptographic handshakes, HTTP exchanges, and local file writes that together form a complete OAuth 2.0 authorization-code flow with PKCE. This essay pulls that chain apart, link by link, so that when something inevitably breaks you will know exactly where to look.

## The Problem

Claude Code is a command-line tool. It runs in your terminal. But the credentials that prove your identity live on Anthropic's servers, and the only trusted way to prove you are who you say you are is through the same login page you would use in a browser on claude.ai. The terminal cannot render that login page. It cannot handle CAPTCHAs, two-factor prompts, or account selection screens. So the CLI needs a way to delegate the authentication step to a browser, get the result back, and then store that result locally for future use.

OAuth 2.0 is the protocol that makes this delegation possible. It was designed for exactly this kind of situation: one application needs to act on behalf of a user, but the user's actual credentials should never pass through that application. Instead of your password, the CLI ends up with a pair of tokens, one short-lived access token and one longer-lived refresh token, that together let it make authenticated requests to Anthropic's API without ever knowing your password.

PKCE, which stands for Proof Key for Code Exchange and is pronounced "pixy," is an extension to OAuth that protects against a specific class of attack. Without PKCE, if someone intercepted the authorization code during the redirect back to your machine, they could exchange it for tokens themselves. PKCE prevents that by tying the token exchange to a secret that only the original client knows.

## Preparation

Before the browser opens, the CLI has some prep work to do. It generates three values.

The first is a PKCE verifier. This is a high-entropy random string, typically between 43 and 128 characters, drawn from the unreserved URI character set. Think of it as a one-time secret that the CLI creates and keeps to itself. In most implementations this is generated using a cryptographically secure random number generator, then base64url-encoded.

The second value is the PKCE challenge. This is derived from the verifier by taking its SHA-256 hash and then base64url-encoding the result. The relationship between verifier and challenge is one-way: given the challenge, you cannot recover the verifier, but given the verifier, anyone can recompute the challenge. That asymmetry is the whole point.

```python
import hashlib, base64, os
verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
challenge = base64.urlsafe_b64encode(
    hashlib.sha256(verifier.encode()).digest()
).rstrip(b"=").decode()
```

The third value is a random state parameter. This is an anti-CSRF measure. The CLI generates it, includes it in the authorize request, and later checks that the same value comes back in the callback. If it does not match, the response is discarded.

## The Authorization Request

With those three values ready, the CLI constructs a URL that points to Anthropic's authorization endpoint. For Claude Code, that endpoint is:

```
https://claude.ai/oauth/authorize
```

The URL includes several query parameters. The `client_id` identifies the application requesting access. For Claude Code, the observed client ID is `9d1c250a-e61b-44d9-88ed-5944d1962f5e`. The `response_type` is set to `code`, which tells the server this is an authorization-code flow rather than an implicit flow. The `redirect_uri` tells the server where to send the user after they authenticate. The `scope` parameter lists the permissions being requested. The `code_challenge` carries the PKCE challenge computed a moment ago, and `code_challenge_method` is set to `S256` to indicate that SHA-256 was used. Finally, the `state` parameter carries the random anti-CSRF value.

A fully assembled authorize URL might look something like:

```
https://claude.ai/oauth/authorize?client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e&response_type=code&redirect_uri=http://localhost:54545/callback&code_challenge=...&code_challenge_method=S256&state=xyz123&scope=user:profile+user:inference+user:sessions:claude_code+user:mcp_servers
```

The CLI opens this URL in the user's default browser. From this point on, the CLI is waiting. It has started a tiny HTTP server on localhost, listening on a specific port (typically 54545), ready to catch the callback.

## The Browser Flow

What happens next is entirely in the browser. The user sees Anthropic's login page. They might enter an email and password, they might use a social login, they might go through a two-factor authentication step. The CLI has no visibility into any of this. It does not need to.

Once the user successfully authenticates and grants consent, Anthropic's server constructs a redirect response. The redirect URL points back to the localhost address the CLI registered as its `redirect_uri`, and it includes two query parameters: `code` and `state`.

```
http://localhost:54545/callback?code=SplxlOBeZQQYbYS6WxSbIA&state=xyz123
```

The authorization code in that URL is short-lived, typically valid for only a few minutes, and can only be used once. It is also useless on its own. To turn it into actual tokens, you need the PKCE verifier that matches the challenge sent earlier. This is why intercepting the code alone is not enough for an attacker.

## The Token Exchange

The CLI's localhost server receives the callback, extracts the `code` and `state`, and immediately verifies that the state matches what it originally generated. If the state does not match, the whole flow is aborted.

Then the CLI makes a POST request to Anthropic's token endpoint. For Claude Code, that endpoint is:

```
https://platform.claude.com/v1/oauth/token
```

**One detail worth highlighting here:** this endpoint expects JSON in the request body, not `application/x-www-form-urlencoded`. Many OAuth implementations use form encoding for the token exchange, so if you are building or debugging tooling around this, sending form data will silently fail or return an unhelpful error.

The request body contains:

```json
{
  "grant_type": "authorization_code",
  "code": "SplxlOBeZQQYbYS6WxSbIA",
  "redirect_uri": "http://localhost:54545/callback",
  "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
  "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
  "state": "xyz123"
}
```

The server receives this, recomputes the SHA-256 hash of the provided `code_verifier`, and checks that it matches the `code_challenge` from the original authorize request. If it matches, the server knows that whoever is making this token exchange is the same party that initiated the flow. The authorization code is consumed and a token set is returned.

The response typically includes:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "tGzv3JOkF0XG5Qx2TlKWIA...",
  "expires_in": 3600,
  "scope": "user:profile user:inference user:sessions:claude_code user:mcp_servers"
}
```

The access token is what gets sent with every authenticated API request. The refresh token is what gets used later to obtain new access tokens without going through the browser flow again. The `expires_in` value tells you how many seconds the access token will remain valid.

## Local Storage

Once the tokens are in hand, Claude Code writes them to disk. The primary storage location is `~/.claude/.credentials.json`. The token data sits under a key called `claudeAiOauth`:

```json
{
  "claudeAiOauth": {
    "accessToken": "<bearer-token>",
    "refreshToken": "<refresh-token>",
    "expiresAt": 1760000000000,
    "scopes": [
      "user:profile",
      "user:inference",
      "user:sessions:claude_code",
      "user:mcp_servers"
    ],
    "subscriptionType": "max",
    "rateLimitTier": "default_claude_max_20x"
  }
}
```

Note that `expiresAt` is stored as a Unix timestamp in milliseconds. Comparing it against `Date.now()` in JavaScript or `time.time() * 1000` in Python tells you whether the token is still valid.

A second file, `~/.claude.json`, holds account-level metadata: the account UUID, email address, organization UUID, organization name, and billing type. This file is used by Claude Code to display status information and to set context for API requests, but it does not contain the actual bearer tokens.

On macOS, there is an additional storage layer. Claude Code may store credentials in the system keychain under a service name like `Claude Code-credentials`. When reading credentials programmatically, the keychain entry can be fresher than what is on disk, especially if a recent re-login updated the keychain but the file write was interrupted or delayed. On Linux, the file is generally the authoritative source.

## Using the Tokens

With a valid access token stored locally, every subsequent request to Anthropic's API includes it as a bearer token in the Authorization header:

```bash
curl -H "Authorization: Bearer <access-token>" \
  -H "Content-Type: application/json" \
  https://api.anthropic.com/v1/messages \
  -d '{"model":"claude-sonnet-4-20250514","max_tokens":1024,"messages":[{"role":"user","content":"hello"}]}'
```

The API server validates the token, checks its scopes and expiration, and either processes the request or returns a 401 if something is wrong.

## Diagnostic Endpoints

Two diagnostic endpoints are worth knowing about when you are troubleshooting. The profile endpoint tells you which account and organization the token resolves to:

```bash
curl -H "Authorization: Bearer <access-token>" \
  -H "Content-Type: application/json" \
  https://api.anthropic.com/api/oauth/profile
```

The CLI roles endpoint reveals what permissions and rate-limit tier the token carries, though it requires a beta header:

```bash
curl -H "Authorization: Bearer <access-token>" \
  -H "anthropic-beta: oauth-2025-04-20" \
  -H "Content-Type: application/json" \
  https://api.anthropic.com/api/oauth/claude_cli/roles
```

These are invaluable when you can see that authentication is succeeding but the behavior is not what you expect—maybe you are hitting an unexpected rate limit, or the token is resolving to a different organization than intended.

## Token Refresh

Access tokens expire. The `expires_in` value from the original token response tells you the window, and once that window closes, any request using the old access token will fail. The refresh token exists so you do not have to send the user through the browser flow every time this happens.

The refresh request is simpler than the initial token exchange:

```json
{
  "grant_type": "refresh_token",
  "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
  "refresh_token": "<refresh-token>"
}
```

This goes to the same token endpoint, `https://platform.claude.com/v1/oauth/token`, and the response has the same shape as the original token response: a new access token, a new expiration, and potentially a new refresh token as well.

That last point is important. When the server issues a new refresh token alongside the new access token, the old refresh token is typically invalidated. This is called refresh token rotation, and it is a security measure. If an attacker somehow captured an old refresh token, it would already be dead by the time they tried to use it. But it also means that any system holding a copy of the old refresh token is now holding a useless string.

## The Refresh Token Problem

This is where things get interesting in practice. The initial login is rarely the problem. The problems come later, when multiple processes or tools share the same identity and tokens start rotating out from under each other.

Consider this scenario. You log in with `claude auth login`. Refresh token A is stored in `~/.claude/.credentials.json`. Some time later, maybe an hour, maybe a day, the access token expires. Claude Code transparently refreshes it, receiving a new access token and a new refresh token B. Refresh token A is now dead.

But what if another process, maybe a long-running automation script, read the credentials file earlier and cached refresh token A in memory? When that process tries to refresh, it sends the revoked token A to Anthropic's token endpoint and gets back an error:

```json
{
  "error": "invalid_grant",
  "error_description": "Refresh token not found or invalid"
}
```

The same thing happens if you log in a second time from a different terminal session, or if you log in from a different machine using the same Anthropic account. Each new login can rotate the refresh token, killing whatever was stored before.

This is not a bug in OAuth. It is the intended security behavior. But it creates a real operational challenge for any system that caches credentials.

## Headless Authentication

The entire PKCE flow described above assumes the CLI can open a browser and listen on a localhost port for the callback. On a normal desktop, that works. On a headless server, an SSH session, or a remote container, it does not.

There are a few workarounds. One approach is to use a manual PKCE flow. The idea is to separate the steps that need a browser from the steps that need a terminal. You generate the PKCE verifier and challenge on the headless machine, construct the authorize URL, copy that URL to a machine that does have a browser, complete the login there, and then paste the resulting authorization code back into the headless machine's terminal. The headless machine already has the verifier, so it can complete the token exchange.

When using the manual approach with Claude's OAuth, the redirect URI is typically set to `https://platform.claude.com/oauth/code/callback`, which displays the authorization code on a web page instead of redirecting to localhost. You then copy the code and paste it back.

A minimal Python implementation of the verifier and challenge generation looks like this:

```python
import hashlib, base64, secrets

def generate_pkce():
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge

verifier, challenge = generate_pkce()
state = secrets.token_urlsafe(16)
```

You would then assemble the authorize URL with these values, open it in any browser you have access to, complete the login, grab the code from the callback, and run the token exchange from the headless machine using curl or a script:

```bash
curl -X POST https://platform.claude.com/v1/oauth/token \
  -H "Content-Type: application/json" \
  -d '{
    "grant_type": "authorization_code",
    "code": "<paste-code-here>",
    "redirect_uri": "https://platform.claude.com/oauth/code/callback",
    "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
    "code_verifier": "<your-verifier>",
    "state": "<your-state>"
  }'
```

If that returns a valid token set, you write it into `~/.claude/.credentials.json` in the shape described earlier, and Claude Code will pick it up.

## Scopes

The `scope` parameter in the authorize request determines what the resulting tokens are allowed to do. For Claude Code, the observed scopes include `user:profile`, `user:inference`, `user:sessions:claude_code`, and `user:mcp_servers`.

The `user:profile` scope allows reading account information. The `user:inference` scope is what actually grants permission to send messages to Claude models. The `user:sessions:claude_code` scope ties the session specifically to Claude Code usage. The `user:mcp_servers` scope allows interaction with MCP (Model Context Protocol) server configurations associated with the account.

If you request fewer scopes, you get a token that can do less. If you request scopes that the account or organization does not permit, the authorization server will either strip them silently or reject the request.

## Token Lifetime

Access tokens from Anthropic's OAuth flow are short-lived. The exact duration can vary, but a common value is around one hour. This is a deliberate design choice. Short-lived access tokens limit the damage if one is leaked: an attacker who steals an access token only has a narrow window to use it.

Refresh tokens last longer, but they are not immortal. They can be revoked explicitly by the server, rotated during a refresh operation, or invalidated by a new login. In practice, a refresh token that is not used for a long period may also expire, though the exact policy is up to Anthropic's implementation.

The `expiresAt` field stored in the credentials file is your best guide. Before making an API call, check whether the current time has passed that value. If it has, refresh first. A simple check in JavaScript:

```javascript
const creds = JSON.parse(fs.readFileSync(
  path.join(os.homedir(), ".claude", ".credentials.json"),
  "utf8"
));
const oauth = creds.claudeAiOauth;
if (Date.now() >= oauth.expiresAt) {
  // refresh needed
}
```

## Security Properties

A few security properties of this flow are worth calling out explicitly.

The PKCE verifier never leaves the client machine during the authorize phase. Only the challenge, which is a one-way hash of the verifier, is sent to the server. An attacker who intercepts the authorize request sees the challenge but cannot derive the verifier from it. When the token exchange happens, the verifier is sent directly to the token endpoint over HTTPS, so it is protected by TLS.

The state parameter protects against CSRF attacks. Without it, an attacker could craft a malicious authorize URL and trick a user into completing the login, then intercept the callback. With a random state value that the client checks, this attack fails because the attacker cannot predict the state.

Refresh token rotation means that even if a refresh token leaks, it becomes useless after the next legitimate refresh operation. The tradeoff is the synchronization complexity described earlier, but the security benefit is substantial.

The credentials file at `~/.claude/.credentials.json` should be treated like any other secret on disk. Its permissions should be restricted to the owning user. On a shared machine, anyone who can read that file can impersonate the authenticated user against Anthropic's API.

## Debugging

When authentication stops working, a methodical approach saves time. Start by checking whether Claude Code itself thinks it is logged in:

```bash
claude auth status --json
```

If that shows a valid session, the problem is probably not in the login flow itself. If it shows expired or missing credentials, check the file directly:

```bash
cat ~/.claude/.credentials.json | python3 -m json.tool
```

Look for the `claudeAiOauth` object. Is the `accessToken` present? Is `expiresAt` in the future? Is the `refreshToken` present and non-empty?

On macOS, also check whether the keychain has a different (possibly fresher) credential:

```bash
security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null
```

If the access token is expired but the refresh token looks valid, try a manual refresh:

```bash
curl -X POST https://platform.claude.com/v1/oauth/token \
  -H "Content-Type: application/json" \
  -d '{
    "grant_type": "refresh_token",
    "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
    "refresh_token": "<your-refresh-token>"
  }'
```

If that returns `invalid_grant`, the refresh token has been revoked. You need to log in again from scratch with `claude auth login` or the manual PKCE flow.

If the refresh succeeds but API calls still fail, hit the profile endpoint to confirm the token resolves to the expected account and organization. A token that works but belongs to a different org than you expect is a surprisingly common source of confusion, especially on machines where multiple accounts have been used.

## Conclusion

This is, at its core, a well-trodden OAuth flow. The PKCE extension adds a small amount of complexity at the start, but it meaningfully raises the security bar for CLI-based authentication. The local storage model is straightforward once you know which files to look at. And the refresh mechanics, while they can create headaches when multiple consumers share a single identity, follow standard OAuth 2.0 conventions. When something goes wrong, the debugging path is almost always the same: check the files, check the expiration, try a manual refresh, and if all else fails, log in again.
