# V4 多数据源审计

日期：2026-09-17。以当前源码、官方文档、既有 `docs/` 与真实运行痕迹为准。本文件只记录现状与缺口，不伪造未观测到的接口字段。

官方文档（实现前已核对）：

| 源 | 文档 | 本轮采用的接口 |
|---|---|---|
| Moralis Solana Wallet Swaps | `docs.moralis.com/data-api/solana/wallet/wallet-swaps` | `GET https://solana-gateway.moralis.io/account/{network}/{address}/swaps` |
| Moralis Token Metadata Batch | `docs.moralis.com/data-api/solana/token/token-metadata-batch` | `POST https://solana-gateway.moralis.io/token/{network}/metadata`，`addresses` 1–100 |
| Moralis Token Metadata | `docs.moralis.com/data-api/solana/token/token-metadata` | `GET /token/{network}/{address}/metadata` |
| Moralis Wallet Portfolio | `docs.moralis.com/data-api/solana/wallet/portfolio` | `GET /account/{network}/{address}/portfolio` |
| Moralis Native Balance | `docs.moralis.com/web3-data-api/solana/reference/native-sol-balance` | `GET /account/{network}/{address}/balance` |
| DEX Screener | `docs.dexscreener.com/api/reference` | `/token-pairs/v1/{chainId}/{tokenAddress}`；`/tokens/v1/{chainId}/{tokenAddresses}` 最多 30 |
| Solana RPC | `solana.com/docs/rpc/http` | `getTransaction` / `getSignaturesForAddress` / `getTokenAccountsByOwner` / `getAccountInfo` / `getTokenSupply` / `getTokenAccountBalance` / `getBlockTime` |
| Helius | `helius.dev/docs` | 标准 RPC 可选；`getTransactionsForAddress` / `getTransfersByAddress` 为套餐能力，必须探测 |
| GMGN | 现有 `docs/api-mapping.md` | `wallet_activity` / `wallet_stats` / `wallet_profits` / `token_info` / `pool_info` |

Moralis OpenAPI 示例仍混用 EVM `0x` 地址。实现必须以 **Solana mint / signature** 的真实 JSON 为准，禁止按 EVM 示例硬编码。

---

## 1. 当前所有 Excel 字段

来源：`CompletenessService.token_export_row` / `trade_export_row`，`ExportService.export` / `export_batch`。

### 代币分析

`#` `币种` `代币名称` `代币合约` `来源平台` `获得方式` `获得状态` `入场市值` `首笔买入` `首买数量` `买入时间` `创建时间` `开盘时间` `池子创建时间` `时差` `时差HMS` `时差秒数` `持仓时长` `持仓时长秒数` `买入笔数` `买入总额` `卖出笔数` `卖出总额` `已实现盈亏` `未实现盈亏` `总盈亏` `总盈亏%` `本地FIFO已实现` `当前余额` `活动推算余额` `余额口径` `缺失成本` `缺失成本卖出笔数` `缺失成本数量` `Launchpad` `资产来源` `流动性平台` `持仓状态` `状态` `钱包` `警告`

批量文件额外带 `钱包`。

### 交易明细

`时间` `类型` `币种` `代币合约` `数量` `USD金额` `SOL金额` `价格USD` `Gas USD` `Gas SOL` `单笔盈亏` `来源平台` `钱包` `TxHash` `是否报告范围`

### 异常与补全 / 采集范围 / 原始概要

异常：`钱包` `Token` `代币合约` `字段` `最终值` `状态` `原因` `数据来源` `是否估算`

采集范围：周期、起止、最早/最晚交易、报告交易数、历史追溯交易数、API 页数、Token 数、截断、版本、路径。

原始概要：请求数、缓存、429、错误、Raw 目录、GMGN 利润周期/状态。

批量另有：`钱包汇总`、`API性能`。

