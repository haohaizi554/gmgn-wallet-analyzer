# V4 字段矩阵

主键永远是 `(chain, mint)`。`symbol` 只用于展示。

状态：`VERIFIED` `CONSENSUS` `DIRECT` `DERIVED` `ESTIMATED` `NOT_APPLICABLE` `UNRESOLVED` `CONFLICT`。

无法取得时 **禁止** `None` / `""` / `NaN` / `0` 伪装。必须输出明确语义。

| 字段 | 主数据源 | 备用 | 最终裁决 | 可计算 | 允许 ESTIMATED | 无法取得时的明确值 |
|---|---|---|---|---|---|---|
| token_address | Moralis swap / RPC mint | GMGN activity | mint 原文 | 否 | 否 | 跳过无 mint 的记录 |
| symbol | Moralis metadata batch | Helius DAS / Metaplex / GMGN | 一致→CONSENSUS；不同→CONFLICT 保留双值 | 否 | 否 | 未知 |
| name | 同上 | 同上 | 同上 | 否 | 否 | 未知 |
| decimals | Moralis / mint account | RPC `getAccountInfo` | RPC mint | 否 | 否 | 无法验证 |
| acquisition_type | Moralis swaps | Helius transfers / RPC / GMGN | 链上 token delta + 是否存在 swap | 是 | 否 | UNKNOWN（未发现历史买入） |
| first_buy_time | Moralis earliest BUY tx | Helius / GMGN | **Solana `blockTime`** | 否 | 否 | 无 Buy：不适用（转入获得）；否则无法验证 |
| first_buy_tx | Moralis `transactionHash` | Helius / GMGN | RPC signature 必须能 `getTransaction` | 否 | 否 | 无法验证 |
| first_buy_amount | 链上 token delta | Moralis `bought.amount` | RPC pre/post token | 是 | 否 | 无法验证 |
| first_buy_usd | Moralis `bought.usdAmount` / `totalValueUsd` | 历史价 × 链上数量 | 成交隐含价优先于 K 线 | 是 | 否 | 无法验证历史美元成本 |
| first_buy_sol | 链上 SOL/WSOL delta − fee | Moralis sold 若为 SOL | RPC；USDC 对为 NOT_APPLICABLE 或 DERIVED 折算 | 是 | 折算时是 | 不适用 / 无法验证 |
| actual_quote_asset | Moralis sold.address | RPC transfers | RPC | 否 | 否 | 无法验证 |
| actual_quote_amount | Moralis sold.amount | RPC | RPC | 否 | 否 | 无法验证 |
| equivalent_sol_amount | 历史 SOL/USD | — | DERIVED/ESTIMATED，不得伪装成交 SOL | 是 | 是 | 无法验证 |
| gas_sol | RPC `meta.fee` | Helius | RPC | 是 | 否 | 无法验证 |
| gas_usd | fee_sol × **当时** SOL/USD | Moralis 同期 | 无历史 SOL 价则 UNRESOLVED | 是 | 否 | 无法验证历史SOL价格 |
| mint_created_at | Mint initialize tx | Helius / GMGN creation | RPC blockTime | 否 | 否 | 无法验证 |
| metadata_created_at | Metaplex account | — | 不得覆盖 mint_created_at | 否 | 否 | 无法验证 |
| pool_created_at | DEX Screener `pairCreatedAt` | GMGN pool | Pair 创建，非 Token 创建 | 否 | 否 | 无法验证 |
| open_at | GMGN `open_timestamp` | — | 辅助 | 否 | 否 | 无法验证 |
| time_diff | 本地 first − mint_created | — | 本地 | 是 | 否 | 无法计算 |
| holding_duration | 本地 | — | 清仓 last_sell−first；否则 now−first | 是 | 否 | 无法计算 |
| launchpad_platform | 创建 tx program IDs | GMGN launchpad + registry | Program registry；不用 symbol | 是 | 否 | 非 Launchpad |
| asset_source | special_assets.json | 证据充分的发行方 | 仅有证据时填写 | 否 | 否 | 无登记资产来源 |
| liquidity_platform | DEX Screener 主池 dexId | Moralis exchangeName / GMGN | PoolResolver | 否 | 否 | 无法验证 |
| primary_pool | DEX Screener 最大流动性完整池 | Moralis pairAddress | PoolResolver 非 result[0] | 否 | 否 | 无法验证 |
| current_price_usd | Moralis metadata / swap | DEX Screener priceUsd / GMGN | 误差≤5% CONSENSUS；>10% CONFLICT | 否 | 否 | 无法验证 |
| market_cap | Moralis `marketCap` | DEX `marketCap` / GMGN | 同上，禁止用 FDV 顶替 | 否 | 否 | 无法验证 |
| fully_diluted_value | Moralis `fullyDilutedValue` | DEX `fdv` | 与 market_cap 分列 | 否 | 否 | 无法验证 |
| entry_market_cap | first_buy_price × historical_supply | 当前 supply | 供给未变且可证→DERIVED；仅当前供给→ESTIMATED | 是 | 是 | 历史供应量不可验证 / 无可验证历史市值 |
| historical_supply | 当时链上 supply / 交易内 | 当前 `getTokenSupply` | 能证明未变才 DERIVED | 是 | 当前供给时是 | 历史供应量不可验证 |
| official_balance | RPC token account | Moralis portfolio / Helius DAS | RPC | 否 | 否 | 无法验证 |
| derived_activity_balance | 本地 FIFO | — | 仅 cross-check | 是 | 否 | 活动推算余额 |
| balance_source | 上列优先级 | — | RPC > Moralis > 活动推算 | 否 | 否 | DERIVED_FROM_ACTIVITY |
| local_fifo_realized_pnl | 本地 FIFO | — | 本地 | 是 | 否 | 无法验证历史成本 |
| provider_reported_pnl | GMGN profits | Moralis 若有 | 不覆盖本地；接近 CONSENSUS | 否 | 否 | GMGN限流，已使用其它数据源验证 / 接口不支持该周期 |
| buy_count / sell_count | 报告窗 swaps | GMGN | 本地计数 | 是 | 否 | 0 仅当窗口内确实没有 |
| buy_total_usd / sell_total_usd | swaps usdAmount | GMGN cost_usd | 本地求和 | 是 | 否 | 无法验证 |
| coverage_* | CompletenessAuditor | — | 本地 | 是 | 否 | 0 |

