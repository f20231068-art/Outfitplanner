# Chapter 4. Algorithms and Problem Solving

> **Learning objectives.** Use a repeatable method to attack unfamiliar problems; master the core patterns (hashing, two pointers, sliding window, binary search, sorting, recursion/backtracking, graph traversal, dynamic programming, greedy, heaps); implement the classic algorithms from memory; and see real algorithms inside this repo (backoff, budget clamping, ranking, hash-chain verification, rate limiting).
>
> **Prerequisites.** Chapter 3.

Entry-level interviews for FDE and software roles usually include one or two coding rounds (often 45 minutes, one or two problems). They test whether you can **turn a vague problem into a precise one, find a workable approach, code it cleanly, and reason about its cost**, while talking. This chapter gives you the method and the toolbox. The toolbox is *patterns*: a few dozen ideas that cover the vast majority of problems.

---

## 4.1 The method: how to attack any problem

Use the same sequence every time. Say each step out loud in an interview.

1. **Restate** the problem in your own words. Confirm input and output types and sizes. ("An array of integers, up to 10⁵ elements, return indices?")
2. **Ask clarifying questions**: duplicates allowed? sorted? negative numbers? empty input? What if no answer exists? Memory constraints? Is the data streaming?
3. **Work an example by hand**, including an edge case. Often the algorithm appears when you do it manually.
4. **State a brute force** and its complexity. This is a floor, and proves you understand the problem. ("Check every pair: O(n²).")
5. **Find the bottleneck** and apply a pattern. What work is repeated? Could a hash map, sorting, or a two-pointer sweep remove it?
6. **Agree on the approach** with the interviewer *before coding*.
7. **Code it** in clear, small steps with good names. Do not write clever one-liners.
8. **Test** with your example plus edge cases (empty, one element, duplicates, large, negatives). Trace the code by hand.
9. **State time and space complexity**, and what you would change if constraints changed.

If stuck: simplify (solve a smaller version), draw it, try a different data structure, work backwards from the answer, or ask for a hint (asking is a normal, positive signal).

### Using input size to guess the target complexity

| n (max input) | Acceptable complexity | Typical technique |
|---|---|---|
| ≤ 12 | O(n!) | permutations, brute force |
| ≤ 25 | O(2ⁿ) | subsets, bitmask, backtracking |
| ≤ 500 | O(n³) | triple loops, Floyd-Warshall |
| ≤ 5,000 | O(n²) | nested loops, 2-D DP |
| ≤ 10⁵ - 10⁶ | O(n log n) or O(n) | sorting, heaps, binary search, hash maps, sliding window |
| ≥ 10⁸ | O(log n) or O(1) | math, binary search, formulas |

## 4.2 Sorting and searching

### Sorting you must be able to explain

| Algorithm | Time (avg / worst) | Space | Stable | Idea |
|---|---|---|---|---|
| Insertion sort | O(n²) / O(n²) | O(1) | yes | insert each item into the sorted prefix; great for tiny or nearly-sorted data |
| Merge sort | O(n log n) / O(n log n) | O(n) | yes | split in half, sort halves, merge |
| Quick sort | O(n log n) / O(n²) | O(log n) | no | pick a pivot, partition, recurse; random pivot avoids the worst case |
| Heap sort | O(n log n) / O(n log n) | O(1) | no | build a heap, pop repeatedly |
| Counting/radix sort | O(n + k) | O(k) | yes | not comparison-based; needs small integer keys |
| **Timsort** (Python, Java objects) | O(n log n) / O(n log n) | O(n) | yes | merge sort + insertion sort exploiting existing runs; fast on partially sorted data |

A comparison sort cannot beat Ω(n log n) in the worst case (a decision-tree argument). Merge sort:

```python
def merge_sort(a):
    if len(a) <= 1: return a
    mid = len(a) // 2
    left, right = merge_sort(a[:mid]), merge_sort(a[mid:])
    out, i, j = [], 0, 0
    while i < len(left) and j < len(right):
        if left[i] <= right[j]: out.append(left[i]); i += 1      # <= keeps it stable
        else:                   out.append(right[j]); j += 1
    return out + left[i:] + right[j:]
```

Quick select (finding the k-th smallest without a full sort) is O(n) average using the partition step.

**In practice** you call `sorted(xs, key=...)`. Know how to sort by multiple keys with a tuple and how stability lets you sort in passes (Chapter 3).

