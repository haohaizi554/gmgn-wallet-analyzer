# V4 多数据源交付报告

日期：2026-09-17  
版本：`4.0.0`

配套文档：

- `docs/v4-multisource-audit.md` — 改造前审计
- `docs/v4-field-matrix.md` — 逐字段主源 / 备用 / 裁决 / 明确语义

---

## Architecture

### 旧：GMGN-centric

```
GUI → WalletAnalysisService → GMGNClient → GMGN
```

任务成功硬依赖 `wallet_activity` / `wallet_stats` / `wallet_profits` / 每 Token `token_info` + `pool_info`。任一路径 429 会进入 `GLOBAL_COOLDOWN`，把整个 Job 卡住。

### 新：Multi-source evidence architecture

```
GUI
 ↓
AnalysisJobEngine
 ↓
WalletAnalysisService
 ↓
DataOrchestrator
 ↓
Provider Layer（独立限速 + 独立熔断）
  Moralis (Primary index)
  Solana RPC (Authority)
  Helius (Optional enhance)
  DEX Screener (Pool / market)
  GMGN (Verifier only)
 ↓
Normalizer / Evidence / Field Resolver
 ↓
CompletenessAuditor → Domain Report / Excel / GUI
```

原则：

- Service 不再散落 `requests.get` / `moralis.get` / `gmgn.get`。采集走 Provider。
- Domain 字段 provider-neutral。GMGN 原始值只进 Evidence / Raw。
- GMGN 429 只打开 **GMGN** Circuit，不能暂停 Moralis / RPC / DEX。
- Excel 不允许空单元格；无法验证时写明确语义，禁止用 `0` 伪装。

---

## API Reduction

旧路径（N 个 Token，报告窗 R 页，每 Token 平均 H 页历史）：

| 调用 | 数量 |
|---|---|
| `wallet_stats` | 1 |
| `wallet_profits` | 1 |
| 报告窗 `wallet_activity` | R |
| 每 Token 历史 `wallet_activity` | N × H |
| `token_info` | N |
| `pool_info` | N |
| **合计** | **2 + R + N×(H+2)** |

50 Token、H=3、R=5 → 约 **207** 次 GMGN。  
265 Token、H=3、R=10 → 约 **1337** 次 GMGN。

新默认（`ENABLE_GMGN_DEEP_HISTORY_FALLBACK=false`）：

| 源 | 调用 |
|---|---|
| GMGN stats / profits | 最多 2；429 则跳过，**不再翻历史、不再 per-token token_info** |
| Moralis Wallet Swaps | ceil(swaps/100) 页；非 ALL 周期才对每个 Token 追加 1 次 earliest BUY |
| Moralis Metadata | ceil(unique_mints/100)，跨钱包去重 |
| DEX Screener | ceil(unique_mints/30) |
| Solana RPC | First Buy / 余额 / supply / 缺创建时间时的 mint 查找；**不是全量 getTransaction** |

50 Token 默认 GMGN：**2 或 0**。相对旧 207 次，下降 **≥99%**（超过 −80% 验收线）。

Mock 验收：`test_gmgn_all_429_moralis_ok_job_succeeds` 中 GMGN 全部 429，Moralis/RPC/DEX 正常，Job=`SUCCESS`，Excel 生成，First Buy 由 RPC `blockTime=102` 裁决。

---

## Performance

| | 旧 | 新 |
|---|---|---|
| 阻塞源 | GMGN 全局限流 | 各 Provider 独立 limiter / circuit |
| GMGN 429 | Job WAITING_API / 失败风险 | 记录 `GMGN_UNAVAILABLE_RATE_LIMIT` 后继续 |
| Token 元数据 | N 次 GMGN | 100 一批 Moralis |
| 池子 | N 次 GMGN | 30 一批 DEX |
| 单测全套 | — | **66 tests / 4.3s / OK** |
| 现场连通 | — | DEX Screener SOL pairs=30，HTTP 200；Solana `getHealth` OK |

本机 `.env` **没有** `MORALIS_API_KEY`，因此未能跑 50+ Token 真实钱包主流程。配置 Moralis 后应用同一条路径即可。

