# Chapter 27. Reverse Proxies, TLS, DNS and the Cloud

> **Learning objectives.** Configure and reason about a reverse proxy (Caddy here; nginx, Traefik, cloud load balancers elsewhere); understand automatic HTTPS and certificate operations; use DNS and CDNs deliberately; understand cloud building blocks (regions, VPCs, security groups, IAM, managed services) and their costs; and walk through deploying this app to a small server, including the hardening and the failure modes.
>
> **Prerequisites.** Chapters 16, 23, 25, 26.

---

## 27.1 Caddy and this repo's Caddyfile

A **reverse proxy** is the single front door: it terminates TLS, routes requests to internal services, and hides the topology. **Caddy** is notable for **automatic HTTPS**: give it a real domain name and it obtains, installs and renews certificates itself (Let's Encrypt or ZeroSSL via ACME) with almost no configuration.

### The file, line by line

```caddyfile
{$SITE_ADDRESS::80} {
	@api path /auth/* /conversations /conversations/* /products/* /admin/* /health
	handle @api {
		reverse_proxy {$API_UPSTREAM:api:8000} {
			flush_interval -1
		}
	}
	handle {
		reverse_proxy {$WEB_UPSTREAM:web:3000}
	}

	header {
		-Server
		Strict-Transport-Security "max-age=31536000"
	}
}
```

* **Site address**: `{$SITE_ADDRESS::80}` is an **environment placeholder with a default**: the syntax is `{$NAME:default}`, so this reads `SITE_ADDRESS`, defaulting to `:80`.
  * **`:80`**: serve plain HTTP on port 80 for any hostname (the local test). **No HTTPS, no redirect.**
  * **`demo.example.com`** (a hostname): Caddy enables **automatic HTTPS**: obtains a certificate, serves 443, and **redirects HTTP → HTTPS**.
* **Named matcher** `@api path ...`: matches requests whose path begins with those prefixes. This is an **allow-list**: only these paths may reach the API. Note `/conversations` and `/conversations/*` are listed separately (the `*` form does not match the bare path).
* **`handle` blocks** are mutually exclusive: the first matching `handle` wins; the final `handle` with no matcher is the **fallback** for everything else (the web app). Ordering semantics matter; test with `curl`.
* **`reverse_proxy {$API_UPSTREAM:api:8000}`**: upstream defaults to the compose service `api` on port 8000; platforms that give you an address override via the environment variable.
* **`flush_interval -1`**: flush response data to the client **immediately** (do not buffer), which is **essential for SSE streams**: "send streamed chat events immediately instead of buffering them".
* **`header { -Server; Strict-Transport-Security ... }`**: removes the `Server` header (less information for attackers) and adds **HSTS for one year**. Browsers ignore HSTS on plain HTTP, so the laptop test is unaffected; on a real HTTPS domain it forces HTTPS for a year (a deliberate commitment: if you later need HTTP, browsers will refuse).

### What the proxy gives you (and what it does not)

* **One origin for UI and API** → same-site cookies work, no CORS (Chapter 16).
* **Only the allow-listed paths reach the API; `/metrics` is deliberately unreachable** from outside.
* **TLS termination** with automatic certificates, HTTP/2 and HTTP/3 to browsers.
* **Not present** (honest gaps): response **compression** (`encode zstd gzip`; careful: compression and streaming interact, enable it for static assets and keep SSE uncompressed or flushed), **access logs** (`log`), **rate limiting/WAF** (plugins or an upstream CDN), a **Content-Security-Policy** header, **request body size limits** (`request_body { max_size 1MB }`), **timeouts** (reverse_proxy transport timeouts), **security headers** beyond HSTS (Referrer-Policy etc. are set by the API for API responses only).

### Caddy versus alternatives

| Proxy | Strengths | Notes |
|---|---|---|
| **Caddy** | automatic HTTPS, tiny readable config, HTTP/3 | great for small deployments and demos |
| **nginx** | ubiquitous, very fast, huge ecosystem | manual certificate management (certbot), verbose config; set `proxy_buffering off` for SSE |
| **Traefik** | dynamic config from Docker/Kubernetes labels, ACME | popular in container setups |
| **HAProxy** | high-performance L4/L7 load balancing | advanced health checks, stick tables |
| **Envoy** (Istio, service meshes) | observability, mTLS, advanced routing | complex |
| **Cloud load balancers** (AWS ALB/NLB, GCP LB, Azure App Gateway) | managed, scalable, WAF integration | idle timeouts and costs; SSE needs attention |
| **CDN/edge** (Cloudflare, Fastly, CloudFront) | caching, DDoS protection, WAF, global presence | proxy timeouts apply to streams |

## 27.2 TLS operations

### Certificate lifecycle with ACME

1. You own or control a **domain name** pointing (A/AAAA record) at your server.
2. Caddy asks a CA (Let's Encrypt) for a certificate for that name. The CA sends a **challenge** proving you control the name:
   * **HTTP-01**: the CA fetches a token over **port 80** from the name.
   * **TLS-ALPN-01**: via **port 443**.
   * **DNS-01**: you publish a DNS TXT record (needed for **wildcard** certificates; requires DNS API access).
3. The CA issues a short-lived certificate (about 90 days for Let's Encrypt); Caddy **renews automatically** well before expiry and stores state in `/data` (the `caddy_data` volume), so **restarts do not re-request certificates** (important because **CAs rate-limit issuance**).

Practical consequences:

* **Ports 80 and 443 must be reachable from the internet** and DNS must already resolve; otherwise issuance fails (the first visit logs ACME errors).
* **Test with a staging CA** (to avoid rate limits while experimenting).
* **Wildcard DNS names such as `203-0-113-7.sslip.io`** (a free service resolving a name containing an IP to that IP) let you get a real certificate without buying a domain, as the deploy guide suggests; but names under a shared public domain may share rate limits with many other users, so a domain of your own is better for anything lasting.
* **Never lose the volume** carelessly; if you do, reissue (mind rate limits).
* **Expiry monitoring**: alert if the certificate has < 14 days left (external check).

### TLS configuration notes

* Modern defaults: **TLS 1.2+ (prefer 1.3)**, strong ciphers, forward secrecy; Caddy sets these.
* **HSTS** and **HSTS preload** (submitting to browser preload lists is effectively permanent: be sure all subdomains support HTTPS).
* **OCSP stapling** (Caddy does it).
* **mTLS** for internal service-to-service or customer-specific access.
* **Corporate environments** may use TLS-inspecting proxies with private CAs: your app may need the corporate root certificate in its trust store (a classic FDE issue: `SSL: CERTIFICATE_VERIFY_FAILED` for outbound calls; the fix is trusting the corporate CA bundle, **never** disabling verification).
* **Test**: `curl -vI https://host`, `openssl s_client -connect host:443 -servername host`, and external scanners (SSL Labs) for public sites.

## 27.3 DNS in practice

* **Register a domain** with a registrar; delegate to DNS hosting (registrar, Cloudflare, Route 53, Cloud DNS).
* **Records**: `A` (name → IPv4), `AAAA` (IPv6), `CNAME` (name → another name; not allowed at the zone apex unless the provider offers ALIAS/ANAME flattening), `TXT`, `MX`, `CAA` (restrict who may issue certificates for the domain).
* **TTL strategy**: before a migration, **lower the TTL** (say to 60 s) a day ahead; after cutover raise it again. Caches obey TTL, so "DNS propagation" is just cache expiry.
* **IPv6**: if you publish an `AAAA` record the server must really serve IPv6, or clients that prefer IPv6 will hang (the stall from Chapter 16).
* **Subdomain takeover**: dangling CNAMEs to deprovisioned services can be claimed by attackers; clean up DNS.
* **Split-horizon DNS** (different answers inside and outside a network), private DNS zones in clouds, and **service discovery** (compose names, Kubernetes DNS) are all DNS under the hood.
* **DNSSEC** signs DNS data to prevent spoofing; adoption varies.
* **Debug**: `dig +short A name`, `dig @8.8.8.8 name`, `dig +trace name`, `dig CAA domain`.

## 27.4 CDNs, WAFs and edge services

A **CDN** caches content close to users and absorbs traffic; a **WAF** (web application firewall) filters malicious requests (SQLi/XSS signatures, bot rules, rate limits). **Cloudflare**, **Fastly**, **CloudFront**, **Akamai** combine them with **DDoS protection**.

For this app:

* Cache only **static assets** (Next's `/_next/static/*`); never cache `/auth` or API responses that vary by user.
* **Streaming**: CDNs may buffer or enforce **proxy read timeouts** (on some plans around 100 seconds) and idle cut-offs; test that SSE flows end to end; consider sending heartbeat comments during long silent stages.
* **Real client IP**: the CDN becomes the proxy: trust *its* forwarded headers and restrict the origin to accept traffic only from the CDN (firewall to CDN IP ranges or use authenticated origin pulls/tunnels like **Cloudflare Tunnel**, which also removes the need to open ports 80/443).
* **Bot defence and CAPTCHA** on signup/login to blunt credential stuffing and credit-draining signups.

## 27.5 Load balancers

* **L4** (TCP/UDP) balancers forward connections without understanding HTTP; **L7** (HTTP) balancers route by host/path/header and can terminate TLS.
* **Algorithms**: round robin, least connections, hashing/sticky.
* **Health checks** remove unhealthy backends (`/health`).
* **Idle timeouts**: AWS ALB defaults to **60 s** (configurable), many LBs similar; a stream silent longer than the timeout is cut. Chat turns here emit events as stages finish, but a single slow stage (search under rate limits) could exceed it, so configure higher timeouts or send keep-alive comments.
* **Stickiness**: not required by this app's persistence design (conversation state is in Postgres), but its **in-memory per-process state** means different instances see different limiter counters (Chapter 32).
* **TLS termination at the LB** and plain HTTP inside the VPC is common; re-encrypt if compliance requires.

## 27.6 Cloud fundamentals

### Geography and responsibility

* **Region**: a geographic area with multiple **availability zones (AZs)** (independent data centres). For Indian users and data residency: AWS `ap-south-1` (Mumbai) / `ap-south-2` (Hyderabad), Google Cloud `asia-south1` (Mumbai) / `asia-south2` (Delhi), Azure Central India / South India. Latency to users and **legal residency requirements** drive the choice.
* **Shared responsibility model**: the provider secures the *cloud* (hardware, hypervisor, managed-service internals); **you** secure what you put *in* it (configuration, IAM, data, OS patches on VMs, application).

### Compute

* **VMs** (EC2, Compute Engine, Azure VMs, Oracle Cloud): you manage the OS. Size by vCPU/RAM; burstable types are cheap for light loads. Building Docker images on a **1 GB** VM can run out of memory (add swap, or build in CI and pull images).
* **Containers**: ECS/Fargate, Cloud Run, Container Apps, Kubernetes (Chapter 26).
* **Functions** (Lambda, Cloud Functions): short-lived event handlers; poor fit for long SSE chats and stateful agents.
* **Free tiers** (for example Oracle Cloud's Always Free VMs, mentioned in the deploy guide) are great for demos; read the terms (reclamation of idle instances, region limits).

### Networking

* **VPC** (virtual private cloud): your isolated network. **Subnets** (public: route to an **internet gateway**; private: no direct internet inbound; outbound via a **NAT gateway** (costly)).
* **Security groups** (stateful, instance-level allow-lists: *open only what you need*; for this app inbound 80/443 from anywhere and 22 from your IP) vs **network ACLs** (stateless, subnet-level).
* **Private connectivity** to managed databases; **VPC endpoints** to cloud APIs without traversing the internet.
* **Egress control**: restrict outbound traffic where possible (also mitigates SSRF and exfiltration).
* **Instance metadata service**: `169.254.169.254` hands out credentials to code on the instance; on AWS require **IMDSv2** and avoid attaching powerful roles to web-facing VMs (Chapter 21).

### Storage and data

* **Block** (EBS/Persistent Disk: the VM's disk), **file** (EFS/Filestore), **object** (S3/GCS/Azure Blob: cheap durable blobs, lifecycle rules, **Object Lock** for WORM) (Chapter 22).
* **Managed databases** (RDS/Aurora, Cloud SQL/AlloyDB, Azure Database, Neon, Supabase): automated backups, patching, failover; recommended over self-managed Postgres in production.
* **Managed Redis** (ElastiCache, Memorystore) for the shared limiter/replay state needed when scaling out.

### Identity and access (IAM)

* **Principals** (users, groups, roles/service accounts) get **policies** granting actions on resources. **Least privilege**; **no long-lived access keys** in code or CI (use **role assumption**, **instance profiles**, **workload identity federation / OIDC from GitHub Actions**); **MFA** on human accounts; **separate accounts/projects** per environment; audit with CloudTrail/Cloud Audit Logs.
* **Secrets and keys**: Secrets Manager/Parameter Store, Secret Manager, Key Vault; **KMS** for encryption keys.

### Cost

Cost surprises: **egress bandwidth**, **NAT gateways**, idle load balancers, over-provisioned VMs, unattached disks, snapshots, logs retention, managed-service minimums, and (for AI) **model and search API usage**. Practices: **budgets and alerts** from day one, **tags** per project, right-size, schedule non-prod shutdowns, review the bill monthly, estimate before you build (Chapter 14).

### Infrastructure as Code

Define infrastructure in files (Terraform/OpenTofu, Pulumi, CloudFormation/CDK, Bicep) so environments are **reproducible, reviewable and auditable** (Chapter 28). For a single VM, a documented script or cloud-init can be enough; for anything larger, use IaC.

## 27.7 Deploying this app to a small server (expanded walkthrough)

This expands `docs/deploy.md` with the reasoning and the failure modes. The topology: **one VM** running `docker-compose.prod.yml`, with Caddy as the only public service. (For the platform alternative, Railway with four services and Caddy folded into the web container, see section 1b.9 of [Chapter 1b](01b-how-the-servers-connect.md#1b9-the-railway-layout-the-same-system-as-four-services).)

### Step 0: decide and prepare

* **VM**: Linux (Ubuntu LTS), **2 GB RAM or more**, a few GB disk (images and volumes), in a region near users (Mumbai for Indian users).
* **Keys first**: the deploy guide's step 1: **rotate** any OpenRouter/SerpAPI keys that ever appeared in a committed file or pasted output and use the **new** ones on the server.
* **Name**: a domain's A record, or `<ip-with-dashes>.sslip.io`.

### Step 1: harden the machine

```bash
# as a sudo user on a fresh Ubuntu VM
sudo apt update && sudo apt -y upgrade
sudo adduser deploy && sudo usermod -aG sudo deploy          # non-root admin; add your SSH public key to ~deploy/.ssh/authorized_keys
sudoedit /etc/ssh/sshd_config                                 # PasswordAuthentication no; PermitRootLogin no
sudo systemctl restart ssh
sudo ufw default deny incoming && sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
sudo apt -y install unattended-upgrades fail2ban              # automatic security patches; ban brute-force SSH
```

Also set the **cloud firewall/security group** to allow only 22 (ideally your IP), 80, 443. **Never expose the Docker API (2375/2376)**.

### Step 2: install Docker and get the code

Install Docker Engine + the Compose plugin from Docker's official repository; add the `deploy` user to the `docker` group (note: docker-group membership is effectively root: protect that account); `git clone` the repository. Generate keys **on the server** so private keys never travel:

```bash
uv run --project services/mcp python scripts/generate_jwt_keys.py --out .env.production
python scripts/init_production_env.py --server <your-name>
$EDITOR .env.production      # put in the NEW OPENROUTER_API_KEY, SERPAPI_API_KEY, ADMIN_EMAILS; keep STYLIST_MODEL
chmod 600 .env.production
```

(`init_production_env.py --server name` sets `SITE_ADDRESS`, `PUBLIC_URL=https://name`, generates a random DB password, and prints only names, never values.) On the server **do not set** `ENVIRONMENT` or `BACKEND_MODE`: the defaults are production and real mode.

### Step 3: launch and verify

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.production ps          # all healthy?
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f caddy   # watch certificate issuance
curl -I https://<your-name>/health            # 200 and valid TLS
```

Then in a browser: register an account, ask for "college wear, around ₹4000" (mind the free model quota: ~8 conversations a day), pick a style, click Buy. From outside, verify what must **not** work: `curl https://<name>/metrics` should not reach the API (Caddy does not route it; the request falls through to the web app and returns its 404), `https://<name>:8000` and `:5432` should be unreachable, `/docs` should be absent.

### Step 4: operate

* **Backups** (cron + `pg_dump`, copy off-box, test restore: Chapter 17).
* **Monitoring**: an external uptime probe on `/health`; certificate expiry alert; disk usage alert; (optionally) run the local observability profile only on your laptop, since it is not part of the prod layout.
* **Updates**: `git pull` + `up -d --build`; rebuilds need RAM, so consider building images elsewhere (CI) and pulling.
* **Log hygiene**: Docker's default JSON log driver grows without limit; set `max-size`/`max-file` in `/etc/docker/daemon.json`.
* **Firewall and SSH review**; patch the host; rotate secrets on schedule.
* **Cost watch**: model quota, SerpAPI credits (the prod caps default to 10/user and 25 global per day), VM bill.

### Failure modes and fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| Browser says insecure / Caddy logs ACME errors | DNS not pointing at the VM yet; port 80/443 blocked; wrong `SITE_ADDRESS` | check `dig`, security group and `ufw`; restart Caddy; use staging CA while testing |
| Login works but you are logged out on refresh | cookie `Secure` over HTTP, or different site/origin | use HTTPS; ensure `COOKIE_SECURE` matches the scheme; same origin via Caddy |
| 502 from Caddy | API/web not healthy or crashed | `ps`, `logs api`, OOM kills (`dmesg`) |
| Stream arrives all at once | an intermediary buffering (CDN, LB) | disable buffering; heartbeats; check timeouts |
| `docker compose up` fails with "run scripts/init_production_env.py" | required variable missing (the `:?` guard working) | run the script; fill the file |
| Image build killed | out of memory on a small VM | add swap or build in CI |
| API refuses to start with demo mode | `ENVIRONMENT=prod` and `BACKEND_MODE=demo` | the guard is intentional: remove demo settings |
| Disk fills over weeks | unbounded logs, images, volumes | log rotation; `docker system prune` carefully; monitor `df` |
| 429 for everyone | limits behind a proxy see one IP | set `FORWARDED_ALLOW_IPS`/proxy headers correctly (done in prod compose) |

## 27.8 A cost sketch (illustrative)

Monthly for a demo: a small VM (free tier to roughly the price of a few coffees), a domain (about a year's fee once), model usage (free tier, then per token), SerpAPI plan (per search credit, the dominant per-conversation cost, Chapter 14), optional managed DB/Redis later. The cost *shape* matters more than the numbers: **fixed** (VM, domain), **variable** (model, search), and **risk** (a leaked key or a public endpoint without limits), which is why the controls in Chapters 14 and 21 are part of the budget.

## 27.9 High availability and zero downtime (concepts)

* **Redundancy**: two or more app instances across **availability zones** behind a load balancer; managed DB with a standby.
* **Rolling/blue-green/canary deploys** (Chapter 28), graceful shutdown with long grace periods for streams.
* **Stateless services** + shared state stores (Postgres, Redis) make instances replaceable.
* **Disaster recovery**: backups in another region, documented restore, tested **RTO/RPO**.
* **Single VM** = single point of failure: acceptable for a demo, **state that explicitly** to stakeholders.

## Common mistakes

* Opening ports "temporarily" and forgetting them.
* Exposing the database, Docker API, or admin UIs.
* No certificate/expiry monitoring; deleting the certificate volume.
* DNS TTL left high before a migration; `AAAA` records without IPv6 service.
* Trusting forwarded headers from the open internet.
* Disabling TLS verification to "fix" a corporate-proxy error.
* No log rotation or disk alerts.
* Long-lived cloud access keys in CI and servers.
* No billing alerts.
* Treating a free VM as production without backups.

## Summary

* A reverse proxy is the single, minimal door: path allow-list, TLS termination, streaming-friendly flushing, headers. Caddy automates HTTPS via ACME (needs DNS and ports 80/443; keep the cert volume).
* DNS is cached name resolution: mind TTLs, `AAAA`, CAA, and propagation myths. CDNs/WAFs add caching and protection but impose timeouts and header-trust changes.
* Cloud basics: regions/AZs, VPC and security groups, IAM and least privilege, managed DB/Redis, secrets/KMS, cost controls, IaC.
* Deployment is a repeatable procedure: harden host, install Docker, generate keys on the box, fill env, `up -d --build`, verify both what works and what must not, then back up and monitor.

## Key terms

*reverse proxy, TLS termination, ACME, Let's Encrypt, HTTP-01/DNS-01, HSTS, CAA, TTL, CDN, WAF, load balancer, idle timeout, region, AZ, VPC, security group, NAT gateway, IAM, IMDSv2, managed database, shared responsibility, IaC, `ufw`, fail2ban.*

## Interview questions

1. How does Caddy get a certificate? What must be true for it to succeed?
2. Why does `flush_interval -1` matter? What else can break streaming in a proxy chain?
3. Explain why `/metrics` is unreachable from the internet in the prod layout.
4. How would you migrate a service to a new IP with minimal downtime (DNS)?
5. What is a security group and how would you configure one for this app?
6. What does the shared responsibility model mean for a VM-hosted app?
7. Walk me through deploying this app to a fresh VM, including hardening and verification.
8. A corporate customer's proxy breaks outbound TLS. What do you do?

## Exercises

1. Deploy to a free-tier VM with an sslip.io name; capture the Caddy logs showing certificate issuance; document the steps you actually needed.
2. Add `encode`, `log`, `request_body` limits and a CSP header to the Caddyfile (keeping SSE unbuffered) and verify streaming still works with `curl -N`.
3. Write a Terraform (or cloud-CLI) script creating the VM, firewall rules and DNS record.
4. Put Cloudflare in front; set the origin to accept only Cloudflare; test SSE and fix any timeout problems.
5. Write the restore drill: destroy the VM, rebuild from git + backup, and measure your actual RTO.
