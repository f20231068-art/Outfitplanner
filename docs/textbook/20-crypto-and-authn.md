# Chapter 20. Cryptography and Authentication

> **Learning objectives.** Think like a defender (threat modelling, trust boundaries); understand the cryptographic primitives you will actually use (hashes, HMAC, symmetric and asymmetric encryption, signatures, randomness, password hashing); design authentication (passwords, sessions, tokens, OAuth/OIDC, MFA, service-to-service); understand **JWT** completely, including its pitfalls; and read every security-related file in this repo (`security/*`, `accounts.py`, `mcp_auth.py`, `mcp_server/auth.py`, `scripts/generate_jwt_keys.py`) with full understanding.
>
> **Prerequisites.** Chapters 3 (hashing), 16 (HTTP, TLS, cookies), 17.

> **A rule for this whole chapter:** *do not invent your own cryptography.* You will learn how the pieces work so you can choose and use vetted libraries correctly, not so you can write your own ciphers.

---

## 20.1 The security mindset

### Goals: the CIA triad (and friends)

* **Confidentiality**: only authorised parties can read data.
* **Integrity**: data cannot be modified undetected.
* **Availability**: the system works when needed.
* Also: **authenticity** (who sent it), **non-repudiation** (cannot deny doing it; audit), **privacy** (limit collection and use of personal data).

### Threat modelling in five questions

1. **What are we protecting?** (assets: user accounts, conversation history, API keys, search credits, the audit log, the model quota)
2. **Who might attack, and why?** (curious users, credential stuffers, competitors scraping, a stolen laptop, a malicious third-party tool server, an insider)
3. **How could they attack?** (the attack surface: every endpoint, input, dependency, secret, build step)
4. **What are we doing about it?** (controls)
5. **Did we do a good job?** (tests, review, monitoring, incident drills)

A structured helper is **STRIDE**: **S**poofing identity, **T**ampering with data, **R**epudiation, **I**nformation disclosure, **D**enial of service, **E**levation of privilege. Walk each component (browser, API, tool server, database, proxy) through the six letters. Draw **trust boundaries** (browser ↔ internet ↔ Caddy ↔ private network ↔ tool server ↔ search provider) and examine every arrow that crosses one.

### Principles (each appears in this repo)

| Principle | Meaning | Example here |
|---|---|---|
| **Least privilege** | each component holds only the power it needs | tool server has the *public* key only; non-root containers with all capabilities dropped; Mastra loads only an allow-list of env vars |
| **Defence in depth** | multiple independent layers | tool server: no public address + signed tokens + single-use + host/origin + rate limits + credit caps |
| **Fail closed / secure by default** | when unsure, deny | server refuses to start without a valid public key; replay memory full ⇒ refuse; demo mode refused in prod |
| **Complete mediation** | check every access, every time | ownership check on every conversation/product request; a new token for every MCP request |
| **Minimise attack surface** | expose less | Caddy allow-list of paths; `/metrics` not routed; docs disabled in prod |
| **Separation of duties / keys** | different keys for different purposes | separate key pairs for user tokens and tool-server tokens |
| **Don't trust inputs** | validate at boundaries | Pydantic everywhere; LLM output and tool results verified |
| **Keep secrets secret** | never in code, images, logs, URLs, front end | `.env` git-ignored; tests for hygiene |
| **Make attacks detectable** | log and audit | hash-chained audit log; refresh-reuse detection event |
| **Assume breach** | limit blast radius, rotate, monitor | short-lived tokens; credit caps |

## 20.2 Cryptographic building blocks

### Encoding, hashing and encryption are different things

| | Reversible? | Key? | Purpose | Example |
|---|---|---|---|---|
| **Encoding** (Base64, URL-encoding, hex) | yes, by anyone | no | represent bytes as text | JWT parts are Base64url-**encoded**, *not* encrypted |
| **Hashing** (SHA-256) | **no** | no | fingerprint, integrity | store a token's SHA-256, chain audit entries |
| **MAC / HMAC** | no | **shared secret** | integrity + authenticity | HS256 signatures, webhook signatures |
| **Encryption** (AES-GCM) | yes, with the key | yes | confidentiality | disk/database encryption, TLS records |
| **Signature** (RSA/ECDSA/Ed25519) | verify only | **private signs, public verifies** | authenticity + integrity, non-repudiation | RS256 JWTs, certificates |
| **Password hash** (Argon2) | no | no (has salt) | slow verification of low-entropy secrets | `users.password_hash` |

### Cryptographic hash functions

