# Chapter 23. Linux and the Shell

> **Learning objectives.** Navigate and administer a Linux machine confidently; understand files, permissions, users, processes, signals, resources and the kernel features (namespaces, cgroups, capabilities) that containers are built from; use SSH safely; write robust shell scripts; handle Windows/Git-Bash/PowerShell differences (the environment this project was built in); and debug a misbehaving server methodically.
>
> **Prerequisites.** None, but Chapter 16 helps.

You may develop on Windows or macOS, but **production is Linux** (almost always), **containers are Linux**, and an FDE regularly SSHes into a customer's VM at 6 p.m. to find out why it is out of disk. Linux fluency is a force multiplier for everything in Part VI.

---

## 23.1 The mental model

An **operating system** manages hardware and gives programs: **processes** (running programs), **memory**, a **filesystem**, **networking**, and **users/permissions**. **Linux** is a kernel; a **distribution** (Ubuntu, Debian, Alpine, RHEL/Rocky, Amazon Linux) packages it with tools. **Everything is a file** is a guiding idea: devices, sockets and process info appear as files (`/dev/null`, `/proc/<pid>/status`).

You interact through a **shell** (bash, zsh, sh, dash, fish): a program that reads commands, starts processes and connects their input and output. **Containers do not have their own kernel**: they are ordinary processes isolated by kernel features (Section 23.5), so understanding Linux *is* understanding Docker.

## 23.2 Filesystem, paths and permissions

### Layout

```
/            root of everything
├── bin, sbin, usr/bin   programs
├── etc/                 configuration (text files)
├── home/<user>/         user files
├── var/                 variable data: logs (/var/log), databases (/var/lib/postgresql), caches
├── tmp/                 temporary files (often tmpfs, cleared on reboot)
├── proc/, sys/          kernel and process information (virtual)
├── dev/                 devices
├── opt/, srv/           optional software, served data
└── run/                 runtime state (PIDs, sockets, secrets in containers: /run/secrets)
```

Paths: **absolute** (`/etc/caddy/Caddyfile`) vs **relative** (`./scripts/x.py`); `.` current, `..` parent, `~` home. Case-sensitive. **Hidden files** start with a dot (`.env`).

In this repo's containers: code in `/app`, prompts in `/app/prompts`, the Caddyfile mounted at `/etc/caddy/Caddyfile`, Prometheus's token at `/run/secrets/metrics_token`, Postgres data at `/var/lib/postgresql/data` (a volume), and `/tmp` a `tmpfs` because the root filesystem is read-only.

### Permissions

Each file has an **owner**, a **group** and **mode bits** for **user / group / others**: **r**ead (4), **w**rite (2), e**x**ecute (1; on directories: may enter/traverse).

```
$ ls -l
-rw-r--r-- 1 app app  5035 Oct  3 22:33 .env.production     # 644: owner rw, group r, others r
-rwx------ 1 app app   212 Oct  3 22:33 run.sh               # 700: owner only
drwxr-xr-x 2 app app  4096 Oct  3 22:33 scripts
```

```bash
chmod 600 .env.production        # owner read/write only  (what the deploy guide recommends on a server)
chmod +x run.sh                  # make executable
chown app:app /data              # change owner and group
umask 077                        # new files default to owner-only
```

