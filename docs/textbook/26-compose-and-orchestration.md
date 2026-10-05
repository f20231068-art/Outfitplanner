# Chapter 26. Docker Compose and Orchestration

> **Learning objectives.** Define multi-container applications with Docker Compose (services, networks, volumes, secrets, profiles, health-gated startup, variable interpolation); read both compose files in this repo and explain every key; understand orchestration concepts and what Kubernetes and managed platforms add; map this app onto Kubernetes manifests; and choose a platform by team size, scale and operational appetite.
>
> **Prerequisites.** Chapters 16, 23, 25.

---

## 26.1 What Compose is

**Docker Compose** describes a set of containers that make up an application, in one YAML file, and starts them together:

```bash
docker compose up -d --build        # build images if needed; create network + volumes; start everything in the background
docker compose ps                   # status
docker compose logs -f api          # follow one service's logs
docker compose exec api sh          # shell in a running service
docker compose down                 # stop and remove containers and the network (volumes kept)
docker compose down -v              # ...and DELETE named volumes (your data!)
docker compose config               # print the final, interpolated configuration (may reveal secrets: do not paste it)
```

Compose gives **declarative, repeatable, version-controlled environments**: any developer runs the same stack with one command, and the same file can run on a single server.

### Core building blocks

| Key | Meaning |
|---|---|
| `services:` | each container (name, image or `build:`, environment, ports, volumes...) |
| `image:` / `build:` | pull an image, or build one (`context`, `dockerfile`) |
| `environment:` / `env_file:` | variables injected into the container |
| `ports:` | publish container ports on the host (`"host:container"`, optionally `127.0.0.1:` bound) |
| `volumes:` | named volumes (persistent data) and bind mounts (host files) |
| `networks:` | custom networks; by default all services share one project network with **service-name DNS** |
| `depends_on:` | start ordering, optionally gated on `condition: service_healthy` |
| `healthcheck:` | how to test readiness (compose keys, or inherited from the image `HEALTHCHECK`) |
| `restart:` | restart policy (`no`, `on-failure`, `always`, `unless-stopped`) |
| `profiles:` | optional service groups started only when requested (`--profile observability`) |
| `secrets:` | files mounted at `/run/secrets/<name>` |
| `read_only`, `tmpfs`, `cap_drop`, `cap_add`, `security_opt`, `mem_limit`, `pids_limit`, `extra_hosts` | the hardening and tuning flags (Chapter 25) |
| `name:` | the **project name** (prefix for networks/volumes/containers) |

### Variable interpolation

Compose substitutes `${VAR}` from the shell environment or an env file:

* `${VAR}` required-ish (empty if unset, with a warning).
* `${VAR:-default}`: use `default` if unset **or empty** (`${POSTGRES_USER:-stylist}`).
* `${VAR:?message}`: **fail with `message` if unset or empty** (`${POSTGRES_PASSWORD:?run scripts/init_production_env.py}`). This is a *fail-fast guard*: the stack refuses to start without the secret instead of silently using a blank one, and the message tells you the fix.
* `${VAR:-}` explicitly allows empty (`SERPAPI_API_KEY: ${SERPAPI_API_KEY:-}` in prod so demo mode works without a key).

Sources and precedence (highest first): **shell environment**, `--env-file` file, the default `.env` file in the project directory. **Compose reads `.env` automatically**; `--env-file .env.production` replaces that default for the run. Note: `env_file:` *inside a service* (not used here) injects variables into the **container**, whereas `.env`/`--env-file` feed **interpolation of the compose file** itself; this repo passes values explicitly in `environment:` using interpolation, so **each service gets only the variables listed**.

## 26.2 `docker-compose.yml` (local development stack)

