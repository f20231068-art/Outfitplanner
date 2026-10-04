# Chapter 5. Math, Probability and Statistics for AI Engineers

> **Learning objectives.** Understand vectors and similarity (the basis of embeddings and retrieval), the probability behind language-model outputs (softmax, temperature, entropy, perplexity), and the statistics you need to *trust* an evaluation (percentiles, confidence intervals, sample size, variance). Do capacity and cost arithmetic confidently.
>
> **Prerequisites.** High-school algebra. Chapter 3 helps.

You do not need to derive backpropagation to be a strong AI **application** engineer. You do need *working fluency* with a small set of ideas, because they show up in every design discussion: "how similar are these two texts?", "what does temperature do?", "is 13 out of 13 passing good enough to ship?", "what is our p95 latency?", "how many concurrent users can one server handle?"

---

## 5.1 Vectors: the language of embeddings

A **vector** is an ordered list of numbers, `v = [v₁, v₂, ..., v_d]`. Geometrically it is a point (or an arrow from the origin) in d-dimensional space. A text **embedding** (Chapter 6, 10) is a vector of, say, 768 or 1536 numbers produced by a model such that *texts with similar meaning land near each other*.

### Operations

* **Addition and scaling**: element-wise. `[1,2] + [3,4] = [4,6]`; `2·[1,2] = [2,4]`.
* **Dot product**: `a · b = Σ aᵢ bᵢ`. A single number. It is large when the vectors point in the same direction.
* **Norm (length)**: `‖a‖ = √(a · a)` (Euclidean/L2).
* **Cosine similarity**: `cos(a, b) = (a · b) / (‖a‖ ‖b‖)`, ranging from -1 (opposite) through 0 (unrelated/orthogonal) to 1 (same direction). It ignores *magnitude* and compares *direction*, which is what you usually want for text meaning.
* **Euclidean distance**: `‖a - b‖`. Smaller is closer.
* **Normalised (unit) vectors** have length 1; for them, dot product *equals* cosine similarity, and Euclidean distance is a monotonic function of it. Many embedding APIs return normalised vectors so a plain dot product suffices (faster).

```python
import math
def dot(a, b):  return sum(x * y for x, y in zip(a, b))
def norm(a):    return math.sqrt(dot(a, a))
def cosine(a, b): return dot(a, b) / (norm(a) * norm(b) + 1e-12)   # epsilon avoids dividing by zero
```

**Worked example.** `a = [1, 2, 3]`, `b = [2, 4, 6]` (same direction, double length): `a·b = 28`, `‖a‖ = √14`, `‖b‖ = √56`; cosine = 28 / (√14 · √56) = 28/28 = **1.0**. Euclidean distance is √14 ≈ 3.74 (not zero), so *cosine and distance disagree about "same"*; choose based on whether magnitude carries meaning.

### Matrices and why GPUs matter

A **matrix** is a 2-D grid of numbers. **Matrix multiplication** `C = A · B` computes dot products of A's rows with B's columns: `C[i][j] = Σₖ A[i][k]·B[k][j]`. A neural network layer is (roughly) `output = activation(W · input + b)`. A transformer is a large stack of matrix multiplications, which is why **GPUs** (thousands of simple cores doing the same multiply-add in parallel) accelerate it. The cost of generating text is dominated by multiplying huge matrices, so *cost scales with parameters × tokens* (Chapter 14).

### High-dimensional intuition (and its traps)

* In high dimensions, **random vectors are almost orthogonal** and **distances between points concentrate** (the "curse of dimensionality"): the nearest and farthest neighbours become similar in distance. This is why *exact* nearest-neighbour search degrades and why embedding models are trained specifically to make useful structure appear.
* Similarity scores are **not calibrated probabilities**. A cosine of 0.82 means different things for different models and domains. Set thresholds empirically using *your* data, with an evaluation set.
* Embeddings from **different models are not comparable.** Never mix vectors from two models in one index; re-embed everything if you switch.

