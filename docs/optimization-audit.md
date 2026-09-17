# 第二轮架构优化审计

审计日期：2026-09-17。以当前源码为准，不按 Goal 假设直接改。

## 1. 当前完整业务流程

`GUI 开始分析` → `AnalysisWorker` 线程 → 对每个钱包串行调用 `WalletAnalysisService.analyze`：

1. 校验地址（GUI）
2. `wallet_stats` → `wallet_profits`（周期不支持则标记 API_MISSING）
3. `wallet_activity` 无 token 过滤，翻页直到早于 start_ts 或 next=null（`max_transactions` 只限制报告窗）
4. 对每个 token **串行**：完整 `wallet_activity?token=` 直到 next=null → Token Info → Pool → First Buy / Transfer → 平台 → FIFO → 完整性
5. Excel / JSON / SQLite 历史报告
6. Worker 把消息丢进 `ui_queue`，主线程 `after(80)` 消费

## 2. API 调用链

全部走 `GMGNClient._request`：Header `X-APIKEY` + query `timestamp`/`client_id`。

| 方法 | 路径 | weight |
|---|---|---|
| GET | `/v1/user/wallet_activity` | 3 |
| GET | `/v1/user/wallet_stats` | 3 |
| POST | `/v1/user/wallet_profits` | 3 |
| GET | `/v1/token/info` | 1 |
| GET | `/v1/token/pool_info` | 1 |
| GET | `/v1/user/info` | 2 |

不调用 `wallet_holdings`。业务层直接 `acquire(weight)` 散落在 client 内，weight 来自 `ENDPOINT_WEIGHTS`。

## 3. RateLimiter

`WeightedRateLimiter`：线程安全 leaky bucket，`rate=5, capacity=5`，**无 80% 目标**，无滑动窗口利用率，无自适应。每次请求前 `acquire(weight)`，HTTP 同步完成才发下一个 → 实际约 0.3–0.5 activity/s（受 RTT 限制，不是 limiter 本身）。

429：读 `X-RateLimit-Reset` / `reset_at`，同请求最多再试 2 次。单 Key。

## 4. 线程模型

- UI 主线程：绘制 + `ui_queue` 轮询
- 分析：`AnalysisWorker(Thread)` **单线程串行钱包和 Token**
- 无 ThreadPoolExecutor，无 in-flight 并发 HTTP
- Worker 不直接改 widget（日志已通过 QueueLogHandler）

## 5. 缓存模型

| 数据 | 表 | TTL | 问题 |
|---|---|---|---|
| Token Info | token_info_cache | 12h | 合理 |
| Token Pool | token_pool_cache | 同 12h | 过长 |
| Trades | trades | 永久 | 粗唯一键 |
| History | token_history_meta.history_complete | **永久视为完整** | **P0 stale** |
| stats/profits | 无 | 每次打 API | |

`history_complete=1` 时 `collect_token_history` **直接读 SQLite，0 次 API**。新 Buy/Sell 会被漏掉。**已在源码确认。**

## 6. First Buy

`resolve_acquisition`：全历史 `event_type==buy` 取 **最小 timestamp**。报告窗 ≠ First Buy 窗。算法正确。风险来自 stale cache 导致历史不完整。

## 7. FIFO

`app/services/pnl_service.py`：Sell 若 `remaining>0` 先 `missing += 1`，随后 `unverifiable` 再 `missing += 1`。**同一 Sell 可 +2。源码确认。** TransferIn 也标 `missing_cost=True` 但不计入 count。

`current_balance` 来自 lot 剩余，被 GUI 当“当前余额”展示，实际是活动推算。

## 8. Trade 唯一键

`UNIQUE(wallet_address, tx_hash, token_address, event_type)`。内存去重同样 4 元组。真实 GMGN JSON **没有** `activity_id` / `log_index`；有 `token_amount`、`cost_usd`、`timestamp`、`from_address`、`to_address`、`is_open_or_close`。同 tx 多笔同 event 不同 amount 会被丢掉。

## 9–10. Worker

`AnalysisWorker`：多钱包 **for 循环串行**。`BatchPage(AnalysisPage)` 只改标题，**同一套 Worker**。无独立 BatchAnalysisWorker。Goal 里“两套业务”不完全成立，但 GUI 有两套页面且消息双播。

## 11. GUI 消息路由

`MainWindow._poll_queue`：非 log 消息先给 `analysis` 页，progress/done 等再给 `batch` 页。**Job 无 id，两页共享同一 worker 状态。已确认。**

## 12. API Key

仅 `GMGN_API_KEY` 单 Key。`.env` + 设置页密码框。无 CredentialPool，无多 Key，无脱敏日志（client 也不打 key）。

## 13. SQLite schema

wallet_reports, trades, token_info_cache, token_pool_cache, analysis_results, api_cache, task_runs, token_history_meta。WAL 在 executescript 里。`check_same_thread=False`，**无 busy_timeout，无写锁**。单 worker 时勉强可；并发后会 lock。

无 migrations 模块。

## 14. 测试覆盖（baseline）

unit：First Buy、Transfer、同名币、平台、空导出、FIFO（只断言 missing>0）、429、Cancel、parser/cursor、formatter。  
integration：mock 全流程 First Buy + Pump.fun。  
**缺**：stale cache、fingerprint 双 activity、FIFO 双计数精确断言、多 Key 共享桶、SingleFlight、Job 路由、增量同步。

## Goal 条目核对

| 假设 | 源码结论 |
|---|---|
| stale history_complete | **真实存在** |
| 粗唯一键丢 activity | **真实存在** |
| FIFO 双计数 | **真实存在** |
| First Buy 窗口错误 | **不存在**（算法对，缓存会间接破坏） |
| 特殊资产硬编码 | **部分存在**（dict 在 py 文件） |
| 平台单一 source_platform | **真实存在** |
| 单 Key | **真实存在** |
| limiter 无 80% / 无并发 | **真实存在** |
| 两套 Worker 业务 | **部分**：一套 Worker，两套 GUI + 双播 |
| autofill 死开关 | **真实存在**（只写入 options，service 未读） |
| 余额语义误导 | **真实存在** |
| Session 每请求新建 | **不存在**：已复用 Session；但非线程安全 |
| GUI 双播 | **真实存在** |
