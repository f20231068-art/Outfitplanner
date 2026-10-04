# Chapter 3. Data Structures

> **Learning objectives.** Understand complexity analysis (Big-O); know how arrays, linked lists, stacks, queues, hash tables, heaps, trees, tries and graphs work *internally*; know Python's built-ins and their costs; choose the right structure for a problem; and recognise each structure in this repo's code.
>
> **Prerequisites.** Chapter 2 (references, mutability).

A **data structure** is a way of organising data in memory so that certain operations are fast. An **algorithm** (Chapter 4) is a procedure that uses data structures to solve a problem. Interviews for entry-level FDE and software roles test both, because they reveal whether you can reason about *cost*. Production systems need the same skill: the difference between O(n) and O(1) is the difference between a rate limiter that works and one that melts under load.

---

## 3.1 Complexity analysis: counting cost

We want to compare approaches *independent of hardware*. So we count how the number of basic steps **grows with input size n**.

### Big-O notation

`O(f(n))` is an **upper bound on growth** (usually used for the worst case): the cost is at most proportional to `f(n)` for large n. We drop constants and lower-order terms: `3n² + 100n + 7` is `O(n²)`.

| Class | Name | Example | n = 1,000,000 (rough ops) |
|---|---|---|---|
| O(1) | constant | dict lookup, array index | 1 |
| O(log n) | logarithmic | binary search, balanced-tree/B-tree lookup | ~20 |
| O(n) | linear | scan a list, `x in list` | 1,000,000 |
| O(n log n) | linearithmic | good sorting (merge sort, Timsort) | ~20,000,000 |
| O(n²) | quadratic | nested loops over the same list, naive duplicate check | 10¹² (too slow) |
| O(2ⁿ) | exponential | naive subsets/recursion | impossible beyond n ≈ 40 |
| O(n!) | factorial | all permutations | impossible beyond n ≈ 12 |

Related notations: **Ω** (lower bound), **Θ** (tight bound: both). People say "Big-O" for Θ in conversation; in interviews, be precise if asked.

### Cases and amortization

* **Worst case** (guaranteed bound), **average case** (expected over random inputs: hash tables are O(1) *average* but O(n) worst case when everything collides), **best case** (rarely useful).
* **Amortized** cost averages over a *sequence* of operations. Appending to a Python list is O(1) amortized: usually it writes into spare capacity, occasionally it must allocate a bigger array and copy (O(n)), but the doubling strategy makes the average per append constant.

### Space complexity

How much *extra memory* grows with n. A hash set to detect duplicates trades O(n) space for O(n) time instead of O(n²). **Time-space trade-off** is the most common design lever (caching is exactly this).

### Practical truths

* **Constants and n matter.** For n = 20, an O(n²) loop is fine and often faster than a clever O(n log n) one. Do not optimise what is not slow. Measure first.
* **I/O dwarfs CPU.** One network call (tens to hundreds of milliseconds) costs more than millions of in-memory operations. In an AI app, the algorithmic win is usually *fewer model/search calls*, not faster loops: the repo caches searches and runs the eight searches in parallel.
* **Know the hidden cost of "innocent" operations.** `x in some_list` is O(n); `list.insert(0, x)` is O(n); string `+=` in a loop is O(n²) in the worst case (use `"".join`). `x in some_set` is O(1).

### How to analyse code

1. Identify the input size(s) (there may be several: `m` users, `n` events each).
2. Count how many times the innermost operation runs.
3. Sequential loops add; nested loops multiply; halving the problem each step gives log.
4. Recursion: write the recurrence (`T(n) = 2T(n/2) + n` is merge sort: O(n log n)).

**In this project.** `verify_product` tokenises the title and description once (`_tokens`, O(L) for text length L) and then checks `t in hay`, where `hay` is a **list**, so each membership test is O(L), making an item check O(w · L) for w wanted words. That is perfectly fine for titles of 10-30 words; if hay were a *set* the check would be O(w). The author optimised for clarity because n is tiny. *Judging when not to optimise is part of the skill.*

## 3.2 Arrays and Python lists