### Binary search

Search a **sorted** (or monotonic) space in O(log n) by halving. Off-by-one errors are the whole difficulty, so memorise one **template** and always use it. The "first index where the condition is true" form:

```python
def lower_bound(a, x):          # first index i with a[i] >= x (len(a) if none)
    lo, hi = 0, len(a)          # search the half-open range [lo, hi)
    while lo < hi:
        mid = (lo + hi) // 2
        if a[mid] < x: lo = mid + 1
        else:          hi = mid
    return lo
```

`bisect.bisect_left` is exactly this. Exact search = lower_bound then check `a[i] == x`.

**Binary search on the answer.** When the answer is a number and you can test "is `v` feasible?" with a *monotonic* predicate (feasible for all v ≥ some threshold), binary search the answer. Example: *ship packages within D days: minimum ship capacity?*

```python
def ship_within_days(weights, days):
    def can(cap):
        d, load = 1, 0
        for w in weights:
            if load + w > cap: d, load = d + 1, 0
            load += w
        return d <= days
    lo, hi = max(weights), sum(weights)
    while lo < hi:
        mid = (lo + hi) // 2
        if can(mid): hi = mid
        else:        lo = mid + 1
    return lo
```

Variants: rotated sorted array (decide which half is sorted), peak finding, square root, "first bad version", Koko eating bananas, split array largest sum.

## 4.3 Hashing patterns

**Idea:** trade memory for time by remembering what you have seen.

**Two Sum**: find two numbers adding to `target`. Brute force O(n²). With a map of value → index, one pass:

```python
def two_sum(nums, target):
    seen = {}
    for i, x in enumerate(nums):
        if target - x in seen:
            return [seen[target - x], i]
        seen[x] = i
```

O(n) time, O(n) space. The same shape solves: first duplicate, valid anagram (compare `Counter`s), group anagrams (key = sorted letters or a 26-tuple of counts), subarray sum equals k (prefix sums in a map), longest consecutive sequence (a set, starting only at sequence beginnings), intersection of arrays.

**Prefix sums** answer range-sum queries in O(1) after O(n) setup: `prefix[i] = sum(a[:i])`, then `sum(a[l:r]) = prefix[r] - prefix[l]`. Combined with a map: *count subarrays with sum k* (`count += seen[prefix - k]`).

**In this project:** dedupe by URL (`used_urls` set), replay detection by token id (`ReplayGuard`), per-user counters (`defaultdict(int)`), and word lookups in the verifier are all hashing patterns.

## 4.4 Two pointers and sliding window

### Two pointers

Two indices moving through a (usually **sorted**) array to avoid a nested loop.

```python
def three_sum(nums):                           # unique triplets summing to 0, O(n²)
    nums.sort(); out = []
    for i in range(len(nums) - 2):
        if i and nums[i] == nums[i-1]: continue            # skip duplicates
        lo, hi = i + 1, len(nums) - 1
        while lo < hi:
            s = nums[i] + nums[lo] + nums[hi]
            if s < 0: lo += 1
            elif s > 0: hi -= 1
            else:
                out.append([nums[i], nums[lo], nums[hi]])
                lo += 1
                while lo < hi and nums[lo] == nums[lo-1]: lo += 1
                hi -= 1
    return out
```

Related: container with most water (move the shorter wall inward), pair with a given sum in sorted data, remove duplicates in place (slow/fast pointers), palindrome check, merge two sorted arrays, linked-list middle and cycle (slow/fast).

### Sliding window

A window `[left, right]` over a sequence that grows on the right and shrinks on the left, keeping an invariant. Turns many O(n²) substring/subarray problems into O(n).

```python
def longest_unique(s):                        # longest substring without repeating characters
    last, start, best = {}, 0, 0
    for i, ch in enumerate(s):
        if ch in last and last[ch] >= start:
            start = last[ch] + 1              # shrink: move past the previous occurrence
        last[ch] = i
        best = max(best, i - start + 1)
    return best
```

Fixed-size window: max sum of k consecutive elements (add the entering element, subtract the leaving one). Variable window: smallest subarray with sum ≥ s, minimum window substring, longest repeating character replacement.

**In this project: the rate limiter *is* a sliding window.** The deque in `SlidingWindow` holds exactly the timestamps inside the last `window_s` seconds; each check drops the left edge and tests the size. The same pattern also solves "count events in the last 60 seconds".

