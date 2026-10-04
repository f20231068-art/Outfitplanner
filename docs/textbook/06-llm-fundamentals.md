# Chapter 6. How Language Models Work

> **Learning objectives.** Explain what an LLM is and how it generates text; understand tokens, context windows, attention, training stages, and sampling; reason about why models hallucinate and what they cannot do; know the shape of a chat API call (messages, roles, usage, streaming, errors); and map all of it onto `services/api/src/api/agent/llm.py`.
>
> **Prerequisites.** Chapter 5 (vectors, softmax, probability).

You do not need to build a transformer to build products on one. You do need an accurate mental model, because every design decision in Part III (prompting, tools, agents, evaluation, cost) follows from *how the model actually behaves*.

---

## 6.1 What a language model is

A **language model** is a function that, given a sequence of text so far, outputs a **probability distribution over the next token**. That is the whole job: *predict the next piece of text*.

> P(next token | all previous tokens)

A **large language model (LLM)** does this with a neural network of billions of parameters, trained on a vast amount of text. To produce a paragraph, the system repeats:

1. Feed the text so far (the **context**) into the model.
2. Get a distribution over the next token.
3. **Choose** one token (by sampling or taking the most likely).
4. Append it to the context. Repeat until a stop condition (an end-of-sequence token, a length limit, a stop string).

This loop is called **autoregressive generation**. Everything else (answering questions, writing code, following instructions) emerges from predicting text *well enough*, after additional training to make the predictions *useful* (Section 6.5).

Two consequences you should internalise now:

* The model has **no hidden database of facts and no internal notion of "true"**. It produces text that is *plausible given its training and the context*. Sometimes that coincides with truth, sometimes not.
* The only thing it "sees" at inference time is **the text in the context window**. It does not remember previous conversations unless *you* put them in the context. The API is **stateless**.

### A short history (so the vocabulary makes sense)

* **n-gram models**: count how often word sequences occur. Tiny context, no generalisation.
* **RNN / LSTM** (2010s): process text step by step with a hidden state; hard to parallelise, forget long-range context.
* **The Transformer** (2017, "Attention Is All You Need"): processes all tokens in parallel using **attention**, so it trains efficiently on GPUs and scales. Every modern frontier LLM is a transformer descendant.
* **Scaling** (2018-): more parameters + more data + more compute gave steadily better models (and surprising abilities).
* **Instruction tuning and RLHF** (2022-): turned raw predictors into helpful assistants (the chat experience).
* **Reasoning models and tool use** (2024-): models trained to "think" before answering and to call tools; the basis for agents (Chapters 8-9).

## 6.2 Tokens

Models do not read characters or words; they read **tokens**: chunks of text from a fixed vocabulary of typically tens of thousands to a few hundred thousand pieces.

### Tokenisation

A **tokenizer** converts text to a list of integer token ids and back. Most use **byte-pair encoding (BPE)** or a variant: start from bytes/characters and repeatedly merge the most frequent adjacent pairs, building a vocabulary where common words are one token and rare words split into several.

Illustrative (the exact split depends on the model):

* `"college"` → 1 token. `"unbelievably"` → perhaps `["un", "believ", "ably"]`.
* `" Myntra"` (with a leading space) can be a different token from `"Myntra"`.
* `"₹4000"` may be several tokens (the rupee sign is a multi-byte character; digits often split into groups).

**Rules of thumb** for English prose: **1 token ≈ 4 characters ≈ 0.75 words**; 1,000 tokens ≈ 750 words. Other languages, code, and unusual symbols use *more tokens per word*, so they cost more and fit less. JSON with long keys is token-hungry (a reason `FindProductsOutput` field names are short-ish and why prompts avoid sending whole product pages).

### Why tokens matter to you