## 交叉验证触发

| 级别 | 字段 | 策略 |
|---|---|---|
| Critical | First Buy、Acquisition、Creation、Entry MC、PnL | 多源 + 链上（按 VERIFICATION_MODE） |
| Normal | name/symbol/decimals | 主源可信即可 |
| Market | price / market cap / FDV | Moralis + DEX Screener，冲突不静默 |

## Provider 优先级

| Capability | 顺序 |
|---|---|
| WALLET_SWAPS | Moralis → Helius Enhanced → GMGN → Raw Solana |
| WALLET_TRANSFERS | Helius → RPC reconstruction → GMGN activity |
| WALLET_BALANCES | Solana RPC → Moralis portfolio → Helius DAS |
| TRANSACTION_DETAIL | Solana RPC → Helius RPC |
| TOKEN_METADATA | Moralis Batch → Helius → on-chain Metaplex → GMGN |
| TOKEN_MARKET | Moralis → DEX Screener → GMGN |
| TOKEN_POOLS | DEX Screener → Moralis → GMGN |
| TOKEN_CREATION | RPC mint finder → Helius → GMGN |
| HISTORICAL_PRICE | 成交隐含价 → pair OHLC → 其它 |
| PNL | Local FIFO → GMGN |
| LAUNCHPAD | Program IDs + registry → GMGN → special assets |

## 验证模式

| Mode | 链上核验 |
|---|---|
| FAST | First Buy + Creation |
| **BALANCED（默认）** | First Buy + Creation + Transfer acquisition + 冲突 + 随机 5% |
| STRICT | 所有关键交易 |

`ENABLE_GMGN_DEEP_HISTORY_FALLBACK=false`：禁止默认每 Token 把 GMGN activity 翻到底。