**For AI work:** **text chunking with overlap** for retrieval is a sliding window over words or tokens:

```python
def chunk_words(words, size=200, overlap=40):
    step = size - overlap
    for i in range(0, len(words), step):
        yield words[i:i + size]
        if i + size >= len(words): break
```

Overlap prevents splitting a fact across a chunk boundary (Chapter 10).

## 4.5 Recursion, backtracking and divide and conquer

**Recursion** solves a problem by solving smaller instances of itself. Every recursive function needs a **base case** (stops) and a **recursive case** that moves *toward* the base case. Draw the **call tree**; its size tells you the complexity (Fibonacci's naive tree is O(2ⁿ) because it recomputes the same subproblems; memoisation turns it into O(n)).

```python
from functools import lru_cache
@lru_cache(maxsize=None)
def fib(n): return n if n < 2 else fib(n-1) + fib(n-2)
```

**Divide and conquer**: split, solve the parts, combine (merge sort, quicksort, binary search, closest pair, fast exponentiation `pow(x, n)` in O(log n)).

**Backtracking** explores a decision tree: *choose, explore, un-choose*. Prune branches that cannot work.

```python
def subsets(nums):
    res, path = [], []
    def go(i):
        if i == len(nums):
            res.append(path[:])               # copy! path is reused (the shared-reference trap)
            return
        go(i + 1)                             # skip nums[i]
        path.append(nums[i]); go(i + 1); path.pop()    # take nums[i], then undo
    go(0)
    return res
```

Patterns: permutations, combinations (with a start index to avoid duplicates), combination sum, N-Queens, sudoku, word search on a grid, generating parentheses, partitioning a string into palindromes. Complexity is usually exponential, so say so.

Python's recursion limit is ~1000 frames by default. For deep inputs convert to an iterative version with an explicit stack.

## 4.6 Graph and tree algorithms

### Trees

```python
def height(node):               return 0 if not node else 1 + max(height(node.left), height(node.right))
def is_valid_bst(node, lo=float("-inf"), hi=float("inf")):
    if not node: return True
    if not (lo < node.val < hi): return False
    return is_valid_bst(node.left, lo, node.val) and is_valid_bst(node.right, node.val, hi)
def lca(root, p, q):            # lowest common ancestor in a binary tree
    if not root or root is p or root is q: return root
    l, r = lca(root.left, p, q), lca(root.right, p, q)
    return root if l and r else l or r
```

Patterns: pass bounds or accumulators down; return values up; BFS by levels (process `len(queue)` nodes per level); path sums; serialise/deserialise.

### Grids as graphs

Each cell is a node with up to 4 neighbours. **Number of islands**:

```python
def num_islands(grid):
    if not grid: return 0
    rows, cols, count = len(grid), len(grid[0]), 0
    for r in range(rows):
        for c in range(cols):
            if grid[r][c] == "1":
                count += 1
                stack = [(r, c)]
                grid[r][c] = "0"                     # mark visited by sinking the land
                while stack:
                    x, y = stack.pop()
                    for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < rows and 0 <= ny < cols and grid[nx][ny] == "1":
                            grid[nx][ny] = "0"; stack.append((nx, ny))
    return count
```

Shortest path in an unweighted grid: **BFS** with a `visited` set (the first time BFS reaches a cell is the shortest). Multi-source BFS (rotting oranges): start with *all* sources in the queue.

### Topological sort (dependency order)

```python
from collections import deque
def course_order(n, prereqs):                  # prereqs: [(course, requires)]
    adj = [[] for _ in range(n)]; indeg = [0] * n
    for a, b in prereqs: adj[b].append(a); indeg[a] += 1
    q = deque(i for i in range(n) if indeg[i] == 0); order = []
    while q:
        u = q.popleft(); order.append(u)
        for v in adj[u]:
            indeg[v] -= 1
            if indeg[v] == 0: q.append(v)
    return order if len(order) == n else []     # a leftover node means a cycle
```

### Shortest paths: Dijkstra

```python
import heapq
def dijkstra(adj, src):                         # adj[u] = [(v, weight >= 0)]
    dist = {src: 0}; heap = [(0, src)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist.get(u, float("inf")): continue        # stale entry
        for v, w in adj.get(u, []):
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd; heapq.heappush(heap, (nd, v))
    return dist
```

O((V + E) log V). Fails with negative weights (use Bellman-Ford).

### Union-find

```python
class DSU:
    def __init__(self, n): self.p = list(range(n)); self.r = [0] * n
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]       # path compression (halving)
            x = self.p[x]
        return x
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb: return False
        if self.r[ra] < self.r[rb]: ra, rb = rb, ra
        self.p[rb] = ra
        if self.r[ra] == self.r[rb]: self.r[ra] += 1
        return True
```

Uses: number of connected components, detect a cycle in an undirected graph, Kruskal's MST, "accounts merge".

## 4.7 Dynamic programming

**DP** solves problems with **overlapping subproblems** and **optimal substructure** by storing sub-answers. If brute-force recursion recomputes the same states, think DP.

### The five-step recipe

1. **Define the state**: what does `dp[i]` (or `dp[i][j]`) *mean*, in a sentence?
2. **Write the transition**: how does a state depend on smaller states?
3. **Set the base cases.**
4. **Choose the order** so dependencies are computed first (or use memoised recursion).
5. **Extract the answer**; then optimise space if possible.

Two implementations: **top-down** (recursion + memo; easy to write from the recurrence) and **bottom-up** (a table; faster, no recursion limit).

```python
def coin_change(coins, amount):               # fewest coins to make `amount`; -1 if impossible
    INF = amount + 1
    dp = [0] + [INF] * amount                 # dp[a] = fewest coins for amount a
    for a in range(1, amount + 1):
        for c in coins:
            if c <= a: dp[a] = min(dp[a], dp[a - c] + 1)
    return -1 if dp[amount] >= INF else dp[amount]

def max_subarray(a):                          # Kadane: best sum of a contiguous subarray
    best = cur = a[0]
    for x in a[1:]:
        cur = max(x, cur + x)                 # extend the run, or start fresh at x
        best = max(best, cur)
    return best

def climb_stairs(n):                          # 1 or 2 steps at a time
    a, b = 1, 1
    for _ in range(n - 1): a, b = b, a + b
    return b

def rob(houses):                              # house robber: no two adjacent
    take = skip = 0
    for h in houses: take, skip = skip + h, max(take, skip)
    return max(take, skip)

import bisect
def lis(a):                                   # longest increasing subsequence in O(n log n)
    tails = []                                # tails[k] = smallest tail of an increasing run of length k+1
    for x in a:
        i = bisect.bisect_left(tails, x)
        if i == len(tails): tails.append(x)
        else: tails[i] = x
    return len(tails)

def edit_distance(a, b):                      # Levenshtein: insert, delete, replace
    n = len(b); dp = list(range(n + 1))       # dp[j] = distance between a[:i] and b[:j] (rolling row)
    for i in range(1, len(a) + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, n + 1):
            cur = dp[j]
            dp[j] = prev if a[i-1] == b[j-1] else 1 + min(prev, dp[j], dp[j-1])
            prev = cur
    return dp[n]
```

Families to recognise: **1-D** (stairs, robber, jump game), **knapsack** (0/1: iterate capacity downward; unbounded: upward; subset sum, partition equal subset), **sequences** (LIS, LCS, edit distance), **grids** (unique paths, min path sum), **intervals** (burst balloons), **strings** (word break, palindromic substrings), **bitmask DP** for small n. *Edit distance is also how fuzzy matching and spell correction work, and is a baseline metric for comparing strings in evaluations.*

## 4.8 Greedy algorithms

A **greedy** algorithm makes the locally best choice at each step and never revisits it. It is correct only when a *greedy-choice property* holds (prove it with an **exchange argument**: any optimal solution can be transformed to include the greedy choice).

* **Interval scheduling:** sort by *end time*, take each interval that starts after the last chosen one ends (maximum number of non-overlapping meetings).
* **Merge intervals:** sort by start; extend or start a new interval.

```python
def merge_intervals(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]: out[-1][1] = max(out[-1][1], e)
        else: out.append([s, e])
    return out
```

* **Jump game, gas station, assign cookies, task scheduler, Huffman coding, activity selection.**
* Counter-example to remember: **coin change with arbitrary coins** is *not* greedy-solvable (coins {1,3,4}, amount 6: greedy gives 4+1+1, optimal is 3+3). That is why it needs DP.

**In this project:** `find.py` picks the best verified product per slot greedily by `(confidence, score, price)`, and outfits are filled **in order**: `used_urls` is reserved only for outfits that were accepted, so earlier outfits get first choice. That is an intentionally *simple greedy* approach to a hard assignment problem (assigning distinct products to four outfits to maximise overall quality, which could be solved optimally as a bipartite matching). The simplicity is a conscious trade: matching optimality is irrelevant when the downstream filter (verification) matters far more.

## 4.9 Heaps and top-k patterns

* **K-th largest**: min-heap of size k; the root is the answer. O(n log k).
* **Top k frequent**: `Counter(nums).most_common(k)` (heap-based) or bucket sort by frequency in O(n).
* **Merge k sorted lists**: heap of (value, list index).

```python
import heapq
def merge_k_sorted(lists):
    heap = [(l[0], i, 0) for i, l in enumerate(lists) if l]
    heapq.heapify(heap); out = []
    while heap:
        val, i, j = heapq.heappop(heap)
        out.append(val)
        if j + 1 < len(lists[i]): heapq.heappush(heap, (lists[i][j+1], i, j + 1))
    return out
```

* **Running median**: a max-heap for the lower half and a min-heap for the upper half.

**For AI work:** *top-k nearest vectors* is a heap problem: score every document against the query vector and keep the k best.

```python
import heapq, math
def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x*x for x in a)) * math.sqrt(sum(y*y for y in b)) + 1e-12)

def top_k(query_vec, docs, k=5):                       # docs: [(id, vec)]
    return heapq.nlargest(k, docs, key=lambda d: cosine(query_vec, d[1]))
```

That is O(N · d) per query for N documents of dimension d: fine for thousands, hopeless for hundreds of millions, which is why vector databases build **approximate** indexes (Chapter 10).

## 4.10 Stack patterns

* **Monotonic stack** ("next greater element", "daily temperatures"):

```python
def daily_temperatures(t):
    ans, stack = [0] * len(t), []                  # stack of indices with decreasing temperatures
    for i, x in enumerate(t):
        while stack and t[stack[-1]] < x:
            j = stack.pop(); ans[j] = i - j
        stack.append(i)
    return ans
```

* **Expression evaluation** (two stacks, or the shunting-yard algorithm), **min stack** (store `(value, current_min)`), **decode string** (`3[a2[c]]`), **largest rectangle in histogram**.

## 4.11 Linked-list patterns

```python
def reverse(head):
    prev = None
    while head:
        head.next, prev, head = prev, head, head.next
    return prev

def has_cycle(head):                              # Floyd
    slow = fast = head
    while fast and fast.next:
        slow, fast = slow.next, fast.next.next
        if slow is fast: return True
    return False
```

Also: merge two sorted lists (dummy head node), remove n-th from end (two pointers n apart), reorder list (find middle, reverse second half, interleave), copy list with random pointer (hash map old→new). A **dummy head** removes special cases for the first node.

## 4.12 Bit manipulation and math

* `x & 1` (odd), `x >> 1` (halve), `x & (x-1)` clears the lowest set bit (counts set bits, power-of-two test: `x > 0 and x & (x-1) == 0`).
* **XOR** tricks: `a ^ a = 0`, so the single number appearing once among pairs is the XOR of all. Swap without temp.
* **GCD** by Euclid: `while b: a, b = b, a % b`. **Sieve of Eratosthenes** for primes up to n in O(n log log n). **Fast exponentiation** (square-and-multiply) in O(log n); `pow(a, b, mod)` in Python does modular exponentiation (the core of RSA, Chapter 20).
* **Modular arithmetic** for large answers (`% (10**9 + 7)`).
* **Reservoir sampling** picks k items uniformly from a stream of unknown length in O(1) memory.

## 4.13 Algorithms that live inside this repo

Reading real code with algorithmic eyes is the best practice. Each of these is small enough to understand completely.

### 1. Budget clamping: proportional scaling (`agent/graph.py::clamp_to_budget`)

The model proposes per-item price caps, and the code guarantees the **sum** never exceeds the budget:

```python
total = spec.top.max_price_inr + spec.bottom.max_price_inr
if total <= budget: return spec
scale = budget / total
top    = int(spec.top.max_price_inr * scale)
bottom = int(spec.bottom.max_price_inr * scale)
```

Why it is correct: `int()` truncates toward zero, so `floor(a·s) + floor(b·s) ≤ (a + b)·s = total · (budget/total) = budget`. The caps shrink *proportionally* (keeping the model's intended top/bottom ratio) and the total is at most the budget, losing at most a couple of rupees to truncation. A proof in one line is what interviewers love to hear. (The guarantee is *per spec*; `find.py` additionally requires the **actual** product prices to sum within budget.)

### 2. Exponential backoff with jitter (`mcp_server/net.py::get_json`)

```python
await asyncio.sleep(base_delay * (2 ** attempt) + random.uniform(0, 0.25))
```

Waits 0.5 s, 1 s, 2 s... plus a random 0-0.25 s. **Why exponential?** If a server is overloaded, retrying immediately makes it worse; backing off gives it room. **Why jitter?** If 1,000 clients fail simultaneously and all retry after exactly 1 s, they stampede together again (a *thundering herd*). Randomisation spreads them. The widely recommended "full jitter" variant sleeps `random.uniform(0, min(cap, base · 2^attempt))`. The code also honours a server's `Retry-After` header (capped at 10 s) when one is given. The decision tree is itself an algorithm: *retry 429 and 5xx and transport errors; fail immediately on other 4xx.*

### 3. The verifier: set containment and ranking (`agent/verify.py`)

`_check_item` tokenises the wanted item and the product's title into word lists and checks `missing = [t for t in wanted if t not in hay]`: a **subset test** ("are all wanted words present?"). If some are missing but the garment noun is present, the result is `unknown + assumed` (low confidence). `_contains_phrase(hay, phrase)` is a naive **substring search over token lists**: for each start position compare a slice, O(n·m), perfectly fine at this size (KMP would be overkill).

`_check_color` is a small decision procedure with *priority*: stated field → title/description → contradiction by another colour word → assumed. Order matters; each rung is more speculative than the one above it. Designing such **evidence hierarchies** is a recurring skill in AI quality systems.

### 4. Verifying a hash chain: O(n) linear scan (`audit.py::verify_chain`)

For each row in order: check `prev_hash == previous row's hash`, recompute `hash` from `(ts, actor, action, details, prev)`, compare. Stop at the first mismatch and report its id. The docstring notes the scalability answer: "for a very large log you would verify in slices and remember a checkpoint". (An incremental verifier stores the last verified hash and id and resumes from there.)

### 5. Canonical serialisation (`audit.py::_canonical`, `chain.ts::canonicalize`)

To hash a JSON object reproducibly, the byte string must be identical every time: sorted keys, no spaces, fixed encoding. The Python version uses `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=True)`; the TypeScript version implements recursive key sorting by hand, because `JSON.stringify` does not sort keys. **Both languages must produce the same canonical form for cross-checks to work**: this is a general lesson for signatures, hashes, caching keys and deduplication.

### 6. Loop termination in the agent

`after_validate` decides whether to replan: `len(outfits) >= OUTFITS_WANTED or retries > MAX_RETRIES` → respond. Combined with `MODEL_ATTEMPTS = 3` for malformed outputs and `ATTEMPTS = 2` for search, every loop has an explicit **bound**. With LLMs in a loop, **a hard iteration cap is not optional**: the budget (money, time, rate limits) is finite, and models can fail to converge.

### 7. Search query construction (`tools/search_products.py::build_query`)

```python
words = []
for part in ("men", color, fit or "", fabric or "", item):
    for w in part.lower().split():
        if w not in words: words.append(w)
```

Ordered deduplication ("olive green oversized cotton t-shirt" never repeats "t-shirt"). With ≤ 10 words a list is fine; with many, you would keep a `seen` set *and* an output list to preserve order and get O(1) checks.

## 4.14 AI-flavoured problems an FDE should be ready for

You will sometimes get "practical" problems, closer to real work than puzzles. Practise these:

1. **Chunk a long document** into overlapping pieces respecting sentence boundaries (sliding window plus boundary snapping).
2. **Top-k similar items** from vectors (heap), then discuss why exact search stops scaling.
3. **Rate limiter** (sliding window, token bucket): implement `allow(user)` and discuss distributed correctness.
4. **Retry with exponential backoff and jitter** for a flaky API; make it idempotent-aware.
5. **Parse a streaming response** (SSE/JSON lines) robustly with buffering.
6. **Deduplicate near-identical records** (normalise, hash, MinHash/Jaccard for fuzzy).
7. **Merge overlapping time intervals** / find free slots (calendar problems).
8. **Log analysis**: count errors per minute, p95 latency (sort or heap or a histogram; percentiles).
9. **Validate and repair JSON from an LLM** (strip code fences, balance braces, fall back to re-asking).
10. **Cost estimator**: given token counts and prices, project the monthly cost of a feature (Chapter 14).

### Token bucket (a rate limiter you should be able to write)

```python
import time
class TokenBucket:
    def __init__(self, rate_per_s, capacity, clock=time.monotonic):
        self.rate, self.cap, self.clock = rate_per_s, capacity, clock
        self.tokens, self.last = capacity, clock()
    def allow(self, cost=1):
        now = self.clock()
        self.tokens = min(self.cap, self.tokens + (now - self.last) * self.rate)   # refill lazily
        self.last = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False
```

O(1) time and memory per key, allows bursts up to `capacity`, then enforces the long-run `rate`. Compare to the repo's sliding window log (exact, O(limit) memory per key).

## 4.15 A practice plan and how to talk during interviews

**Volume that works**: about 100-150 well-chosen problems, done *with review*, beat 500 skimmed ones. Cover each pattern in this chapter with 5-10 problems: arrays/hashing, two pointers, sliding window, stack, binary search, linked list, trees, heap, backtracking, graphs, 1-D and 2-D DP, greedy, intervals, bit manipulation. Re-solve missed problems after a week and again after a month (spaced repetition).

**Session routine (60-90 minutes)**: 25 minutes alone on one problem; 5 minutes to write complexity; then read a solution, *close it*, and re-implement from memory; finally write a 2-line note ("pattern: sliding window; trap: shrink condition").

**Talking**: narrate your reasoning, state assumptions, name the pattern ("this looks like sliding window because the answer is a contiguous range"), write readable code, test aloud, and end with complexity. A correct but silent solution scores lower than a nearly correct, well-communicated one. If you are stuck, say what you have tried and ask a targeted question.

## Common mistakes

* Jumping to code before a clear example and approach.
* Off-by-one errors in binary search and sliding windows; use one template.
* Forgetting empty input, single element, duplicates, negatives, overflow (not an issue in Python, but mention it for fixed-width ints in other languages).
* Mutating shared state during backtracking without copying (`res.append(path)` instead of `path[:]`).
* Missing a `visited` set in graph search.
* Claiming greedy where DP is needed.

## Summary

* A method (restate, examples, brute force, pattern, code, test, complexity) beats inspiration.
* A few dozen patterns solve most problems; learn their recognition cues.
* Input size tells you the target complexity.
* This repo contains real algorithms: proportional clamping, backoff with jitter, evidence-ranked verification, sliding-window limiting, hash-chain verification, canonical serialisation, bounded retries.

## Key terms

*Big-O, pattern, brute force, two pointers, sliding window, prefix sum, binary search, backtracking, memoisation, dynamic programming, greedy, topological sort, Dijkstra, union-find, monotonic stack, top-k, backoff, jitter.*

## Interview questions

1. Find two numbers in an array that sum to a target. Then do it in a sorted array with O(1) space.
2. Longest substring without repeating characters.
3. Merge overlapping intervals.
4. Number of islands (BFS and DFS versions).
5. Course schedule: can all courses be finished? What order?
6. Coin change: fewest coins; why does greedy fail?
7. Kth largest element: heap vs quickselect trade-offs.
8. Implement a rate limiter. Discuss fixed window vs sliding window vs token bucket.
9. Design and implement an LRU cache.
10. Explain exponential backoff and why jitter matters.

## Exercises

1. Implement all of 4.2-4.11's code from memory in a scratch file, with tests. Do not look.
2. Write a property test (Hypothesis) that `clamp_to_budget` never returns specs whose caps sum above the budget for random inputs.
3. Implement a *full-jitter* variant of `get_json`'s sleep and compare retry timing distributions in a simulation with 1,000 clients.
4. Write an incremental audit-chain verifier that resumes from the last verified `(id, hash)`.
5. Solve "assign 4 outfits their best distinct products" optimally with the Hungarian algorithm (or min-cost matching) and compare with the greedy result on mock data. Is the difference ever visible to a user?