```yaml
services:
  postgres:    image: postgres:17 ... ports "5432:5432" ... healthcheck pg_isready ... volume pgdata
  mcp:         build ./services/mcp ... NO ports ... hardened ... mem 512m
  api:         build (context ., dockerfile services/api/Dockerfile) ... depends_on healthy ... ports "8000:8000" ... hardened
  jaeger, prometheus, grafana   (profiles: [observability]; ports bound to 127.0.0.1)
secrets:  metrics_token (file)
volumes:  pgdata, promdata, grafanadata
```

Key ideas:

* **Postgres published on 5432** so tools and the host-run tests can reach it (`uv run pytest` uses `localhost:5432`). **Acceptable on a laptop; not on a server** (the prod file publishes nothing but Caddy).
* **`mcp` has no `ports:`**: "NO 'ports:' on purpose: nothing outside the Docker network can reach it. Other containers reach it as `http://mcp:8001/mcp`." Its env sets `MCP_HOST: 0.0.0.0` (listen on all container interfaces) and `MCP_ALLOWED_HOSTS: mcp` (the only `Host` header accepted); the server **refuses to start** with a non-loopback host and no allowed hosts.
* **Least-privilege configuration**: the tool server receives only `MCP_JWT_PUBLIC_KEY`, `SERPAPI_API_KEY`, credit caps and `METRICS_TOKEN`, "never the whole `.env`", **so it holds the PUBLIC key and can verify tokens but never create them**. The API receives the private keys and model keys.
* **Health-gated startup**: the API `depends_on` Postgres `service_healthy` and mcp `service_healthy`, using the image `HEALTHCHECK`s and Postgres's `pg_isready`. (Defence in depth: the app also retries; `depends_on` only orders *startup*, it does not keep dependencies healthy at runtime.)
* **Database URL composed** from variables: `postgresql://${POSTGRES_USER:-stylist}:${POSTGRES_PASSWORD:-stylist_dev_password}@postgres:5432/${POSTGRES_DB:-stylist}`: host `postgres` is the **service name**. Dev defaults (`stylist_dev_password`) are for local use and documented as such.
* **Dev-only relaxations are explicit**: `COOKIE_SECURE: "false"` ("this local stack is plain http; set true behind https"), `ENVIRONMENT: dev`.
* **Switches**: `BACKEND_MODE: ${BACKEND_MODE:-live}` ("demo = offline scripted model + mock products (free, for evals)").
* **Observability profile**: `docker compose --profile observability up -d` adds **Jaeger** (UI 16686, OTLP 4318), **Prometheus** (9090; mounts `prometheus.yml` read-only and the `metrics_token` secret; `extra_hosts: host.docker.internal:host-gateway` to scrape an API running on the host), **Grafana** (3001 → 3000; provisioned datasources/dashboards; anonymous Viewer; admin password from env). All bound to **`127.0.0.1`** so only your machine can reach them.
* **Secrets via file**: the `metrics_token` secret's `file:` is `./infra/observability/.secrets/metrics_token`, git-ignored and created by `scripts/init_observability.py`; Prometheus reads it from `/run/secrets/metrics_token`.
* **Restart policy** `unless-stopped`.

## 26.3 `docker-compose.prod.yml` (the hosted layout)

Header comment: *"Only ONE service publishes ports: caddy (the door). The database, tool server, API and web app have no published port, so nothing outside the Docker network can reach them except through Caddy's allow-list."*