### Approximate nearest-neighbour (ANN) in one paragraph

Comparing a query to all N stored vectors costs O(N·d). ANN indexes trade a little accuracy for large speedups: **HNSW** (a layered proximity graph; greedy search from a coarse layer down), **IVF** (cluster the vectors, search only the nearest clusters), **product quantisation** (compress vectors). Vector databases (and Postgres `pgvector`) implement these (Chapter 10). Measure **recall@k**: what fraction of the true top-k does the ANN index return?

## 5.2 Probability essentials

### Basics

* A **probability** P(A) ∈ [0, 1]. Probabilities of mutually exclusive, exhaustive outcomes sum to 1.
* **Independence**: `P(A and B) = P(A)·P(B)`.
* **Conditional probability**: `P(A | B) = P(A and B) / P(B)`.
* **Bayes' theorem**: `P(A | B) = P(B | A)·P(A) / P(B)`. It underlies spam filters, medical-test reasoning, and *thinking about base rates*.

**Base-rate example (a classic interview/real-life trap).** A hallucination detector flags 90% of hallucinated answers (sensitivity) and wrongly flags 5% of correct ones (false-positive rate). Suppose only 2% of answers are hallucinations. If it flags an answer, what is the chance the answer is truly a hallucination?

`P(H | flag) = 0.9·0.02 / (0.9·0.02 + 0.05·0.98) = 0.018 / (0.018 + 0.049) ≈ 0.27`.

Only 27%: most flags are false alarms because real hallucinations are rare. *Always ask what the base rate is.* (This also drives how you set alert thresholds for monitoring.)

### Random variables, expectation, variance

A **random variable** takes values with probabilities. The **expected value** `E[X] = Σ x·P(x)` is the long-run average; the **variance** `Var(X) = E[(X - E[X])²]` and **standard deviation** `σ = √Var` measure spread.

Practical identity: **expectation is linear** (`E[aX + bY] = aE[X] + bE[Y]`, even if dependent). Use it for cost estimates: *expected cost per conversation = Σ (cost of each step × probability it runs)*. In this app a replan loop runs with some probability p, adding one model call each time; expected calls ≈ base + p·(extra).

### Distributions you will meet

* **Bernoulli / Binomial**: a yes/no trial; the number of successes in n independent trials (`k` passing eval cases of `n`).
* **Normal (Gaussian)**: the bell curve; sums of many small effects (the central limit theorem). 68% of values within 1σ, 95% within 2σ, 99.7% within 3σ.
* **Poisson**: counts of rare independent events per interval (requests per second, errors per hour).
* **Exponential**: waiting time between Poisson events.
* **Heavy-tailed (log-normal, power-law)**: a few huge values dominate. **Latency, response sizes, token counts and user activity are heavy-tailed.** That is why you report **percentiles, not averages** (Section 5.4).

## 5.3 Probability inside a language model

### Logits, softmax, sampling

A language model (Chapter 6) outputs, at each step, a vector of raw scores called **logits** `z`, one per token in its vocabulary (tens to hundreds of thousands). **Softmax** converts them to a probability distribution:

`p_i = exp(z_i / T) / Σ_j exp(z_j / T)`

where **T is the temperature**.

```python
import math
def softmax(logits, T=1.0):
    m = max(logits)                                    # subtract the max for numerical stability
    exps = [math.exp((z - m) / T) for z in logits]
    s = sum(exps)
    return [e / s for e in exps]

softmax([2.0, 1.0, 0.1], T=1.0)   # [0.66, 0.24, 0.10]
softmax([2.0, 1.0, 0.1], T=0.2)   # [0.99, 0.01, 0.00]   sharper: nearly always the top token
softmax([2.0, 1.0, 0.1], T=5.0)   # [0.40, 0.33, 0.27]   flatter: closer to uniform
```

