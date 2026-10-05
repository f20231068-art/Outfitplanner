# Chapter 25. Docker

> **Learning objectives.** Explain what containers and images are and how layers, caching and multi-stage builds work; write production-quality Dockerfiles; apply runtime hardening flags and know the threat each one blocks; debug containers; understand registries, tagging and image supply chain; and read all three Dockerfiles and `.dockerignore` files in this repo line by line.
>
> **Prerequisites.** Chapter 23 (processes, namespaces, cgroups, capabilities).

---

## 25.1 Why containers

**The problem:** "it works on my machine". Software depends on a specific OS, library versions, runtimes and configuration. **Containers** package an application *with its dependencies* into a portable unit that runs the same on a laptop, a CI runner and a server.

| | **Virtual machine** | **Container** |
|---|---|---|
| Isolation | full guest OS on a hypervisor | process isolation on the *shared host kernel* |
| Start time | tens of seconds | milliseconds to seconds |
| Size | GBs | tens to hundreds of MB |
| Density | few per host | many per host |
| Isolation strength | stronger (separate kernel) | weaker (shared kernel; mitigated by hardening) |

Vocabulary:

* **Image**: a read-only, layered template (filesystem + metadata such as default command, user, exposed ports).
* **Container**: a running (or stopped) instance of an image, with a thin writable layer and its own namespaces/cgroups.
* **Dockerfile**: the recipe for building an image.
* **Registry**: a server storing images (Docker Hub, GitHub Container Registry, AWS ECR, Google Artifact Registry).
* **Tag**: a human label (`postgres:17`); **digest**: the immutable content hash (`postgres@sha256:...`).
* **Docker Engine/daemon**, **BuildKit** (the modern builder), **Compose** (multi-container definitions, Chapter 26), **OCI** (the open image/runtime standards: Podman, containerd and Kubernetes run the same images).

### How images are built: layers and caching

Each Dockerfile instruction that changes the filesystem creates a **layer** (a tar of file changes), identified by a content hash. An image is a stack of layers. Consequences:

* **Layers are shared and cached.** If instruction N and everything before it is unchanged (same instruction text, same inputs), Docker reuses the cached layer. The first changed instruction invalidates the cache **for it and every later instruction**.
* **Order instructions from least to most frequently changing.** Install dependencies (change rarely) *before* copying source code (changes constantly). This is the single most important Dockerfile skill; the API Dockerfile does it deliberately (below).
* **Layers are additive**: deleting a file in a later layer does *not* shrink the image (the earlier layer still contains it). Remove temporary files **in the same `RUN`** that created them.
* **Secrets in any layer are forever** (`docker history` and layer extraction reveal them) (Section 25.5).

## 25.2 Dockerfile reference (the parts that matter)

| Instruction | Purpose | Notes |
|---|---|---|
| `FROM image AS name` | base image; starts a stage | pin versions: `python:3.12-slim`, never `latest` |
| `WORKDIR /app` | set (and create) the working directory | use instead of `RUN cd` |
| `COPY src dst` | copy from the build context (or `--from=stage`) | prefer `COPY` over `ADD` (no surprises) |
| `RUN cmd` | execute during build, creating a layer | chain related commands with `&&`; clean up in the same layer |
| `ENV K=V` | environment variable in image and container | not for secrets |
| `ARG K=V` | build-time variable | visible in image history; not for secrets |
| `EXPOSE 8000` | **documentation** of the listening port | does *not* publish it |
| `USER app` | switch to a non-root user for later instructions and runtime | essential |
| `HEALTHCHECK` | command that reports container health | used by compose/orchestrators |
| `CMD [...]` | default command (overridable) | **exec form** (JSON array) so signals reach your process |
| `ENTRYPOINT [...]` | fixed executable; `CMD` supplies default args | for wrapper scripts |
| `LABEL` | metadata (source repo, revision) | |

**Shell form vs exec form.** `CMD python app.py` runs `/bin/sh -c "python app.py"` (the shell is PID 1 and may not forward SIGTERM). `CMD ["python", "app.py"]` runs the program directly as PID 1 (Chapter 23). Use exec form.

### Build context and `.dockerignore`

