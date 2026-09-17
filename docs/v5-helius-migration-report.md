# V5 Helius 主数据源迁移报告

日期：2026-09-17。版本：5.0.0。

## Before

V4：Moralis 是 `collect_wallet_swaps` / metadata / earliest-buy 的硬主路径。无 Moralis Key 时主索引为空，只能降级 GMGN 深历史。JobEngine 仅在 Moralis enabled 时跳过 GMGN cooldown。GUI 要求 Moralis 或 GMGN。

基线测试：66 passed。

## After

Helius 是默认主 Provider：

1. Wallet History（运行时 capability probe == AVAILABLE 才用）
2. 失败/套餐不可用 → Standard RPC fallback（钱包签名 + 有限 ATA）
3. Moralis 仅在 `ENABLE_MORALIS=true` 且有 Key 时作为可选交叉验证
4. GMGN 仍只做 stats/profits 辅助；429 不阻塞 Helius / DEX

默认免费路径：`HELIUS_API_KEY` + DEX Screener + Helius/Solana RPC。Moralis 默认关闭。

## Capabilities

本机 `.env` 当前 **没有 HELIUS_API_KEY**，因此本轮未对真实账号做 live probe。

单元测试 mock 覆盖：

| Capability | Mock Free-like | Mock plan unavailable |
|---|---|---|
| RPC | AVAILABLE | — |
| DAS | AVAILABLE | — |
| WALLET_HISTORY | AVAILABLE | PLAN_UNAVAILABLE → RPC fallback，任务不 FAILED |
| GTFA | PLAN_UNAVAILABLE（JSON-RPC method not found） | 不假定 Free 一定有 |
| Enhanced | 探测但不作为主索引 | — |

真实账号能力必须以 GUI「测试数据源」或 Job 启动时的轻量 probe 为准，结果缓存 SQLite `helius_capabilities`（TTL 1h）。

## API Usage

未跑真实 50+ Token 钱包（缺少 Helius Key）。

单元测试验证：

- 100 Token → **1 次** wallet history 分页调用（不是 100 次）
- 3 page cursor 能拼成完整 `WalletHistoryIndex`
- DEX 61 Token → 3 批
- GMGN 全 429 + Helius mock → Job SUCCESS，Excel 生成
- Moralis disabled / 无 Key → 任务不崩
- Provider cooldown 隔离：GMGN 60s cooldown 时 Helius 仍可取历史

## Cold / Warm

未跑真实 Cold/Warm。已落地：

- `wallet_history_state` 增量同步（遇到 known newest signature 停止）
- `getTransaction` / mint creation 走 provider cache
- 本地 `HeliusCreditTracker`（LOCAL ESTIMATE，不是官方剩余额度）

配置 HELIUS_API_KEY 后应用同一钱包跑两次即可对比。

## Accuracy

15 Token 人工抽检未执行（无 Helius Key）。

已用 mock 验证：

- First Buy：history time 100 + RPC blockTime 102 → 最终 102 VERIFIED，两边 evidence 保留
- TransferIn：`acquisition_type=TRANSFER_IN`，first_buy 状态 NOT_APPLICABLE，note 含「转入获得」
- Gas：5000 lamports → 0.000005 SOL

## Coverage

Excel 仍强制 0 空单元格。Coverage sheet 继续输出完整率 / 验证率 / 估算 / 无法验证。Helius 行增加 **估算Credits**（不得写成 Official Credits Used）。

## GUI

系统设置：

- Helius Key、月度 Credit 预算、目标 RPS、测试数据源 + capability 列表
- RPC URL 可选覆盖；有 Helius Key 时按官方 `https://mainnet.helius-rpc.com/?api-key=` 生成
- Moralis：开关 + 多行 Key（增删/轮换），默认关闭
- 分析页不再把 Moralis 当硬依赖

## Tests

`python -m unittest discover -s tests -v`

**80 passed**（原 66 V4 + 14 V5）。

## Known limitations

1. **没有 HELIUS_API_KEY，不能宣布真实 50+ Token / 15 Token 抽检完成。** 配上 Key 后用 GUI「测试数据源」再跑一次钱包即可。
2. RPC fallback 仍是两阶段有限额度，不是无限 ATA 全历史；老钱包深历史可能 PARTIAL。
3. Helius Wallet History 解析是候选，First Buy 最终仍以 `getTransaction` 为准。
4. Credit 统计是本地估算；未知 method 记 `unpriced_requests`，不记成 0。
5. Moralis 两把 Key 已写入本地 `.env`（gitignore），默认架构仍是 optional；本地 `ENABLE_MORALIS=true` 以便轮换交叉验证。
6. 未调用官方 Usage API，GUI 不得显示「官方剩余额度」。