* **T → 0**: always pick the most likely token (greedy, near-deterministic). **T = 1**: sample from the model's raw distribution. **T > 1**: more random.
* **Top-k** sampling keeps only the k most likely tokens; **top-p (nucleus)** keeps the smallest set whose cumulative probability ≥ p. Then renormalise and sample.
* **Why "temperature 0" is still not perfectly deterministic** in hosted models: floating-point non-associativity across GPU kernels and batching, and provider-side changes, mean identical prompts can produce slightly different outputs. *Design your evaluations and tests for non-determinism* (Chapter 12).

### Entropy, cross-entropy, perplexity

* **Entropy** `H(p) = -Σ pᵢ log₂ pᵢ` measures uncertainty in bits: 0 for a certain outcome, 1 bit for a fair coin, `log₂ N` for a uniform choice among N.
* **Cross-entropy loss** is how models are trained: `-log p(correct token)`, averaged over the training data. Lower means the model assigned higher probability to the true text.
* **Perplexity** `= exp(average cross-entropy)`: "the effective number of equally likely choices per token". A model with perplexity 10 is as uncertain as picking among 10 equally likely tokens. It is a quality metric for *language modelling*, not directly for task success.
* **KL divergence** `D(p‖q) = Σ pᵢ log(pᵢ/qᵢ)` measures how one distribution differs from another; it appears in fine-tuning objectives (RLHF keeps the tuned model close to the original).

### Log-probabilities

APIs sometimes return **log-probs** of generated tokens. Uses: confidence signals (a low probability on the answer token), classification via the probability of label tokens, and detecting where a model was unsure. Multiply probabilities of a sequence by *adding* logs (avoids numerical underflow).

## 5.4 Statistics for engineers: measuring honestly

### Summarising data: mean, median, percentiles

* **Mean** is sensitive to outliers; **median (p50)** is not. For heavy-tailed data (latency, cost per request) the mean can badly mislead.
* **Percentile p95** is the value below which 95% of observations fall; **p99** for the tail. "p95 latency is 40 s" means 1 in 20 users waits at least that long.
* **Never average percentiles** across servers or time windows; aggregate the underlying histograms.

```python
def percentile(values, p):                      # nearest-rank method
    xs = sorted(values)
    k = max(0, min(len(xs) - 1, math.ceil(p / 100 * len(xs)) - 1))
    return xs[k]
```

**In this project.** `HTTP_SECONDS` and `CHAT_TURN_SECONDS` in `telemetry.py` are Prometheus **histograms**: counters per latency **bucket** (`le="1"`, `le="2.5"`, ...). Prometheus estimates a percentile with `histogram_quantile(0.95, ...)` by *interpolating inside a bucket*, so accuracy depends on **bucket boundaries**. The chat-turn buckets `(1, 2.5, 5, 10, 20, 30, 45, 60, 90, 120, 180)` were chosen around a task that takes tens of seconds; the same buckets on a 5 ms endpoint would put everything in the first bucket and tell you nothing. *Choose histogram buckets around the values you care about.*

### Averages hide failures: SLIs and SLOs

An **SLI** (service level indicator) is a measured quantity (fraction of chat turns that finish without error; p95 turn time). An **SLO** (objective) is a target ("99% of turns succeed over 30 days"). The gap, `1 - SLO`, is the **error budget** you may spend on risk and releases (Chapter 28).

### Sampling and uncertainty

You almost never measure *everything*; you measure a **sample** and infer. The key discipline: **a number from a small sample is a wide range, not a point.**

**Confidence interval for a proportion.** If `k` of `n` eval cases pass, the observed rate is `p̂ = k/n`, but the *true* rate could be quite different. The **Wilson score interval** (better than the naive normal approximation for small n or extreme p̂):

```python
def wilson(k, n, z=1.96):                       # 95% by default
    if n == 0: return (0.0, 1.0)
    p = k / n
    denom = 1 + z*z/n
    centre = (p + z*z/(2*n)) / denom
    half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / denom
    return (max(0, centre - half), min(1, centre + half))

wilson(13, 13)   # (0.77, 1.00): 13/13 passing is consistent with a true pass rate as low as 77%
wilson(130, 130) # (0.97, 1.00)
```