| Aspect | Dev compose | Prod compose |
|---|---|---|
| Project name | default (folder) | `name: stylist-prod` (separate resources: never mixes with dev containers/volumes) |
| Published ports | postgres 5432, api 8000, observability UIs on 127.0.0.1 | **only Caddy** (`${HTTP_PORT:-80}:80`, `${HTTPS_PORT:-443}:443`) |
| Postgres | default creds, published | password **required** (`${POSTGRES_PASSWORD:?...}`), `cap_drop: ALL` + minimal `cap_add`, no ports |
| Secrets required | soft defaults | **hard-required** via `:?` (`MCP_JWT_PUBLIC_KEY`, `POSTGRES_PASSWORD`) |
| API environment | `ENVIRONMENT: dev`, `COOKIE_SECURE: "false"` | `ENVIRONMENT: ${ENVIRONMENT:-prod}`, `COOKIE_SECURE: ${COOKIE_SECURE:-true}`; `FORWARDED_ALLOW_IPS: "*"` (only Caddy can reach it) |
| Web service | none (runs via `npm run dev`) | built from `apps/web/Dockerfile`, read-only, tmpfs for `.next/cache` |
| Reverse proxy | none | `caddy:2` with `Caddyfile`, `caddy_data` volume for certificates, `cap_add: NET_BIND_SERVICE` |
| Observability stack | optional profile | not included (honest limit) |
| Search quotas | 40 per user / 100 global per day | **10 per user / 25 global** (protect a small SerpAPI quota) |
| Public URL | `WEB_ORIGIN` localhost:3000 | `WEB_ORIGIN: ${PUBLIC_URL:-http://localhost:8080}` |

How it is run (from `docs/deploy.md`):

```bash
uv run --project services/mcp python scripts/generate_jwt_keys.py --out .env.production
python scripts/init_production_env.py                          # DB password, addresses; copies model/search keys from .env
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Details to be able to explain:

* **`--env-file .env.production`**: feeds interpolation; `.env.production` is git-ignored and holds *every* secret (the guide says `chmod 600` on a server).
* **Laptop test** uses `HTTP_PORT=8080`, `SITE_ADDRESS=:80` (plain http), `COOKIE_SECURE=false`, `PUBLIC_URL=http://localhost:8080`. **Server** uses `SITE_ADDRESS=<name>` so **Caddy obtains a Let's Encrypt certificate automatically**; the cookie is `Secure`.
* **Demo mode in prod compose** requires `ENVIRONMENT=dev` and `BACKEND_MODE=demo` in the env file because the API refuses `demo` when `ENVIRONMENT=prod` (a guard against accidentally shipping the fake model).
* **Same origin through Caddy** removes the need for CORS and a custom domain for cookies.
* **Caddyfile** uses `{$SITE_ADDRESS::80}`, `{$API_UPSTREAM:api:8000}` and `{$WEB_UPSTREAM:web:3000}`: environment placeholders with defaults, so the same file works in compose (service names) and on platforms that set upstream addresses (the file mentions Railway).
* **Health-gated startup** is the same; Caddy `depends_on: [api, web]`.

## 26.4 Day-2 operations with Compose

* **Update**: `git pull && docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`: Compose recreates containers whose image/config changed (brief downtime per service; not a rolling update).
* **Rollback**: check out the previous commit (or image tag) and `up -d` again.
* **Logs**: `logs -f api`; ship them off-box in production.
* **Resource use**: `docker stats`, `docker system df`; prune old images/build cache carefully.
* **Backups**: `pg_dump` via `docker compose exec -T postgres ...` (Chapter 17); back up the `caddy_data` volume if you care about certificates (re-issuable) and rate limits.
* **Secrets rotation**: edit `.env.production`, `up -d` (recreates affected services); rotating the JWT keys logs users out.
* **Boot persistence**: `restart: unless-stopped` + Docker enabled at boot; or a systemd unit (Chapter 23).
* **Firewall**: allow only 80/443 (and your SSH source).
* **Monitoring**: external uptime check against `https://your-name/health`.

## 26.5 Limits of Compose (when to graduate)

Compose is **single-host**: no scheduling across machines, no automatic rescheduling if the VM dies, no autoscaling, no rolling updates or canaries, basic secret handling, no cluster-level networking policy, no built-in ingress management. Fine for demos, internal tools and small production loads; insufficient when you need **high availability, zero-downtime deploys, horizontal autoscaling, or many teams**. Also: `docker compose up --scale api=3` would start three API containers, which immediately exposes this app's **in-memory state** (rate limiters, active-turn lock, replay guard) (Chapter 32).