**缺口：** 无「数据验证」「冲突与缺失」「数据源统计」Sheet；无隐藏审计列；无 coverage / verified_rate；无当前市值 / FDV 分列。

---

## 2. 每个字段当前来自哪个 API

| 字段 | 当前 API / 计算 | JSON / 算法 |
|---|---|---|
| 币种 / 名称 | `wallet_activity.token` 或 `token_info` | `symbol` / `name` |
| 代币合约 | `wallet_activity` | `token.address` |
| 来源平台 | `token_info` → `pool_info` → 特殊资产 | `launchpad_platform` / `launchpad` / `pool.exchange` |
| Launchpad / 资产来源 / 流动性平台 / 主池 | 同上 + `special_assets.json` | 见 PlatformResolver |
| 获得方式 | `wallet_activity` 全历史 | 最早 `buy`，否则 `transferIn` |
| 首笔买入 / 数量 / 时间 | `wallet_activity?token=` 翻到 `next=null` | min timestamp buy |
| 入场市值 | 首买 `price_usd × supply` | 历史 supply 缺失则用当前 supply 并标估算 |
| 创建时间 | `token_info` | `creation_timestamp` |
| 开盘时间 | `token_info` | `open_timestamp` |
| 池子创建时间 | `token_info.pool` 或 `pool_info` | `creation_timestamp` |
| 时差 / 持仓时长 | 本地 | first_acq − created；清仓 last_sell − first_acq |
| 买入/卖出笔数与总额 | 报告窗 `wallet_activity` | event_type + cost_usd |
| 已实现/总盈亏/总盈亏% | `wallet_profits` | **钱包级**，单 Token 明确「不提供拆分」 |
| 本地 FIFO | 本地 | Buy/TransferIn lots vs Sell |
| 当前余额 | 本地 FIFO | `DERIVED_FROM_ACTIVITY`，无链上余额 |
| Gas | `wallet_activity` | `gas_usd` / `gas_sol` |
| GMGN 钱包统计 | `wallet_stats` | 7d/30d |

---

## 3. 完全依赖 GMGN 的字段

硬依赖（无 GMGN 则当前任务无法完成）：

- 报告周期 Token 集合（`wallet_activity` 无 token 过滤分页）
- 每 Token 完整历史 / First Buy（`wallet_activity?token=`）
- TransferIn 识别（activity `event_type`）
- Token 创建/开盘（`token_info`）
- Launchpad（`token_info.launchpad_platform`）
- 池子/DEX（`token_info.pool` + `pool_info`）
- 交易 USD/SOL/Gas（activity）
- 钱包官方利润（`wallet_profits` / `wallet_stats`）

JobEngine 把 `GMGNRateLimitError` 当成钱包级阻塞：`WAITING_API` 循环，超时 FAILED。

---

## 4. 已经本地计算的字段

- First Buy = 全历史 min timestamp Buy（`acquisition_resolver`）
- 入场市值 = price × supply（可 ESTIMATED）
- 时差、持仓时长
- FIFO 已实现、单笔盈亏、缺失成本计数
- 活动推算余额
- 平台 display fallback（非 Launchpad / 特殊资产）
- Completeness 文案与 0 空单元格断言
- activity fingerprint

---

## 5. 能从链上直接验证的字段

当前 **零实现**。可验证但未做：

| 字段 | 链上依据 |
|---|---|
| 交易是否存在 / 成功 | `getTransaction` |
| first_buy_time | `blockTime` |
| first_buy_amount | `preTokenBalances` / `postTokenBalances` delta |
| first_buy_sol | wallet SOL/WSOL delta − fee |
| Gas SOL | `meta.fee` / 1e9 |
| 当前余额 | `getTokenAccountsByOwner` / `getTokenAccountBalance` |
| 当前供给 | `getTokenSupply` |
| Mint 创建 | 初始化 mint 的 signature + `blockTime` |
| Launchpad | 创建交易 `programIds` vs 已知 Program Registry |
| TransferIn | ATA 入账且非 swap |