An **array** stores elements contiguously in memory: element i lives at `base + i × size`. That gives **O(1) random access** and great CPU cache behaviour, but inserting or deleting in the middle shifts everything after it (O(n)).

A Python `list` is a **dynamic array of references**: it stores pointers to objects (so it can hold mixed types), over-allocates capacity, and resizes (amortized O(1) append).

| Operation | Cost |
|---|---|
| `lst[i]` | O(1) |
| `lst.append(x)` | O(1) amortized |
| `lst.pop()` | O(1) |
| `lst.pop(0)`, `lst.insert(0, x)` | O(n) |
| `x in lst`, `lst.index(x)`, `lst.remove(x)` | O(n) |
| `lst[a:b]` (slice) | O(b - a) (creates a copy) |
| `lst.sort()` | O(n log n), **stable** (Timsort) |
| `len(lst)` | O(1) |

**Stable sort** means equal elements keep their original relative order. `rank_and_validate` uses it on purpose:

```python
valid.sort(key=lambda o: o.get("confidence") != "high")   # False (high) sorts before True (low)
```

Confirmed outfits float to the front **while keeping the planner's original order within each group**: "confirmed outfits first (stable)". This is the standard way to do multi-level ordering: sort by the least important key first, or use a tuple key.

`find.py` ranks with a **tuple key**: `max(verified, key=lambda p: (p.verification.confidence == "high", p.verification.score, p.price_inr))`. Python compares tuples element by element, so: confirmed first, then higher match score, then higher price. That one line is an `O(n)` scan expressing a three-level preference.

**Slicing the top k**: `plan.outfits[:need]`, `kept[:limit]`. Slices are cheap here because the lists are tiny.

**Two-dimensional arrays** (matrices) are lists of lists; remember `[[0]*3]*3` makes three references to the *same* row (the shared-reference trap again). Use `[[0]*3 for _ in range(3)]`.

## 3.3 Linked lists

A **linked list** is a chain of nodes, each holding a value and a pointer to the next (singly linked) or to both neighbours (doubly linked).

```python
class Node:
    def __init__(self, val, next=None):
        self.val, self.next = val, next
```

* Insert/delete at a *known node* is O(1) (rewire pointers); finding a node is O(n); no random access.
* Rarely the right choice in Python day to day (lists and deques are faster in practice), but **essential for interviews** and as the foundation of other structures (LRU caches, queues, adjacency lists).

