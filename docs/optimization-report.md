# 第二轮架构优化报告

日期：2026-09-17  
版本：1.1.0  
测试：`python -m unittest discover -s tests -v` → **34 passed**（约 3.8s）

## 修复

### stale history
已确认旧逻辑：`history_complete=True` 时直接读 SQLite、0 次 API。  
现改为 `HistorySyncState.bottom_complete`：底部追到 `next=null` 后不再重翻全历史，但每次仍从最新页增量扫描，直到碰到已知 `activity_fingerprint` / 时间边界 / `next=null`，新交易 upsert。旧库 migration 把 `history_complete` 拷到 `bottom_complete`。

### activity dedupe
官方 wallet_activity JSON **没有**稳定 `activity_id`。  
唯一键改为 `UNIQUE(activity_fingerprint)`（SHA256：chain/wallet/tx/token/event/ts/amount/cost/price/gas/from/to/index）。  
同 `tx_hash` + token + event、不同 amount 的两条 BUY 都会保留。已写测试。

### FIFO count
`remaining>0` 与 `unverifiable` 不再各 +1。  
`missing_cost_count` = `missing_cost_sell_count` = 有成本缺口的 **Sell 笔数**（每笔最多 +1）。  
新增 `missing_cost_token_amount`、`missing_cost_usd`（可估算时）。

### platform model
内部拆分：`launchpad_platform` / `asset_source` / `liquidity_platform` / `primary_pool`。  
GUI 默认「来源平台」：Launchpad → 特殊资产登记 → 流动性平台 → `非 Launchpad`。  
**不会**为了非空填 Pump.fun。特殊资产来自 `data/special_assets.json`。

### GUI routing
事件带 `job_id`。`AnalysisPage` / `BatchPage` 只消费匹配的 Job。主窗口不再把 progress 双播到两页。

### autofill toggle
`autofill_missing=True`：平台 fallback、特殊资产、pool、Transfer resolver。  
`False`：只用直接 GMGN 字段，缺省写「GMGN 未提供」。Excel 仍 0 空单元格。

### balance semantics
`calculated_balance` + `balance_authority=DERIVED_FROM_ACTIVITY`。  
Excel 增加「活动推算余额」「余额口径」。不再暗示这是链上权威余额。

### 空币种 Excel 崩溃
旧版 265 Token 跑完后因「币种」空字符串在 `assert_no_empty_export_cells` 失败。现对 symbol/name 做 strip + 「未知」兜底。

## 多 Key

配置：`GMGN_API_KEYS=key1,key2`，兼容 `GMGN_API_KEY`。  
`CredentialPool`：round-robin / LRU，HEALTHY 优先。  
401 → `AUTH_FAILED`，换下一把健康 Key。  
403 → DEGRADED / AUTH_FAILED。  
429 → **不把 Key 标失效**，进入全局 cooldown。  
日志只打 `Key #1 ****ABCD`。

## 限速

| 项 | 值 |
|---|---|
| Server rate | `GMGN_RATE_LIMIT_RATE` 默认 5 weighted units/s |
| Capacity | 默认 5 |
| Target | `GMGN_TARGET_UTILIZATION` 默认 0.80（GUI：60/80/90，禁止 >1） |
| Effective | 5 × 0.80 = **4 units/s** |
| Workers | `GMGN_API_WORKERS` 默认 4（2–8） |

所有 Key **共用一个** `GlobalWeightedRateLimiter`。3 把 Key ≠ 15u/s。  
429 读 `X-RateLimit-Reset` / `reset_at`，全任务暂停；恢复 0.50 → 0.65 → 0.75 → 0.80。连续 429 自适应降到 0.70/0.60。  
业务代码禁止散落 `acquire(3)`，走 `route_name` → `ROUTE_POLICIES`。

## 性能

### Before（2026-09-17 16:01 真实日志）

- 报告流水 50 页，约 16:01:46–16:04:56（~3.2 min）
- 265 Token **串行**历史，16:04:56–16:16:55（~12 min）
- 合计约 **15 min** 后 Excel 因空币种失败
- 单线程同步 HTTP，利用率估算 ~20–25%