---

## 6. 属于第三方市场数据的字段

当前全部来自 GMGN，没有 Moralis / DEX Screener：

- 当前价格、当前市值、FDV、流动性、pair 标签、`pairCreatedAt`
- Swap USD（`bought.usdAmount` / `totalValueUsd`）
- Token metadata 批量（name/symbol/decimals/supply/marketCap）

DEX Screener 官方：`pairCreatedAt` 是 **Pool 创建时间**，禁止当作 Token 创建时间。

---

## 7. 当前 429 对哪些业务链路产生阻塞

观测（源码 + V3 事故日志 + 本轮 raw dump `9P9aAh3kdMK651Cc`）：

1. **报告窗 activity 分页**：weight=3，Token 发现的唯一入口。429 → 整钱包停。
2. **每 Token 全历史 activity**：最大 GMGN 消耗源。N Token × 多页。
3. **wallet_stats / wallet_profits**：任务开头，429 会 `raise`。
4. **token_info / pool_info**：每 Token 各 1 次（有缓存/SingleFlight），weight=1 仍会 429。
5. **CredentialScheduler GLOBAL_COOLDOWN**：多 Key 同时 429 时 **所有 GMGN 请求** 等待；且当前没有其它数据源，等于整个 Job 停住。
6. **JobEngine `_guard_api`**：没有 HEALTHY Key 就 `wait_for_available_credential`，UI 显示 WAITING_API，任务不算失败但实质空转。

V4 必须：GMGN 429 **不得** 暂停 Moralis / RPC / DEX Screener。

---

## 8. 当前 SQLite schema

`app/storage/database.py` + `migrations.py`：

- `wallet_reports`（已加 `job_id` / `wallet_task_id`）
- `trades` UNIQUE(`activity_fingerprint`)
- `token_info_cache` / `token_pool_cache`
- `analysis_results`
- `api_cache`
- `task_runs`
- `token_history_meta`（`bottom_complete` 增量头）
- `analysis_jobs` / `jobs` / `wallet_tasks`

**缺失：** `provider_cache` `evidence` `resolved_fields` `token_metadata_cache` `token_market_cache` `mint_creation_cache` `pool_cache` `provider_metrics` `transactions`（链上核验缓存）。

---

## 9. 当前 Raw JSON 保存方案

`app/storage/raw_dump.py`：`data/raw/<job_id>/<wallet[:16]>/<ts>_<route>_<uuid6>.json`

V3 已修并发撞名。仍只保存 GMGN 响应。V4 应对 Moralis / RPC / DEX / Helius 同样落盘，且 **禁止写入 API Key**。

---

## 10. 当前缓存策略

| 缓存 | TTL | 键 |
|---|---|---|
| token_info | 12h 默认 | `(chain, mint)` |
| token_pool | 30min | `(chain, mint)` |
| trades + history_meta | 长期，增量头同步 | `(wallet, mint)` |
| GMGN token_info/pool SingleFlight | 进程内 | route+mint |
| wallet_stats | 配置有 TTL 字段，**业务未真正用独立 stats cache** | — |

无跨钱包 metadata 去重批处理：两钱包同 USDC 仍可能各打 GMGN（SingleFlight 仅同进程同时请求）。

---

## 11. 当前 First Buy 算法

1. 报告窗 `wallet_activity` 发现 Token。
2. 对该 mint `wallet_activity?token=` 直到 `next is null`（或 `bottom_complete` 后只增量头）。
3. `resolve_acquisition`：timestamp 最小的 `buy`。
4. 无 buy → 最小 `transferIn` → 特殊资产 BRIDGE/WRAPPED → UNKNOWN。
5. **时间戳来自 GMGN activity，未经 `getTransaction.blockTime` 裁决。**
6. **不会区分 Swap Buy vs 单纯 Transfer 入账的链上证据。**

---

## 12. 当前 Platform Resolver

优先级：

