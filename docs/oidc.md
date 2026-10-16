# Monitor OpenID Connect login

Monitor supports OIDC authorization-code login with S256 PKCE and signed RS256
or ES256 ID tokens. This is an additional login method for the existing local
administrator, not a multi-user role system. Local password and 2FA login remain
available. The identity provider controls MFA for OIDC login.

1. Enable local authentication in **Security → Authentication**, then configure
   HTTPS directly or through a reverse proxy serving both the dashboard and its
   `/api` routes. OIDC requires an HTTPS issuer and public dashboard URL.
2. Create an OIDC client in your provider. Use authorization-code flow, enable
   S256 PKCE, and register the exact redirect URI shown in **Security → OpenID
   Connect**, for example `https://monitor.example/api/auth/oidc/callback`.
   Include a reverse-proxy path prefix if applicable.
3. Enter the exact issuer advertised by the provider, including its trailing
   slash if present. Do not enter the provider's authorization endpoint. Enter
   the client ID and choose the provider's client authentication method:
   `client_secret_basic`, `client_secret_post`, or `none` for a public PKCE client.
4. Add each permitted user's immutable **`sub` claim for this client**, one per
   line. These users receive full Monitor administrator access. An email address
   or display name is not a subject, and some providers issue pairwise subjects
   that differ between clients. Obtain the value from the provider's OIDC client
   configuration or claims preview.
5. Save and verify discovery. Leave the client-secret field empty to retain its
   stored value; choosing a public client removes it. Saving verifies discovery
   and the advertised flow/method, but cannot verify client credentials until a
   real login. Test **Continue with [provider]** in a separate browser while
   retaining your local administrator session.

The issuer's discovery document must expose authorization, token and JWKS HTTPS
endpoints. TLS certificate verification is always enabled; install a private CA
in the host trust store rather than disabling verification. No provider access
tokens are stored or used as Monitor API credentials. A verified allowed subject
receives a normal 24-hour Monitor session with an OIDC identity marker. Disabling
OIDC or saving new settings immediately invalidates those OIDC sessions; local
password sessions are unaffected.

State, nonce and PKCE verifiers are stored temporarily in the server process.
Callbacks and the final 30-second exchange code are single-use and bound to an
HttpOnly, Secure, SameSite=Lax browser cookie. The URL fragment carries only that
exchange code, never the Monitor JWT. Restarting the service during login requires
starting the login again. Run the Monitor's normal single-process server or use
sticky routing if an external deployment starts multiple workers.

Secrets are saved atomically with mode `0600` in
`~/.config/proxmenux-monitor/oidc.json` under the service account. The configuration
API requires an authenticated administrator and never returns the client secret.
OIDC defaults to disabled. Its cryptography runtime is bundled separately for
the Python 3.11 and 3.13 ABIs used by supported Monitor hosts.

If login fails, check the exact issuer, redirect URI, client authentication
method, subject and provider logs. Use local credentials to correct or disable
the provider in Security. Invalid signatures, wrong issuer/audience/nonce,
expired responses and unlisted subjects all fail closed.

Protocol references: [OpenID Connect Core](https://openid.net/specs/openid-connect-core-1_0.html#CodeFlowAuth),
[PKCE](https://www.rfc-editor.org/rfc/rfc7636),
[PyJWT validation](https://pyjwt.readthedocs.io/en/stable/usage.html).