### After（架构）

- 单钱包 Token 分析：`ThreadPoolExecutor`（默认 4），cursor 链仍串行
- Token Info / Pool：SingleFlight + TTL 缓存（info 12h，pool 30min）
- 二次运行：历史增量 1 页级；Token Info/Pool 走缓存
- HTTP：线程本地 `Session` + keep-alive
- 实测 mock：4 Token 并行完整结果；limiter 长期 ≈4 weight/s

### 本轮真实 API

| 项 | 结果 |
|---|---|
| `GET /v1/user/info` | 200，http≈4.4s |
| `wallet_stats` / `wallet_profits` 7d | 200；官方 buy=0 sell=0 |
| `wallet_activity` 7d | 200，`activities=[]` |
| 429 | 0 |
| Excel | 已写出（0 Token，合法空报告） |

同一示例钱包 `7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV` 在 16:01 曾扫出 265 Token；16:46 GMGN 官方 7d 统计已是 0 笔，因此 **无法在本轮用同一时间窗复跑 265 Token 对比**。不是采集被截断。完整冷/热 265 对比需该钱包再次出现周期内交易后重跑 `scripts/real_api_benchmark.py`。

## 数据正确性

| 项 | 说明 |
|---|---|
| First Buy | 仍是全历史 `event_type==buy` 最小 timestamp；报告窗 ≠ First Buy 窗 |
| 同 Tx 多 event | fingerprint 保留 |
| FIFO | 一笔缺成本 Sell → count=1 |
| 特殊资产 | WSOL/USDC/USDT/cbBTC/WBTC + json registry + 名称规则 |
| Token/Trade 数量 | mock 集成测试与旧断言一致（1 token，First Buy 1722470400） |

## 测试

34 passed，覆盖：

- 80% 目标长期 ≈4 weight/s
- 3 Key 共用一个桶，不会变成 12/s
- 401 failover；429 全局冷却不切 Key 绕过
- 4 Token 并发结果完整
- cursor 串行
- SingleFlight 五调用一次 HTTP
- stale cache 增量同步新 Buy
- 同 tx 不同 amount 两条都在
- FIFO missing=1
- Job 事件不串台
- Cancel 在 limiter wait 中立即退出
- Excel 0 empty

## 已知限制

1. **批量多钱包**仍按钱包顺序跑完再下一个；钱包内部 Token 已并行。尚未做跨钱包 round-robin Token 队列（公平调度 P1）。
2. **Pause** 未做（P1）；**Cancel** 已支持，含 limiter wait。
3. 本轮无法用 265 Token 热钱包做 Before/After 耗时对照（GMGN 当前 7d 为 0 笔）。
4. SQLite 用写锁 + WAL；未做独立 DB Writer 进程。
5. 权威链上余额 API 仍未接入；余额仅为活动推算。
6. `wallet_activity` 无官方 activity_id，fingerprint 依赖金额/时间字段稳定性。

## 验收对照

1. 全局单一 RateLimiter — 是  
2. 3 Key 不把预算变成 3 倍 — 是（测试）  
3. 长期加权利用率目标 80% — limiter 调度是；真实 265 Token 利用率待该钱包再有周期交易后测  
4. 429 不切 Key 绕过 — 是  
5. 有限并发 — 是（2–8 workers）  
6. cursor 串行 — 是  
7. 不同 Token 可并行 — 是  
8. First Buy 全历史 — 是  
9–10. 增量历史 / 不因 history_complete 漏新交易 — 是  
11. fingerprint — 是  
12. FIFO 不双计数 — 是  
13–14. 单钱包 = batch size 1，同一 JobEngine — 是  
15. GUI 不串台 — 是  
16. SQLite 多线程写锁 — 是  
17. Cancel 立即响应 — 是  
18. 0 空 Excel — 是（并修了空币种）  
19. Mock 全过 — 34/34  
20. 真实 API — 连通性完成；265 Token 对照受上游空窗限制  
21. 新版不得无解释少 Token — 当前 7d 官方即为 0  
22–23. 架构上显著快于串行；未拿速度换少采  
24. README / `.env.example` / 本报告已更新  