1. `token_info.launchpad_platform` / `launchpad` / activity launchpad
2. 特殊资产登记（mint 精确匹配，不用 symbol）
3. autofill 时用 `pool.exchange` 作为 **display**（会把流动性平台显示成「来源」）
4. 否则「非 Launchpad」

已知问题：display 仍可能用 Raydium 冒充发行来源。Launchpad / asset_source / liquidity_platform 字段已拆，但证据只来自 GMGN。无 Program ID 注册表。

---

## 13. 当前 PnL 算法

- **本地 FIFO**：Buy/Add 入列；TransferIn 入列但 `known_cost=False`；Sell 匹配，不可验证则「无法验证历史成本」，不填 0。
- **GMGN profits**：钱包级 `realized_profit` / `total_profit`，单 Token 不拆分。
- **无共识**：不比较 local vs provider，无 CONFLICT。
- 余额 = FIFO 剩余 lots，不是链上余额。

---

## 14. 当前 task / job 架构

```
GUI(CustomTkinter) 仅 分析任务 / 历史 / 导出 / 设置 / 关于
  └─ AnalysisWorker 线程
       └─ AnalysisJobEngine
            └─ WalletAnalysisService
                 ├─ GMGNClient + CredentialScheduler（每 Key limiter）
                 ├─ ActivityCollector
                 ├─ TokenEnricher（info/pool）
                 ├─ AcquisitionResolver / PlatformResolver / FIFO
                 ├─ CompletenessService
                 └─ ExportService
```

- `job_id` 与 `wallet_task_id = job_id:wallet` 已分离（V3）。
- 新 Job **不** `limiter.reset()`。
- 多钱包 ThreadPool 公平跑；Token 级 workers 来自 `GMGN_API_WORKERS`。
- `batch_page.py` 仍存在但侧边栏不再挂「任务进度」导航。
- Service **直接** 调 `client.get_*`。无 Provider / Evidence / Orchestrator。

---

## 15. 429 / 限流现状（不是本轮优化目标）

已有且应保留：每 Key limiter、safety margin、min-spacing、换 Key、GLOBAL_COOLDOWN、429 不双计（V3 已修）。

本轮改变的是 **职责**：这些只作用于 `GMGNVerifierProvider`。Moralis / RPC / DEX / Helius 必须有 **独立** limiter 与 circuit breaker。

---

## 16. GUI 现状

- 分析页顶部：Job 摘要 + GMGN Key 卡 + 429/缓存。
- 设置页：仅 GMGN Keys / Base / 套餐 / rate。
- 无 Provider Health 条。
- Token 表无「RPC VERIFIED / ESTIMATED」来源标签。
- `APP_NAME` = GMGN 钱包分析工具，`version=1.1.0`。

---

## 17. 测试现状

已有：First Buy 窗口、FIFO、Transfer、Platform、homonym、empty export、rate limiter、parsers、cancel、V3、integration cursor。

**没有：** Moralis 分页、batch=100/30、RPC first buy、Gas lamports、GMGN 全 429 任务仍成功、circuit breaker、CONSENSUS/CONFLICT、pool vs mint created、entry MC ESTIMATED。

---

## 18. 密钥与安全

`.env.example` 仅 GMGN。`.gitignore` 已忽略 `.env` `data/` `logs/` `output/`。V4 需增加 Moralis / Helius / RPC URL，且禁止写入日志、SQLite、Excel、raw JSON、Git。

---

## 19. 迁移约束

- 不删除现有 GMGN client / scheduler / multi-key。
- 不丢 `trades` / `token_history_meta` / `wallet_reports`。
- 旧 First Buy / FIFO / Completeness 测试必须继续通过。
- GMGN 无 Key 或全 429 时，有 Moralis/RPC 仍应产出 Excel。
- 无 Moralis Key 时程序不崩，降级 Helius/RPC/GMGN，GUI 提示建议配置 Moralis。
