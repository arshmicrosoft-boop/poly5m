# Polymarket Research — BTC 5-Minute Up/Down Trading Bot

> Research gathered from official Polymarket documentation (docs.polymarket.com) and live API exploration. Date: 2026-11-10.

## 1. Platform Overview

Polymarket is a non-custodial, peer-to-peer prediction market on Polygon. Prices are probabilities in [0,1] pUSD. Every market is binary (Yes/No). Winning shares redeem for $1 pUSD; losers are worth $0. Trades settle on-chain via a hybrid CLOB: off-chain matching, on-chain settlement. You always retain custody until a matched trade settles atomically.

- Collateral: **pUSD** (Polymarket USD), ERC-20 backed by USDC.
- Chain: Polygon (chainId 137).
- Position tokens: ERC-1155, recorded as Gnosis CTF (V1) or Polymarket Protocol V2 positions.
- Resolution: UMA Optimistic Oracle (or other mechanisms for V2 markets).

## 2. APIs Available

Base URLs:

| API | Base URL | Purpose |
|---|---|---|
| Gamma | `https://gamma-api.polymarket.com` | Discover events/markets, metadata |
| CLOB | `https://clob.polymarket.com` | Live market state, place/manage orders |
| Data (v2) | `https://data-api.polymarket.com` | Account & market activity (cursor pagination) |
| Relayer | `https://relayer-v2.polymarket.com` | Gasless wallet tx submission |
| WebSocket | realtime streams | market, account, sports, RFQ events |
| Bridge | `https://bridge.polymarket.com` | Fund/withdraw |

Plus WebSocket realtime streams and Bridge API.

## 3. SDKs

Official unified SDKs:

- **Python**: `polymarket-client` (PyPI). `AsyncPublicClient` / `PublicClient` for data; `AsyncSecureClient` / `SecureClient` for trading. Async-only features include realtime subscriptions.
- **TypeScript**: `@polymarket/client` (npm). `createPublicClient()` / `createSecureClient()`. Supports Viem, Privy, Ethers v5 adapters.

Key SDK primitives:
- `list_markets(closed=False)` with paginator (`first_page`, `iter_items`, `from_cursor`).
- `fetchMarket({ slug })` / `get_market(slug=...)`.
- `placeMarketOrder({ assetId, side, amount })` (amount in pUSD for buys).
- `placeLimitOrder` (via CLOB) for price control.
- `waitForOrderFillSettlement(response)` to await on-chain settlement.
- `listPositions({ market: [conditionId] })`.
- `subscribe([MarketSpec(asset_ids=[...]), UserSpec()])` for realtime streams.

Identifiers: markets have `conditionId`, `tokenId` (CTF) / `positionId` (V2), and `assetId` (unified trading id = tokenId for V1, positionId for V2). Always branch on `market.version === "v2"`.

## 4. Authentication

- L1: EIP-712 `ClobAuth` typed data signed by the signer → POST `/auth/api-key` (or GET `/auth/derive-api-key`) → returns `apiKey`, `secret`, `passphrase` (L2 creds).
- L2 creds authenticate private requests (orders, cancels, account data).
- Wallet types: EOA (0), POLY_PROXY (1), GNOSIS_SAFE (2), DEPOSIT_WALLET (3). Deposit wallet is default for accounts created on/after May 4, 2026.
- Relayer API key (from polymarket.com → Settings → API Keys → Relayer API Keys) enables gasless wallet ops.
- Session Keys: scoped, time-limited trading access for a separate signer on Deposit Wallets.

## 5. Trading Mechanics

- All orders are technically limit orders; a "market order" is a limit order priced to execute immediately (unfilled remainder canceled).
- Order sides: BUY / SELL. For BUY, `amount` is pUSD to spend.
- Hybrid CLOB: off-chain matching by operator; on-chain settlement via smart contracts.
- Makers never pay fees; only takers pay.
- Fees: `fee = C × feeRate × p × (1-p)`, rounded to 5 decimals, min 0.00001 USDC. Crypto category feeRate = 0.07 (highest). Peak fee at p=0.5.
- Crypto markets are the relevant category for BTC → feeRate 0.07.
- No size limits on orderbook, but large orders move price — check depth.
- Sports markets auto-cancel outstanding limit orders at game start (not relevant here).
- Matching engine maintenance windows exist (post-only mode after restart).