**This project's eval set has 13 cases.** "All 13 passed" does **not** mean the system is right 100% of the time; with 95% confidence it only tells you the true pass rate is probably above ~77%. The **rule of three** gives the same intuition: with **zero** failures in n trials, the 95% upper bound on the failure rate is about `3/n` (here ≈ 23%). To claim "at most 1% failures" you need roughly 300 clean trials. *This is exactly the kind of statement an FDE must make honestly to a customer.* (Also: the project's evals test **guarantees of the pipeline in demo mode**, which a scripted model passes by construction; they do not measure the real model, as `docs/observability.md` says plainly.)

**Sample size to detect a difference.** To distinguish pass rates of 80% vs 90% with decent confidence you need on the order of a couple of hundred cases per variant; for 90% vs 92%, thousands. Small improvements need large samples. Beware **overfitting your prompts to a small eval set**: if you tune until the 13 cases pass, you have measured memorisation. Keep a **held-out** set you do not tune on.

**Bootstrap.** When you have no formula, resample your data with replacement thousands of times, recompute the statistic each time, and take the 2.5th/97.5th percentiles:

```python
import random
def bootstrap_ci(xs, stat=lambda a: sum(a)/len(a), n=2000, alpha=0.05):
    stats = sorted(stat([random.choice(xs) for _ in xs]) for _ in range(n))
    return stats[int(n*alpha/2)], stats[int(n*(1-alpha/2)) - 1]
```

### Comparing two systems (A/B tests and prompt changes)

* **Null hypothesis** "no difference"; a **p-value** is the probability of seeing a difference at least this large *if* the null were true. It is **not** "the probability the prompt is better".
* **Statistical vs practical significance**: a tiny effect can be significant with huge n and still be worthless.
* **Multiple comparisons**: test 20 prompt variants and one will look "significant" by luck. Correct (Bonferroni) or hold out a confirmation set.
* **Paired comparison**: when the same cases are run through both variants, compare *per-case differences* (sign test, paired bootstrap); it removes case-difficulty noise and needs far fewer cases.
* **Randomise and avoid leakage**: do not tune on the test set; do not let an LLM judge see which variant is which.

### Variance from non-determinism

LLM outputs vary run to run. Run each eval case **several times** and report the mean and spread; flaky evals erode trust. A deterministic scorer on a non-deterministic system still gives noisy results. For a pass/fail gate, require the *rate* over repeats to exceed a threshold, not a single run.

### Classification metrics (for judges, classifiers, guardrails)

For a binary decision with true/false positives (TP, FP) and negatives (TN, FN):

* **Precision** = TP / (TP + FP): of what I flagged, how much was right?
* **Recall** = TP / (TP + FN): of what was really there, how much did I flag?
* **F1** = 2PR / (P + R): harmonic mean. **Accuracy** misleads on imbalanced data (flag nothing and get 98% accuracy when 2% are positive).
* **Threshold trade-off**: lowering a threshold raises recall and lowers precision. Pick the point by **cost**: a missed fraud costs more than a false alarm; a verifier that wrongly rejects good products costs a little (fewer outfits), whereas one that wrongly *accepts* a women's item breaks the product promise. This is why `verify_product` is deliberately strict on `price`, `item`, `colour`, and why unconfirmed colours are *kept but labelled* rather than silently accepted or rejected.
* **LLM-as-judge agreement**: when a model grades outputs, measure agreement with humans on a sample using **Cohen's κ** (agreement corrected for chance) before trusting it at scale.
* **pass@k** (code generation): probability that at least one of k samples passes.

## 5.5 Queueing and capacity: back-of-envelope math

### Little's Law

`L = λ · W`: the average number of items in a system (L) equals the arrival rate (λ) times the average time each spends in it (W). It holds for almost any stable system and needs no assumptions about distributions.