1. **Cost** is billed per token (input and output separately; output is usually pricier) (Chapter 14).
2. **Context limits** are measured in tokens.
3. **Speed**: generation time grows with output tokens (each is a separate forward pass).
4. **Odd failures** come from tokenisation: counting letters in a word ("how many r's in strawberry"), exact string reversal, and digit arithmetic are hard because the model sees token chunks, not letters. *If you need exact character-level or numeric precision, use code, not the model.* (The project does this: the budget is enforced by Python arithmetic, not by trusting the model's sums.)
5. **Count tokens with the provider's own tokenizer or token-counting endpoint**, not a different vendor's library; counts differ between models.

## 6.3 Embeddings inside the model

The first layer maps each token id to a learned vector (its **embedding**); positions are encoded too, so the model knows word order. These vectors flow through the network, being refined at each layer into context-aware representations. The vector at the last position, after all layers, is projected to **logits** over the vocabulary, and softmax (with temperature) turns them into the next-token distribution (Chapter 5).

A separate family, **embedding models**, are trained specifically to output *one vector for a whole text* such that similar meanings are close. Those power search and retrieval (Chapter 10). They are *not* the same thing as the chat model's internal embeddings, and are usually much cheaper to call.

## 6.4 The transformer, conceptually

You should be able to explain this at a whiteboard in five minutes.

### Attention

For each token, attention asks: *which other tokens in the context should I pay attention to, and how much?* Each token produces three vectors from learned projections:

* a **query** Q ("what am I looking for?"),
* a **key** K ("what do I contain?"),
* a **value** V ("what information do I pass along if attended to?").

The attention output for a token is a weighted average of all values, where the weights come from comparing its query with every key:

`Attention(Q, K, V) = softmax(Q Kᵀ / √d) · V`

(`√d` keeps the dot products from growing too large.) In a **decoder-only** model (the architecture of chat LLMs) a **causal mask** prevents each token from attending to *later* tokens, because during generation the future does not exist yet.

**Multi-head attention** runs several attention computations in parallel with different projections, letting the model track different relationships (syntax, coreference, topic) at once.

### A block, and a stack

One **transformer block** = multi-head self-attention → add & normalise (a **residual connection** and **layer norm**) → a position-wise **feed-forward network** (two big matrix multiplications with a non-linearity) → add & normalise. A model stacks dozens to over a hundred blocks. Most of the parameters, and much of the "knowledge", live in the feed-forward layers.

### Costs that follow from the design

* **Attention is O(n²)** in context length n: doubling the context roughly quadruples attention compute. Providers use optimisations (FlashAttention, sparse or sliding-window attention, grouped-query attention) so long contexts are practical, but long inputs remain slower and costlier.
* **KV cache.** During generation, the keys and values of previous tokens never change, so servers cache them instead of recomputing. This makes each new token cheap *relative to the context* but uses a lot of GPU memory proportional to context length × number of concurrent users. It is why long contexts and high concurrency are memory-bound.
* **Prefill vs decode.** Processing the prompt (**prefill**) is highly parallel and fast per token; generating output (**decode**) is sequential, one token at a time, and limited by memory bandwidth. Hence: *time to first token* (TTFT) depends mostly on prompt length; *tokens per second* depends on the model size and hardware.
* **Mixture-of-experts (MoE)**: some models route each token to a few "expert" sub-networks, so only a fraction of parameters run per token (big total capacity, cheaper per-token compute).
* **Quantisation**: storing weights in fewer bits (8-bit, 4-bit) to shrink memory and speed inference, with small quality loss. Important when running open models yourself.
* **Parameters × tokens** drives compute: a rough rule is about 2 × (parameters) floating-point operations per generated token.

## 6.5 How models are trained

A modern assistant goes through stages. Each is *the same loop* (Chapter 5, Section 5.7: gradient descent on a loss) with different data.

1. **Pre-training.** Predict the next token over trillions of tokens of text, code and other data. This produces a **base model**: knowledgeable, fluent, but just continues text (ask it a question and it may produce more questions). It has a **knowledge cutoff**: it knows nothing after the data was collected.
2. **Supervised fine-tuning (SFT / instruction tuning).** Train on curated (instruction, ideal response) pairs so the model follows instructions and adopts a chat format.
3. **Preference optimisation.** Humans (or AI judges) compare pairs of responses; the model is trained to prefer the better ones. Methods: **RLHF** (train a reward model, then optimise the policy with reinforcement learning), **DPO** and relatives (optimise directly on preference pairs), and **constitutional/AI-feedback** variants. This shapes tone, helpfulness, refusals and safety behaviour.
4. **Reinforcement learning on verifiable tasks.** For maths and code (where answers can be checked automatically), models are trained with rewards for correct final answers, which produced **reasoning models** that generate long internal chains of thought before answering.
5. **Tool-use and agentic training.** Models are trained on trajectories of calling tools, observing results and continuing, which makes function calling reliable (Chapter 8).

**Fine-tuning for your application** (continuing training on your data) is a separate, optional step: **full fine-tuning** updates all weights (expensive), **LoRA/adapters** train small add-on matrices (cheap, common for open models). Use it for **style, format, and narrow behaviours**, rarely for *injecting facts* (retrieval does that better, Chapter 10). Try, in order: better prompts → structured outputs → examples in the prompt → retrieval → tools → *then* consider fine-tuning (Chapter 14).

## 6.6 Inference: what you control

When you call a model you set **sampling parameters**. Know all of them:

| Parameter | Meaning | Typical use |
|---|---|---|
| `temperature` | Softmax sharpness (Chapter 5). 0 ≈ most likely token; higher = more varied | 0-0.3 for extraction/classification/code; 0.7-1 for creative text. (Some newer models fix or restrict sampling parameters; check the model's docs.) |
| `top_p` (nucleus) | Sample only from the smallest set of tokens whose probabilities sum to p | Alternative to temperature; do not tune both aggressively |
| `top_k` | Sample only from the k most likely tokens | Rarely needed |
| `max_tokens` | Hard cap on output length | Always set; size it for the task; too low truncates mid-answer (`stop_reason: max_tokens` / `finish_reason: length`) |
| `stop` sequences | Strings that end generation | Delimiters, format control |
| `seed` | Request reproducibility (best effort where supported) | Testing |
| `frequency/presence penalty` | Discourage repetition | Long-form text |
| `stream` | Receive tokens as they are produced | Chat UIs; avoids timeouts on long outputs |
| reasoning/effort controls | How much hidden "thinking" the model does before answering | Newer models expose an effort or thinking setting; more effort = better on hard tasks, slower and costlier |

**Context window.** The total tokens of *input + output* the model can handle in one call. Windows have grown from a few thousand to hundreds of thousands and even a million tokens on some current models. Bigger is not free: more tokens cost more, add latency, and models are **less reliable at using information buried in the middle of very long contexts** ("lost in the middle"), and can be distracted by irrelevant text. **Context engineering**, choosing *what* goes in, matters more than *how much* fits (Chapter 10).

**Prompt (prefix) caching.** Providers cache the processed form of an unchanged *prefix* of your prompt and bill repeated prefixes at a steep discount and with lower latency. It works on **exact prefix matches**: any change earlier in the prompt invalidates what follows. So design prompts with **stable content first** (instructions, tool definitions, examples) and **volatile content last** (the user's message, timestamps). Verify with the usage fields the API returns for cache reads and writes.

**Streaming.** Responses can be delivered as a series of small events (token deltas) as they are generated, usually over SSE. It does not make the model faster; it makes the *perceived* latency much lower, and prevents HTTP timeouts on long generations.

**Reasoning ("thinking") models.** Many current models can spend extra tokens on an internal reasoning trace before answering. Controls vary by vendor (an "effort" level; an adaptive mode where the model decides how much to think). Implications: better accuracy on multi-step problems; **higher cost and latency**, because thinking tokens are billed as output; some APIs return a summary of the reasoning, others hide it; and parameters such as forced tool choice or temperature may be restricted on those models. Always read the model-specific notes before swapping models.

## 6.7 Kinds of models, and choosing among them

* **Base vs chat/instruct** models (you almost always want chat/instruct).
* **Small vs large**: small models are fast and cheap; large models are more capable on hard, ambiguous tasks. A common production pattern: *route* easy work to a small model and hard work to a large one (Chapter 14).
* **Closed (API-only)** vs **open-weight** (you can download and run them: Llama, Mistral, Qwen, DeepSeek, Gemma families, and others). Open weights give control, privacy and fixed cost at scale, at the price of running infrastructure (GPUs, serving stacks like vLLM or TGI) and often a capability gap to the frontier.
* **Multimodal** models accept images, audio, video or PDFs as input (and some produce images/audio). Vision input uses tokens too.
* **Embedding models**, **reranking models**, **speech-to-text/text-to-speech**, **image generators** are separate model types you will combine with LLMs.
* **Model cards and benchmarks.** Read: context window, modalities, knowledge cutoff, tool-calling support, structured-output support, rate limits, pricing, data-retention policy. **Public benchmarks are noisy and can be gamed or contaminated; build a small evaluation set from *your* task and test candidates on it** (Chapter 12). This project did exactly that kind of testing: it found the free model rejects `json_schema` and returns nulls in plain JSON mode, but works with tool-calling, a fact no leaderboard would have told it.

## 6.8 What LLMs are bad at (know the failure modes)

| Failure | Why | Mitigation |
|---|---|---|
| **Hallucination** (confident false statements, invented citations, URLs, product details) | The model maximises plausibility, not truth; gaps in knowledge are filled with plausible text | Ground answers in retrieved or tool-provided data; require citations; verify claims in code; allow "I don't know"; low temperature for factual tasks |
| **Stale knowledge** | Training cutoff | Retrieval/search tools; supply today's date and facts in the prompt |
| **Arithmetic, counting, exact string manipulation** | Token-level view; no built-in calculator | Use code or calculator tools |
| **Non-determinism** | Sampling; infrastructure effects | Evals with repeats; structured outputs; validation and retries |
| **Instruction drift in long conversations** | Context dilution | Re-state key rules; summarise; keep system prompts focused |
| **Sycophancy** (agreeing with the user) | Preference training rewards pleasing answers | Ask for critique explicitly; evaluate against ground truth |
| **Prompt injection** | Instructions and data share one text channel | Treat all external text as untrusted; least-privilege tools; confirmation steps (Chapter 21) |
| **Format breakage** (invalid JSON, missing fields) | It is generating text, not filling a typed object | Structured output/tool calling, schema validation, retries (Chapter 7) |
| **Bias and uneven quality across languages/groups** | Training data | Test across groups; human review for high-stakes decisions |
| **Over-confident reasoning errors** | Plausible-looking steps can be wrong | Verification steps; tests; self-consistency; deterministic checks |
| **Cost/latency blow-ups** from loops and long contexts | Each token costs | Hard caps on iterations, tokens and time |

**The engineering stance** (the thesis of this book): *treat the model as a powerful, unreliable component.* Wrap it with validation, verification, limits, and observability. The AI Stylist's verifier, clamping, retry limits and ownership checks are all expressions of it.

## 6.9 The API shape: a chat completion

### Messages and roles

You send a list of **messages**, each with a **role** and content:

* `system`: standing instructions (persona, rules, format). Some APIs take it as a separate top-level field; some models also accept later system-role messages.
* `user`: the human's input (and in many APIs, tool results are sent back with a user or tool role).
* `assistant`: the model's earlier replies (you resend them to maintain the conversation).
* `tool`: results of tool calls (OpenAI-style) or `tool_result` content blocks (Anthropic-style).

Because the API is **stateless**, your application stores the history and resends it every call. In this project **LangGraph's checkpointer stores the history in Postgres** under the conversation's thread id and the graph rebuilds the message list each time. Token cost therefore grows with conversation length: long chats get more expensive each turn unless you summarise or truncate.

### An OpenAI-compatible request (what this repo uses)

```json
POST https://openrouter.ai/api/v1/chat/completions
Authorization: Bearer <key>
{
  "model": "apodex/apodex-1.1-mini:free",
  "messages": [
    {"role": "system", "content": "You read a conversation between a shopper ..."},
    {"role": "user", "content": "College wear, around 4000 rupees"}
  ],
  "temperature": 0,
  "max_tokens": 1024,
  "tools": [ ... ],            // optional: function/tool definitions (Chapter 8)
  "stream": false
}
```

The response contains `choices[0].message` (content and/or `tool_calls`), `finish_reason` (`stop`, `length`, `tool_calls`, ...), and a `usage` object (`prompt_tokens`, `completion_tokens`, `total_tokens`) which you should **log for cost tracking**.

The **OpenAI Chat Completions format became a de-facto standard**: many providers and gateways (OpenRouter, Together, Groq, vLLM, Ollama, and others) expose the same shape, which is why one client class can talk to many backends. Vendors also have their own native APIs (Anthropic's Messages API with `system` as a top-level field and content as typed blocks; OpenAI's Responses API; Google's Gemini API) with richer features such as typed content blocks, built-in tools, caching controls and extended thinking. The concepts are the same.

### Errors you must handle

| Status | Meaning | Action |
|---|---|---|
| 400 | Invalid request (bad parameter, **context too long**, unsupported feature for this model) | Do not retry unchanged; fix the request |
| 401/403 | Bad key / not permitted | Alert; do not retry |
| 404 | Unknown model | Config error |
| 408 / network | Timeout | Retry with backoff |
| 429 | Rate limit or quota exceeded | Retry after `Retry-After` with backoff; shed load |
| 5xx / 529 overloaded | Provider trouble | Retry with backoff and a cap; consider fallback model |

Also handle **finish reasons** like `length` (truncated), content-policy refusals, and malformed tool calls.

### In this project: `llm.py`

```python
def get_llm(cfg: Settings = settings) -> ChatOpenAI:
    provider, _, model = cfg.stylist_model.partition("/")   # "openrouter/apodex/apodex-1.1-mini:free"
    if provider == "openrouter":
        return ChatOpenAI(model=model, api_key=cfg.openrouter_api_key,
                          base_url=cfg.openrouter_base_url,
                          default_headers={"X-Title": "AI Stylist"}, **_http_clients(cfg))
    if provider == "opencode": ...
```

Points to study:

* **One model setting, two parts**: `STYLIST_MODEL` = `<provider>/<model-id>`, split on the **first** slash only (`partition`), because model ids themselves can contain slashes and colons (`apodex/apodex-1.1-mini:free`). Parsing bugs like this are mundane and real.
* **`ChatOpenAI` pointed at a different `base_url`**: because OpenRouter speaks the OpenAI protocol, the OpenAI client library works unchanged. That is the payoff of a de-facto standard.
* **`default_headers={"X-Title": ...}`**: OpenRouter's optional attribution header.
* **Fail fast on config**: an empty key raises at startup of the first call with a clear instruction.
* **Per-provider quirks live here and nowhere else**: OpenCode serves GPT/Grok through the *Responses* endpoint and Qwen/DeepSeek/Kimi through *chat completions*, so `use_responses_api` is chosen from the model name; Claude models on that gateway use a different endpoint style and raise `NotImplementedError` instead of silently failing. *A model-gateway layer exists to hide such differences; leaks of the differences are bugs.*
* **IPv4 pinning** (`httpx.HTTPTransport(local_address="0.0.0.0")`) works around networks where the first IPv6 attempt stalls ~40 seconds.
* **Decorating the model for telemetry**: `InstrumentedLLM` wraps `with_structured_output` to count and time each call and feed Prometheus counters. The agent code never knows.

### Choosing the model for your product

Decide using a table of: **quality on your eval set, latency (TTFT and total), price per request at your token sizes, context needs, structured-output/tool-call reliability, rate limits and quotas, data-retention/privacy terms, availability and fallbacks**. For a hosted product, plan for *the model changing under you*: provider model deprecations, version updates that shift behaviour, and outages. Keep a **fallback model**, **pin versions** where the vendor allows, and **re-run your evals before switching**. (The free model in this repo works for development, but its 50 requests/day cap means it cannot serve real users: "Must move to a paid model before real users.")

## 6.10 A tiny hands-on model of generation

To make the loop concrete, here is a toy generator with a hard-coded distribution:

```python
import random

NEXT = {                                  # token -> {next token: probability}
    "<s>":     {"college": 0.5, "office": 0.5},
    "college": {"wear": 1.0},
    "office":  {"wear": 1.0},
    "wear":    {"under": 0.6, "around": 0.4},
    "under":   {"4000": 1.0},
    "around":  {"4000": 1.0},
    "4000":    {"</s>": 1.0},
}

def generate():
    tok, out = "<s>", []
    while tok != "</s>":
        choices = NEXT[tok]
        tok = random.choices(list(choices), weights=choices.values())[0]   # sample
        if tok != "</s>": out.append(tok)
    return " ".join(out)
```

A real LLM replaces the dictionary with a neural network that computes the distribution from the *entire* context (not just the last token), over a vocabulary of ~100k tokens. The loop (distribution → pick → append) is identical.

## Common mistakes

* Assuming the model remembers earlier calls (it does not; you resend history).
* Trusting model arithmetic, counts or URLs.
* Sending huge contexts "because it fits" (cost, latency, distraction).
* Mixing up sampling controls across models (some reject temperature or forced tool choice).
* Not logging `usage` (you cannot manage cost you do not measure).
* Parsing free-form text where a schema (structured output) was available.
* No retry/backoff and no fallback model.
* Choosing a model from a leaderboard instead of from your own eval.

## Summary

* An LLM predicts the next token from the context; text generation is that step in a loop.
* Tokens are the unit of cost, context and speed; tokenisation explains odd failures.
* Transformers use attention; attention costs grow with context; KV caches and prompt caches make long prefixes cheaper.
* Training = pre-training → instruction tuning → preference optimisation → (RL for reasoning, tool use). Fine-tuning is rarely the first tool.
* The API is stateless; you send the full history; parameters control randomness and length; handle errors and finish reasons.
* Treat the model as an unreliable component and wrap it with checks.

## Key terms

*token, tokenizer, BPE, context window, autoregressive, logits, softmax, temperature, attention, KV cache, prefill, decode, TTFT, pre-training, SFT, RLHF, DPO, hallucination, prompt caching, streaming, stateless API, OpenAI-compatible, usage.*

## Interview questions

1. How does an LLM generate text? What are logits, temperature and top-p?
2. What is a token? Why can an LLM miscount letters but write good prose?
3. What is the context window, and why is "just use the longest context" not a strategy?
4. Explain attention in one minute. Why is it O(n²)?
5. What is the difference between pre-training, instruction tuning and RLHF?
6. Why do LLMs hallucinate, and what are three engineering mitigations?
7. The API is stateless. How does this app give a conversation memory?
8. When would you fine-tune instead of using retrieval or prompting?
9. What is prompt caching and how does prompt design affect it?

## Exercises

1. Use a tokenizer library (or your provider's token-count endpoint) to count tokens for: a product title, a 500-word prompt, the same text in Hindi, and a JSON blob. Compute the cost of each at a hypothetical price.
2. Call a model with `temperature` 0 ten times with the same prompt; count distinct outputs. Repeat at 1.0.
3. Log `usage` for a full AI Stylist conversation (all calls) and total input and output tokens. Which node costs the most?
4. Extend the toy generator to use a bigram model trained on 1,000 product titles you scrape or write.
5. Find a prompt that makes a model hallucinate a product URL; then rewrite the system so it refuses to produce URLs it was not given.
