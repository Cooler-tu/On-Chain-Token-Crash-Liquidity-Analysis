# On-Chain Token Crash & Liquidity Risk Report

## Executive Summary

- **Token:** CREDI ([0xaE6e307c...014c6B](https://etherscan.io/address/0xaE6e307c3Fe9E922E5674DBD7F830Ed49c014c6B))
- **Chain:** Ethereum (Chain ID: 1)
- **Analysis Window:** Block 19000170 to 19008313
- **Incident Block:** Not specified
- **Report Generated:** 2026-07-16 05:18:02 UTC

### Risk Score

| Metric | Value |
|--------|-------|
| **Final Risk Score** | **0.0 / 1.00** |
| **Risk Level** | **LOW** |
| Evidence Confidence | 50.00% |
| Visual | `░░░░░░░░░░░░░░░░░░░░` |


## Token Profile

| Property | Value |
|----------|-------|
| Address | [0xaE6e307c...014c6B](https://etherscan.io/address/0xaE6e307c3Fe9E922E5674DBD7F830Ed49c014c6B) |
| Symbol | CREDI |
| Name | CREDI |
| Decimals | 18 |
| Total Supply | 939978336.0000 |
| Is Contract | True |
| Proxy Address | None |
| Implementation | None |
| Behavior Flags | minting |


## Pool Summary

**2** verified pool(s), **0** unverified candidate(s).

| Pool Address | Protocol | Version | Token0 | Token1 | Fee | Confidence |
|-------------|----------|---------|--------|--------|-----|------------|
| [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | uniswap | v2 | 0xaE6e307c... | 0xdAC17F95... | N/A | 100.00% |
| [0xAB26D209...8a3084](https://etherscan.io/address/0xAB26D20964CC0284e190Bc22e67d52b8A88a3084) | uniswap | v3 | 0xaE6e307c... | 0xC02aaA39... | 10000 | 100.00% |


## Related Addresses

| Address | Label | Category | Confidence |
|---------|-------|----------|------------|
| [0x5C69bEe7...c5aA6f](https://etherscan.io/address/0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f) | Factory (uniswap)_v2 | protocol_deployment | 100% |
| [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | Uniswap V2 Pool | pool | 100% |
| [0x7a250d56...F2488D](https://etherscan.io/address/0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D) | Router (uniswap_v2) | router | 100% |
| [0x1F98431c...31F984](https://etherscan.io/address/0x1F98431c8aD98523631AE4a59f267346ea31F984) | Factory (uniswap)_v3 | protocol_deployment | 100% |
| [0xAB26D209...8a3084](https://etherscan.io/address/0xAB26D20964CC0284e190Bc22e67d52b8A88a3084) | Uniswap V3 Pool | pool | 100% |
| [0xC36442b4...11FE88](https://etherscan.io/address/0xC36442b4a4522E871399CD717aBDD847Ab11FE88) | PositionManager (uniswap_v3) | position_manager | 100% |
| [0xE592427A...861564](https://etherscan.io/address/0xE592427A0AEce92De3Edee1F18E0157C05861564) | Router (uniswap_v3) | router | 100% |
| [0x00000000...00dEaD](https://etherscan.io/address/0x000000000000000000000000000000000000dEaD) | Burn Address | burn | 100% |
| [0x00000000...00dead](https://etherscan.io/address/0x000000000000000000000000000000000000dead) | Burn Address | burn | 100% |
| [0x00000000...000000](https://etherscan.io/address/0x0000000000000000000000000000000000000000) | Burn Address | burn | 100% |


## TVL & Price History

| Metric | Value |
|--------|-------|
| Total TVL (in token units) | 0 |
| Active Pools | 0 |


## Liquidity Events

- **Liquidity Additions:** 0 events
- **Liquidity Removals:** 0 events


## LP Concentration

| Metric | Value |
|--------|-------|
| Total LP Positions | 0 |
| Unique LPs | 0 |
| Top LP Share | 0.00% |
| Top 5 LP Share | 0.00% |


## Withdrawal Analysis

| Metric | Value |
|--------|-------|
| Pre-Crash Withdrawals | 0 |
| Total Removed (token0) | 0 |
| Pre-Event TVL | 0 |
| Withdrawal Severity | 0.00% of pre-event TVL |


## Incident Timeline

| Metric | Value |
|--------|-------|
| Total Events | 10 |
| Swaps | 0 |
| Liquidity Events | 0 |
| Block Range | 19000170 → 19008313 |
| Time Range | 2024-01-13 19:51:23 UTC → 2024-01-14 23:09:47 UTC |

### Alternative Cause Check


### Key Events by Block

| Block | Timestamp | Event | Pool | Actor | Detail |
|-------|-----------|-------|------|-------|--------|
| 19000170 | 2024-01-13 19:51:23 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xd91eFec7...950747](https://etherscan.io/address/0xd91eFec7E42f80156d1D9f660a69847188950747) | Value: 99419.2638 |
| 19000196 | 2024-01-13 19:56:35 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x58edF782...a36A51](https://etherscan.io/address/0x58edF78281334335EfFa23101bBe3371b6a36A51) | Value: 1000000.0000 |
| 19001337 | 2024-01-13 23:45:47 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | Value: 3892.3852 |
| 19001337 | 2024-01-13 23:45:47 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xf081470f...DcdD67](https://etherscan.io/address/0xf081470f5C6FBCCF48cC4e5B82Dd926409DcdD67) | Value: 3892.3852 |
| 19003756 | 2024-01-14 07:52:23 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x5572db4D...7a3671](https://etherscan.io/address/0x5572db4D954bb53AAFf732780f3B1A90D37a3671) | Value: 1000.0000 |
| 19003801 | 2024-01-14 08:01:47 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x5572db4D...7a3671](https://etherscan.io/address/0x5572db4D954bb53AAFf732780f3B1A90D37a3671) | Value: 542235.8024 |
| 19004798 | 2024-01-14 11:22:35 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xF942aE13...40CA27](https://etherscan.io/address/0xF942aE1372A26767434739A381702AbB5f40CA27) | Value: 543235.8024 |
| 19005645 | 2024-01-14 14:13:11 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | Value: 7230.3346 |
| 19008269 | 2024-01-14 23:00:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x763A0CA9...F8b89a](https://etherscan.io/address/0x763A0CA93AF05adE98A52dc1E5B936b89bF8b89a) | Value: 60360.0161 |
| 19008313 | 2024-01-14 23:09:47 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x12d8E040...852E28](https://etherscan.io/address/0x12d8E0407140bCf38f1c041eD5916195fE852E28) | Value: 60360.0160 |


## Risk Feature Breakdown

| Feature | Value | Weight | Contribution | Description |
|---------|-------|--------|-------------|-------------|
| Pool Concentration | 0.0000 | 0.15 | 0.0000 | Main pool holds 0.00% of total DEX liquidity. |
| Lp Concentration | 0.0000 | 0.15 | 0.0000 | Largest LP holds 0.00% of pool shares. |
| Withdrawal Severity | 0.0000 | 0.20 | 0.0000 | Liquidity removed before crash is 0.00% of pre-event TVL. |
| Temporal Proximity | 0.0000 | 0.15 | 0.0000 | No incident block or no withdrawals to evaluate. |
| Role Sensitivity | 0.0000 | 0.15 | 0.0000 | Deployer unknown — cannot assess role sensitivity. |
| Market Impact | 0.0000 | 0.15 | 0.0000 | No timeline data or incident block. |
| Combined Activity | 0.0000 | 0.05 | 0.0000 | Suspicious activity: 0 withdrawals. |
| **Raw Score** | | | **0.0000** | |

### Interpretation

The available evidence suggests **low risk** of a liquidity-attributable crash.
The market impact may be driven by normal trading activity or external factors.


## Limitations & Caveats

1. **TVL estimates** for V3 Uniswap pools are approximate — actual liquidity is range-dependent.
2. **Price estimates** use simple AMM formulas and may not reflect actual trade prices.
3. **LP ownership** for V2 is reconstructed from Transfer events and may miss complex delegation patterns.
4. **V3 position analysis** is limited to visible PositionManager events.
5. **Alternative causes** (e.g., broader market events, exploits) are not exhaustively checked.
6. **Confidence scores** reflect data quality and completeness, not certainty of malicious intent.
7. A **high risk score indicates correlation, not causation** — always verify with independent data.

> **Important:** This report is for informational purposes. It does not constitute financial advice.


## Data Sources & Methodology

- **RPC Provider:** Ethereum mainnet via configured ETH_RPC_URL
- **Protocol Whitelist:** `config/protocols.ethereum.yaml`
- **Pool Discovery:** Factory getPair/getPool + event logs (PairCreated, PoolCreated)
- **Pool Verification:** On-chain factory, token pair, and event provenance checks
- **Event Indexing:** Chunked log queries with checkpoint/resume support
- **Position Reconstruction:** V2 LP-Transfer events; V3 PositionManager NFT ownership
- **Risk Model:** Weighted feature combination with migration adjustment

### Output Files

| File | Description |
|------|-------------|
| `token_profile.json` | Token metadata and behavior flags |
| `pool_candidates.json` | Raw pool discovery results |
| `verified_pools.json` | Verified pool addresses with confidence |
| `swaps.json` | Normalized swap events |
| `liquidity_events.json` | Normalized liquidity change events |
| `events_all.json` | All indexed events (combined) |
| `positions.json` | LP position ownership |
| `address_labels.json` | Address role annotations |
| `metrics.json` | TVL, concentration, and withdrawal metrics |
| `incident_timeline.json` | Chronological event timeline |
| `risk_assessment.json` | Explainable risk score |
| `report.md` | This report |

