# Chapter 19. Frontend for AI Apps

> **Learning objectives.** Understand how the browser renders and runs your code; use TypeScript and React (components, state, effects, refs) correctly; understand Next.js (App Router, client components, build-time environment variables, deployment); build a streaming chat UI with robust auth handling; secure the front end (XSS, tokens, links, CSP); test it; and design good UX for AI products. Every idea is tied to `apps/web`.
>
> **Prerequisites.** Chapters 2, 16.

An FDE ships *products*, and customers judge products through the interface. You do not need to be a front-end specialist, but you must be able to build a clean, accessible, secure UI that handles the awkward realities of AI: slow responses, streaming, partial failure, and uncertainty.

---

## 19.1 The web platform in five minutes

* **HTML** structures content (the DOM tree); **CSS** styles it; **JavaScript** adds behaviour by reading and changing the DOM and calling web APIs.
* **Events** (click, input, keydown) trigger handlers; the **event loop** runs them one at a time (Chapter 2). Long synchronous work freezes the page.
* **`fetch`** performs HTTP requests; the response body can be **streamed** (`response.body.getReader()`).
* **Storage**: cookies, `localStorage`, `sessionStorage`, IndexedDB, plus **in-memory variables** (cleared on reload).
* **Rendering pipeline**: parse HTML → build DOM and CSSOM → layout → paint → composite. Expensive operations: layout thrash, huge DOMs, unoptimised images.
* **Accessibility (a11y)** is part of correctness: semantic elements (`button`, `nav`, `main`), labels for inputs, keyboard operability, focus states, colour contrast, ARIA only where semantics are insufficient.

## 19.2 TypeScript essentials (in this repo)

* **Types describe shapes**: `interface Outfit { id: string; total_inr: number; top: Item; ... }` in `lib/types.ts`, "kept in one file so the UI and the backend contract are easy to compare".
* **Union types and discriminated unions** (`Pending`, `StreamEvent`) with narrowing inside `if (ev.event === 'status')`.
* **Generics**: `AsyncGenerator<StreamEvent>`, `Promise<BuyLink>`.
* **`unknown` vs `any`**; `as` casts are promises to the compiler that you must back with runtime checks (or a validator such as zod when data comes from outside).
* **`strict` mode** in `tsconfig` turns on null checks and more; `npm run typecheck` runs `tsc --noEmit` in CI.
* Types disappear at runtime: **the compiler cannot validate what the server actually sends**. Keep the types in sync with the API (generate them from OpenAPI when the API is large).

## 19.3 React in depth

React renders UI as a **function of state**: `UI = f(state)`. You describe what the screen should look like for the current state; React updates the DOM to match.

### Components, props, JSX

```tsx
export default function StyleCards({ styles, onPick, disabled }: { styles: Style[]; onPick: (s: Style) => void; disabled: boolean }) {
  return (
    <section aria-label="Choose a style">
      {styles.map((s) => (
        <button key={s.id} onClick={() => onPick(s)} disabled={disabled}>
          <strong>{s.name}</strong><span>{s.description}</span>
        </button>
      ))}
    </section>
  )
}
```

A **component** is a function returning JSX. **Props** are inputs (read-only). Data flows **down** (props); events flow **up** (callbacks like `onPick`). **`key`** gives list items a stable identity so React updates, not recreates, them (use a real id, not the array index, when order can change; `Chat.tsx` uses `c.id` for conversations and `o.id` for outfits, but the array index for messages and progress steps, which is fine because those lists only ever append).

### State

`const [draft, setDraft] = useState('')`: state survives re-renders; calling the setter schedules a re-render. **Rules:**

1. **Never mutate state**; create new values: `setMessages((m) => [...m, newMessage])`, `setOutfits((o) => [...o, ...ev.data.outfits])`. React detects change by reference.
2. **Use the functional update form** (`(m) => ...`) when the new value depends on the old one, so rapid updates do not overwrite each other. In the streaming loop, many `setSteps` calls fire quickly; the functional form keeps all of them.
3. **Keep state minimal; derive the rest** (`const empty = messages.length === 0 && !pending && !busy`). Duplicated state drifts.
4. **Lift state up** to the nearest common parent (`Chat` owns conversations, messages, pending, outfits, steps, busy, error, draft).

### Effects

`useEffect(() => { ...; return cleanup }, [deps])` synchronises with something *outside* React (network, timers, subscriptions). The dependency array lists what the effect reads.

