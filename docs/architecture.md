# 架构说明

## 目标

Windows 桌面工具：输入 Solana 钱包地址与时间范围，通过 GMGN OpenAPI 拉取交易与 Token 元数据，产出可审计的首次买入、来源平台、时差、盈亏与 Excel。

核心原则：**准确、完整、可解释、可恢复、0 空字段**。主键永远是 `(chain, token_address)`。

## 分层

```
GUI (CustomTkinter, 主线程)
  └─ queue.Queue ← Worker Thread
       └─ WalletAnalysisService
            ├─ GMGNClient + WeightedRateLimiter
            ├─ ActivityCollector（cursor 直到 next=null）
            ├─ AcquisitionResolver（min timestamp Buy / TransferIn）
            ├─ TokenEnricher + PlatformResolver
            ├─ FIFO PnL
            ├─ CompletenessService
            └─ ExportService → Excel / JSON
SQLite：缓存、断点、历史报告、审计
```

GUI 主线程禁止 HTTP。Worker 禁止直接改 widget。停止使用 `threading.Event` 协作退出。

## 分析流程

1. 校验 Solana Base58 地址
2. `wallet_stats`、`wallet_profits`（仅当周期属于 1d/7d/30d/all）
3. 无 token 过滤地翻 `wallet_activity`，收集报告窗口内交易（`max_transactions` 只限制这一步）
4. 对每个 `token_address` 独立 `wallet_activity?token=`，翻到 `next == null`
5. First Buy = 全部历史里 `event_type=buy` 且 timestamp 最小的一笔
6. 无 Buy 则看 TransferIn / 特殊资产
7. Token Info / Pool → 来源平台多级 fallback
8. FIFO 对账；GMGN 官方利润单独保存
9. Completeness → Excel / JSON / GUI

## 限频

Free 默认 leaky bucket `rate=5, capacity=5`。

| 接口 | weight |
|---|---|
| wallet_activity / wallet_stats / wallet_profits | 3 |
| token_info / token_pool_info | 1 |

429 读取 `X-RateLimit-Reset` 或 JSON `reset_at`，等到该时间再重试，同一请求最多 2 次，禁止空转。

## 认证

每次请求由 `GMGNClient` 注入：

- Header `X-APIKEY`
- Query `timestamp`（Unix 秒）
- Query `client_id`（uuid4，每次新生成）

业务层不得自己拼认证参数。不要求钱包私钥。
