# Product search: a model searches the approved stores, the stores' own pages give the facts

## Current design (2026-10-06): model web search, then verification

The default search provider is **OpenRouter's web-search tool with `openai/gpt-6-luna`** (`SEARCH_PROVIDER=openrouter`; Tavily
below is still selectable with `SEARCH_PROVIDER=tavily`). Why it replaced ranked results: Tavily returns pages ranked by
meaning, so a specific colour is rare among 20 results ("olive oversized t-shirt" returned no olive tee at all). The model
search reads the page excerpts it gets back, so one call returned eight olive oversized tees from approved stores.

```
shopper picks a style card ("Olive polo & beige chinos")
  └─ planner designs the outfits; colours the CARD names become verified colours (colour_source "style")
       └─ per distinct piece, the store groups are split into chunks of <= 35 stores and searched side by side
            (tool server: search_products, `style` = the look; the model reads the excerpts for pieces that suit it)
            └─ every address is checked: approved store, single product page; then each page is READ for price/image/stock
                 └─ rules verify (price, garment, men's, colour...), a reader model judges, best pair within budget
```

What the model is and is not trusted for: it finds and filters candidates by reading content. It is never trusted for price,
image or stock (read from the store's page) and anything it names that is not an approved store is dropped in code.

Measured limits that shaped it: the domain filter returns only approved stores at ~30 domains, lets stray stores through at
~61 and is ignored at 100, so searches are **chunked** (`SEARCH_CHUNK_DOMAINS`, default 35) and run in parallel; the list of
allowed stores is also put in the prompt. A garment the shopper fixed is searched in every everyday group at once (`wide_groups`)
so there is no waiting for a second search. Cost is about $0.008 per search (about $0.03-0.06 per turn); the cost is returned
as `search_cost_usd`. Settings: `SEARCH_MODEL`, `SEARCH_ENGINE` (exa), `SEARCH_USES`, `SEARCH_RESULTS`, `SEARCH_TIMEOUT_S`; the tool
server needs `OPENROUTER_API_KEY`. The agent's model calls use `LLM_REASONING_EFFORT=low`.

## The earlier Tavily design (kept as `SEARCH_PROVIDER=tavily`)

Replaces SerpAPI / Google Shopping (2026-10-05). Why: Google Shopping returns whatever merchants feed to Google and
ranks it by popularity, which mostly means Myntra, Amazon and Flipkart. We want the niche brands in
[niche-sellers.md](niche-sellers.md), so every search is **restricted to those 100 domains**.

## The flow

```
shopper picks a style
  └─ planner (model) designs 4 outfits AND chooses 1-3 store groups for the look
       └─ code adds the group a garment needs (jeans → denim, kurta → traditional)
            └─ for each top and each bottom (8 per round):
                 1. DISCOVER   one Tavily search over every store in the chosen groups   (1 credit)
                 2. READ       the best candidate pages are read, a few at a time, until 8 usable products are found (free)
                               price, image, stock and colour come from the store's own page
                 3. CHECK      the rule-based verifier (price, garment, men's, the colour the shopper asked for...)
                 4. JUDGE      a model READS the survivors against what the shopper asked for, keeps or drops each, and when
                               too few fit suggests extra search words; the search is repeated (see "The reader")
                 └─ the best top and bottom that fit the budget together become an outfit
```

**Credits.** One search = one Tavily credit (`basic` depth) and covers a whole group, up to 20 pages, so a round of 4
outfits costs 8 credits however many stores are searched. Searches are cached for 6 hours by (query, groups); page
facts are cached per page; `get_buy_link` costs nothing (a result already is the store's own page).

## Why not use Tavily's own price and image?

Measured on real responses (2026-10-05, three queries, 59 results; the files are in `services/mcp/tests/fixtures/`):

* the page text came back for **7 of 59** results, and a price appeared in only **26 of 59** (44%) even counting the
  short snippets;
* snippet prices were often **promo banners** ("FLAT ₹100 OFF", "reverse shipment fee Rs 100"), which a price rule
  would take as the product's price;
* the per-result `images` list was **empty**; images only come as one list for the whole query.

The stores publish the facts themselves, in the page, in a standard machine-readable form (schema.org `Product`
JSON-LD, with Open Graph meta tags as a fallback). Reading them gave, on 30 real candidate pages: **27 readable, 26 with a
price, 27 with an image, 26 with stock status** (several items were genuinely sold out), each in well under a second.
`providers/page_facts.py` does it; no model is involved, so a page that states nothing yields nothing, never a guess.

The fetch obeys the same safety rules as `check_link`: https only, approved stores only, public addresses only, connect
to the address that was checked, every redirect re-checked, a 2.5 MB and 9 second limit.

## The reader: a model that reads the real results

The verifier is exact about price, garment and men's wear but cannot read like a person: a page called "Cloud Tee, relaxed
fit" that never says "white" in its data is a white tee in the photo, and a "white" tee that is a white-and-red colour block
is not what was asked for. `agent/judge.py` adds the missing reading. It is the "AI-enabled web search" layer on top of
Tavily (Tavily's own Research and answer features were looked at and do not fit: see below).

What it does, per garment search:

1. It is shown up to 8 candidates that are already **real** (read from the store's own page) and already **passed the rules**:
   title, store, price, the colour and fabric the page states, the search snippet, the page's own description, and the words in
   its link.
2. It is told what the shopper **fixed** (the garment, and maybe colour, fit, fabric) and what is only the planner's hint
   (never a reason to reject). It answers per candidate: `yes`, `no` or `unsure`, with a one-line reason.
3. `no` drops the product (the reason is kept in the rejected list as "reader: ..."). `yes` ranks first. `unsure` stays.
4. If fewer products fit than the outfits need, it gives extra search words, and the search is repeated, up to
   `JUDGE_SEARCH_RETRIES` (default 2) times, each time over stores not yet searched: first the stores that specialise in the
   garment (jeans: the denim stores), then the everyday-clothing groups left. One search spreads its 20 results across all the
   stores in it, so a different set of stores finds different products.

What keeps it safe: it can only keep or drop a product that is already real and verified. It never supplies a price, a link, a
stock status or a product. If the model fails or answers badly the rule-based result stands.

It runs only when the shopper asked for something specific (a fixed garment, colour, fit or fabric, or colours to avoid). Pieces
that ask for the same thing (a "white oversized t-shirt" in all four outfits) share one search and one reading.

**What the shopper asked for** is read on the first message into fields (`prefs.top`, `prefs.bottom`, `prefs.avoid`: item,
colour, fit, fabric), imposed on every outfit in code, checked on the products, and kept (or updated) as the conversation
goes on. Anything the shopper did not state for a fixed garment stays open, so the outfits share one search.

Tavily's other AI features, and why they are not used:

| Feature | Verdict |
|---|---|
| `include_answer` (an LLM paragraph) | no product list, nothing guaranteed |
| Research API | `include_domains` is a soft preference limited to 20 domains (we need a hard limit over 100); 4-110 credits a request |
| Extract (1 credit per 5 pages) | the free page read does the same job; a possible fallback for stores that block our reader |

## The five store groups

| Group | Stores | Typical looks |
|---|---|---|
| `streetwear` | 30 | streetwear, Korean casual, Gen-Z, sporty, graphic tees, cargos |
| `smart_casual` | 31 | office, smart casual, linen, minimal, formal, premium, global labels |
| `denim` | 7 | jeans-led looks |
| `traditional` | 23 | ethnic, wedding, festive, kurtas, handloom |
| `activewear` | 9 | gym, lounge, joggers, innerwear |

Who decides: the **planner** picks the groups (the prompt `plan_outfits.v5.md` shows it every group with example
brands); **code** guarantees each garment has a store that sells it (`api/agent/stores.py`) and falls back to a
sensible default if the planner chose nothing valid. At most 3 groups.

## Tavily parameters

Checked against the [Search API reference](https://docs.tavily.com/documentation/api-reference/endpoint/search).

| Parameter | We send | Why |
|---|---|---|
| `query` | item + fit/fabric/colour + "for men" | focused; one garment per search |
| `include_domains` | the groups' domains | **required by our design**; max 300 allowed, we send 30 to 100 |
| `search_depth` | `basic` (1 credit) | `advanced` is 2 credits; try it with the probe if recall is poor |
| `max_results` | 20 (the maximum) | costs the same as 5 |
| `keywords` (our own) | added to the query on a retry | the reader's synonyms or style words; a different query is a different search and credit |
| `include_usage` | true | the real credits charged, counted against the daily caps |

Not sent: `include_raw_content` and `include_images` (measured unreliable; they made the response 400 KB),
`include_domains_mode`, `exact_match`, `topic`, `auto_parameters` (+1 credit), `chunks_per_source`, `country`
(optional `TAVILY_COUNTRY=india`; the domain list already restricts).

## Measured yield (live, 2026-10-05)

| Query | Pages read | Usable products | Left out |
|---|---|---|---|
| blue polo, streetwear + smart casual | 8 | 4 | 5 not product pages, 1 unreadable, 3 sold out |
| beige chinos, smart casual | 6 | 5 | 13 not product pages, 1 unreadable |
| black oversized tee, streetwear | 8 | 2 | 3 not product pages, 1 unreadable, 5 sold out |

Through the agent's own search client: 4 searches (2 outfit specs) built 2 verified outfits in 8 seconds.

## Known limits

* **Some stores block automated reads** (HTTP 403, e.g. Bewakoof; some Wrogn pages), so they are dropped. A paid fallback
  (Tavily Extract, 1 credit per 5 pages) is possible but not built.
* **Sold-out items are common** in small-brand catalogues (about a third of candidates in the tests). They are left out
  automatically, so a search whose top results are sold out reads further down the list.
* **A store's own data can be odd**: some pages give variant names ("Default Title", "30") as the product name (the
  search title is used instead), and one Jack & Jones page had a URL naming a blazer under chinos data. The verifier only
  sees what the store states.
* **Colour** is known only where the page states it (Snitch does); a colour the shopper asks for is otherwise unconfirmed.
* **Latency:** a search plus page reads takes 4–5 seconds; the model's planning call is the slow part of a turn.

## Running the probe

```bash
# put your key in the git-ignored .env:  TAVILY_API_KEY=tvly-...
uv run --project services/mcp python scripts/tavily_probe.py            # 3 queries = 3 credits; the real pipeline
uv run --project services/mcp python scripts/tavily_probe.py -q "linen shirt" -g smart_casual --save
```