* **Run on mount** with `[]`; re-run when dependencies change.
* **Cleanup** undoes the effect (unsubscribe, abort).
* **Strict Mode (development)** deliberately **mounts, unmounts and re-mounts** components to expose effects that are not idempotent or lack cleanup. This is why `refreshSession()` shares one in-flight Promise: *a second simultaneous refresh with a rotated cookie would look like token theft and log the user out.* A bug that appears only in development is a gift: it shows a latent race.
* **The effect callback must return nothing or a cleanup function.** The repo's comment explains a subtle one: `scrollIntoView()` returns a Promise in newer browsers; writing `useEffect(() => ref.current?.scrollIntoView(...))` would return that Promise, and React would try to call it as cleanup. Hence the block body `{ endRef.current?.scrollIntoView(...) }`.
* **Do not use effects for things that are not synchronisation** (deriving data, handling clicks). Event handlers handle events.
* **Async in effects**: define an inner `async` function and call it (as `Chat.tsx` does) because the effect function itself cannot be `async`.

### Refs

`useRef` holds a mutable value or a DOM node without causing re-renders (`endRef` for scrolling).

### `useCallback`, memoisation

`useCallback(fn, deps)` keeps a function identity stable (here `loadList` is used as an effect dependency). Do not sprinkle memoisation everywhere; use it when identity matters (dependencies, memoised children) or measurement shows a cost.

### Controlled inputs

`<textarea value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={500} />`: React state is the single source of truth for the text; the counter `draft.length/500` derives from it. `onKeyDown` sends on Enter and allows Shift+Enter for newline.

### Common React pitfalls

* **Stale closures**: a callback captures old state. Use functional updates or refs.
* **Infinite effect loops**: setting state in an effect whose dependency is that state.
* **Missing keys / index keys on reorderable lists.**
* **Setting state after unmount** (cancel or ignore).
* **Race conditions in data fetching**: an older response arriving after a newer one; use request ids, abort controllers, or ignore stale results (`open(id)` in `Chat.tsx` resets state first and guards with `busy`).
* **Over-fetching in effects** without cleanup.

## 19.4 Next.js

**Next.js** is a React framework adding **routing, rendering strategies, bundling, optimisation and server features**. This repo uses version 16 with the **App Router**:

```
apps/web/
  app/layout.tsx          the root layout (HTML shell, metadata, global CSS)
  app/page.tsx            "/"      -> <Chat />
  app/login/page.tsx      "/login" -> the sign-in/register form
  components/             Chat, OutfitCard, StyleCards
  lib/                    api.ts, sse.ts, types.ts
```