`docker build -f services/api/Dockerfile .` sends the **build context** (the directory `.`) to the builder; `COPY` can only see files inside it. A large or sensitive context slows builds and risks leaking files into layers. **`.dockerignore`** excludes paths from the context. This repo has three:

* **Root `.dockerignore`** (used by the API build, whose context is the repo root): excludes `.git`, `.env`, `.env.*` (but not `.env.example`), `*.pem`, virtualenvs, `node_modules`, `.next`, caches, `docs`, `scripts`, `evals`, `**/.data`. *Secrets and junk never reach the builder.*
* **`services/mcp/.dockerignore`**: `.venv`, caches, `tests`, `.env*`, `*.pem` (context is `services/mcp`).
* **`apps/web/Dockerfile.dockerignore`**: BuildKit supports a **per-Dockerfile ignore file** named `<Dockerfile>.dockerignore`, taking precedence over the root `.dockerignore` for that build. The web build's context is also the repo root (the npm lockfile lives there) but it needs none of `services`, `docs`, `scripts`, `infra`, `prompts` or the Mastra *source* (only `apps/mastra/package.json`, for lockfile consistency), so it excludes them. A **different ignore list per image from one shared context**.

### Multi-stage builds

Use one stage to **build** (compilers, dev dependencies, caches) and a clean final stage to **run**, copying only the results:

```dockerfile
FROM python:3.12-slim AS build        # heavy tooling lives here
...
FROM python:3.12-slim                 # the final image starts clean
COPY --from=build /app /app           # take only the built artefacts
```

The final image does not contain build tools, caches or intermediate layers: smaller and with less attack surface.

### Choosing a base image

| Base | Size | Notes |
|---|---|---|
| `python:3.12` (full) | large | has compilers; convenient, heavy |
| **`python:3.12-slim`** (Debian slim) | small | glibc, works with manylinux wheels; **this repo's choice** |
| `alpine` | tiny | musl libc: some Python/Node wheels are unavailable or slower; DNS and locale quirks; fine for static binaries |
| **distroless** (`gcr.io/distroless/...`) | very small | no shell/package manager; excellent hardening, harder to debug |
| `scratch` | empty | static binaries only (Go) |
| `node:22-slim` | small | this repo's Node choice |

Pin the **major/minor** version, rebuild regularly for security patches, and consider pinning by **digest** for reproducibility.

## 25.3 The three Dockerfiles in this repo, line by line

### `services/api/Dockerfile` (FastAPI + LangGraph)

```dockerfile
FROM python:3.12-slim AS build
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY services/api/pyproject.toml services/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services/api/src ./src
COPY services/api/migrations ./migrations
RUN uv sync --frozen --no-dev
```

* **Context is the repo root** (`docker build -f services/api/Dockerfile .`) because the runtime image also needs `/prompts` (a sibling of `services/`). The header comment says so.
* Install **uv** (fast resolver/installer); `--no-cache-dir` avoids storing pip's cache in the layer.
* **Dependency layer first**: copy only `pyproject.toml` and `uv.lock`, then `uv sync --frozen --no-dev --no-install-project`:
  * `--frozen`: use the lockfile exactly; **fail** if it is out of date (reproducible builds).
  * `--no-dev`: skip test/lint tools (smaller, safer).
  * `--no-install-project`: install only third-party dependencies now.
  This layer is rebuilt **only when the lockfile changes**; editing source code does not re-download hundreds of packages. *This is cache-ordering in practice.*
* Then copy `src` and `migrations` and run `uv sync` again to install the project itself (fast).
* The virtual environment lives at `/app/.venv`.

```dockerfile
FROM python:3.12-slim
RUN useradd --system --uid 10002 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build --chown=app:app /app /app
COPY --chown=app:app prompts /app/prompts
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 ENVIRONMENT=prod COOKIE_SECURE=true
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2)" || exit 1
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
```

