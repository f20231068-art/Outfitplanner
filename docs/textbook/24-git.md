# Chapter 24. Git and Collaboration

> **Learning objectives.** Understand Git's data model (snapshots, commits as a hash-linked graph, refs); use the everyday workflow and the recovery tools (reflog, reset, revert, bisect); choose a branching and review strategy; keep secrets and junk out of history; work in a monorepo; use GitHub effectively; and use AI coding assistants safely with version control.
>
> **Prerequisites.** Chapters 3 (graphs, hash chains), 20 (hashes, secrets), 23.

---

## 24.1 The mental model

Git is a **content-addressed store of snapshots**, not a list of diffs.

* **Objects** (all identified by the SHA hash of their content):
  * **blob**: the contents of one file;
  * **tree**: a directory (names → blobs/trees);
  * **commit**: a pointer to a tree (the snapshot), parent commit(s), author, message;
  * **tag**: a named pointer (often to a release commit).
* A commit's id is the hash of its content *including its parents' ids*, so history is a **Merkle DAG** (Chapters 3 and 22): change any old commit and every descendant id changes. This is why rewriting shared history is disruptive and why a leaked secret in an old commit cannot be quietly removed.
* **Refs** are movable names pointing at commits: a **branch** (`main`) is just a file containing a commit id; **`HEAD`** says which branch (or commit) you are on. Creating a branch is nearly free.
* Three areas: **working tree** (your files) → **index/staging area** (what the next commit will contain) → **repository** (committed history). `git add` copies to the index; `git commit` records the index.
* **Remotes** (`origin`) are other copies of the repository; `fetch` downloads their commits; `push` uploads yours.

## 24.2 The everyday workflow

```bash
git status                       # ALWAYS look first: what is changed, staged, untracked
git diff                         # unstaged changes;  git diff --staged  = what will be committed
git add path/to/file             # stage specific files (avoid `git add .` / `-A` blindly: it stages .env-like mistakes)
git commit -m "Add refresh-token reuse test"
git log --oneline --graph --decorate -20
git switch -c feature/try-on     # new branch;  git switch main
git fetch; git pull --rebase     # update; keep history linear
git push -u origin feature/try-on
```