## 6. Market Discovery for BTC 5-Min

- Use Gamma `/events` and `/markets` with filters. Markets have `enableOrderBook`, `conditionId`, `clobTokenIds`/`positionIds`, `endDate`, `feeType`, etc.
- For a 5-min BTC up/down market, expect a single-market event with question like "Bitcoin Up or Down - 5 min ..." and an `endDate` ~5 min out, recurring on a schedule (series).
- Each market resolves to Yes (BTC went up over the window) / No (down).
- Need to continuously discover the *next* active market as each 5-min window resolves; markets are short-lived and new ones spin up. Use `closed=False` filters and `endDate` proximity, or follow the series.

## 7. Rate Limits (IP-based, Cloudflare throttling — delayed, not rejected)

Key limits for a bot:

- General: 15,000 req / 10s
- Gamma `/markets`: 300 req / 10s; `/events`: 500 req / 10s
- CLOB general: 9,000 req / 10s
- CLOB market data: `/book` 1,500/10s; `/price` 1,500/10s; `/midpoint` 1,500/10s
- CLOB trading: POST /order burst 5,000/10s, sustained 120,000/10min; DELETE /order same.
- Data API v2: 800/10s general.
- Relayer `/submit`: 25 req / 1 min (gasless ops — scarce!).
- Per-signer token-bucket limits also apply to order/cancel (see trading-rate-limits).

Implication: prefer WebSocket streams over polling for prices/order updates; batch where possible (`/books`, `/prices`).

## 8. Realtime / WebSocket

- Market stream: book, price change, last trade price, tick size change, best bid/ask, new market, market resolved.
- User stream (authenticated): order/trade activity.
- Sports stream (irrelevant).
- Realtime is async-only in SDK.

## 9. Geographic Restrictions

Order placement is geo-blocked in some jurisdictions. Must check `geoblock.md` before deploying. Relayer and trading endpoints may be restricted.

## 10. Recommended Architecture for BTC 5-Min Bot

1. **Discovery loop**: poll Gamma for active BTC up/down 5-min markets (or subscribe to `NewMarketEvent`), pick the next market by `endDate` within ~5 min.
2. **Price feed**: subscribe to market WebSocket for best bid/ask + last trade; maintain local orderbook.
3. **Signal**: combine external BTC price oracle (e.g., Binance/Chainlink) with market price; decide Up/Down edge.
4. **Execution**: `placeMarketOrder` (or limit at best ask/bid) with size in pUSD; account for crypto feeRate 0.07 and slippage.
5. **Settlement**: `waitForOrderFillSettlement`; track position via Data API / `listPositions`.
6. **Redemption**: after resolution, redeem winning shares for pUSD (manage positions).
7. **Risk**: position sizing, max loss per window, kill switch, idempotency on orders, retry with backoff respecting rate limits.
8. **Auth**: L2 creds cached; relayer key for gasless ops; session keys for delegated signer if needed.

## 11. Key Risks / Open Questions

- Market availability & geo-blocks (must verify account region).
- Short 5-min windows → latency-sensitive; need low-latency infra near Polygon RPC & CLOB.
- Fee math (crypto 0.07) eats edge; only trade with clear edge.
- Resolution source & timing for BTC 5-min markets (need to confirm exact oracle/window).
- V1 vs V2 market versions → branch on version for asset id.
- Per-signer rate limits on order/cancel (not fully documented here) — need to read trading-rate-limits page.
- Need to inspect actual BTC 5-min market slugs/series via Gamma to automate discovery.

## 12. Next Steps (Implementation)

- Scaffold project (Python or TS). Given workspace has Python available and bot-style async fits Python SDK, recommend Python with `polymarket-client` + `asyncio`.
- Implement config (.env for keys), discovery, websocket price feed, strategy, execution, position tracking, redemption.
- Add tests (mocked CLOB), dry-run mode, and risk guards.
- Read remaining docs: trading/place-orders, manage-orders, realtime-order-updates, trading-rate-limits, geoblock, market-details (fees), positions/manage, session-keys.

---
Sources: docs.polymarket.com (overview, polymarket-101, markets-events, prices-orderbook, trading/overview, trading/quickstart, trading/wallets-auth, getting-started/python, getting-started/typescript, trading/fees, api-reference/rate-limits, market-data/discover-markets).