Classic problems: reverse a list (iteratively with three pointers), find the middle (slow/fast pointers), **detect a cycle (Floyd's tortoise and hare)**, merge two sorted lists, remove the n-th node from the end (two pointers n apart).

**In this project: the hash chain.** The audit log (`audit.py`) is conceptually a *linked list whose pointers are hashes*: each entry stores `prev_hash`, the hash of the entry before it, and its own `hash = SHA-256(prev_hash + contents)`. A normal pointer can be rewired silently; a hash pointer cannot be changed without changing the node's own hash, which breaks the next node's pointer. **A linked list with hash pointers is a blockchain.** `verify_chain` is simply a **linear traversal** that recomputes each hash: O(n). (Chapter 22 covers Merkle trees, which let you verify one entry in O(log n).)

## 3.4 Stacks

A **stack** is **last-in, first-out (LIFO)**: `push`, `pop`, `peek`, all O(1). In Python use a `list` (`append`/`pop`).

Uses you must know:

* The **call stack** itself (function calls, recursion; Chapter 2).
* **Undo** histories; browser back button.
* **Parsing and matching**: balanced parentheses (push on open, pop on close; mismatch or leftover means invalid).
* **Depth-first search**, iteratively (an explicit stack replaces recursion, avoiding stack overflow on deep structures).
* **Monotonic stack**: "next greater element", "largest rectangle in a histogram", "daily temperatures": keep a stack whose values are monotonic, popping while the new element breaks the order. Each element is pushed and popped once, so O(n).

```python
def valid_parentheses(s: str) -> bool:
    pairs, stack = {")": "(", "]": "[", "}": "{"}, []
    for ch in s:
        if ch in pairs.values():
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack
```

## 3.5 Queues, deques and priority queues

A **queue** is **first-in, first-out (FIFO)**: `enqueue`, `dequeue`. A Python `list.pop(0)` is O(n), so use **`collections.deque`** (a doubly linked list of blocks): O(1) at both ends.

Uses: **breadth-first search**, task scheduling, buffering between a fast producer and slow consumer, and at system scale the **message queue** (Kafka, RabbitMQ, SQS, Chapter 30).

### In this project: the sliding window (a deque)

`security/throttle.py` and `mcp_server/limits.py` implement rate limiting with a deque of timestamps per key:

```python
class SlidingWindow:
    def __init__(self, limit, window_s, clock=time.time):
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key):
        now = self._clock()
        events = self._trim(key, now)          # popleft() while the oldest event is outside the window
        if len(events) >= self.limit:
            raise TooManyAttempts(...)
        events.append(now)
```

Because events arrive in time order, the *oldest* are always at the left: expired ones are popped (`popleft`, O(1)) and the new one is appended at the right (O(1)). Each timestamp is added once and removed once, so the cost per check is **O(1) amortized**. This is a **sliding window log** rate limiter: exact, but memory is O(limit) per key. (Chapter 30 compares it with token bucket, fixed window, and sliding-window counter.)

Notice `clock=time.time` as a **parameter**: a test passes a fake clock and advances time instantly. That is dependency injection applied to *time*, the most common thing that makes tests flaky.

Honest observation: `defaultdict(deque)` creates an entry for every distinct key ever seen and `_trim` empties deques but never deletes the key. With per-IP keys, memory grows slowly with the number of distinct addresses. Production would periodically delete empty entries or use Redis keys with expiry. (The FailureCounter does `pop` the key on success, so it is better behaved.)

### Priority queues and heaps

A **priority queue** always gives you the element with the highest (or lowest) priority first. The standard implementation is a **binary heap**: a complete binary tree stored in an array where each parent is ≤ its children (min-heap). Push and pop are O(log n); peek is O(1); building from n items (`heapify`) is O(n).

```python
import heapq
h = []
heapq.heappush(h, (priority, item))
priority, item = heapq.heappop(h)
heapq.nsmallest(3, data), heapq.nlargest(3, data)
```

Python's `heapq` is a **min-heap** (for a max-heap, push negated priorities). The classic use is **top-k**: keep a min-heap of size k while scanning n items: O(n log k), better than sorting everything when k is small. (This is also the shape of "return the k nearest vectors", Chapter 10.)

Other uses: scheduling (run the earliest-deadline job), **Dijkstra's shortest path**, merging k sorted lists, running medians (two heaps).

## 3.6 Hash tables: dictionaries and sets

This is the most important data structure in practice. A **hash table** maps keys to values in **O(1) average time**.

### How it works

1. A **hash function** turns a key into an integer (`hash("myntra")`).
2. The integer, taken modulo the table size, picks a **bucket** (a slot in an array).
3. Different keys can land in the same bucket: a **collision**. Two strategies:
   * **Chaining**: each bucket holds a small list of entries.
   * **Open addressing**: probe other slots until one is free. **CPython dicts use open addressing** with a perturbation scheme.
4. The **load factor** (entries ÷ slots) is kept low by **resizing** (doubling) when it grows, which keeps chains short and keeps average cost O(1). A resize is O(n) but amortized away.

Worst case, if every key collides, operations degrade to O(n). Python **randomises string hashes per process** (`PYTHONHASHSEED`) precisely so an attacker cannot craft many keys that collide (a *hash-flooding denial of service*). That is a security feature hiding in a data structure, and a good interview anecdote.

### Requirements for keys

Keys must be **hashable**: their hash must not change while in the table, so mutable containers (`list`, `dict`) cannot be keys; tuples of hashables and frozen dataclasses can. Equal keys must have equal hashes.

### Python specifics

* `dict` preserves **insertion order** (guaranteed since 3.7). Lookup/insert/delete are O(1) average.
* `set` is a hash table with keys only: O(1) membership, plus set algebra (`a & b`, `a | b`, `a - b`).
* `collections.defaultdict(factory)` creates missing values automatically (`defaultdict(deque)`, `defaultdict(int)`); `collections.Counter` counts hashables; `OrderedDict` adds `move_to_end` (handy for LRU).

### Where this repo uses hashing

* **Deduplication with a set.** In `find.py`: `used_urls = set(inp.exclude_urls)` then `hit.url in used_urls` is O(1), and `used_urls |= {top.url, bottom.url}` adds products only when an outfit is accepted. With a list, the check would be O(n) per candidate.
* **Counting.** `CreditLedger._users: defaultdict(int)` counts credits per user per day; the global total is an integer.
* **Caches.** `TTLCache._data: dict[key, (expires_at, value)]` (below).
* **Replay protection.** `ReplayGuard._seen: dict[jti -> forget_after]`: has this token id been used? One O(1) lookup per request.
* **Lookup tables.** `_CANON` in `verify.py` maps "tees"→"tshirt", "trousers"→"pant", "gray"→"grey"; sets such as `_COLORS`, `_MALE`, `_FEMALE`, `_KIDS` make `word in _COLORS` O(1). The words-intersect check `words & _KIDS` is a set operation.
* **Allow-lists as data.** `DEFAULT_ALLOWED_DOMAINS` is a tuple scanned linearly (about 20 entries; fine), but a real list of thousands of domains should be a set or a trie (suffix matching complicates it).
* **Database indexes** are hash- or tree-based structures too (Section 3.8, Chapter 17).

### Cryptographic hashes (a different thing with the same name)

A **cryptographic hash function** (SHA-256) maps any input to a fixed-size digest such that: it is deterministic; infeasible to invert; infeasible to find two inputs with the same digest (collision resistance); and a tiny input change changes the output unpredictably (avalanche). This is *not* the same function as a hash table's, though both "scatter" inputs. The audit log, token fingerprints and refresh-token storage use SHA-256 (Chapters 20 and 22). Never use a hash table hash for security.

### TTL cache (a dict plus time)

`mcp_server/cache.py` is a 25-line lesson:

```python
class TTLCache:
    def get(self, key):
        item = self._data.get(key)
        if item is None: return None
        expires_at, value = item
        if expires_at < time.monotonic():   # lazy expiry: only noticed when read
            del self._data[key]; return None
        return value

    def set(self, key, value):
        if len(self._data) >= self.max_items:       # bounded memory
            self._data.pop(next(iter(self._data)))  # evict the OLDEST INSERTED entry
        self._data[key] = (time.monotonic() + self.ttl_s, value)
```

Observe three design decisions:

1. **`time.monotonic()`, not `time.time()`**: monotonic clocks never go backwards when the system clock is adjusted (NTP, daylight changes). Use monotonic for *measuring durations*; use wall-clock time only for *timestamps people read*.
2. **Lazy expiration**: entries are deleted when read. Expired entries that are never read stay in memory until eviction. A background sweeper or Redis' `EXPIRE` solves it.
3. **Eviction policy is FIFO (first inserted, first out)**, *not* LRU: re-reading an entry does not refresh it. Policies you should know: **FIFO**, **LRU** (least recently used), **LFU** (least frequently used), **TTL** (time-based), **random**. Section 3.10 implements LRU.

## 3.7 Strings

Strings are **immutable arrays of characters** (Unicode code points in Python 3). Implications:

* Every "change" builds a new string: concatenating in a loop is O(n²); build a list and `"".join(parts)`.
* **Encoding matters**: text is Unicode; bytes are what the network and files carry (`.encode("utf-8")`). The rupee sign `₹` is one character but three bytes in UTF-8, which is why `TextDecoder(..., {stream:true})` exists (Chapter 2), and why `json.dumps(..., ensure_ascii=True)` is used when *hashing* canonical JSON in `audit.py`: it makes the byte representation unambiguous.
* **Normalisation**: `email.strip().lower()` before comparing emails; the database also has a unique index on `lower(email)`. Whenever identity depends on text, normalise *at the boundary*, once.
* **Regex** (`re`): `^[^@\s]+@[^@\s]+\.[^@\s]+$` (the email shape check), `_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")` (the W3C trace header). Danger: **ReDoS**, where a badly written regex takes exponential time on crafted input. Keep patterns simple and anchored, and bound input length (the API caps emails at 254 characters).
* **Tokenisation** in the verifier: `re.findall(r"[a-z0-9]+", text)` after lowercasing splits titles into words, dropping punctuation. `_CANON` then normalises variants. This is the same idea as the tokenisers inside language models, just much simpler (Chapter 6).

Useful string algorithms for interviews: two pointers (palindromes), sliding window (longest substring without repeats), anagram grouping with a sorted key or a counter, KMP/Rabin-Karp for substring search (know they exist), **tries** for prefixes.

## 3.8 Trees

A **tree** is a connected, acyclic graph with a root; each node has children. Terms: root, leaf, parent, depth (distance from root), height, subtree.

### Binary trees and traversals

A **binary tree** has at most two children per node. Traversals:

* **Pre-order** (node, left, right): copy a tree.
* **In-order** (left, node, right): on a **binary search tree** this visits keys in sorted order.
* **Post-order** (left, right, node): delete a tree; evaluate an expression.
* **Level-order** (breadth first, using a queue).

```python
def inorder(node):
    if node:
        yield from inorder(node.left)
        yield node.val
        yield from inorder(node.right)
```

### Binary search trees (BST)

Left subtree < node < right subtree. Search, insert and delete are O(h), where h is the height: O(log n) if **balanced**, O(n) if degenerate (inserting sorted data into a plain BST gives a linked list). **Self-balancing** trees (AVL, red-black) keep h = O(log n) with rotations; they power ordered maps in standard libraries (C++ `std::map`, Java `TreeMap`). Python has no built-in balanced tree; use `bisect` on a sorted list or `sortedcontainers`.

### B-trees and B+ trees: how databases find rows

A **B-tree** is a *wide* balanced tree (each node holds many keys, hundreds), designed so one node fits one disk page. Because the fan-out is huge, the tree is extremely shallow: finding one row among a billion takes only a handful of page reads. **PostgreSQL indexes are B-trees by default.**

In `001_init.sql`:

```sql
CREATE UNIQUE INDEX users_email_lower_idx ON users (lower(email));
CREATE INDEX conversations_user_recent_idx ON conversations (user_id, updated_at DESC);
CREATE INDEX outfit_items_product_idx ON outfit_items (product_id);
```

A comment in `repo.py` says the second one serves "this user's most recent conversations" *with no sorting needed*: a composite B-tree index ordered by `(user_id, updated_at DESC)` lets the database jump to the user's range and read the newest first. This is **index design as data-structure design**. (Chapter 17 goes deeper: index-only scans, selectivity, write cost.)

### Tries (prefix trees)

A **trie** stores strings character by character along root-to-node paths. Lookup/insert is O(length of the word), independent of how many words are stored. Uses: autocomplete, spell check, IP routing (longest prefix match), and routers in web frameworks.

```python
class Trie:
    def __init__(self): self.children, self.end = {}, False
    def insert(self, word):
        node = self
        for ch in word:
            node = node.children.setdefault(ch, Trie())
        node.end = True
    def starts_with(self, prefix):
        node = self
        for ch in prefix:
            if ch not in node.children: return False
            node = node.children[ch]
        return True
```

**In this project**, `host_allowed(host, domains)` matches `host == d or host.endswith("." + d)`. That linear scan over ~21 domains is fine; matching against thousands of domains would use a **reversed-label trie** (`com → myntra`). The *correctness* detail is instructive: `endswith("." + d)` (with the dot!) is what stops `evil-myntra.com` from matching `myntra.com`. Prefix/suffix logic is full of such off-by-one traps.

### Merkle trees

A binary tree where each leaf is the hash of a data block and each internal node is the hash of its children. The root hash commits to *all* data; a **Merkle proof** of O(log n) hashes proves one block is included. Used in Git, blockchains, certificate transparency. (Chapter 22.)

## 3.9 Graphs

A **graph** is vertices (nodes) joined by edges. Edges may be **directed** or **undirected**, **weighted** or not. Graphs model networks, dependencies, maps, social connections, and workflows.

### Representations

* **Adjacency list**: `{node: [neighbours]}`, O(V + E) space; best for sparse graphs (most real ones).
* **Adjacency matrix**: V × V grid; O(1) edge test; O(V²) space; good for dense graphs.
* **Edge list**: simple list of pairs.

```python
graph = {"gather_prefs": ["ask_user", "propose_styles"], "ask_user": ["gather_prefs"], ...}
```

### Your agent *is* a directed graph with a cycle

```python
g.add_edge(START, "gather_prefs")
g.add_conditional_edges("gather_prefs", after_gather, ["ask_user", "propose_styles"])
g.add_edge("ask_user", "gather_prefs")                      # cycle: ask, then re-check
g.add_edge("propose_styles", "wait_for_choice")
g.add_edge("wait_for_choice", "plan_outfits")
g.add_edge("plan_outfits", "find_products")
g.add_edge("find_products", "rank_and_validate")
g.add_conditional_edges("rank_and_validate", after_validate, ["plan_outfits", "respond"])   # cycle: replan
g.add_edge("respond", END)
```

Eight nodes plus `START`/`END`; **conditional edges** choose the next node from state; two **cycles** (ask-then-recheck; replan-until-four). The retry cycle is *bounded* by a counter (`MAX_RETRIES`) because an unbounded cycle in an agent is an infinite loop that spends your money. Whenever a graph has a cycle, ask: *what guarantees it terminates?*

### Traversals: BFS and DFS

* **BFS** (breadth-first, queue): visits nodes in order of distance from the start; gives the **shortest path in an unweighted graph**.
* **DFS** (depth-first, stack or recursion): explores as deep as possible first; used for cycle detection, connected components, topological sort, and backtracking.

```python
from collections import deque
def bfs(graph, start):
    seen, q = {start}, deque([start])
    while q:
        node = q.popleft()
        yield node
        for nxt in graph.get(node, []):
            if nxt not in seen:
                seen.add(nxt); q.append(nxt)
```

Always keep a `seen` set or you loop forever on cycles. Complexity O(V + E).

### DAGs and topological sort

A **directed acyclic graph** has no cycles; a **topological order** lists nodes so every edge goes forward. It is how **dependency resolution** works: Docker Compose `depends_on` (postgres and mcp must be healthy before the API starts), database migrations applied in numeric order, build systems, task schedulers. Implement with Kahn's algorithm (repeatedly remove nodes with no incoming edges) or DFS post-order. A cycle means no valid order, which is a circular dependency error.

### Shortest paths, spanning trees, union-find

* **Dijkstra** (non-negative weights, priority queue), **Bellman-Ford** (negative weights), **A\*** (Dijkstra with a heuristic), **Floyd-Warshall** (all pairs).
* **Minimum spanning tree**: Kruskal (sort edges + union-find) and Prim (heap).
* **Union-Find (Disjoint Set Union)** tracks which items are in the same group with near-O(1) operations (path compression + union by rank). Used for connected components and Kruskal.

### Graphs in AI engineering

* **Workflow/agent graphs** (LangGraph, Mastra workflows).
* **Knowledge graphs** (entities and relations) and GraphRAG.
* **Vector indexes**: HNSW (Hierarchical Navigable Small World) is a *layered proximity graph* used by vector databases for approximate nearest-neighbour search (Chapter 10).
* **Dependency graphs** of tasks, services and packages.

## 3.10 Designing with data structures: LRU cache (a classic)

A **Least-Recently-Used cache** evicts the item unused for the longest time. Requirements: `get` and `put` in O(1). The trick is **a hash map plus a doubly linked list**: the map finds a node in O(1); the list orders nodes by recency so the oldest is at the tail and a touched node can be moved to the head in O(1).

In Python the standard library does the list for you:

```python
from collections import OrderedDict

class LRU:
    def __init__(self, capacity):
        self.cap, self.d = capacity, OrderedDict()
    def get(self, key):
        if key not in self.d: return None
        self.d.move_to_end(key)             # mark as most recently used
        return self.d[key]
    def put(self, key, value):
        self.d[key] = value
        self.d.move_to_end(key)
        if len(self.d) > self.cap:
            self.d.popitem(last=False)      # evict least recently used
```

Know also `functools.lru_cache` (memoise a function) and why the project's search cache wants TTL *and* a bound: results go stale (TTL), and memory is finite (bound).

## 3.11 Other structures worth knowing

* **Ring buffer / circular queue**: fixed-size array with head/tail indices; used for logs, audio, rate counters.
* **Bloom filter**: a bit array plus several hashes answering "definitely not present" or "probably present", with no false negatives, using tiny memory. Used to avoid expensive lookups (databases, caches, "have I crawled this URL?").
* **HyperLogLog**: estimates the count of distinct items in a few kilobytes (Redis `PFCOUNT`).
* **Skip list**: layered linked lists giving O(log n) search; used by Redis sorted sets.
* **Segment tree / Fenwick tree**: range-sum or range-min queries with updates in O(log n).
* **Disjoint intervals / interval trees**: calendar and scheduling conflict problems.
* **Immutable/persistent structures**: functional programming and React state.

## 3.12 Choosing a structure

| You need... | Use | Why |
|---|---|---|
| Fast lookup by key | `dict` | O(1) average |
| "Have I seen this?" | `set` | O(1) membership |
| Count things | `Counter` / `defaultdict(int)` | O(1) per item |
| Ordered sequence, index access | `list` | O(1) index |
| Add/remove at both ends | `deque` | O(1) both ends |
| Always the smallest/largest next | `heapq` | O(log n) push/pop |
| Sorted data with binary search | sorted `list` + `bisect` | O(log n) search |
| Sliding window over time | `deque` of timestamps | evict from the left |
| Prefix queries | trie | O(length) |
| Relationships/dependencies | graph (adjacency list) | O(V+E) traversals |
| Ordered range queries at scale | B-tree index (database) | log-time, disk friendly |
| Cache with eviction | `dict` + policy (`OrderedDict` for LRU) | bounded memory |
| Group membership merging | union-find | near-constant |
| Tamper evidence | hash chain / Merkle tree | cheap verification |

## Common mistakes

* Using a list for membership tests in a loop (accidental O(n²)).
* Mutating a collection while iterating over it.
* Forgetting a `seen` set in graph traversal.
* Assuming dictionary order is meaningful across languages (it is in modern Python, not in all languages).
* Unbounded caches and rate-limit tables.
* Using a hash-table hash where a cryptographic hash is needed.
* Optimising an O(n) that runs on n = 8 while ignoring a network call in the same loop.

## Summary

* Complexity tells you how cost grows; know the table of classes and the costs of Python's built-ins.
* Dict/set (hash tables) solve most practical problems; deque for queues and windows; heap for "next best".
* B-trees underlie database indexes; tries handle prefixes; graphs model dependencies and workflows, and your agent is a directed graph with bounded cycles.
* Every in-memory structure that outside input can grow needs a bound and an eviction policy.

## Key terms

*Big-O, amortized, array, linked list, stack, queue, deque, heap, hash table, collision, load factor, B-tree, trie, graph, DAG, topological sort, BFS, DFS, union-find, LRU, TTL, Bloom filter, Merkle tree.*

## Interview questions

1. What is the time complexity of `x in list`, `x in set`, `list.append`, `list.insert(0, x)`, `dict[key]`?
2. How does a hash table handle collisions? What is the load factor?
3. Implement an LRU cache with O(1) get/put. Why a doubly linked list?
4. Why do databases use B-trees rather than binary search trees?
5. Detect a cycle in a linked list. In a directed graph.
6. Design a rate limiter's data structure for "at most 10 requests per minute per user".
7. What is a topological sort and where does it appear in tooling you use?
8. Why does the cache in this repo use `time.monotonic()`?

## Exercises

1. Implement `SlidingWindow.check` from scratch, then add a test using a fake clock proving the 11th call in a minute is refused and the 12th call 61 seconds later is allowed.
2. Add `move_to_end` behaviour to `TTLCache` to make it LRU. Write a test that distinguishes FIFO from LRU.
3. Replace `host_allowed`'s scan with a trie of reversed domain labels. Benchmark with 10,000 domains.
4. Draw the LangGraph graph as an adjacency list and run BFS from `START`. Which nodes are reachable? Which are on a cycle?
5. In `find.py`, rewrite `_best_verified`'s selection with `heapq.nlargest` and explain why `max` is better here.