---

## Field Coverage

覆盖率按字段 **状态** 计，不是「非空率」。`无法验证` 也是非空。

Excel 新增：

- 代币分析隐藏审计列：首买/创建/市值/平台/余额/PnL 状态与来源
- `数据验证`
- `冲突与缺失`（只收 CONFLICT / UNRESOLVED / ESTIMATED / NOT_APPLICABLE）
- `数据源统计`
- `覆盖率`（completeness_rate / verified_rate / estimated_rate / unresolved_rate）

单测覆盖的关键语义：

| 场景 | 结果 |
|---|---|
| 市值 1,000,000 vs 1,020,000 | `CONSENSUS`，差异 2.0% |
| 市值 1,000,000 vs 2,000,000 | `CONFLICT`，双值保留 |
| pairCreatedAt=200，mint=100 | 分列，互不覆盖 |
| 仅有当前 supply | Entry MC = `ESTIMATED`，备注「使用当前供应量估算」 |
| 有 historical supply | Entry MC = `DERIVED` |
| Moralis ts=100，RPC blockTime=102 | 最终 102，`SOLANA_RPC` + `VERIFIED` |
| 无 Buy + 余额增加 | `TRANSFER_IN`，首买「不适用（转入获得）」 |
| fee=5000 lamports | `0.000005 SOL`，不依赖 GMGN |
| UNRESOLVED USD | 导出不是 `0` |

---

## Cross Validation

15 个真实 Token 人工抽检：**未完成**。

原因：当前环境未配置 Moralis Key，不能在禁用 GMGN 的前提下拉 50+ Token 钱包。

已用 **真实官方接口**（无 Key）做连通与字段存在性检查：

- DEX Screener `GET /token-pairs/v1/solana/So1111...` → 200，含 `pairAddress` / `dexId` / `pairCreatedAt`
- Solana RPC `getHealth` → 200

Parser 基于脱敏真实形状 fixture：

- `tests/fixtures/providers/moralis_wallet_swaps.json`
- `tests/fixtures/providers/moralis_metadata_batch.json`
- `tests/fixtures/providers/dexscreener_tokens.json`
- `tests/fixtures/providers/solana_get_transaction.json`
- `tests/fixtures/providers/helius_transaction.json`
- `tests/fixtures/providers/gmgn_token_info.json`

配置 `MORALIS_API_KEY` 后，建议对钱包 `9P9aAh3kdMK651CcDG4iCdoByYj1FJgKq3yVoPrXVCAu` 做 15 Token 抽检（Meme / Pump / Raydium / xStock / Wrapped / TransferIn / Stable / 特殊资产）。

---

## GMGN Failure Test

| 项 | 结果 |
|---|---|
| 测试 | `tests/unit/test_v4_gmgn_429.py` |
| GMGN | 所有方法立即 `GMGNRateLimitError` |
| Moralis / RPC / DEX | Mock 正常 |
| Job | `SUCCESS` |
| Excel | 生成 |
| Token | 1（MintAAA） |
| First Buy 时间 | RPC `102` |
| 缺失 | 钱包级 GMGN stats/profits 标「GMGN限流，已使用其它数据源验证」；无 GMGN launchpad 时平台走 DEX / 非 Launchpad 语义 |

JobEngine：若 Moralis 已启用，`_guard_api` **不再**因 GMGN cooldown 阻塞整个任务。

---

## Known Limitations