A hash `H(x)` maps any input to a fixed-size digest (SHA-256: 256 bits). Required properties: **deterministic**, **fast**, **preimage resistant** (cannot find x from H(x)), **second-preimage resistant**, **collision resistant**, **avalanche** effect. Use **SHA-256/SHA-512/SHA-3/BLAKE2/BLAKE3**; **MD5 and SHA-1 are broken** for security uses.

Uses: **integrity** (file checksums), **fingerprints** (audit entries store `inputFingerprint`), **identifiers** (git commits), **hash chains/Merkle trees**, **storing high-entropy secrets** (refresh tokens: only `sha256(token)` is stored).

*A fast hash is wrong for passwords*, right for 384-bit random tokens (see 20.5).

```python
import hashlib
hashlib.sha256(b"hello").hexdigest()   # 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824
```

### HMAC and constant-time comparison

An **HMAC** (`HMAC(key, message)`) proves that whoever made the tag knew the key and the message was not changed. Do not build MACs as `sha256(key + message)` (length-extension weaknesses); use HMAC.

```python
import hmac, hashlib
tag = hmac.new(key, message, hashlib.sha256).digest()
hmac.compare_digest(tag, received_tag)       # CONSTANT-TIME comparison
```

**Timing attacks.** A normal `==` on strings stops at the first differing byte, so response time leaks how many leading bytes were right; an attacker can recover a secret byte by byte. `hmac.compare_digest` takes the same time regardless. The repo uses it for the **`/metrics` bearer token** on both services. (The same principle motivates the **dummy hash verification** when a login email does not exist: equalise the time of the "no such user" and "wrong password" paths.)

### Randomness

Security needs a **cryptographically secure pseudo-random number generator (CSPRNG)**, seeded from OS entropy: Python's **`secrets`** module (`secrets.token_urlsafe(48)`) and `os.urandom`. **Never use `random`** (Mersenne Twister: predictable) for tokens, keys, passwords or ids that must be unguessable. Refresh tokens here: `secrets.token_urlsafe(48)` = 48 random bytes = **384 bits**; `uuid.uuid4()` uses 122 random bits.

### Symmetric encryption

One shared key encrypts and decrypts. Fast. Modern choices are **AEAD** ciphers (Authenticated Encryption with Associated Data) such as **AES-256-GCM** and **ChaCha20-Poly1305**: they provide confidentiality *and* integrity (tampering is detected). Rules: **never reuse a (key, nonce) pair**; do not use ECB mode; do not use unauthenticated encryption; use a library's high-level API (`cryptography`'s `AESGCM`, Fernet, libsodium's `secretbox`). The hard part is **key management**: where the key lives, who can read it, how it rotates.

```python
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os
key = AESGCM.generate_key(bit_length=256); aes = AESGCM(key)
nonce = os.urandom(12); ct = aes.encrypt(nonce, b"secret", b"context")     # associated data is authenticated, not encrypted
aes.decrypt(nonce, ct, b"context")
```

### Asymmetric (public-key) cryptography

A **key pair**: a **private key** (secret) and a **public key** (shareable) with a mathematical relationship. Two big uses:

1. **Digital signatures**: the private key **signs**; anyone with the public key **verifies**; nobody can forge without the private key. *This is what makes RS256 tokens useful: the verifier cannot mint tokens.*
2. **Key exchange / encryption**: parties derive shared secrets (Diffie-Hellman, ECDH) or encrypt to a public key (RSA-OAEP, rarely used directly; hybrid encryption is typical).

**RSA** (Rivest-Shamir-Adleman) in miniature: pick two large primes `p, q`; `n = p·q`; choose public exponent `e` (65537); the private exponent `d` satisfies `e·d ≡ 1 (mod φ(n))`. Signing: `s = m^d mod n`; verifying: `s^e mod n == m`. Security rests on the difficulty of factoring `n`. A toy example you can run:

```python
p, q = 61, 53; n = p * q                    # 3233
phi = (p - 1) * (q - 1)                     # 3120
e = 17; d = pow(e, -1, phi)                 # 2753 (modular inverse)
m = 65
c = pow(m, e, n)                            # "encrypt": 2790
assert pow(c, d, n) == m                    # decrypt
s = pow(m, d, n); assert pow(s, e, n) == m  # sign / verify
```