## 26.6 Orchestration concepts

An **orchestrator** runs containers across a cluster according to **desired state** you declare:

| Concept | Meaning |
|---|---|
| **Scheduling** | pick which node runs each workload given CPU/memory requests, constraints, affinities |
| **Desired-state reconciliation** | controllers continuously compare actual vs declared state and fix drift (restart crashed pods, replace failed nodes) |
| **Service discovery & load balancing** | stable names/virtual IPs spreading traffic across healthy instances |
| **Health probes** | *liveness* (restart if dead), *readiness* (send traffic only when ready), *startup* (slow boot) |
| **Rolling updates & rollbacks** | replace instances gradually, halt/roll back on failure |
| **Config & secrets** | injected at runtime, separate from images |
| **Storage** | persistent volumes bound to workloads |
| **Autoscaling** | more/fewer replicas (CPU, memory, custom metrics) and more/fewer nodes |
| **Networking policy** | which workloads may talk to which |
| **RBAC and namespaces** | who may do what; isolation between teams/environments |
| **Jobs/CronJobs** | batch and scheduled work (migrations, backups, nightly evals) |

## 26.7 Kubernetes primer

**Kubernetes (K8s)** is the dominant open-source orchestrator.

### Architecture

* **Control plane**: **API server** (the front door; everything goes through it), **etcd** (the cluster's key-value database), **scheduler**, **controller manager** (runs reconciliation loops), cloud controller.
* **Nodes**: **kubelet** (agent that runs pods), **container runtime** (containerd/CRI-O), **kube-proxy** (service networking).
* You interact with the API server via **`kubectl`** and YAML manifests (GitOps tools like Argo CD/Flux apply them from git).

### Core objects

| Object | Purpose |
|---|---|
| **Pod** | one or more containers sharing network/storage; the unit of scheduling (ephemeral) |
| **Deployment** (+ ReplicaSet) | declares N identical stateless pods, rolling updates, rollbacks |
| **Service** | stable virtual IP/DNS in front of pods: `ClusterIP` (internal), `NodePort`, `LoadBalancer` (cloud LB) |
| **Ingress / Gateway API** | HTTP(S) routing from outside into services (what Caddy does here) |
| **ConfigMap / Secret** | configuration and sensitive values (Secrets are base64, **not encrypted by default**: enable encryption at rest or use an external secrets operator) |
| **StatefulSet** | pods with stable identity and storage (databases) |
| **PersistentVolume / Claim** | storage lifecycle separate from pods |
| **Job / CronJob** | run-to-completion and scheduled tasks |
| **HorizontalPodAutoscaler** | scale replicas on metrics |
| **NetworkPolicy** | pod-level firewall rules |
| **Namespace** | logical partitions |
| **ServiceAccount, Role, RoleBinding** | RBAC |

### This app as Kubernetes manifests (sketch)

The compose hardening flags map directly onto `securityContext`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata: { name: stylist-api }
spec:
  replicas: 2
  strategy: { type: RollingUpdate, rollingUpdate: { maxUnavailable: 0, maxSurge: 1 } }
  selector: { matchLabels: { app: stylist-api } }
  template:
    metadata: { labels: { app: stylist-api } }
    spec:
      terminationGracePeriodSeconds: 90          # let in-flight 30-60 s chat turns finish after SIGTERM
      securityContext: { runAsNonRoot: true, runAsUser: 10002 }
      containers:
        - name: api
          image: registry.example.com/stylist-api:3f9a1c2     # immutable tag = commit SHA
          ports: [{ containerPort: 8000 }]
          envFrom: [{ secretRef: { name: stylist-api-secrets } }]   # DATABASE_URL, keys: only what the API needs
          env:
            - { name: ENVIRONMENT, value: prod }
            - { name: MCP_URL, value: "http://stylist-mcp:8001/mcp" }
          readinessProbe: { httpGet: { path: /health, port: 8000 }, periodSeconds: 5 }
          livenessProbe:  { httpGet: { path: /health, port: 8000 }, periodSeconds: 15, failureThreshold: 3 }
          resources: { requests: { cpu: 250m, memory: 512Mi }, limits: { memory: 1Gi } }
          securityContext:
            allowPrivilegeEscalation: false          # == no-new-privileges
            readOnlyRootFilesystem: true             # == read_only: true
            capabilities: { drop: [ALL] }            # == cap_drop: [ALL]
          volumeMounts: [{ name: tmp, mountPath: /tmp }]
      volumes: [{ name: tmp, emptyDir: { medium: Memory } }]   # == tmpfs
---
apiVersion: v1
kind: Service
metadata: { name: stylist-api }
spec:
  selector: { app: stylist-api }
  ports: [{ port: 8000, targetPort: 8000 }]
```

Plus: a `stylist-mcp` Deployment and a **ClusterIP-only** Service (no Ingress rule = private, equivalent to "no published port"), a `NetworkPolicy` allowing only the API pods to reach MCP and Postgres, an **Ingress** routing `/auth`, `/conversations`... to the API and `/` to the web Service (with TLS from cert-manager), a **managed Postgres** (or a StatefulSet), a Job for migrations, and a CronJob for backups. Mapping summary:

| Compose | Kubernetes |
|---|---|
| service | Deployment + Service |
| `ports:` published | Ingress / LoadBalancer Service (only for the public door) |
| no ports (private) | ClusterIP Service + NetworkPolicy |
| `healthcheck` | readiness/liveness probes |
| `depends_on: healthy` | readiness + retry logic (no ordering guarantee) |
| `environment` / secrets | ConfigMap / Secret (+ external secret managers) |
| `volumes: pgdata` | PersistentVolumeClaim / managed DB |
| `mem_limit`, `pids_limit` | resource `limits`, pod limits |
| `read_only`, `cap_drop`, `no-new-privileges`, user | `securityContext` |
| `restart: unless-stopped` | the Deployment controller |
| Caddy | Ingress controller + cert-manager |

Everyday commands: `kubectl get pods -A`, `kubectl describe pod X` (events: why Pending/CrashLoopBackOff), `kubectl logs -f X`, `kubectl exec -it X -- sh`, `kubectl rollout status|undo deployment/stylist-api`, `kubectl port-forward svc/stylist-api 8000:8000`, `kubectl top pods`. Common failures: **ImagePullBackOff** (registry auth/tag), **CrashLoopBackOff** (app exits; check logs and probes), **Pending** (insufficient resources/volume), **OOMKilled** (limit too low), failing readiness probes (traffic never arrives).

**Helm** templates manifests; **Kustomize** overlays them per environment; **Argo CD/Flux** reconcile a git repo into the cluster (GitOps).

**When Kubernetes is worth it:** multiple services/teams, need for autoscaling and self-healing across nodes, organisational standards, or the customer already runs it. **When it is not:** one or two services on one VM; the operational cost (upgrades, networking, security, cost) is real. Managed Kubernetes (EKS, GKE, AKS) reduces but does not remove it.

## 26.8 Managed container and PaaS options

| Platform | Model | Notes for an app like this |
|---|---|---|
| **Cloud Run** (GCP) | serverless containers, scale to zero | request timeouts (configurable up to long limits), concurrency per instance; stateless only; great fit once in-memory state moves to Redis; use Cloud SQL |
| **AWS ECS/Fargate**, **App Runner** | managed container orchestration | IAM integration; ALB idle timeouts matter for SSE |
| **Azure Container Apps** | serverless containers on Kubernetes | similar |
| **Fly.io, Railway, Render** | developer-friendly PaaS, git/Docker deploys | simple; the Caddyfile already allows platform-provided upstream addresses (it mentions Railway) |
| **Vercel/Netlify** | front-end/edge platforms | host the Next.js app; long-lived SSE and the Python API need a different home |
| **A single VM + Compose** | this project's plan | cheapest, simplest, least resilient |

**Considerations specific to this app on serverless/PaaS:** (1) long streaming requests (30-60 s) vs platform timeouts and idle cut-offs; (2) **in-process state** (limiters, replay guard, active-turn lock) breaks with multiple or scaled-to-zero instances; (3) the **tool server must remain private**: use internal networking/service-to-service auth, not a public URL; (4) cold starts add seconds to the first request; (5) managed Postgres replaces the compose container; (6) secrets move to the platform's secret store.

## 26.9 Choosing

| Situation | Recommendation |
|---|---|
| Demo, class project, a few users | Compose on one VM (this repo's plan) |
| Small production, one team, modest availability needs | Compose on a VM with backups and monitoring, or a PaaS (Fly, Render, Railway) |
| Variable traffic, minimal ops staff | Serverless containers (Cloud Run, Container Apps) + managed DB + Redis |
| Many services, multiple teams, compliance or portability needs | Kubernetes (managed) + GitOps |
| Customer mandates their platform | adapt: containers + 12-factor config make your app portable |

A durable principle: **build 12-factor, stateless-where-possible containers with explicit config, and the orchestration choice becomes a deployment detail.**

## Common mistakes

* Publishing databases or internal services (`ports:`) in production.
* Putting secrets in the compose file or baking `.env` into images.
* Assuming `depends_on` guarantees runtime health.
* `docker compose down -v` on a machine with data you need.
* Using dev compose on a server.
* Scaling replicas of an app with in-process state.
* No resource limits; no restart policy; no health checks.
* Forgetting that `localhost` in a container is the container.
* Treating Kubernetes Secrets as encrypted.

## Summary

* Compose defines multi-container apps declaratively with networks, volumes, secrets, profiles and health-gated startup; interpolation operators (`:-`, `:?`) provide defaults and fail-fast guards.
* This repo's dev compose is for convenience (published DB/API, optional observability); prod compose publishes only Caddy and requires secrets.
* Compose is single-host; orchestrators add scheduling, self-healing, rolling updates, autoscaling and policy.
* Kubernetes concepts map cleanly from Compose (`securityContext` ↔ hardening flags; probes ↔ healthchecks; Ingress ↔ Caddy).
* Choose the simplest platform that meets availability and scale needs; keep the app twelve-factor.

## Key terms

*Compose, service, project, network, volume, secret, profile, interpolation, healthcheck, `depends_on`, orchestrator, desired state, Pod, Deployment, Service, Ingress, ConfigMap, Secret, probe, HPA, NetworkPolicy, Helm, GitOps, PaaS.*

## Interview questions

1. What does `depends_on: condition: service_healthy` guarantee and not guarantee?
2. What is the difference between `ports:` and `expose`/no ports? How is the MCP server kept private?
3. Explain `${VAR:-default}` vs `${VAR:?message}` and where each is used here.
4. What does `docker compose down -v` do? Why is it dangerous?
5. When would you move from Compose to Kubernetes? What would you gain and lose?
6. Map three Compose hardening options to Kubernetes `securityContext` fields.
7. What breaks if you run three replicas of the API container, and how would you fix it?

## Exercises

1. Run the dev compose with the `observability` profile; open Jaeger, Prometheus and Grafana; explain why each is only reachable on `127.0.0.1`.
2. Remove `:?` from `POSTGRES_PASSWORD` in a copy of the prod file and observe what happens with an unset variable; restore it.
3. Write Kubernetes manifests for the tool server with a ClusterIP Service and a NetworkPolicy; test on `kind` or `minikube`.
4. Add a `backup` service using the `postgres:17` image and a cron-like loop writing `pg_dump` to a volume.
5. Try `docker compose up --scale api=2` behind Caddy and demonstrate the rate-limit inconsistency.
