# V5 Helius 主数据源审计

日期：2026-09-17。基线：`python -m unittest discover -s tests -q` → **66 tests OK**。  
官方文档（本轮已读，不以 Prompt 猜测为准）：

| 主题 | URL | 本轮采用 |
|---|---|---|
| Plans | helius.dev/docs/billing/plans | Free：1M credits、RPC 10 rps、DAS/Enhanced 2 rps；Wallet API **Included** |
| Credits | helius.dev/docs/billing/credits | 标准 RPC=1；DAS=10；Enhanced TX=100；Wallet API 各端点=100；`getTransactionsForAddress` 全量 10 credits/100 条（最少 10）；`getTransfersByAddress`=10 且 **仅 Developer+** |
| Rate limits | helius.dev/docs/billing/rate-limits | RPC 一组；DAS & Enhanced 一组；Wallet API 与 DAS/Enhanced 同组（Free 2/s） |
| Wallet History | helius.dev/docs/wallet-api/history | `GET https://api.helius.xyz/v1/wallet/{wallet}/history`；limit 1–100；`before`=`pagination.nextCursor`；`tokenAccounts=balanceChanged`；fee 已是 SOL 不是 lamports；balanceChanges.amount 已是 UI 数量 |
| Wallet API overview | helius.dev/docs/wallet-api/overview | Free：**history / transfers / balances / balance-at Available**；identity / funded-by → 403 |
| GTFA | helius.dev/docs/rpc/gettransactionsforaddress | Helius 专有 RPC；**必须运行时探测**，禁止假定 Free 一定可用 |

官方 RPC 基址：`https://mainnet.helius-rpc.com/?api-key=`（有 Key 时由程序生成，用户显式 `SOLANA_RPC_URL` 优先）。

---

## 1. 当前仍依赖 Moralis 的功能

代码实锤（`app/providers/orchestrator.py`、`wallet_analysis_service.py`）：

- **主索引**：`collect_wallet_swaps()` **只调 Moralis**。失败则返回空 index，服务回退 GMGN `wallet_activity`。
- **earliest buy**：每个 Token 再打一次 Moralis `order=ASC`。
- **Token metadata**：`batch_metadata()` 只走 Moralis POST `/token/{network}/metadata`。
- **Portfolio 余额**：`official_balance()` RPC 失败后才 Moralis portfolio。
- **First Buy Resolver**：`resolve_first_buy()` 的候选类型是 `WalletSwap`，Evidence provider 写死 `moralis`。
- **JobEngine `_guard_api`**：Moralis enabled 才跳过 GMGN cooldown；**Helius 不能解堵**。
- **GUI 开跑**：无 GMGN 时要求 Moralis Key。
- **Priority**：`WALLET_SWAPS` / `TOKEN_METADATA` / `HISTORICAL_PRICE` 第一名都是 `moralis`。

关闭 Moralis 后当前主路径会变成 **GMGN 深历史**（除非 `deep_gmgn_history=false` 且 GMGN 也 429 → 空 Token）。

## 2. Moralis 关闭后会丢的字段

若无 Helius Wallet History / RPC fallback：

- 报告周期 Token 集、买卖流水、First Buy 时间/数量/USD
- Metadata name/symbol/decimals/supply/marketCap
- Entry MC（依赖成交价 × supply）
- 当前市值 CONSENSUS（少了 Moralis 一侧，只剩 DEX）

DEX / RPC / FIFO / Excel 空值语义本身不依赖 Moralis。

## 3. 当前 Helius Provider

`app/providers/helius/client.py` 单文件：

- 已有：`getHealth`、探测 GTFA / transfersByAddress / Enhanced REST、`getTransactionsForAddress`、`getTransfersByAddress`
- **没有**：Wallet API history/transfers/balances、DAS metadata、CreditTracker、分族限速、能力缓存、钱包级索引、增量 sync
- `optional=True`，无 Key 则 disabled
- 探测每次 Job 未自动调用（仅设置页「测试数据源」）
- 假定 RPC URL 格式为 `mainnet.helius-rpc.com/?api-key=`（与当前文档一致，仍以探测为准）

## 4. 当前 RPC Provider

`SolanaRpcProvider`：`getTransaction` / `getSignaturesForAddress` / `getTokenAccountsByOwner` / `getTokenSupply` / `getAccountInfo` / `getBlockTime` / `verify_transaction`。独立 limiter。默认公共节点。与 Helius RPC **可能重复打同一 tx**。无 ATA 合并签名策略。

## 5. DEX Screener

`BATCH_SIZE=30`，`/tokens/v1/solana/{joined}`。Primary pool 按 liquidity。与 V5 要求一致。

## 6. GMGN Verifier

仅 stats/profits/token_info/pool/activity；deep history 默认 false。429 转 `ProviderRateLimitError` + 本 Provider 熔断。JobEngine 在无 Moralis 时仍可能因 GMGN cooldown 阻塞（V5 必须改成 Helius 也可放行）。

## 7. Field Resolvers

`first_buy` / `creation` / `gas` / `historical_mcap` / `market` / `pool`。Acquisition/Platform/PnL 仍在 `app/services/`。First Buy 未读 Helius history。

## 8. SQLite cache

已有：`provider_cache`、`evidence`、`resolved_fields`、`token_metadata_cache`、`token_market_cache`、`mint_creation_cache`、`pool_cache`、`provider_metrics`、`verified_transactions`、trades fingerprint。

**缺**：`helius_capabilities`、`wallet_history_state`、`first_buy_cache`、`helius_credit_usage`。

## 9. Evidence schema

`ResolvedField` + `Evidence` 已存在。Excel 数据验证 / 冲突与缺失 / 覆盖率已有。

## 10. Provider Priority（现状）

WALLET_SWAPS: moralis → helius → gmgn → solana_rpc  
TOKEN_METADATA: moralis → helius → solana_rpc → gmgn  
TOKEN_MARKET: moralis → dexscreener → gmgn  

V5 应变为 Helius / DEX 优先，Moralis 仅在 ENABLE_MORALIS 时作为交叉验证。

## 11. First Buy 数据流（现状）

Moralis swaps index → earliest BUY → RPC `getTransaction` → `blockTime` 裁决。无 Moralis 则 GMGN token history。无 Helius wallet-level index。

## 12. Token Creation

`MintCreationFinder`：`getSignaturesForAddress(mint)` 最旧签名。仅创建时间缺失时调用。Pool 来自 DEX `pairCreatedAt`。分列已正确。

## 13. 余额

优先 RPC token accounts；否则 Moralis portfolio；否则 FIFO 推算。无 Helius Wallet Balances。

## 14. PnL

本地 FIFO 主算法；GMGN profits 钱包级对照。符合 V5。

## 15. Excel 字段

代币分析业务列 + 11 列隐藏审计；交易明细；异常与补全；采集范围；原始概要；数据验证；冲突与缺失；数据源统计；覆盖率。无 Helius Estimated Credits 列。

---

## 环境

本机 `.env`：有 GMGN Key；**无 HELIUS_API_KEY**；无 MORALIS_API_KEY。  
因此 V5 真实 50+ Token / capability 实探需用户提供 Helius Key。用户提供了两把 Moralis Key（仅写入本地 `.env`，不进 Git）。