* **Never `chmod 777`.** If something "needs" it, you have a user/ownership problem to solve properly.
* **Special bits**: **setuid** (run as the file's owner: a classic privilege-escalation surface; `no-new-privileges` in containers blocks gaining privileges through it), **setgid**, **sticky** (`/tmp`: only the owner can delete their files).
* **Users and groups**: `id`, `whoami`, `/etc/passwd`, `/etc/group`. **root** (UID 0) can do anything; **`sudo`** runs a command as root with logging; prefer a normal user + `sudo`. **System users** (like the containers' `app` user with `--shell /usr/sbin/nologin`) exist to run services with minimal rights.
* **Principle**: services run as **non-root users**, owning only what they must write.

### Links and special files

**Hard links** and **symbolic links** (`ln -s target link`), `/dev/null` (discard), `/dev/urandom` (random bytes), `/dev/stdout`.

## 23.3 Commands you must know

**Navigate and inspect**
```bash
pwd; ls -la; cd /var/log; tree -L 2
cat file; less file; head -n 20 file; tail -n 100 file; tail -f file      # follow a log live
stat file; file mystery.bin; du -sh *; df -h; wc -l file
```

**Search**
```bash
grep -rn "TODO" src/                    # recursive, line numbers
grep -E "ERROR|WARN" app.log            # extended regex
grep -v health app.log                  # invert
find . -name "*.py" -mtime -1           # modified in the last day
find / -type f -size +100M 2>/dev/null  # big files
rg pattern                              # ripgrep: faster, respects .gitignore
```

**Text processing (the Unix pipeline philosophy: small tools composed with `|`)**
```bash
cut -d, -f1,3 data.csv
sort | uniq -c | sort -rn | head        # frequency table
awk '{sum += $3} END {print sum}' f     # column sums
sed -n '10,20p' file; sed 's/old/new/g' file
tr 'a-z' 'A-Z'; xargs; tee out.txt      # tee: show AND save
```

**JSON**: **`jq`** is essential for APIs and this repo's JSON logs.
```bash
curl -s localhost:8000/health | jq .
docker compose logs api --no-log-prefix | jq -R 'fromjson? | select(.level=="ERROR")'      # only error lines, ignoring non-JSON
docker compose logs api --no-log-prefix | jq -Rr 'fromjson? | select(.trace_id=="4bf92f35...") | "\(.ts) \(.msg)"'
```

**Files and archives**
```bash
cp -r src dst; mv a b; rm -rf build/        # rm -rf is irreversible: double-check the path, never `rm -rf $VAR/` with an empty variable
tar czf backup.tgz dir/; tar xzf backup.tgz; gzip -k file
rsync -avz --delete src/ user@host:/dst/    # efficient sync; scp for single files
sha256sum file                               # verify downloads
```

**Processes and system**
```bash
ps aux | grep uvicorn; pgrep -f uvicorn; top; htop; kill <pid>; kill -9 <pid>
uptime; free -h; vmstat 1; iostat; lsof -i :8000; ss -ltnp
journalctl -u myservice -f; journalctl -p err --since "1 hour ago"; dmesg | tail
systemctl status|start|stop|restart|enable <service>
```

**Networking**: `curl -v`, `dig`, `nc -vz host port`, `ss -ltnp`, `ip addr`, `traceroute` (Chapter 16).

**Environment**: `env`, `export VAR=value`, `printenv`, `which python`, `type cmd`, `echo $PATH`. **Never print secrets**: `env | grep -i key` can leak in terminals, screen shares and logs; list *names* only (`env | cut -d= -f1`), a habit this project learned the hard way.

## 23.4 Streams, pipes, redirection, exit codes

Every process has **stdin (0)**, **stdout (1)**, **stderr (2)**.

```bash
cmd > out.txt          # overwrite stdout        cmd >> out.txt   # append
cmd 2> err.txt         # stderr only             cmd > all.txt 2>&1   # both to one file
cmd1 | cmd2            # stdout of 1 becomes stdin of 2
cmd < input.txt        # file as stdin
cmd > /dev/null 2>&1   # discard everything
```

**Exit codes**: `0` = success, non-zero = failure; read with `$?`. `&&` runs the next command only on success; `||` only on failure; `;` regardless. CI and orchestrators depend on exit codes: this repo's `npm run eval` exits **0** (pass), **1** (a gate failed), **2** (harness crashed), and `audit:verify` exits 1 on tampering.

**Logs belong on stdout/stderr** (twelve-factor); the platform collects them. Containers' `docker logs` shows exactly those streams.

## 23.5 Processes, signals and containers

* A **process** has a PID, a parent, memory, open file descriptors, environment, and a working directory. New processes are made by **`fork`** + **`exec`**.
* **Signals** are asynchronous notifications: **SIGTERM (15)** "please terminate" (catchable: graceful shutdown), **SIGINT (2)** Ctrl-C, **SIGKILL (9)** "die now" (cannot be caught), **SIGHUP** reload/hangup, **SIGCHLD**. **`docker stop`** sends SIGTERM, waits (default 10 s), then SIGKILL. A service that ignores SIGTERM gets killed mid-request. uvicorn handles SIGTERM gracefully (finishes in-flight requests, runs lifespan shutdown).
* **PID 1 in a container** is special: it must **reap zombie children** and **forward signals**. If your `CMD` is in *shell form* (`CMD python app.py` runs `sh -c ...`), the shell can swallow signals. Use **exec form** (`CMD ["uvicorn", ...]`) as the Dockerfiles here do, and `docker run --init`/`tini` if you spawn subprocesses.
* **Zombie** = finished process whose parent has not collected its exit status.
* **Background**: `cmd &`, `jobs`, `nohup cmd &` (survives logout), better: a **service manager**.

### systemd: running services on a VM

A **unit file** describes a service:

```ini
# /etc/systemd/system/stylist.service
[Unit]
Description=AI Stylist (docker compose)
After=docker.service network-online.target
Requires=docker.service

[Service]
WorkingDirectory=/opt/stylist
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml --env-file .env.production up
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml down
Restart=on-failure
User=deploy

[Install]
WantedBy=multi-user.target
```

`systemctl enable --now stylist` starts it now and on boot; `journalctl -u stylist -f` shows logs. (The compose files already use `restart: unless-stopped`, which restarts containers after crashes and reboots as long as the Docker daemon starts on boot: `systemctl enable docker`.) **Timers** (`.timer` units) or **cron** schedule jobs (`crontab -e`: `0 2 * * * /opt/stylist/backup.sh`).

## 23.6 Resources and limits

* **CPU**: load average (runnable processes), per-core utilisation, steal time (noisy neighbours on VMs).
* **Memory**: **RSS** (resident set), **page cache** (the kernel uses spare RAM to cache files: "free memory" looks low but is *available*; read the `available` column of `free -h`), **swap**. When memory runs out the **OOM killer** terminates a process (`dmesg | grep -i oom`; a container killed with exit code 137 = SIGKILL, often OOM). The compose files cap memory (`mem_limit: 1g`) so a leak kills *one container*, not the host.
* **Disk**: space (`df -h`) **and inodes** (`df -i`; many tiny files can exhaust inodes). **Docker images, build cache, volumes and logs fill disks**: `docker system df`, `docker system prune` (careful), log rotation (`--log-opt max-size`).
* **File descriptors**: every socket and file uses one; default per-process limit is often 1024 (`ulimit -n`). Many concurrent SSE streams or database connections can exhaust it ("Too many open files"). Raise via systemd `LimitNOFILE` or Docker `--ulimit`.
* **PIDs**: a fork bomb can exhaust them; `pids_limit: 200/300` in compose.
* **Network**: ports, ephemeral port exhaustion under extreme connection churn, conntrack limits.

### What a container really is

A container is a normal Linux process with restrictions from **kernel features**:

| Feature | What it isolates/limits | In this repo |
|---|---|---|
| **Namespaces** (`pid`, `net`, `mnt`, `uts`, `ipc`, `user`) | what the process can *see*: its own process tree, network stack, filesystem mounts, hostname | each service sees only itself; Docker network gives service-name DNS |
| **cgroups** | how much it can *use*: CPU, memory, PIDs, I/O | `mem_limit`, `pids_limit` |
| **Layered filesystem** (overlayfs) | image layers + a writable layer | `read_only: true` removes even the writable layer; `tmpfs` for `/tmp` |
| **Capabilities** | root's powers split into ~40 pieces | `cap_drop: [ALL]` (+ minimal `cap_add` for Postgres and Caddy) |
| **seccomp / AppArmor / SELinux** | which system calls and resources are allowed | Docker's default seccomp profile applies |
| **User** | UID inside the container | non-root `app` users (UID 10001/10002), `node` |
| **`no-new-privileges`** | blocks setuid escalation | enabled |

Containers share the host kernel, so a kernel exploit can break out (VMs and gVisor/Kata give stronger isolation); that is why you also keep the host patched and minimise container privileges.

## 23.7 SSH

**SSH** gives an encrypted remote shell and file transfer.

```bash
ssh-keygen -t ed25519 -C "me@laptop"            # creates ~/.ssh/id_ed25519 (private) and .pub (public)
ssh-copy-id user@server                          # or append the .pub to ~/.ssh/authorized_keys on the server
ssh user@server
scp file user@server:/tmp/          rsync -avz dir/ user@server:/opt/dir/
ssh -L 5432:localhost:5432 user@server           # local port forward: reach the server's private Postgres as localhost:5432
ssh -L 9090:127.0.0.1:9090 user@server           # view a localhost-bound admin UI (Prometheus) from your laptop safely
```

* Authenticate with **keys, not passwords**; protect the private key (`chmod 600`, passphrase, `ssh-agent`).
* **`~/.ssh/config`** gives hosts short names, users and keys. **`known_hosts`** pins server identity: *verify the fingerprint on first connect*, and never blindly bypass warnings.
* **Harden servers**: `PasswordAuthentication no`, `PermitRootLogin no`, restrict users, keep the OS updated, use a **firewall** (only 22 from your IP, 80/443 public), **fail2ban**, or cloud-provider session managers (AWS SSM, GCP IAP) that avoid open port 22 altogether.
* **Agent forwarding** (`-A`) exposes your keys to the remote host's root; avoid it on untrusted machines; use **jump hosts** (`ProxyJump`) instead.
* **Tunnels** are the safe way to reach private admin UIs (that is why Grafana/Prometheus/Jaeger bind to `127.0.0.1`).

## 23.8 Shell scripting that does not bite

```bash
#!/usr/bin/env bash
set -euo pipefail          # -e: exit on error; -u: error on unset variables; -o pipefail: a failure anywhere in a pipe fails the pipe
IFS=$'\n\t'

usage() { echo "usage: $0 <env-file>" >&2; exit 2; }
[[ $# -eq 1 ]] || usage
ENV_FILE=$1
[[ -f "$ENV_FILE" ]] || { echo "missing $ENV_FILE" >&2; exit 1; }

cleanup() { rm -f "$tmp"; }
tmp=$(mktemp); trap cleanup EXIT            # always clean up, even on error or Ctrl-C

for svc in api web; do                      # QUOTE every expansion: "$var", "${arr[@]}"
  if docker compose -f docker-compose.prod.yml --env-file "$ENV_FILE" ps --status running "$svc" | grep -q "$svc"; then
    echo "$svc is up"
  else
    echo "$svc is DOWN" >&2; exit 1
  fi
done
```

Key habits:

* **Quote variables** (`"$file"`): unquoted expansions split on spaces and glob, causing bugs and injection.
* **`set -euo pipefail`** at the top of non-trivial scripts (know its caveats).
* **Check inputs**; print errors to stderr; use meaningful exit codes.
* **Idempotent scripts** (safe to re-run): `mkdir -p`, `ln -sf`, "create if missing". This repo's `generate_jwt_keys.py` and `init_production_env.py` follow the idea: *"It adds only what is missing."*
* **Do not put secrets in command-line arguments** (visible in `ps` and shell history); read from files or env vars.
* **Do not `source` or `eval` untrusted input.**
* **`trap`** for cleanup. **Here-documents** (`cat <<'EOF' ... EOF`) for multi-line text (the quoted `'EOF'` disables expansion).
* **Use ShellCheck** (`shellcheck script.sh`): catches most mistakes.
* **When a script exceeds ~50 lines or needs data structures, switch to Python** (this repo's tooling is Python for that reason).
* **sh vs bash**: `#!/bin/sh` scripts (Alpine's BusyBox) must avoid bash-isms (`[[ ]]`, arrays).

Useful bash features: parameter expansion (`${var:-default}`, `${var%.txt}`), arrays, `$(command)` substitution, process substitution `<(cmd)`, brace expansion `{a,b}`, `read -r`, `getopts`, arithmetic `$(( ))`.

## 23.9 Windows, Git Bash, PowerShell and WSL (practical gotchas)

This project was built on **Windows 11** with Git Bash and PowerShell, which taught real lessons an FDE meets on customer laptops:

* **Docker Desktop on Windows** runs Linux containers in a **WSL2** virtual machine; bind-mounted Windows files are slower and have different permission semantics. Prefer keeping source inside the WSL filesystem for performance.
* **Line endings**: Windows editors may save **CRLF** (`\r\n`); a shell script or Docker entrypoint with CRLF fails with `bad interpreter: /bin/bash^M` or odd "not found" errors. Fix with `.gitattributes` (`*.sh text eol=lf`), editor settings, `dos2unix`.
* **Path conversion**: Git Bash (MSYS) rewrites path-looking *arguments* to native programs (`/tmp/x` → `C:\Users\...\Temp\x`) but **not paths inside script text or heredocs**; pass scratch paths as arguments.
* **Backslashes and heredocs**: text containing `\n` or `\\n` can be **silently altered** when passed through shell here-documents; write such files with an editor tool, not `cat <<EOF`. (A recorded lesson from this project: a patch script corrupted files because of exactly this.)
* **Default encodings**: Python on Windows may open files as **cp1252** unless you pass `encoding="utf-8"`; writing or printing `₹` can crash and, if the file was already opened for writing, **leave it empty** (this happened here). Always specify UTF-8; set `PYTHONIOENCODING=utf-8`; do not open a file for writing before you have the content ready.
* **PowerShell** differs from bash: objects not text, `$env:NAME`, `Remove-Item`, `Select-String`, `Test-NetConnection`, `Resolve-DnsName`; Windows PowerShell 5.1 lacks `&&`/`||` (use `;` and `if ($?)`). `curl` in old PowerShell is an alias for `Invoke-WebRequest`; use `curl.exe`.
* **File permissions** are not Unix modes; `chmod` is a no-op on NTFS mounts; security checks like "key file permissions" behave differently.
* **Reserved names and case-insensitivity** (`aux`, `con`; `README.md` = `readme.md`) can surprise.
* **Never `cat`/`grep` a file that may hold secrets** without masking, in any shell, anywhere you have scrollback or shared screens.

## 23.10 Packages and runtimes

* System packages: **apt** (Debian/Ubuntu), **apk** (Alpine), **dnf/yum** (RHEL), **brew** (macOS), **winget/choco** (Windows). In Dockerfiles: `apt-get update && apt-get install -y --no-install-recommends pkg && rm -rf /var/lib/apt/lists/*` in **one layer**.
* Language runtimes: **uv** or **pyenv** for Python, **nvm/fnm** for Node. **Never `sudo pip install`** into the system Python; use virtual environments.
* **`curl ... | sh`** installers run unreviewed code with your privileges: read the script first, prefer package managers or checksummed downloads.
* **Pin versions** in automation.

## 23.11 Debugging a sick server (a checklist)

1. **Is it up and reachable?** `ssh`, `curl -v https://host/health`, status page.
2. **Load and memory**: `uptime`, `top`/`htop`, `free -h`. High load with low CPU often means I/O wait or swap thrash.
3. **Disk**: `df -h`, `df -i`, `du -xh / | sort -h | tail`. Full disks break databases, logs and Docker silently.
4. **Containers**: `docker compose ps` (restarts? unhealthy?), `docker compose logs --tail=200 api`, `docker stats`, `docker inspect <c> | jq '.[0].State'` (OOMKilled?).
5. **Processes and ports**: `ss -ltnp`, `ps aux --sort=-%mem | head`.
6. **Kernel and system**: `dmesg -T | tail`, `journalctl -p err -b`.
7. **Network**: `dig`, `curl` from inside the container network, firewall rules, security groups.
8. **Recent changes**: deployments, config edits, certificate expiry, clock drift (`timedatectl`), cron jobs.
9. **Reproduce locally if possible; write down what you tried**: an FDE's notes become the runbook.

## Common mistakes

* `chmod 777` instead of fixing ownership.
* Running services as root.
* Unquoted shell variables; no `set -e`; `rm -rf` with an empty variable.
* Ignoring SIGTERM, shell-form `CMD`.
* Forgetting that disks fill (logs, images).
* Reading "free memory" wrong.
* Secrets in command-line arguments or shell history.
* CRLF line endings in scripts.
* Opening SSH to the world with password auth.

## Summary

* Linux basics: filesystem hierarchy, permissions (rwx, owner/group), users/root/sudo, pipes and redirection, exit codes.
* Process model: signals, graceful shutdown, PID 1, systemd, cron; resources (CPU, memory, disk, inodes, file descriptors).
* Containers are processes constrained by namespaces, cgroups, capabilities and layered filesystems.
* SSH with keys and tunnels; harden servers; scripts that quote, fail fast, clean up and are idempotent.
* Windows hosts bring line-ending, encoding, path and quoting pitfalls.
* Debug servers top-down: reachability, load, disk, containers, logs, network, recent changes.

## Key terms

*shell, pipe, redirection, exit code, permission bits, root, sudo, process, signal, SIGTERM/SIGKILL, PID 1, systemd, cron, OOM killer, inode, file descriptor, namespace, cgroup, capability, SSH key, tunnel, `set -euo pipefail`, WSL2, CRLF.*

## Interview questions

1. What do permissions `rwxr-x---` mean? When would you use `chmod 600`?
2. What is a signal? What is the difference between SIGTERM and SIGKILL, and why does it matter for containers?
3. A server's disk is full. How do you find what is using it?
4. What is a container, technically? Which kernel features are involved?
5. How would you view a Prometheus UI bound to `127.0.0.1` on a remote VM?
6. Why is `set -euo pipefail` useful? What is a trap?
7. A container is killed with exit code 137. What does it likely mean?

## Exercises

1. Using only shell tools, produce from `docker compose logs api` a table of requests per route and the count of non-2xx responses (hint: the log line contains `"POST /conversations/{conversation_id}/messages -> 200 in 31245ms"`).
2. Write an idempotent `backup.sh` with `set -euo pipefail`, a `trap` for cleanup, a dated filename and a retention of 14 files.
3. Create a systemd unit for the production compose stack and test a reboot.
4. Use `docker inspect` and `/proc/<pid>/cgroup` to find a container's memory limit; trigger the OOM killer with a small test container and observe exit code 137.
5. Set up key-based SSH to a throwaway VM, disable password login, and reach a localhost-bound service with a tunnel.