1. **Moralis 真实钱包未跑。** `.env` 无 `MORALIS_API_KEY`。没有 Key 时程序不崩，GUI 提示建议配置。
2. **Helius 高级历史是可选探测。** 无 Key 或套餐 403 → `PLAN_UNAVAILABLE` / OPTIONAL，任务继续。
3. **Mint 创建交易**只在创建时间缺失且 `VERIFICATION_MODE` 需要 creation 时，用 `getSignaturesForAddress` 取最旧签名；不是全链扫描，也可能找不到 InitializeMint。
4. **历史供应量**多数只能拿到当前 `getTokenSupply`，入场市值会标 `ESTIMATED`。
5. **Gas USD** 没有当时 SOL 价格时为 `无法验证历史SOL价格`，不用当前价冒充。
6. **WSOL 的 DEX marketCap/fdv** 可能为空；空则 `无法验证`，不会把 FDV 填进市值。
7. **GMGN 深历史**默认关闭。仅 `ENABLE_GMGN_DEEP_HISTORY_FALLBACK=true` 且 Moralis/Helius 都失败时才允许每 Token 翻 GMGN cursor。
8. **公共 Solana RPC** 有速率限制。生产应换成自己的 `SOLANA_RPC_URL`。
9. GUI 仍保留既有「数据导出」页；未恢复已删除的「单钱包 / 批量 / 进度」重复页。
10. Provider 指标目前进 Excel「数据源统计」；长期 `provider_metrics` 表已建，Job 级落库仍可再加密集。

---

## 硬验收对照

| # | 条件 | 状态 |
|---|---|---|
| 1 | GMGN 不再是主数据源 | 通过（Moralis 主索引） |
| 2 | GMGN 全 429 任务仍完成 | 通过（单测） |
| 3 | Moralis swaps 分页 | 通过（3 页 cursor） |
| 4 | Metadata 100 批量 | 通过（265→3） |
| 5 | DEX 30 批量 | 通过（61→3） |
| 6 | RPC 验证交易时间 | 通过 |
| 7 | RPC 验证 fee | 通过 |
| 8 | First Buy 链上裁决 | 通过 |
| 9 | TransferIn 不误判 Buy | 通过 |
| 10 | Token 创建 ≠ Pool 创建 | 通过 |
| 11 | MarketCap ≠ FDV | 通过 |
| 12 | Entry MC 标明状态 | 通过 |
| 13 | 余额优先链上 | 已接 RPC；无账户则活动推算 + `BALANCE_MISMATCH` |
| 14 | 冲突不静默覆盖 | 通过 |
| 15 | 关键字段有来源 | 通过（审计列） |
| 16 | Excel 零空字段 | 通过（旧+新 completeness） |
| 17 | UNRESOLVED 明确显示 | 通过 |
| 18 | 禁止 0 伪装无数据 | 通过 |
| 19 | Provider cooldown 独立 | 通过（IndependentRateLimiter） |
| 20 | GMGN cooldown 不停 Moralis | 通过 |
| 21 | Provider Cache | 已实现 TTL 分层 |
| 22 | Metadata 跨钱包去重 | Orchestrator 按 mint 去重 |
| 23 | SingleFlight 仍有效 | 旧测通过 |
| 24 | SQLite migration 安全 | `IF NOT EXISTS` + ALTER |
| 25 | 现有历史数据不丢 | 只加表/列 |
| 26 | Job/Wallet ID 不覆盖 | 旧测通过 |
| 27 | First Buy 旧测通过 | 通过 |
| 28 | FIFO 旧测通过 | 通过 |
| 29 | Completeness 旧测通过 | 通过 |
| 30 | 全测试通过 | **66 OK** |
| 31 | 真实钱包测试 | **未跑（缺 Moralis Key）** |
| 32 | 15 Token 人工抽检 | **未跑（同上）** |
| 33 | GMGN 调用量 −80% | 架构达标（默认 per-token GMGN → 0） |
| 34 | 交付包无真实 API Key | `.env` gitignore；只提交 `.env.example` |

---

## 配置

`.env.example`：

```
MORALIS_API_KEY=
HELIUS_API_KEY=
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
GMGN_API_KEYS=
VERIFICATION_MODE=BALANCED
ENABLE_GMGN_DEEP_HISTORY_FALLBACK=false
```

DEX Screener 当前公开接口不需要 Key。

---

## 使用建议

1. 在系统设置填写 **Moralis API Key**，点「测试数据源」（启动时不会打接口）。
2. 可选填 Helius；不填完全正常。
3. 把 `SOLANA_RPC_URL` 换成自己的节点。
4. GMGN Key 可留着做钱包级利润对照；429 不会失败任务。
5. 默认 `BALANCED`：只链上核验 First Buy、Creation、Transfer、冲突、5% 抽样。