(Real RSA uses **2048-bit or larger** keys and **padding** (PSS for signatures, OAEP for encryption): *textbook RSA is insecure.* JWT's `RS256` = RSASSA-PKCS1-v1_5 with SHA-256.) The repo's key generator:

```python
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
private = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
public  = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
```

**Elliptic-curve** schemes (**ECDSA**, **Ed25519**, **X25519**) give equal security with much smaller keys and faster operations; **Ed25519** is the modern default for signatures (JWT alg `EdDSA`; `ES256` is ECDSA with P-256). For new designs prefer Ed25519/ES256 unless a partner requires RSA. **Post-quantum** algorithms (ML-KEM, ML-DSA) are being standardised because large quantum computers would break RSA/ECC; TLS libraries are starting to ship hybrids.

### Certificates and PKI

A **certificate** binds a public key to an identity (a domain name), signed by a **CA**. Browsers trust a set of root CAs; servers present a **chain**. This is how you know the Caddy server is really `demo.example.com` (Chapter 16).

### Password hashing: a different problem

Humans choose **low-entropy** secrets. If a database leaks, attackers can try billions of guesses per second against a fast hash (GPUs: SHA-256 at ~10¹⁰/s). So passwords need a **deliberately slow, memory-hard** function with a per-password **salt**:

* **PBKDF2** (iterated HMAC; acceptable, FIPS-friendly; GPU-friendly so needs very high iteration counts).
* **bcrypt** (adaptive; 72-byte input limit; solid).
* **scrypt** (memory-hard).
* **Argon2id** (winner of the Password Hashing Competition; **memory-hard and time-hard**; current best practice). Parameters: **memory cost `m`**, **time cost `t`** (iterations), **parallelism `p`**. The encoded hash carries everything needed: `$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>`.

Memory-hardness hurts attackers because **memory, not just compute, is expensive on GPUs and ASICs**. A **salt** (random, per password, stored in the hash string) ensures identical passwords have different hashes and defeats **rainbow tables**. A **pepper** (a server-side secret mixed in, stored outside the database) adds a layer if only the DB leaks.

**This repo (`security/passwords.py`)**

```python
_hasher = PasswordHasher()               # argon2-cffi defaults follow current guidance (Argon2id)
MIN_LENGTH, MAX_LENGTH = 10, 128         # the max stops a megabyte "password" burning CPU/memory
COMMON = {"password", "password123", ...}      # a tiny deny-list (a real deployment would check a breach corpus)

def check_policy(password, email):
    ...  # length, deny-list, and "must not contain the email name" (if the local part is >= 4 chars)

_DUMMY_HASH = _hasher.hash("not-a-real-account-password")
def verify_password(password, stored_hash):
    try: _hasher.verify(stored_hash or _DUMMY_HASH, password)     # ALWAYS do one full verification
    except (VerifyMismatchError, VerificationError, InvalidHashError): return False
    return stored_hash is not None                                  # a dummy match never counts as success

def needs_rehash(stored_hash): return _hasher.check_needs_rehash(stored_hash)
```

Study each decision:

* **Dummy verification** equalises timing so response time cannot reveal which emails are registered (**user enumeration**).
* **Rehash on login**: if you strengthen parameters later, hashes created with old parameters are upgraded transparently the next time the user logs in (`accounts.authenticate` calls `needs_rehash`).
* **Policy**: length matters more than composition rules; NIST guidance favours **length, deny-lists of breached/common passwords, and no forced periodic rotation**. Production improvement: check candidates against a **breach corpus** (e.g. the Have I Been Pwned range API with **k-anonymity**: send only the first 5 hex characters of the SHA-1 of the password).
* **Never log or return passwords**; never email them.

## 20.3 Authentication, authorisation and sessions

### Definitions

* **Identification**: claiming an identity ("I am alice@example.com").
* **Authentication (AuthN)**: proving it (password, key, biometric, token).
* **Authorisation (AuthZ)**: deciding what that identity may do.
* **Accounting/audit**: recording what happened.

Factors: **something you know** (password), **have** (phone, hardware key), **are** (biometrics). **MFA** combines two or more. Common second factors: **TOTP** codes (RFC 6238), **WebAuthn/passkeys** (phishing-resistant public-key credentials in hardware or the device), SMS (weakest; SIM-swap risk).

```python
import hmac, hashlib, struct, time
def totp(secret: bytes, step=30, digits=6, t=None) -> str:        # RFC 6238 over RFC 4226 (HOTP)
    counter = int((t or time.time()) // step)
    mac = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = mac[-1] & 0x0F                                             # dynamic truncation
    code = (struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits
    return f"{code:0{digits}d}"
```

(MFA is **not** built in this project; it is a first item on any production roadmap.)

### Server-side sessions vs tokens

| | Server-side session (opaque id in a cookie) | Self-contained token (JWT) |
|---|---|---|
| State | stored on the server | in the token (stateless verification) |
| Revocation | **instant** (delete the session) | hard: valid until it expires |
| Scaling | needs shared session store | any server with the key can verify |
| Size | tiny cookie | larger |
| Best for | classic web apps | APIs, microservices, third parties |

Most robust designs combine them: **short-lived access tokens** (stateless, fast to verify, cannot be revoked but expire in minutes) plus a **long-lived refresh credential** stored server-side (revocable, rotated). That is exactly this app.

### OAuth 2.0 and OpenID Connect (know the vocabulary)

* **OAuth 2.0** is an *authorisation delegation* framework: a user lets an app access their resources at another service without sharing the password. Roles: **resource owner** (user), **client** (app), **authorisation server**, **resource server** (API). Flows: **Authorization Code with PKCE** (the standard for browser/mobile apps; PKCE binds the code to the client that asked and prevents interception attacks), **Client Credentials** (machine-to-machine), device code. Avoid the legacy implicit and password flows. Tokens: **access token** (short-lived), **refresh token**. Use `state` to prevent CSRF on redirects, exact redirect URI matching, scopes for least privilege.
* **OpenID Connect (OIDC)** adds *authentication* on top: an **ID token** (a JWT) describing who logged in, plus a standard `userinfo` endpoint and discovery documents (`/.well-known/openid-configuration`, JWKS).
* **SSO** with identity providers (Google, Okta, Entra ID, Auth0, Keycloak) is what enterprise customers expect; **SAML** is the older enterprise standard. As an FDE you will often integrate with the customer's IdP rather than build login. **Do not build your own identity system when a customer already has one.**
* This app is a first-party app with its own accounts and does not implement OAuth.

### Service-to-service authentication

When one backend calls another: **mTLS**, **signed JWTs** (this repo), **cloud workload identity** (AWS IAM roles, GCP service accounts, Kubernetes service account tokens, SPIFFE/SPIRE), **API keys** (simple, weaker). Prefer **short-lived credentials** and **asymmetric signatures** so the verifier cannot impersonate the signer.

## 20.4 JWT, completely

A **JSON Web Token (JWT, RFC 7519)** is a compact, URL-safe token with three Base64url-encoded parts joined by dots:

```
eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9 . eyJpc3MiOiJzdHlsaXN0LWFwaSIsInN1YiI6IjdmMmMuLi4ifQ . <signature>
        header                                  payload (claims)                                    signature
```

Decode by hand (no library):

```python
import base64, json
def b64url_decode(s): return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
h, p, s = token.split(".")
print(json.loads(b64url_decode(h)))   # {"alg": "RS256", "typ": "JWT"}
print(json.loads(b64url_decode(p)))   # {"iss": "stylist-api", "aud": "stylist-web", "sub": "<user uuid>", "iat": ..., "exp": ..., "jti": "..."}
```

**Anyone can read the payload.** A signed JWT (JWS) is **not encrypted**; never put secrets or sensitive personal data in it (the repo's tests assert "a token holds no secret material" and that the claims are exactly `{iss, aud, sub, iat, exp, jti}`). (JWE, encrypted JWTs, exist but are uncommon.)

### The signature

`signature = Sign(key, base64url(header) + "." + base64url(payload))`.

* **HS256** (HMAC-SHA256): *one shared secret* signs and verifies. Simple, fast; everyone who can verify can also forge. Fine within a single service.
* **RS256** (RSA-SHA256): the **private key signs**, the **public key verifies**; the verifier cannot mint tokens. Choose it (or ES256/EdDSA) when **verifier ≠ signer** or when many services verify (this repo).
* **ES256 / EdDSA**: elliptic-curve signatures, smaller and faster.

From scratch (HS256), to demystify:

```python
import base64, hashlib, hmac, json
b64u = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def sign_hs256(claims: dict, secret: bytes) -> str:
    head = b64u(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64u(json.dumps(claims, separators=(",", ":")).encode())
    sig = hmac.new(secret, f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64u(sig)}"
def verify_hs256(token: str, secret: bytes) -> dict:
    head, body, sig = token.split(".")
    expected = b64u(hmac.new(secret, f"{head}.{body}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected): raise ValueError("bad signature")      # constant time
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
```

### Registered claims

| Claim | Meaning | Check on verification |
|---|---|---|
| `iss` | issuer (who made it) | must equal the expected issuer |
| `sub` | subject (who it is about: user id) | identity |
| `aud` | audience (who it is for) | must include *this* service |
| `exp` | expiry (Unix seconds) | reject if past (plus small leeway) |
| `nbf` | not before | reject if in the future |
| `iat` | issued at | sanity checks; max lifetime |
| `jti` | unique id | replay protection, revocation lists |

### Verification checklist (every item matters)

1. **Pin the algorithm.** `jwt.decode(token, key, algorithms=["RS256"], ...)`: *never* let the token's own `alg` header choose.
2. Verify the **signature** with the right key.
3. Check **`exp`**, **`nbf`** (with small leeway), **`iss`**, **`aud`**.
4. **Require** the claims you rely on (`options={"require": [...]}`), because a missing `exp` means "never expires".
5. Enforce **your own maximum lifetime** (`exp - iat`).
6. For single-use tokens, check **`jti`** against a replay store.
7. Map `sub` to an identity and **authorise** it (a valid token proves identity, not permission).

### Famous JWT vulnerabilities

* **`alg: none`**: some libraries accepted unsigned tokens when the header said "none". *Pin algorithms.*
* **Algorithm confusion (RS256 → HS256)**: an attacker takes the *public key* (public!), signs a token using it as an HS256 *secret*, and sets `alg: HS256`; a naive verifier that picks the algorithm from the header and the key from config accepts it. *Pin algorithms; use separate key objects per algorithm.*
* **Weak HS256 secrets** can be brute-forced offline from any captured token.
* **Missing `aud`/`iss` validation** → **token confusion**: a token minted for service A accepted by service B. This repo uses **two separate key pairs** and different `aud`/`iss`, so *"a user's login token is useless against the tool server and vice versa."*
* **Unbounded lifetime** (no `exp`).
* **Key injection via `jku`/`kid`** headers that point the verifier at attacker-controlled keys. Do not follow untrusted key URLs; whitelist.
* **Storing JWTs in `localStorage`** (XSS theft).
* **Treating JWTs as a session you can revoke**: you cannot (until expiry), hence short lifetimes, refresh tokens, denylists keyed by `jti`, or key rotation in emergencies.
* **Leaking in URLs/logs/referers.**

### Key identification and rotation

Production systems add a **`kid`** (key id) header and publish public keys at a **JWKS** endpoint so verifiers can fetch the right key and rotate keys with overlap (old key still verifies until old tokens expire). This repo uses one fixed key per purpose and rotation is "regenerate and restart", which invalidates in-flight tokens: acceptable at this scale, a limit to name.

### Leeway and clock skew

Machines disagree on time. A token minted "now" by the API may look "issued in the future" to a verifier whose clock is 8 s behind (`ImmatureSignatureError`/`InvalidIssuedAtError`). A small **leeway** (here 10 s) tolerates skew; more leeway lengthens token lifetime for an attacker. When a timing error occurs, the tool server logs **how far off** the token was (`iat +24s ... vs our clock`) so clock drift is visible, and it never makes the decision from that debug value. Fix real skew with **NTP**.

## 20.5 This repo's token and session design

### Two token systems, one library

| | **User login tokens** | **Service (tool-server) tokens** |
|---|---|---|
| Minted by | API (`security/tokens.py::mint_access_token`) | API (`mcp_auth.py::mint_service_token`) |
| Verified by | API (`verify_access_token`) | MCP server (`auth.py::ServiceJWTVerifier`) |
| Algorithm / keys | RS256; `AUTH_JWT_PRIVATE_KEY` / `AUTH_JWT_PUBLIC_KEY` | RS256; `MCP_JWT_PRIVATE_KEY` (API only) / `MCP_JWT_PUBLIC_KEY` (MCP only) |
| `iss` / `aud` | `stylist-api` / `stylist-web` | `stylist-api` / `stylist-mcp` |
| `sub` | user id | the end user's id (for per-user limits) |
| Lifetime | **15 minutes** | **30 seconds**, new token **per HTTP request**, max 60 s enforced |
| Single use? | no | **yes** (`jti` replay guard) |
| Where held | JS memory | in flight only |

### User login tokens (`security/tokens.py`)

```python
claims = {"iss": ..., "aud": ..., "sub": user_id, "iat": issued, "exp": issued + ttl, "jti": uuid.uuid4().hex}
jwt.encode(claims, private_pem, algorithm="RS256")
...
jwt.decode(token, public_pem, algorithms=["RS256"], audience=..., issuer=..., leeway=...,
           options={"require": ["exp", "iat", "sub", "iss", "aud"]})
```

`InvalidToken` never says why (expired? forged? wrong audience?), "so it tells an attacker nothing". `current_user` turns any failure into the same 401.

### Refresh tokens: rotation and reuse detection (`accounts.py`)

The refresh token is **not** a JWT; it is an opaque 384-bit random string:

```python
raw = secrets.token_urlsafe(48);  hashed = sha256(raw)          # only `hashed` is stored
```

**Why a fast hash is fine here**: the input has 384 bits of entropy, so brute force is infeasible; a slow hash would only waste CPU on every refresh.

Lifecycle:

1. **Login** creates a new **family** (`family_id`), stores the first token's hash.
2. **Refresh**: look up the hash `FOR UPDATE`; reject if unknown or revoked; **if `used_at` is set, this is a replay: revoke the whole family** (both the thief and the legitimate user are logged out and must sign in again) and report `reuse`; if expired, invalid; if the user is disabled, invalid; otherwise **mark it used and issue a new token in the same family**.
3. **Logout** revokes the whole family.

Why rotate at all? A stolen refresh token is valuable for 14 days; with rotation, a thief and the real user *race*: whoever refreshes second presents a used token, which **trips the alarm** (the `refresh_token_reuse_detected` audit event). It converts silent theft into a visible event.

Subtle points to be able to discuss:

* **The race with two tabs**: each tab holds its own memory and could call `/auth/refresh` at nearly the same moment with the *same cookie value*; the second request may look like reuse and log everything out. The in-page single-flight protects *one tab*; production systems often allow a short **reuse grace window** (a few seconds) to avoid false positives. A real-world design trade-off.
* **The cookie is scoped** (`Path=/auth`, `HttpOnly`, `SameSite=Strict`, `Secure` in prod), and its use requires a **custom header** (`X-Requested-With: stylist-web`) as CSRF defence.
* **Expired tokens accumulate** in `refresh_tokens`: add a cleanup job.
* **Everything is audited** (`login`, `login_failed`, `token_refreshed`, `refresh_token_reuse_detected`, `logout`) with a **12-hex email tag** (hash prefix), so repeated attempts against one email are visible without storing the email in a permanent record.

### Login hardening checklist (all present)

* **Per-IP rate limit** (30 auth calls/min) and **per-(email, IP) lockout** (5 failures in 15 min → 429 with `Retry-After`; success clears the counter).
* **Uniform failure**: "Invalid email or password." for unknown email, wrong password and disabled account; same time cost (dummy hash).
* **Email normalisation** (trim, lower-case, shape, length ≤ 254).
* **Password policy** and **max length**.
* **Rehash on login** when parameters strengthen.
* **Short access tokens**, **rotating refresh tokens**, **family revocation**.
* **Account disable** (`disabled_at`) honoured at login, refresh and `me`.
* **Audit** of successes and failures.

### What is missing (name these proactively)

* **MFA/passkeys**, **email verification**, **password-reset flow** (a common account-takeover path), **breached-password check**, **session/device list** and "log out everywhere", **suspicious-login alerts**, **CAPTCHA/bot defence** on signup, **per-account lockout** distinct from per-IP, **distributed rate limits** (Redis), **JWKS and `kid`-based rotation**, **reuse grace window**, **expired-token cleanup**.

### Service tokens and the tool server

(Walkthrough from Chapter 8, now with cryptographic detail.)

* **Minted fresh per request** by an `httpx2.Auth` subclass (`ServiceTokenAuth.auth_flow` sets `Authorization: Bearer <new token>` on *every* request).
* **Verified** by `ServiceJWTVerifier.verify_token`: RS256 pinned; `aud`/`iss` checked; `leeway` 10 s; required claims `exp, iat, jti, sub, iss, aud`; separate handling for **timing errors** (logs the skew) versus other JWT errors; **lifetime cap** (`exp - iat <= 60`); then **`ReplayGuard.first_use(jti, exp + leeway)`**: remembers ids until they could no longer be valid and refuses a second use; bounded at 100,000 entries and **fails closed** when full; refusals counted in `mcp_auth_refusals_total{reason}` (`clock_or_expiry`, `invalid_token`, `lifetime_too_long`, `replay`).
* **Returns an `AccessToken`** whose `subject` becomes `caller_id()` for per-user limits.
* **Cannot mint**: the server only loads a **public key** (`serialization.load_pem_public_key`), and refuses to start if it is missing or invalid (`RuntimeError`).
* **Proven behaviour** (from the guide): valid → 200; missing/garbage → 401; same token twice → 200 then 401; API clock 8 s ahead accepted, 25 s ahead → 401; foreign `Host` → 421; foreign `Origin` → 403; logs hold reasons only.
* **Limit**: the `jti` memory is per process. With several tool-server replicas an attacker could replay a token once per replica; the fix is a shared store (Redis `SET jti NX EX ttl`).

### The key-generation script (`scripts/generate_jwt_keys.py`)

* Creates **two pairs** (`mcp`, `auth`): RSA-2048 keys, PKCS#8 PEM private, SubjectPublicKeyInfo PEM public.
* Writes them into `.env` (or `--out .env.production`) as **single-line values with literal `\n`** (the loaders convert back, and **also strip surrounding quote marks**, because hosting platforms' variable screens can store pasted values with the quotes included; `services/mcp/tests/test_key_format.py` checks four spellings), and **never prints** key material, only a **fingerprint** (`sha256(public)[:16]`) so you can tell keys apart.
* `--rotate [pair]` replaces keys (restart the services that use them); existing tokens signed with old keys become invalid.
* Documents the **distribution rule**: *the MCP service gets only `MCP_JWT_PUBLIC_KEY`; the API gets the other three.* The compose files enforce it by passing each service **only** the variables listed.

## 20.6 Secrets management

A **secret** is anything whose disclosure harms you: API keys, private keys, database passwords, tokens, signing keys, cookies.

**Rules**

1. **Never commit secrets.** `.env` and `.env.*` are git-ignored (except `.env.example`), `*.pem` ignored, `.data/` and `infra/observability/.secrets/` ignored. **`.dockerignore` excludes them from images too**, so they cannot be baked into layers.
2. **Never bake secrets into images**; inject at runtime (env vars, mounted files, secret managers).
3. **Give each service only the secrets it needs** (the compose `environment:` lists are explicit; "It gets only the variables listed here (never the whole .env)").
4. **Never log them, put them in URLs, or send them to the browser.** (`httpx` logging lowered; SerpAPI's key is in query strings: take extra care.)
5. **Rotate** on a schedule and **immediately on suspicion**; design so rotation is easy.
6. **Detect leaks**: pre-commit/CI secret scanning (gitleaks, trufflehog, GitHub secret scanning). This repo has a **hygiene test module** (`test_repo_hygiene.py`) with three checks: no *value* may appear next to a `KEY/TOKEN/SECRET/PASSWORD` name in `.env.example` (except one documented dev default), no file git could commit may contain a **key-shaped string** (OpenRouter-style `sk-or-v1-...`, generic `sk-...`, or a PEM `PRIVATE KEY` header), and `.env` must be git-ignored. A **test as a control**; failure messages print variable *names*, never values.
7. **Use a secret manager in production**: HashiCorp Vault, AWS Secrets Manager/SSM, GCP Secret Manager, Azure Key Vault, Doppler/1Password, Kubernetes secrets (base64 is *not* encryption: enable encryption at rest), SOPS/age for encrypted-in-git files.
8. **Separate secrets per environment** (dev ≠ prod keys).
9. **If a secret leaked**: assume compromised; **revoke and rotate**; check usage logs; removing it from git history (`git filter-repo`) is hygiene, not remediation, because copies exist (forks, caches, clones).
10. **Short-lived credentials** beat long-lived ones (OIDC to cloud, IAM roles).

This project's own history contains the realistic version of rule 9: real OpenRouter and SerpAPI keys were pasted into a tracked example file and one was printed in a terminal; the correct response is **rotate the keys**, add a **test** that makes that mistake fail loudly, and **mask values** when inspecting env files (print names and set/empty only).

**Scripts here that handle secrets safely**: `init_production_env.py` generates a random database password, adds only what is missing, **never prints a secret**, and tells you which keys are still empty; `init_observability.py` generates the metrics token with `secrets.token_urlsafe(32)`, keeps an existing one on re-run, and prints only whether it was kept or newly generated, never the value. (It writes the token to `.env` and to a git-ignored file that Prometheus mounts; it does not tighten file permissions, so on a shared machine you would `chmod 600` those files.)

## 20.7 Key management and rotation in depth

* **Envelope encryption**: data is encrypted with a **data key (DEK)**; the DEK is encrypted with a **key-encryption key (KEK)** held in a **KMS/HSM** (AWS KMS, GCP KMS, Vault Transit). Rotating the KEK re-wraps small keys, not all data.
* **HSMs** keep private keys in tamper-resistant hardware that signs on request without exposing the key.
* **Rotation with overlap** for signing keys: publish new public key (`kid` 2) while old (`kid` 1) still verifies; start signing with `kid` 2; retire `kid` 1 after the longest token lifetime. For service tokens living 30 s this overlap is tiny.
* **Emergency rotation** should be a documented, rehearsed runbook.
* **Backups of keys**: losing the signing key is an outage; leaking it is a breach. Control access to both.

## 20.8 Attack catalogue for authentication (and what defends in this repo)

| Attack | How | Defence here |
|---|---|---|
| **Brute force** | many guesses at one account | lockout per (email, IP), IP limit, slow Argon2 |
| **Credential stuffing** | breached passwords from other sites | rate limits; (add) breach-password check, MFA, bot defence |
| **Password spraying** | one common password across many accounts | per-IP limit (the (email, IP) lockout alone does not stop this) |
| **User enumeration** | different errors/timing for known vs unknown email | uniform message + dummy hash |
| **Phishing** | fake login page | (add) passkeys/WebAuthn; HSTS and same-origin help only partially |
| **Session/token theft (XSS)** | injected script reads tokens | HttpOnly refresh cookie, access token in memory, escaping (add CSP) |
| **Token theft (logs/URLs/network)** | token leaked from a log or capture | short lifetimes, single-use service tokens, TLS, no tokens in URLs |
| **Replay** | reuse a captured token | `jti` single use (service), rotation + reuse detection (refresh) |
| **CSRF** | forged cross-site request using cookies | `SameSite=Strict`, custom header on cookie endpoints, bearer header elsewhere |
| **Timing attacks** | measure response times | `compare_digest`, dummy hash |
| **JWT attacks** | `alg:none`, confusion, weak keys, wrong audience | pinned `RS256`, required claims, separate key pairs and audiences |
| **Account takeover via reset** | weak recovery flow | (no reset flow built; design carefully: single-use, short-lived tokens, no email enumeration) |
| **Insider/DB leak** | stolen database | Argon2id; only hashes of refresh tokens; no plaintext secrets; audit chain |
| **Clock manipulation** | skew to extend/deny tokens | small leeway; NTP; skew logging |

## Common mistakes

* Inventing crypto, or using `random` for secrets.
* Fast hashes (MD5/SHA-256) for passwords.
* `==` for comparing secrets.
* Letting the JWT header choose the algorithm; missing `aud`/`iss`/`exp` checks.
* Putting sensitive data in JWT payloads (it is public).
* Long-lived access tokens with no revocation story.
* One shared key for unrelated token types.
* Different error messages for "no such user" and "wrong password".
* Secrets in git, images, logs, front-end bundles, or URLs.
* Never rotating keys, and no plan for it.
* Building your own login when the customer's SSO exists.

## Summary

* Think in assets, adversaries, trust boundaries and layered controls; apply least privilege, fail closed, defence in depth.
* Know the primitives: hashes, HMAC (+ constant-time compare), CSPRNG, AEAD encryption, signatures, and password hashing (Argon2id with salt); encoding is not encryption.
* Authentication = proving identity; authorisation = checking permission on every object; combine short-lived access tokens with rotating, server-tracked refresh tokens.
* JWT: Base64url header.payload.signature; readable by anyone; pin algorithms, validate `iss/aud/exp`, separate key pairs per purpose, bound lifetimes, use `jti` for single use, plan rotation.
* This app's design: Argon2id; 15-minute RS256 access tokens in memory; 14-day rotating refresh tokens (hash stored, reuse revokes the family); lockouts; uniform errors; 30-second single-use service tokens verified with a public key; secrets scoped per service and checked by tests.

## Key terms

*CIA, STRIDE, trust boundary, hash, HMAC, constant-time comparison, CSPRNG, AEAD, RSA, ECDSA/Ed25519, signature, certificate, Argon2id, salt, pepper, MFA, TOTP, passkey, OAuth 2.0, OIDC, PKCE, JWT, JWS, claim, `alg` confusion, JWKS, `kid`, `jti`, leeway, refresh token rotation, reuse detection, token family, replay, secret manager, KMS.*

## Interview questions

1. Explain hashing vs encryption vs signing. Which would you use for passwords? Refresh tokens? API webhooks?
2. Why Argon2id for passwords but plain SHA-256 for the refresh token here?
3. What is in a JWT? Is it encrypted? What are three ways JWT verification goes wrong?
4. HS256 vs RS256: when do you choose each? Why does the tool server hold only a public key?
5. Describe refresh-token rotation with reuse detection. What attack does it address, and what false positive can it cause?
6. How does the login endpoint avoid revealing whether an email exists?
7. How would you add MFA to this app? Where in the flow?
8. A teammate pasted an API key into a committed file. What do you do, in order?
9. What is a timing attack and where is it relevant in this code?
10. How would you rotate the JWT signing keys without downtime?

## Exercises

1. Decode an access token from your running app by hand (no library) and list every claim; then verify the signature with the public key using `cryptography`.
2. Implement the alg-confusion attack against a deliberately vulnerable verifier (header-chosen algorithm) in a scratch script, then show the pinned version rejecting it.
3. Add TOTP-based MFA to the account flow: migration (`mfa_secret` encrypted at rest, recovery codes hashed), enrolment, verification step, tests.
4. Add a 10-second **reuse grace window** to `rotate` and a test for the two-tab race; discuss the security trade-off.
5. Implement JWKS-style rotation for the MCP verifier: accept two public keys keyed by `kid`, with tests for overlap and retirement.
6. Write a pre-commit hook that runs a secret scanner and prove it blocks a fake key.