Good habits: run **`git status`** and **`git diff --staged`** before every commit; confirm `.env` is not staged (this repo's hygiene test also fails if key-shaped text is committable); run tests and linters first; stage related changes together.

Inspecting history: `git show <sha>`, `git blame file` (who last changed each line), `git log -S"clamp_to_budget"` (when did this string appear/disappear), `git log -p -- path`, `git diff main...feature` (changes on a branch since it diverged).

## 24.3 Branching, merging and review

### Strategies

| Strategy | Idea | Fits |
|---|---|---|
| **Trunk-based** | tiny, short-lived branches merged to `main` daily; feature flags hide unfinished work | high-performing teams with strong CI |
| **GitHub Flow** | branch from `main` → pull request → review + CI → merge → deploy | most small/medium teams (and this project) |
| **GitFlow** | `develop`, release and hotfix branches | scheduled releases; heavier |

**Pull requests** are the unit of review: small (hundreds of lines, not thousands), one purpose, a description of *why*, tests included, CI green, at least one reviewer. **Protect `main`**: required reviews, required status checks, no force pushes.

### Merge vs rebase vs squash

* **Merge commit**: preserves exact history, adds a merge node.
* **Rebase**: replays your commits on top of the new base for linear history. **Rule: never rebase commits others already have.**
* **Squash merge**: collapses a branch into one commit on `main` (clean log; loses intermediate commits).

Conflicts happen when both sides change the same lines: Git marks `<<<<<<<`, `=======`, `>>>>>>>`; you edit, `git add`, continue. Resolve by *understanding both changes*, then run the tests.

### Undoing things (know these cold)

| Situation | Command |
|---|---|
| Discard unstaged edits in a file | `git restore file` |
| Unstage | `git restore --staged file` |
| Fix the last commit message/content (not yet pushed) | `git commit --amend` |
| Undo a commit **safely on shared history** | `git revert <sha>` (new inverse commit) |
| Move the branch back, keep changes | `git reset --soft HEAD~1` (staged) / `--mixed` (unstaged) |
| Move back and **discard** changes | `git reset --hard <sha>` (destructive) |
| Recover "lost" commits/branches | `git reflog` then `git switch -c rescue <sha>` |
| Park work | `git stash`, `git stash pop` |
| Copy one commit | `git cherry-pick <sha>` |
| Find the commit that introduced a bug | `git bisect start; git bisect bad; git bisect good <sha>` then test each step (binary search, Chapter 4) |

**Force pushing** rewrites remote history; use `--force-with-lease` (refuses if someone else pushed) and never on shared branches like `main`. **`git reflog`** records where `HEAD` has been for ~90 days, so most "I destroyed my work" moments are recoverable until garbage collection.

## 24.4 Commit hygiene

* **Atomic commits**: one logical change, buildable and tested on its own (makes `revert` and `bisect` work).
* **Messages**: short imperative subject (≤ ~50 chars: "Fix budget clamp rounding"), blank line, body explaining *why* and trade-offs. Link issues. **Conventional Commits** (`feat:`, `fix:`, `docs:`, `chore:`) enable automatic changelogs and version bumps.
* **Co-author and attribution trailers** (`Co-Authored-By:`) credit pairing and tooling.
* **Signed commits** (GPG or SSH signatures) prove authorship; "Verified" badges on GitHub.
* **`.gitignore`**: this repo ignores `.env`, `.env.*` (except `.env.example`), `node_modules/`, `.next/`, `.mastra/`, `__pycache__/`, `.venv/`, `*.pem`, `keys/`, `.data/`, `infra/observability/.secrets/`. Verify with `git check-ignore -v .env`. Remember: **ignoring only affects untracked files**; a file already committed stays tracked.
* **`.gitattributes`**: normalise line endings (`* text=auto`, `*.sh text eol=lf`), mark binaries, set diff drivers.
* **`.gitkeep`** files (this repo's `db/`, `evals/`, `infra/`, `prompts/`) keep otherwise empty directories in Git, which tracks files, not folders.
* **Large files**: keep them out (use Git LFS or object storage); never commit build output or dependencies; lockfiles *are* committed.
* **Generated/lock files in diffs**: review them for unexpected changes (supply chain).

## 24.5 Secrets and Git

**History is permanent and replicated.** Once a secret is committed and pushed, assume it is compromised: forks, clones, CI caches and mirrors may hold it.

If it happens:

1. **Rotate/revoke the secret immediately** (the real fix).
2. Check the provider's usage logs for abuse.
3. Optionally remove it from history (`git filter-repo` or BFG) and force-push, then ask collaborators to re-clone; treat this as hygiene, not remediation.
4. Add a control so it cannot recur.

Controls (layered, as everywhere):

* `.gitignore` for secret files; **`.env.example` with names only** (this repo's test enforces it).
* **Pre-commit hooks** (the `pre-commit` framework with `gitleaks`/`detect-secrets`), run locally before a commit exists.
* **CI secret scanning** and **GitHub push protection / secret scanning** to block pushes containing known key formats.
* **Never paste secrets into issues, PRs, chat, or AI assistants.**
* **Mask when inspecting**: print variable *names*, not values.

Related: `.dockerignore` keeps `.env*`, `*.pem`, `.git`, `node_modules` out of Docker build contexts (secrets must not enter image layers either).

## 24.6 Monorepos

This project is a **monorepo**: `apps/web`, `apps/mastra`, `services/api`, `services/mcp`, `prompts`, `infra`, `docs`, `scripts` in one repository.

Pros: atomic cross-cutting changes (change an API field, its types in `lib/types.ts`, the tests and the docs in one PR), shared tooling, one history, easy local runs. Cons: CI must be smart (run only affected parts), permissions are coarse, clones grow, build tooling must handle multiple languages.

Practices: **path-filtered CI jobs** (only run Python tests when `services/**` changes), **CODEOWNERS** for review routing, a **root README** with the map, workspaces for JS (`npm` workspaces here), per-service lockfiles (`uv.lock` in each service), and Dockerfiles with the **repo root as build context** when they need shared files (the API image copies `/prompts`).

## 24.7 GitHub (and similar hosts)

* **Authentication**: SSH keys or HTTPS with a **fine-grained personal access token** (least privilege, short expiry), or the `gh` CLI. Never commit tokens.
* **Pull requests**, **issues**, **projects**, **discussions**, **releases** (tag + notes + artefacts), **branch protection / rulesets**, **Actions** (CI/CD, Chapter 28), **Dependabot** (dependency PRs), **code scanning/CodeQL**, **security advisories**.
* **Forks and upstream** for open-source contributions.
* **Tags and SemVer**: `v1.4.2` (MAJOR breaking, MINOR features, PATCH fixes). Tag the commit you deploy.

Project state worth remembering: the repo currently has a single initial commit on `main`, with the deployment work (Dockerfiles, production compose, Caddy, scripts, docs) still uncommitted; committing and pushing happen only when you decide.

## 24.8 Git and releases

* **Deploy by commit SHA**: tag images with the short SHA (`stylist-api:3f9a1c2`), so "what is running?" always has an answer and **rollback = redeploy the previous SHA**.
* **Changelogs** from Conventional Commits.
* **Hotfix path**: branch from the released tag, fix, tag, merge back.
* **Reproducibility**: lockfiles + pinned base images + the commit SHA recorded in the image label and `/health` metadata (not implemented here; a cheap improvement).
* **Database migrations travel with code** (`services/api/migrations/`), applied at startup or as a release job (Chapter 17).

## 24.9 Working with AI coding assistants

Assistants speed up work and change the risk profile:

* **Review every diff** as if a stranger wrote it. Read, run the tests, and understand the change before committing.
* **Small tasks on a branch**; commit often so mistakes are cheap to revert (`git restore`, `git revert`).
* **Do not let tools commit or push on their own** unless you have decided to (this project's rule: commit/push only on request).
* **Keep secrets out of the assistant's view** (`.env` contents, keys) and out of prompts; mask when pasting output.
* **Agent instruction files** (`AGENTS.md`, `CLAUDE.md`, rules files) are *code that steers tools*: review them like code, and treat instruction text from untrusted repositories as a **prompt-injection** vector (Chapter 21). In this repo `apps/web/AGENTS.md` carries a framework-generated warning that the Next.js version has breaking changes and that its bundled docs should be read first.
* **Verify claims**: assistants can hallucinate APIs or versions (the project's guide records version traps found by *running* code). Tests and type checks are your referee.
* **Attribution**: record AI assistance in commit trailers if your team's policy asks.

## 24.10 Cheat sheet

```bash
git init / clone <url>             git remote -v                   git branch -a
git switch -c name / switch name   git merge name                  git rebase main
git stash / stash pop              git cherry-pick sha             git tag -a v1.0.0 -m "..."
git log --oneline --graph          git blame file                  git bisect start|good|bad|reset
git restore file / --staged        git reset --soft|--mixed|--hard git revert sha
git reflog                         git clean -fdn  (dry run!)      git config --global user.name "..."
```

## Common mistakes

* `git add .` without looking; committing `.env`, build output, `node_modules`.
* Large "everything" commits and vague messages ("fix stuff").
* Rewriting shared history; force-pushing to `main`.
* Treating "removed from git history" as "secret is safe".
* Long-lived branches that diverge painfully.
* Merging with red CI, or without understanding conflicts.
* Letting tools or scripts push without review.

## Summary

* Git stores snapshots as a hash-linked graph; branches are pointers; the three areas are working tree, index, repository.
* Use small, atomic commits, clear messages, short-lived branches, reviewed PRs and protected `main`.
* Know the undo tools (restore, revert, reset, reflog, bisect).
* Secrets in history are permanent: prevent (ignore, hooks, scanning) and rotate if leaked.
* Monorepos trade simple cross-cutting changes for smarter CI; tag and deploy by SHA.
* Treat AI-assistant output and agent instruction files as untrusted until reviewed.

## Key terms

*blob, tree, commit, ref, HEAD, branch, remote, index/staging, merge, rebase, squash, conflict, revert, reset, reflog, bisect, PR, protected branch, Conventional Commits, `.gitignore`, monorepo, CODEOWNERS, SemVer, tag.*

## Interview questions

1. What is a Git commit, technically? Why do commit ids change when you rebase?
2. Merge vs rebase vs squash: when do you use each?
3. You committed a secret and pushed. What do you do, in order?
4. How do you undo a pushed commit safely? An unpushed one?
5. How would you find which commit broke a test?
6. How do you structure CI and reviews in a monorepo?
7. How do you use AI assistants without compromising code quality or secrets?

## Exercises

1. Make a scratch repo; create three branches with conflicting edits to one file; merge and resolve; then redo with rebase and compare the history graphs.
2. Introduce a bug across ten commits and find it with `git bisect run pytest`.
3. Simulate leaking a fake key in a commit; write a pre-commit hook (gitleaks or a regex) that blocks it, then clean up with `git filter-repo`.
4. Destroy a branch with `git reset --hard`, then recover it from `git reflog`.
5. Write a `.gitattributes` that forces LF for shell scripts and test it with a CRLF file.