**Worked example for this app.** A chat turn takes about 30 s and runs inside a worker thread (the endpoint is a sync `def`, Chapter 2). If 2 turns arrive per second, concurrent turns `L = 2 × 30 = 60` threads busy. Web servers typically run sync endpoints in a thread pool of limited size (Starlette/AnyIO's default is on the order of 40 threads; verify for your version), so a single API process saturates around **~1.3 turns per second** (40 ÷ 30). Beyond that, requests queue and latency explodes. Options: raise the thread limit, run more processes/containers, make the pipeline async, and reduce per-turn latency (every second saved raises capacity proportionally). This is the kind of calculation you do on a whiteboard in a system-design interview (Chapters 30-32).

### Utilisation and queueing delay

As utilisation ρ (busy fraction) approaches 1, waiting time grows without bound (roughly `ρ/(1-ρ)` for simple queues). A system at 90% utilisation has long queues; at 99% it is nearly stalled. **Keep headroom** (target 50-70% at peak) and **shed load** (rate limits, 429s, timeouts) instead of queueing forever.

### Numbers every engineer should know (order of magnitude)

| Operation | Approximate time |
|---|---|
| CPU cycle | ~0.3 ns |
| L1 cache / main memory reference | ~1 ns / ~100 ns |
| SSD random read | ~100 µs |
| Same data-centre round trip | ~0.5 ms |
| Database query (indexed, warm) | ~1-5 ms |
| Cross-continent network round trip | ~100-150 ms |
| TLS handshake (extra round trips) | tens of ms |
| LLM time to first token | ~0.3-3 s |
| LLM generation speed | ~20-150 tokens/s (varies by model/provider) |
| Web search API call | ~0.5-3 s |

The punchline: **the model call and the search call dominate** every AI-app latency budget; everything else is noise. (Measured here: first live search 0.79 s; cached 0.01 s.)

### Cost arithmetic

* **Token cost** per request = `input_tokens × input_price + output_tokens × output_price`. Output tokens usually cost several times input tokens. **Monthly cost** = requests × average cost. Work in a spreadsheet with *low / expected / high* scenarios.
* **Quota arithmetic from this project**: a free model allowing 50 requests per day and a conversation using ~6 calls gives ⌊50/6⌋ = **8 conversations per day**; the search tool's caps (10 credits per user and 25 per day globally in the hosted layout) mean *at most 25 paid searches a day in total*; with 8 searches per planning round, that is **3 planning rounds a day** across all users. Those two numbers together define what the demo can honestly promise. (Caches change this: a repeated query costs 0 credits.)
* **Cache hit rate** `h` reduces expected cost: `E[cost] = (1 - h)·cost_miss + h·cost_hit`. If misses cost 1 credit and hits 0, a 60% hit rate cuts spend by 60%.

## 5.6 Security-flavoured math (why the numbers in this repo are what they are)

* **Entropy of secrets.** The refresh token is `secrets.token_urlsafe(48)`: 48 random bytes = **384 bits**. Guessing it takes about 2³⁸³ tries on average: not feasible by any physical means. That is why the comment says "a fast hash is fine here: the input is 384 random bits, so it cannot be guessed or brute-forced". Contrast a *human password* with maybe 30-40 bits of real entropy, which needs a deliberately **slow, memory-hard hash** (Argon2id) to resist guessing from a leaked database.
* **Unique ids and collisions (birthday paradox).** After about `√(2ⁿ)` random n-bit ids, a collision becomes likely. `uuid4().hex` has 122 random bits, so you would need ~2⁶¹ ids before a collision is likely: ignore it. The same math tells you a 32-bit random id collides after only ~65,000 items (use longer ids).
* **Brute force time** = keyspace ÷ guess rate. An RSA-2048 key is not brute-forced; it is attacked via factoring, which is why *key size* and *algorithm* choices (Chapter 20) matter more than guessing.
* **Rate limits as probability**: 5 login failures per 15 minutes means an attacker gets at most ~480 guesses per account per day from one address; with a good password that is nothing (and per-IP limits stop distribution across accounts).
* **Truncated hashes**: the audit fingerprints are truncated SHA-256 (12 or 32 hex characters = 48 or 128 bits). Fine for *grouping and recognition* (a 48-bit tag for "repeated attempts on one email"), not for security guarantees.

## 5.7 Optimisation in one page (so ML vocabulary is not scary)

A model has parameters (weights) θ. A **loss function** L(θ) scores how wrong its predictions are. **Gradient descent** repeatedly nudges θ in the direction that decreases L: `θ ← θ - η ∇L(θ)`, where η is the **learning rate** and the **gradient** ∇L is the vector of partial derivatives (slopes). **Backpropagation** computes those gradients efficiently through the layers using the chain rule. **Stochastic** gradient descent uses a random mini-batch of data per step. **Overfitting** is memorising the training data (low training loss, poor on new data); **regularisation**, more data and validation sets fight it. **Pre-training** (predict the next token on huge text), **fine-tuning** (continue on a narrow task), and **RLHF/preference optimisation** (shape behaviour from human or AI preferences) are all *this loop with different data and losses* (Chapter 6).

As an application engineer you will rarely train from scratch; you will **choose** models, **prompt** them, **retrieve** context, **evaluate**, and occasionally **fine-tune**. Knowing the vocabulary lets you read papers, model cards and vendor docs critically.

## Common mistakes

* Treating cosine similarity thresholds as universal truths.
* Reporting means for latency and cost; ignoring tails.
* Declaring victory from a tiny eval set; tuning on the test set.
* Ignoring base rates when evaluating detectors and alerts.
* Comparing embeddings from different models.
* Forgetting that "temperature 0" is *nearly*, not perfectly, deterministic.
* Capacity planning without Little's Law.

## Summary

* Embeddings are vectors; similarity is a dot product or cosine; at scale you use approximate indexes.
* LLM outputs are samples from a probability distribution shaped by softmax and temperature.
* Be honest about uncertainty: confidence intervals, held-out sets, repeated runs.
* Report percentiles; reason about capacity with `L = λW`; calculate cost and quota explicitly.
* Secret sizes in this repo are chosen with explicit probability arguments.

## Key terms

*vector, dot product, cosine similarity, embedding, ANN, HNSW, softmax, temperature, top-p, entropy, perplexity, percentile, histogram, confidence interval, Wilson, bootstrap, precision, recall, F1, Little's Law, error budget, birthday bound.*

## Interview questions

1. What is cosine similarity and why use it instead of Euclidean distance for text?
2. What does temperature do mathematically? What would you set for extraction vs creative writing?
3. Our eval has 20 cases and all pass. What can you honestly say about reliability?
4. Why is p95 latency more useful than the average?
5. A classifier flags 90% of bad outputs with a 5% false-positive rate and 2% of outputs are bad. What fraction of flags are real?
6. Use Little's Law to estimate how many concurrent conversations one API process can serve.
7. Why can't you compare embeddings from two different models?

## Exercises

1. Implement `cosine`, `top_k`, and a brute-force nearest-neighbour search; time it for N = 1,000 / 100,000 random 768-d vectors using plain Python and then NumPy.
2. Compute Wilson intervals for 13/13, 12/13, 45/50, and 450/500 and plot how the interval narrows.
3. In Grafana/Prometheus (or by hand), compute p95 from a list of 1,000 sampled latencies using (a) exact percentile and (b) the histogram buckets in `telemetry.py`; compare the error.
4. Build a quota calculator: given calls per conversation, daily model quota, search credits and cache hit rate, output "conversations per day".
5. Simulate temperature: sample 10,000 tokens from `softmax([2,1,0.1], T)` for T ∈ {0.1, 0.5, 1, 2} and plot the empirical frequencies.