* **File-system routing**: a `page.tsx` under `app/<segment>/` is a route.
* **Server Components vs Client Components**: by default components render on the **server**; a file with **`'use client'`** at the top (all the interactive components here: `Chat`, `OutfitCard`, the login page) is a **client component** that runs in the browser with hooks and event handlers. `layout.tsx` and `page.tsx` here are server components that just render client ones. Rule: *push `'use client'` as far down the tree as practical.*
* **Rendering strategies**: SSR (HTML per request), SSG (HTML at build), ISR (periodically regenerated), CSR (render in the browser). This app is effectively **client-rendered after a minimal server shell**, because everything depends on a logged-in user's in-memory token.
* **Environment variables**: only variables prefixed **`NEXT_PUBLIC_`** are exposed to the browser, and they are **inlined into the JavaScript bundle at build time**, not read at runtime. `NEXT_PUBLIC_API_URL` is therefore a **build argument** in the web Dockerfile (`ARG NEXT_PUBLIC_API_URL=""` → `ENV ...`). To change it you must **rebuild the image**. The default in the production build is the empty string, meaning "same origin", and the code's `?? 'http://localhost:8000'` correctly **keeps** the empty string (Chapter 2). **Never put secrets in `NEXT_PUBLIC_` variables**: everyone can read the bundle.
* **Build and run**: `next build` produces optimised output in `.next/`; `next start` serves it (the production Dockerfile's CMD). The prod compose gives `.next/cache` a writable `tmpfs` because the container's filesystem is otherwise read-only.
* **This Next.js version differs from older ones.** `apps/web/AGENTS.md` instructs: read the version's own docs in `node_modules/next/dist/docs/` before writing code, and heed deprecation notices. (Practical advice for any fast-moving framework, especially when an AI assistant helps you code: *its memory of the API may be out of date.*)
* **Other features** you will meet: route handlers (API routes), middleware, `next/image` optimisation (this repo uses a plain `<img>` with an ESLint exemption because thumbnails come from arbitrary retailer CDNs), `next/font`, metadata API, streaming/Suspense, caching controls.

## 19.5 The client in this repo, file by file

### `lib/api.ts`: the API client and session logic

**The token model**

```ts
let accessToken: string | null = null          // module-level variable: in MEMORY only
let refreshing: Promise<boolean> | null = null
```

* **Access token in memory** (15-minute JWT): gone on tab close or reload; invisible to storage-reading scripts.
* **Refresh token in an HttpOnly cookie**: JavaScript cannot see it; the browser sends it to `/auth/*`.
* **On load**: call `refreshSession()` (POST `/auth/refresh`, `credentials: 'include'`, header `X-Requested-With: stylist-web` as CSRF protection); success → we have an access token; failure → go to `/login`.

**`refreshSession()` single-flight**

```ts
refreshing ??= (async () => { ...fetch refresh...; finally { refreshing = null } })()
return refreshing
```

All concurrent callers await the *same* request. Why it matters: refresh tokens **rotate** and **reuse is treated as theft**.

**`request()` with automatic retry**

```ts
r = await fetch(`${API}${path}`, { ...init, headers, credentials: 'include' })
if (r.status === 401 && retry && (await refreshSession())) return request(path, init, false)   // retry ONCE
if (!r.ok) throw new ApiError(await message(r), r.status, retryAfterSeconds)
```

When an access token expires mid-session, the first 401 triggers a silent refresh and replays the request once (`retry=false` prevents loops). `ApiError` carries a *user-safe* message (the server's `detail`, or a generic fallback; network failure becomes "Cannot reach the server...").

**Error normalisation**: `message(r)` understands both FastAPI error shapes: `detail` as a string, or a validation array (`detail[0].msg`, stripping Pydantic's "Value error, " prefix).

**Streaming**: `sendMessage` is an `async function*` that does the authenticated POST, then `yield* readEvents(r.body)`.

### `lib/sse.ts`: the stream parser

Reads the `ReadableStream`, decodes UTF-8 with `{stream: true}`, normalises `\r\n`, **buffers** until it sees a blank line, parses each block into `{event, data}`, **skips malformed blocks** instead of crashing, and flushes a final block with no trailing blank line. The test file `sse.test.ts` covers: normal events, malformed JSON, **events split across chunks**, Windows line endings, **a `₹` split between byte chunks**, a final event without a trailing newline, and a corrupt block followed by good ones. *Good parsers are tested against hostile chunking.*

### `components/Chat.tsx`: the conversation state machine

State: `convos`, `activeId`, `messages`, `pending` (a question or style choice from the server), `outfits`, `steps` (progress labels), `busy`, `error`, `draft`.

The flow of `ask(text)`:

1. Ignore blank text or if `busy`.
2. Clear error/steps/pending/draft; set `busy`.
3. Create a conversation if none (POST).
4. Append the user's message *optimistically* (the UI shows it immediately; `shownAs` lets a style-card click display the style's name while sending its id).
5. `for await (const ev of sendMessage(id, clean))` and dispatch by event type: `status` → append a step label; `interrupt` → set `pending` (render a question or style cards); `outfits` → append; `message` → append assistant text; `error` → show.
6. `finally`: clear `busy`/`steps`, refresh the conversation list.

Design details worth noticing:

* **Pending-driven UI**: whether to show a question bubble or style cards is determined by `pending.type`; reopening a conversation restores `pending` from `GET /conversations/{id}` so a reload shows the unanswered state (the *server* is the source of truth).
* **`busy` locks inputs** (textarea, send button, style cards) preventing double submission; the server also enforces one-turn-at-a-time (409).
* **Progress as a first-class UI**: `role="status"` + `aria-live="polite"` announces step changes to screen readers; each completed step is shown as a chip with "Working on it…" last.
* **Empty state with example chips** that call `ask(example)`: onboarding for free.
* **Error display** with `role="alert"`.
* **Refs and smooth scrolling** to the newest content on every change.

### `components/OutfitCard.tsx` and the Buy button

```ts
const tab = window.open('', '_blank')      // open the tab NOW, inside the click
if (tab) tab.opener = null                 // the new page cannot access this window (reverse tabnabbing)
...
const link = await buyLink(item.product_id)           // network round trip (seconds)
if (link.link_status === 'dead') { tab?.close(); setNote('That listing seems to be gone...'); return }
if (tab) tab.location.href = link.url                  // navigate the already-open tab
```

Why open first? **Pop-up blockers only allow `window.open` during a direct user gesture**; after an `await` the gesture is gone and the tab would be blocked. So it opens a blank tab synchronously and fills in the URL once the server answers. It also handles the **notes**: out of stock, unverified link. A small, thoughtful piece of UX engineering.

Security note: the code assigns `link.url` to the tab's location after trusting the server. The server guarantees an `https` allow-listed store domain, but a **defence in depth** step would validate on the client too (`new URL(url).protocol === 'https:'`) so a compromised or buggy API could never navigate a tab to a `javascript:` or `data:` URL.

### `app/login/page.tsx`

A controlled form with `mode: 'login' | 'register'`, proper `autoComplete` attributes (`current-password` vs `new-password` help password managers), a hint "At least 10 characters" (mirroring the server's policy), disabled submit while busy or empty, safe error display, and an effect that **skips the form if a valid refresh cookie exists** (`refreshSession().then(ok => ok && router.replace('/'))`). Client-side validation is a convenience; **the server validates everything again**.

## 19.6 Security in the front end

* **XSS (cross-site scripting)**: injected script runs with your page's privileges (reads memory tokens, calls your API as the user). React **escapes text by default**; model output and product titles render as text (`{m.text}`), never as HTML. **Never use `dangerouslySetInnerHTML` with untrusted content**, and if you render Markdown from a model, sanitise (DOMPurify) and restrict links. *Model output is untrusted input: it can contain markup, links, and instructions.*
* **Token storage**: memory for the access token, HttpOnly cookie for the refresh token (Chapter 16). XSS remains dangerous even so (attackers can *use* the in-memory token while the page is open), so prevent XSS in the first place.
* **CSP (Content-Security-Policy)**: restrict script, image, connect and frame sources; strongly limits XSS impact. Not yet configured here; adding `default-src 'self'; img-src 'self' https: data:; connect-src 'self'` (tuned) is a worthwhile hardening step. Note `img-src https:` is needed because thumbnails come from retailer CDNs.
* **Third-party images** (`<img src={item.image_url}>`) are fetched directly from retailer servers: that reveals the user's IP to them and could be used for tracking. `referrerPolicy="no-referrer"` avoids sending your page URL and avoids hotlink blocks. A privacy-preserving alternative is an **image proxy** (with size limits and SSRF protection, as for `check_link`).
* **External links**: `rel="noopener noreferrer"` or `window.open` with `opener = null`.
* **Clickjacking**: API headers set `X-Frame-Options: DENY`; the web app should also send frame protection (via `frame-ancestors` CSP or headers in Caddy/Next).
* **Dependency risk**: front-end dependencies run in your users' browsers; pin, audit (`npm audit`), and minimise.
* **Secrets**: never in the bundle (`NEXT_PUBLIC_*` is public).
* **Do not trust the client**: every rule is enforced server-side again; the client is a convenience layer an attacker controls.

## 19.7 Testing the front end

* **Unit tests (Vitest)**: pure logic such as the SSE parser (`npm test -w apps/web`).
* **Type checking** (`tsc --noEmit`) catches whole bug classes cheaply.
* **Component tests** (React Testing Library): render a component, simulate clicks, assert the DOM; mock `fetch`.
* **End-to-end tests (Playwright/Cypress)**: drive a real browser through register → chat → outfits → Buy; the project did a browser E2E in Edge via Playwright during development. Run against the demo backend (`BACKEND_MODE=demo`) for determinism and zero cost.
* **Accessibility tests**: axe-core, keyboard-only walkthrough, screen reader check.
* **Visual regression** (optional): screenshot diffs.
* **Contract tests**: keep `types.ts` and the API in sync (OpenAPI-generated types, or tests that parse real responses).

## 19.8 Performance

* **Measure first**: browser DevTools Performance and Lighthouse; Core Web Vitals (LCP, INP, CLS).
* **Bundle size**: avoid heavy libraries; code-split routes (Next does this automatically); load rarely used features lazily.
* **Images**: right-size, lazy-load (`loading="lazy"`), use modern formats; `next/image` where domains are known.
* **Rendering**: avoid re-rendering huge lists on every keystroke (state placement, `React.memo` when measured), virtualise long lists.
* **Network**: caching headers, compression (Caddy compresses), HTTP/2/3, avoid waterfalls.
* **Perceived performance for AI**: **stream and show progress**, skeleton states, instant optimistic echo of the user's message.

## 19.9 UX for AI products

AI features have special UX duties. A checklist distilled from this app and from industry practice:

1. **Show progress and partial results** (streaming, step chips). Silence for 30 s looks broken.
2. **Set expectations**: say what the assistant can do (the welcome text: occasion and budget → styles → outfits).
3. **Make uncertainty visible**: the **"Colour confirmed / Colour not confirmed"** badge is honest UI. Never present guesses as facts.
4. **Show sources and let users verify**: product photos, prices, store names, links.
5. **Let users steer and recover**: free-text alternatives to cards, "New look", editable follow-ups (the planned "make it cheaper"). Provide **stop/cancel** and **retry** (stop is not built yet).
6. **Error messages that help**: "Please try again in a minute", not stack traces; distinguish *your* problem from *ours*.
7. **Guide input**: example prompts, input limits with a counter, sensible defaults.
8. **Preserve state**: reload restores the conversation and pending question.
9. **Respect privacy**: say what is stored; offer deletion; do not over-collect.
10. **Collect feedback** (thumbs, "wrong item") linked to trace ids.
11. **Accessibility and mobile** from the start.
12. **Do not over-anthropomorphise** or claim abilities the system lacks.
13. **Handle abuse and limits gracefully**: show "try again in N seconds" from `Retry-After`.

## 19.10 Alternatives and quick-prototype tools

| Tool | Use |
|---|---|
| **Vite + React** | SPA without a server framework |
| **SvelteKit, Nuxt (Vue), Remix** | other full-stack frameworks |
| **HTMX + server templates** | minimal JS, server-driven UI |
| **Streamlit, Gradio, Chainlit** | **fastest way to demo an AI idea to a customer** in pure Python; not for polished multi-user products |
| **Vercel AI SDK, assistant-ui, CopilotKit** | libraries for chat UIs, streaming hooks (`useChat`), tool-call rendering |
| **Mobile**: React Native, Flutter | native apps |

An FDE typically starts with Streamlit/Gradio/Chainlit for a same-day demo, then moves to a real front end once the workflow is validated.

## Common mistakes

* Mutating state; stale closures; effects without cleanup.
* Storing tokens in `localStorage`.
* Rendering model output as HTML.
* Putting secrets in `NEXT_PUBLIC_*`.
* Forgetting that env vars are baked in at build time.
* Letting the UI show only success states (no loading, empty, error).
* Trusting client-side validation.
* Streams that only work on localhost (proxy buffering).
* No keyboard or screen-reader support.

## Summary

* React = UI as a function of state; keep state minimal, immutable, lifted appropriately; effects synchronise with the outside world and must be idempotent (Strict Mode will test that).
* Next.js adds routing and rendering; `'use client'` components handle interactivity; `NEXT_PUBLIC_*` values are build-time and public.
* This app's client keeps the access token in memory, refreshes with an HttpOnly cookie, single-flights refreshes, retries a 401 once, parses SSE robustly, and opens tabs synchronously to defeat pop-up blockers.
* Treat model output and third-party content as untrusted in the UI; add CSP; validate URLs.
* AI UX: progress, honesty about uncertainty, sources, recovery, accessibility.

## Key terms

*DOM, event loop, component, props, state, effect, ref, Strict Mode, key, controlled input, App Router, client component, `NEXT_PUBLIC_`, SSR/CSR, hydration, XSS, CSP, reverse tabnabbing, single-flight, optimistic UI, a11y, `aria-live`.*

## Interview questions

1. Explain React state, props and effects. What is a stale closure?
2. Why does Strict Mode run effects twice in development, and how did that matter in this app?
3. Where would you store tokens in a SPA, and why?
4. How does the front end handle an expired access token?
5. What does `'use client'` do? What is hydration?
6. Why does the Buy button open a blank tab before the network call?
7. What is XSS and how does React reduce the risk? What does it not protect against?
8. How would you design the UI for a long-running AI task?

## Exercises

1. Add a "Stop" button that aborts the in-flight `fetch` with `AbortController` and tell the server the client left (what should the server do?).
2. Write React Testing Library tests for `StyleCards` and `OutfitCard` (mock `buyLink`, assert the dead-link note).
3. Add client-side URL validation before navigating the Buy tab, with a test using a `javascript:` URL.
4. Add a CSP in Next's headers config (or Caddy) and fix whatever breaks.
5. Build the same chat with Streamlit in 60 lines against the API's streaming endpoint; compare effort and limitations.