* **Fresh runtime stage** from the same base (same Python, so the copied virtual environment's interpreter symlinks stay valid at the same path `/app`).
* **Non-root system user**: UID 10002 (a high, fixed UID), **no home directory**, **no login shell**. If the app is exploited, the attacker is not root and has no interactive shell. A fixed UID lets orchestrators and volume permissions be predictable.
* `COPY --chown=app:app`: files are owned by the runtime user *as copied* (cheaper than a later `chown -R`, which would duplicate every file into a new layer).
* **Prompts are copied in**: `load_prompt` finds `/app/prompts/stylist` by walking parents.
* `ENV` choices:
  * `PATH` puts the venv first, so `uvicorn` and `python` are the venv's.
  * `PYTHONUNBUFFERED=1`: logs appear immediately (essential for `docker logs` and JSON logging).
  * `PYTHONDONTWRITEBYTECODE=1`: do not write `.pyc` files; **required for a read-only root filesystem** (nothing may be written).
  * **`ENVIRONMENT=prod`, `COOKIE_SECURE=true`**: **secure defaults baked into the image**: docs disabled, secure cookies, demo mode refused. Local dev overrides them explicitly in compose (`COOKIE_SECURE: "false"`, `ENVIRONMENT: dev`). *Safe by default, relaxed on purpose.*
* `USER app` before `CMD` so the process runs unprivileged.
* **HEALTHCHECK** with Python's stdlib (no `curl` needed in a slim image): `GET /health`, every 15 s, 3 s timeout, a 20 s **start period** (grace while migrations and pools start), 3 retries. Compose's `depends_on: condition: service_healthy` and orchestrators use this.
* **CMD in exec form**; `--host 0.0.0.0` (listen on all container interfaces; not published unless compose says so), `--proxy-headers` (trust `X-Forwarded-*` from permitted proxies; see `FORWARDED_ALLOW_IPS` in compose).
* **No secrets, no `.env`**: keys arrive as environment variables at runtime ("No secrets are baked in").

### `services/mcp/Dockerfile` (the private tool server)

Same pattern with differences worth noting:

* **Context is `services/mcp`** (it needs nothing outside).
* `COPY pyproject.toml uv.lock README.md* ./`: the glob `README.md*` copies the README *if it exists* without failing if it does not (hatchling's metadata may reference it).
* UID **10001** (different from the API's 10002: distinct identities per service).
* `EXPOSE 8001`, but the compose files **do not publish** it.
* HEALTHCHECK reads `MCP_PORT` from the environment: `f'http://127.0.0.1:{os.getenv("MCP_PORT","8001")}/health'`. `/health` needs no auth and returns only `{"status":"ok"}`.
* `CMD ["python", "-m", "mcp_server.server"]`: the server's `__main__` calls `assert_safe_bind(settings)` first, then `run(transport="http", host=..., port=..., host_origin_protection=True, allowed_hosts=[...])`.

### `apps/web/Dockerfile` (Next.js)

```dockerfile
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY apps/mastra/package.json apps/mastra/package.json
RUN npm ci -w apps/web
COPY apps/web apps/web
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build -w apps/web
```

* The **workspace lockfile lives at the root**, so the build copies the root `package.json` + lockfile and *each workspace's* `package.json` (including `apps/mastra`'s, so `npm ci` sees a consistent workspace graph) before `COPY apps/web`. The ignore file excludes Mastra's *source*.
* **`npm ci -w apps/web`**: clean install exactly from the lockfile, only the web workspace's dependency tree (fails on mismatch).
* **`ARG NEXT_PUBLIC_API_URL=""`** → `ENV`: Next inlines `NEXT_PUBLIC_*` at **build** time (Chapter 19). An **empty value means "same origin"**. It is an `ARG` (visible in image history), acceptable because it is a **public** value; **never pass secrets through `ARG`**.
* `NEXT_TELEMETRY_DISABLED=1`: no usage telemetry from the framework.

```dockerfile
FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build --chown=node:node /app /app
USER node
EXPOSE 3000
CMD ["node", "node_modules/next/dist/bin/next", "start", "apps/web", "-H", "0.0.0.0", "-p", "3000"]
```

* Runs as the image's built-in **non-root `node` user**.
* Copies the **whole `/app`** (including installed `node_modules`) from the build stage: simple and correct, but larger than necessary. **Next.js "standalone" output** (`output: 'standalone'`) emits a minimal server bundle, usually shrinking the image a lot; a worthwhile optimisation.
* **`CMD` invokes `node` directly** on Next's CLI instead of `npm start`: npm as PID 1 can fail to forward signals. Exec form again.
* `.next/cache` must be writable: the prod compose gives it a **`tmpfs` owned by uid 1000** (`/app/apps/web/.next/cache:uid=1000,gid=1000`) because the container filesystem is read-only. (A good example of "harden first, then grant the minimum exceptions".)

## 25.4 Running containers: the flags that matter

```bash
docker build -t stylist-api -f services/api/Dockerfile .
docker run --rm -p 127.0.0.1:8000:8000 --env-file .env.docker stylist-api
docker run --rm -it stylist-api sh               # explore (if the image has a shell)
```

| Flag (compose key) | Meaning |
|---|---|
| `-p host:container` (`ports`) | **publish** a port on the host. `127.0.0.1:8000:8000` = loopback only |
| `-e`, `--env-file` (`environment`) | set variables; `.env` files must stay out of images and git |
| `-v name:/path` (`volumes`) | **named volume** (managed by Docker; persists data: `pgdata`) |
| `-v ./dir:/path:ro` | **bind mount** of a host path (config files like `Caddyfile`, Prometheus config; `:ro` read-only) |
| `--tmpfs /tmp` (`tmpfs`) | in-memory writable directory |
| `--read-only` (`read_only: true`) | root filesystem is read-only: malware cannot persist or modify binaries |
| `--cap-drop ALL` (`cap_drop: [ALL]`) | drop every Linux capability |
| `--cap-add X` (`cap_add`) | add back only what is required (Postgres: `CHOWN, SETUID, SETGID, FOWNER, DAC_OVERRIDE`; Caddy: `NET_BIND_SERVICE` to bind ports 80/443 as non-root) |
| `--security-opt no-new-privileges:true` | processes cannot gain privileges (setuid/setcap) |
| `--memory 512m` (`mem_limit`) | cgroup memory cap (OOM-kill the container, not the host) |
| `--pids-limit 200` (`pids_limit`) | cap on processes (fork-bomb protection) |
| `--restart unless-stopped` (`restart`) | restart after crash/reboot unless manually stopped |
| `--network` | which Docker network(s) |
| `--init` | run a tiny init (zombie reaping, signal forwarding) |
| `--user 1000:1000` | override the user |

**Volumes vs bind mounts vs tmpfs**: data that must survive container replacement goes in a **named volume** (`pgdata` for Postgres, `caddy_data` for certificates, `promdata`/`grafanadata`); config you edit on the host is a **bind mount**; scratch space is **tmpfs**. Containers are **ephemeral**: anything written to the container layer disappears on `docker compose down && up`. `down -v` deletes volumes: the deploy guide warns "stop AND delete the data".

## 25.5 Container and image security

A checklist with the *reason* for each item, and where this repo stands:

| Control | Threat addressed | This repo |
|---|---|---|
| **Run as non-root** | root-in-container + a bug can be a host-level problem | yes for the three first-party images (UID 10001/10002, `node`). Postgres's entrypoint starts as root to fix data-directory ownership and then drops to the `postgres` user (hence its few `cap_add`s); the Caddy image's default user should be checked with `docker inspect` (all capabilities except `NET_BIND_SERVICE` are dropped either way) |
| **Read-only root filesystem + tmpfs** | persistence of attacker files; tampering | API, MCP, web (compose) |
| **Drop all capabilities** | kernel-privilege abuse | all services; minimal add-backs for Postgres and Caddy |
| **`no-new-privileges`** | setuid escalation | all services |
| **Resource limits** | DoS/memory leaks affecting neighbours | `mem_limit`, `pids_limit` on API, MCP, web |
| **No published ports except the door** | direct access to internals | prod compose: only Caddy publishes |
| **No secrets in images or ARGs** | secrets leak via registries/layers/history | env vars at runtime; `.dockerignore` blocks `.env*`, `*.pem` |
| **Pinned, minimal base images** | vulnerable/bloated packages | `-slim`; pinned majors; (digest pinning not done) |
| **Image scanning** (Trivy, Grype, Docker Scout, ECR scanning) | known CVEs in OS packages and dependencies | not yet automated |
| **SBOM and signing** (syft, cosign) | provenance, "what is in this image?" | not yet |
| **Don't mount the Docker socket** (`/var/run/docker.sock`) | the container could control the host | not mounted |
| **Never `--privileged`** | disables most isolation | not used |
| **Separate networks / least network access** | lateral movement | single compose network (could split) |
| **Healthchecks** | detect hung services | present |
| **Rebuild regularly** | patched OS layers | process, not automation |
| **Keep the daemon and host patched** | shared-kernel escapes | operations |

### Build-time secrets (when you need them)

If a build needs a credential (a private package index), use **BuildKit secret mounts** (`RUN --mount=type=secret,id=npmrc cat /run/secrets/npmrc ...`), which never persist in a layer. Never `COPY .npmrc` or `ARG TOKEN`.

### Supply chain for images

* Prefer **official** or verified base images; pin tags (and digests for critical paths); scan in CI; keep images small.
* **Registry access** controls and **signed images** (cosign/sigstore) with admission policies in orchestrators.
* **Do not pull random images** into production; the Caddy/Postgres/Jaeger/Prometheus/Grafana images here are official, with **explicit version tags** (`postgres:17`, `caddy:2`, `prom/prometheus:v2.55.1`, `grafana/grafana:11.3.0`, `jaegertracing/all-in-one:1.62.0`).

## 25.6 Faster, smaller builds

* **Order layers by change frequency** (dependencies before source).
* **`.dockerignore`** to shrink the context and avoid cache invalidation by irrelevant files.
* **Multi-stage** to drop build tools.
* **`--no-install-recommends` and cleaning apt lists in the same `RUN`** for Debian packages.
* **BuildKit cache mounts**: `RUN --mount=type=cache,target=/root/.cache/uv uv sync ...` reuses the package cache across builds without keeping it in the image.
* **Slim bases**; avoid unnecessary packages (`curl` just for a healthcheck: this repo uses the Python stdlib instead).
* **Standalone output** for Next.js.
* **Inspect**: `docker history <image>` shows layer sizes; tools like **dive** show per-layer file contents; `docker image ls` for totals.
* **CI caching**: `--cache-from`/`--cache-to` (registry or GitHub Actions cache) so CI builds are incremental.

## 25.7 Language-specific notes

**Python**: use a **virtual environment** in the image; `uv sync --frozen`; wheels: prefer packages with manylinux wheels (`psycopg[binary]`, used here, avoids needing a compiler and libpq headers in the image); `PYTHONUNBUFFERED=1`; `PYTHONDONTWRITEBYTECODE=1` for read-only filesystems; Alpine/musl can force slow source builds; CA certificates are present in `python:slim`; set a **non-root user with a fixed UID**; run a **production ASGI server** (uvicorn/gunicorn), never the dev reload server.

**Node**: `npm ci`, `NODE_ENV=production`, run `node` directly, **build in one stage and run in another**, standalone output, and remember **build-time vs runtime env vars** (`NEXT_PUBLIC_*` are build-time).

**Both**: one process per container (a container is not a mini-VM); logs to stdout/stderr; configuration via env vars; graceful SIGTERM handling.

## 25.8 Debugging containers

```bash
docker ps -a                              # states, exit codes ("Exited (137)" = SIGKILL, often OOM)
docker logs -f --tail=200 <container>
docker inspect <c> | jq '.[0].State'      # OOMKilled? Health? ExitCode?
docker exec -it <c> sh                    # shell inside a running container (if it has one)
docker run --rm -it --entrypoint sh <image>     # shell in a fresh container from the image
docker stats                              # live CPU/memory
docker history <image>                    # layers
docker build --progress=plain --no-cache -t x .  # see every build step, no cache
docker cp <c>:/path ./local               # copy files out
docker system df                          # disk used by images/containers/volumes/cache
docker compose config                     # render the final merged config with env substitution (careful: may print secrets)
```

Common failures and causes: **"exec format error"** (architecture mismatch: arm64 Mac image on amd64 server; build with `--platform`), **permission denied writing files** (read-only filesystem or wrong UID), **container exits immediately** (CMD fails: check logs; missing env var), **unhealthy** (healthcheck cannot reach the app: wrong port/host binding), **works locally, fails in container** (`localhost` means the container itself; missing env; different filesystem paths), **CRLF in scripts**, **cache not invalidated or too eagerly invalidated** (instruction order), **disk full** (images, build cache, logs: `docker system prune`, log rotation).

## 25.9 Registries, tags and releases

* **Tag strategy**: `app:<git-sha>` for every build (immutable), plus moving tags like `app:main` or `app:1.4` if you want; **avoid `latest` in deployments**.
* **Registries**: Docker Hub, GHCR (GitHub), ECR (AWS), GAR (Google), ACR (Azure); private by default for your code; rate limits on public pulls.
* **This project builds on the host** (`build:` in compose), which is simplest for a single VM. The production pattern is **CI builds once, scans, signs, pushes**; servers **pull** the exact digest; rollback = redeploy the previous tag (Chapter 28).
* **Multi-architecture images** (`docker buildx build --platform linux/amd64,linux/arm64`) when developers use Apple Silicon and servers use x86 (or the reverse).

## 25.10 Alternatives and neighbours

* **Podman/Buildah**: daemonless, rootless containers compatible with OCI images.
* **Buildpacks** (Cloud Native Buildpacks, Heroku, Railway's Nixpacks): produce images from source without a Dockerfile.
* **Nix** and **Bazel**: hermetic reproducible builds.
* **gVisor, Kata Containers, Firecracker**: stronger isolation (user-space kernel or micro-VMs) for running untrusted code.
* **Kubernetes** and managed container platforms (Cloud Run, ECS/Fargate, Azure Container Apps, Fly.io): run images at scale (Chapter 26).
* **Dev Containers** (VS Code): containerised development environments.

## Common mistakes

* `latest` tags; unpinned dependencies.
* Copying source before installing dependencies (no cache reuse).
* Secrets in `ENV`, `ARG`, `COPY`, or committed `.env` files baked into layers.
* Running as root; `--privileged`; mounting the Docker socket.
* Shell-form `CMD`; PID 1 that ignores SIGTERM.
* One container running many processes.
* Writing state into the container layer instead of a volume.
* Publishing databases to the internet.
* Forgetting `.dockerignore` (huge contexts, leaked files).
* Treating `EXPOSE` as publishing.

## Summary

* Containers package an app with its dependencies as isolated processes on a shared kernel; images are layered, cached and content-addressed.
* Good Dockerfiles: pinned slim bases, multi-stage builds, dependency layers before source, non-root user, exec-form `CMD`, healthchecks, secure defaults, no secrets.
* Harden at runtime: read-only filesystem, tmpfs, dropped capabilities, `no-new-privileges`, resource limits, no unnecessary published ports.
* Persist data in volumes; treat containers as disposable.
* Scan, pin, sign and tag images by commit SHA; debug with logs, `inspect`, `exec`, and `--progress=plain`.

## Key terms

*image, layer, container, registry, tag, digest, Dockerfile, build context, `.dockerignore`, multi-stage build, BuildKit, exec form, PID 1, healthcheck, volume, bind mount, tmpfs, capability, `no-new-privileges`, cgroup limit, SBOM, OCI.*

## Interview questions

1. What is the difference between an image and a container? Between a VM and a container?
2. Explain Docker layer caching. How would you order a Dockerfile for a Python app?
3. Why use a multi-stage build? What ends up in the final image?
4. Why are `ENV`/`ARG` unsuitable for secrets? What should you use?
5. List five hardening settings and the threat each addresses.
6. What does `EXPOSE` do? How do you actually make a container reachable from outside?
7. Why exec-form `CMD`? What is the PID 1 problem?
8. A container exits with code 137. What do you check?
9. How would you shrink the web image in this repo?

## Exercises

1. Build each image; record sizes with `docker image ls` and layer breakdown with `docker history`. Change one line of source and observe which layers rebuild.
2. Enable Next.js `output: 'standalone'`, adjust the web Dockerfile to copy only the standalone output, and compare image sizes.
3. Run the API container with `--read-only` but without the tmpfs and observe the failure; fix it.
4. Scan the three images with Trivy; fix or document each high-severity finding.
5. Convert the MCP image to a distroless runtime stage; solve the healthcheck without a shell.
6. Add BuildKit cache mounts for `uv` and measure rebuild time.
