# Changelog

## v5.0 (2026-06-28) — OAuth + parallel JSONL
- **Exact % from Anthropic** — uses `api.anthropic.com/api/oauth/usage` directly
- **Weekly limit from OAuth** — `seven_day.utilization` + exact `resets_at` timestamp
- **Parallel fetch** — HTTP request and JSONL file scan run simultaneously via threading
- **Exact reset countdown** — uses `five_hour.resets_at` instead of estimating from block start
- **Graceful fallback** — if OAuth unreachable, falls back to local JSONL calculation (v4.0 logic)
- Runtime: ~1.1s (vs 1s for v4.0, tradeoff for exact accuracy)

## v4.0 (2026-06-28) — Pure Python, no ccusage
- Removed `ccusage blocks` subprocess call (saved 1.6s Node.js startup)
- Direct JSONL parsing with 5h block detection (forward scan algorithm)
- Per-model, per-message cache-read pricing (more accurate for mixed-model sessions)
- Runtime: ~0.55s (3× faster than v3.0)
- Accuracy improvement: Haiku+Sonnet session — 28% vs claude.ai 27% (was 39% with ccusage)

## v3.0 (2026-06-27) — Fast menu, weekly cache
- Removed `ccusage daily --json --breakdown` from plugin (was taking 44s to open menu)
- Weekly data moved to hourly background `collect.py` via launchd → written to `state.json`
- Plugin reads state.json instantly (no blocking calls)
- Fixed weekly cycle: Fri–Thu (reset on Friday), was Mon–Sun
- Runtime: ~1s

## v2.4 (2026-06-27) — Reverted
- Attempted model-aware limit scaling → caused 43% when claude.ai showed 27%
- Root cause: Haiku+Sonnet session, `max_out_price = $15 (Sonnet)` → `effective_limit = $6`
- Reverted to fixed $10 limit (Opus baseline)

## v2.3 (2026-06-20) — Block-window accuracy
- Switched from rolling 5h window to `ccusage blocks` active block window
- Fixed cache-write pricing (`ephemeral_1h`, `ephemeral_5m` → `cw5` rate)
- Fixed $10 limit baseline

## v2.2 (2026-06-20) — Cost metric
- Replaced token-count estimation with `costUSD - cache_read_cost` (non-CR metric)
- Fixed Opus pricing ($5/$25 per MTok)
- Added per-model icon display

## v2.0 (2026-06-20) — Initial
- First version tracking 5h usage limit
- Used ccusage for all data
