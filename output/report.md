# On-Chain Token Crash & Liquidity Risk Report

## Executive Summary

- **Token:** CREDI ([0xaE6e307c...014c6B](https://etherscan.io/address/0xaE6e307c3Fe9E922E5674DBD7F830Ed49c014c6B))
- **Chain:** Ethereum (Chain ID: 1)
- **Analysis Window:** Block 19600035 to 19606648
- **Incident Block:** Not specified
- **Report Generated:** 2026-08-08 07:32:46 UTC

### Risk Score

| Metric | Value |
|--------|-------|
| **Final Risk Score** | **0.1971 / 1.00** |
| **Risk Level** | **LOW** |
| Evidence Confidence | 73.00% |
| Visual | `███░░░░░░░░░░░░░░░░░` |


## Token Profile

| Property | Value |
|----------|-------|
| Address | [0xaE6e307c...014c6B](https://etherscan.io/address/0xaE6e307c3Fe9E922E5674DBD7F830Ed49c014c6B) |
| Symbol | CREDI |
| Name | CREDI |
| Decimals | 18 (onchain) |
| Total Supply | 939978336.0000 |
| Is Contract | True |
| Proxy Address | None |
| Implementation | None |
| Behavior Flags | minting |


## Pool Summary

**5** verified pool(s), **0** unverified candidate(s).

| Pool Address | Protocol | Version | Token0 | Token1 | Fee | Confidence |
|-------------|----------|---------|--------|--------|-----|------------|
| [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | uniswap | v4 | 0x44b28991... | 0x00000000... | N/A | 83.33% |
| [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | uniswap | v3 | 0x44b28991... | 0xC02aaA39... | 10000 | 100.00% |
| [0x21ff5cf7...Bc0078](https://etherscan.io/address/0x21ff5cf76f562c6fb3871b59133a9E214eBc0078) | uniswap | v2 | 0x44b28991... | 0xC02aaA39... | N/A | 100.00% |
| [0x7059A9f1...77a890](https://etherscan.io/address/0x7059A9f16dd2405AeF3Dd4f70a89127Ce577a890) | uniswap | v3 | 0x44b28991... | 0xA0b86991... | 3000 | 100.00% |
| [0x84a69fcD...314230](https://etherscan.io/address/0x84a69fcD071D5c36EF9ca3A31b1ff3aEFB314230) | uniswap | v3 | 0x44b28991... | 0xA0b86991... | 10000 | 100.00% |


## Related Addresses

| Address | Label | Category | Confidence |
|---------|-------|----------|------------|
| [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | Factory (uniswap)_v4 | protocol_deployment | 100% |
| [0xbD216513...64ee9e](https://etherscan.io/address/0xbD216513d74C8cf14cf4747E6AaA6420FF64ee9e) | PositionManager (uniswap_v4) | position_manager | 100% |
| [0x66a9893C...Dd6748](https://etherscan.io/address/0x66a9893Cc07d91d95644cfDcE5591279A7Dd6748) | Router (uniswap_v4) | router | 100% |
| [0x1F98431c...31F984](https://etherscan.io/address/0x1F98431c8aD98523631AE4a59f267346ea31F984) | Factory (uniswap)_v3 | protocol_deployment | 100% |
| [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | Uniswap V3 Pool | pool | 100% |
| [0xC36442b4...11FE88](https://etherscan.io/address/0xC36442b4a4522E871399CD717aBDD847Ab11FE88) | PositionManager (uniswap_v3) | position_manager | 100% |
| [0xE592427A...861564](https://etherscan.io/address/0xE592427A0AEce92De3Edee1F18E0157C05861564) | Router (uniswap_v3) | router | 100% |
| [0x5C69bEe7...c5aA6f](https://etherscan.io/address/0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f) | Factory (uniswap)_v2 | protocol_deployment | 100% |
| [0x21ff5cf7...Bc0078](https://etherscan.io/address/0x21ff5cf76f562c6fb3871b59133a9E214eBc0078) | Uniswap V2 Pool | pool | 100% |
| [0x7a250d56...F2488D](https://etherscan.io/address/0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D) | Router (uniswap_v2) | router | 100% |
| [0x7059A9f1...77a890](https://etherscan.io/address/0x7059A9f16dd2405AeF3Dd4f70a89127Ce577a890) | Uniswap V3 Pool | pool | 100% |
| [0x84a69fcD...314230](https://etherscan.io/address/0x84a69fcD071D5c36EF9ca3A31b1ff3aEFB314230) | Uniswap V3 Pool | pool | 100% |
| [0x02eD4329...426E83](https://etherscan.io/address/0x02eD43292C6be3F49f2B287C499C77560E426E83) | Deployer | token_creator | 100% |
| [0xB3aA9923...bc92A0](https://etherscan.io/address/0xB3aA9923489Bc2BFEc323Bf05346AcD4afbc92A0) | Whale LP | large_liquidity_provider | 80% |
| [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | Frequent Token Receiver | frequent_interactor | 50% |
| [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x163F3103...1856E0](https://etherscan.io/address/0x163F3103De041d25464E2C8A4f8f3187EC1856E0) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x4C82D1fB...0a2cCA](https://etherscan.io/address/0x4C82D1fBFe28C977cBB58D8C7FF8FCF9F70a2cCA) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x7f54F056...A3Be8A](https://etherscan.io/address/0x7f54F05635d15Cde17A49502fEdB9D1803A3Be8A) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x6A93eF5f...97006c](https://etherscan.io/address/0x6A93eF5f666eebE84bA130F8404AD56ee197006c) | Frequent Token Receiver | frequent_interactor | 50% |
| [0xb300000b...c7028d](https://etherscan.io/address/0xb300000b72DEAEb607a12d5f54773D1C19c7028d) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x66a9893c...dBA8Af](https://etherscan.io/address/0x66a9893cC07D91D95644AEDD05D03f95e1dBA8Af) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x3611B82c...45aC7c](https://etherscan.io/address/0x3611B82c7B13e72b26eb0E9BE0613bEE7A45aC7c) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x13Be2E8e...602992](https://etherscan.io/address/0x13Be2E8e6877061032cDf813cB7FFfD934602992) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x1231DEB6...6F4EaE](https://etherscan.io/address/0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x28b1Dc1a...B2a183](https://etherscan.io/address/0x28b1Dc1a5E3699A428BC51d234DFab7C9CB2a183) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x74de5d4F...016631](https://etherscan.io/address/0x74de5d4FCbf63E00296fd95d33236B9794016631) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x8F10B468...13f996](https://etherscan.io/address/0x8F10B468b06c6FD214B65F87778827F7D113f996) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x6747BcaF...dfACB5](https://etherscan.io/address/0x6747BcaF9bD5a5F0758Cbe08903490E45DdfACB5) | Frequent Token Receiver | frequent_interactor | 50% |
| [0xA5F91E59...B730B0](https://etherscan.io/address/0xA5F91E598668040055dC861a7316e677a5B730B0) | Frequent Token Receiver | frequent_interactor | 50% |
| [0xC10eE903...910fb4](https://etherscan.io/address/0xC10eE9031F2a0B84766A86B55a8D90F357910fb4) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x06CFf708...d2f5ef](https://etherscan.io/address/0x06CFf7088619C7178F5e14f0B119458d08d2f5ef) | Frequent Token Receiver | frequent_interactor | 50% |
| [0xcD6b9800...D09799](https://etherscan.io/address/0xcD6b980029E6E6e0733ac8eC3E02be9410D09799) | Frequent Token Receiver | frequent_interactor | 50% |
| [0xba4c9288...0847bf](https://etherscan.io/address/0xba4c928807450c57E4F5Aa18cd507987840847bf) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x4313C378...96b27f](https://etherscan.io/address/0x4313C378Cc91eA583C91387B9216e2c03096b27f) | Frequent Token Sender | frequent_interactor | 50% |
| [0x9642b23E...2F5D4E](https://etherscan.io/address/0x9642b23Ed1E01Df1092B92641051881a322F5D4E) | Frequent Token Sender | frequent_interactor | 50% |
| [0x00000000...00dEaD](https://etherscan.io/address/0x000000000000000000000000000000000000dEaD) | Burn Address | burn | 100% |
| [0x00000000...000000](https://etherscan.io/address/0x0000000000000000000000000000000000000000) | Burn Address | burn | 100% |
| [0x00000000...00dead](https://etherscan.io/address/0x000000000000000000000000000000000000dead) | Burn Address | burn | 100% |


## TVL & Price History

| Metric | Value |
|--------|-------|
| Total TVL (in token units) | 1316.5353 |
| Active Pools | 0 |
| Main Pool | [0xac9fbdbe...1b5071](https://etherscan.io/address/0xac9fbdbe486f8023606b932a747bc476011b5071) |
| Main Pool Share | 100.00% |


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
| Pre-Crash Withdrawals | 121 |
| Total Removed (token0) | 13123.7238 |
| Pre-Event TVL | 1316.5353 |
| Withdrawal Severity | 100.00% of pre-event TVL |


## Incident Timeline

| Metric | Value |
|--------|-------|
| Total Events | 372 |
| Swaps | 139 |
| Liquidity Events | 0 |
| Block Range | 19600035 → 19606648 |
| Time Range | 2024-04-06 23:44:23 UTC → 2024-04-07 22:00:35 UTC |

### Alternative Cause Check

- Large token distributions detected — possible airdrop or coordinated sell.

### Key Events by Block

| Block | Timestamp | Event | Pool | Actor | Detail |
|-------|-----------|-------|------|-------|--------|
| 19605637 | 2024-04-07 18:36:11 UTC | SWAP (dex.trades) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | [0x22F9dCF4...178C18](https://etherscan.io/address/0x22F9dCF4647084d6C31b2765F6910cd85C178C18) | Amount0: 34.95 |
| 19605637 | 2024-04-07 18:36:11 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x22F9dCF4...178C18](https://etherscan.io/address/0x22F9dCF4647084d6C31b2765F6910cd85C178C18) | Value: 6.7871 |
| 19605637 | 2024-04-07 18:36:11 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x22F9dCF4...178C18](https://etherscan.io/address/0x22F9dCF4647084d6C31b2765F6910cd85C178C18) | Value: 692.9117 |
| 19605920 | 2024-04-07 19:33:11 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xeeF636cF...540344](https://etherscan.io/address/0xeeF636cF9d1457Ae8BC85164674A2Ba7d9540344) | Value: 7000000.0000 |
| 19605924 | 2024-04-07 19:33:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x894D5E8f...9a195a](https://etherscan.io/address/0x894D5E8f6cE008b71a0cBa883662fd721B9a195a) | Value: 11000.8861 |
| 19605924 | 2024-04-07 19:33:59 UTC | SWAP (dex.trades) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | [0x0d4a11d5...1f1852](https://etherscan.io/address/0x0d4a11d5EEaaC28EC3F61d100daF4d40471f1852) | Amount0: 11000.8861 |
| 19605986 | 2024-04-07 19:46:47 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x69824E44...9b90e9](https://etherscan.io/address/0x69824E443E7E6911F7Ad5aaD23d3f7bDe39b90e9) | Value: 1622.8862 |
| 19605986 | 2024-04-07 19:46:47 UTC | SWAP (dex.trades) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | [0x0d4a11d5...1f1852](https://etherscan.io/address/0x0d4a11d5EEaaC28EC3F61d100daF4d40471f1852) | Amount0: 1622.8862 |
| 19605989 | 2024-04-07 19:47:23 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xf1a5595e...77177B](https://etherscan.io/address/0xf1a5595ed25Fc44DfD0699a62E75F9A3Ea77177B) | Value: 7000000.0000 |
| 19606020 | 2024-04-07 19:53:35 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | Value: 7080.9131 |
| 19606020 | 2024-04-07 19:53:35 UTC | SWAP (dex.trades) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | [0x74cA3404...1613e1](https://etherscan.io/address/0x74cA34044282eb9cE7937D4bf486EaB1021613e1) | Amount0: 350.86 |
| 19606134 | 2024-04-07 20:16:47 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | Value: 10973.5373 |
| 19606134 | 2024-04-07 20:16:47 UTC | SWAP (dex.trades) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | [0x00000000...0088B8](https://etherscan.io/address/0x00000000A991C429eE2Ec6df19d40fe0c80088B8) | Amount0: 548.30 |
| 19606134 | 2024-04-07 20:16:47 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | Value: 46331.8030 |
| 19606134 | 2024-04-07 20:16:47 UTC | SWAP (dex.trades) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | [0x11111112...960582](https://etherscan.io/address/0x1111111254EEB25477B68fb85Ed929f73A960582) | Amount0: 2377.84 |
| 19606134 | 2024-04-07 20:16:47 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x11111112...960582](https://etherscan.io/address/0x1111111254EEB25477B68fb85Ed929f73A960582) | Value: 46331.8030 |
| 19606134 | 2024-04-07 20:16:47 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x00000000...0088B8](https://etherscan.io/address/0x00000000A991C429eE2Ec6df19d40fe0c80088B8) | Value: 10973.5370 |
| 19606134 | 2024-04-07 20:16:47 UTC | SWAP (dex.trades) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | [0x00000000...0088B8](https://etherscan.io/address/0x00000000A991C429eE2Ec6df19d40fe0c80088B8) | Amount0: 10973.5370 |
| 19606171 | 2024-04-07 20:24:11 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x48a8250B...Ae80eC](https://etherscan.io/address/0x48a8250B961B880755D37B1DdD1D0d59DdAe80eC) | Value: 32310.5211 |
| 19606171 | 2024-04-07 20:24:11 UTC | SWAP (dex.trades) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | [0x0d4a11d5...1f1852](https://etherscan.io/address/0x0d4a11d5EEaaC28EC3F61d100daF4d40471f1852) | Amount0: 32310.5211 |
| 19606187 | 2024-04-07 20:27:23 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xFC65a973...36A23F](https://etherscan.io/address/0xFC65a9737bF5a7E8FFE5Abbe1D80dD99cC36A23F) | Value: 129561.5522 |
| 19606201 | 2024-04-07 20:30:11 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xc2aBaDEE...c5aA14](https://etherscan.io/address/0xc2aBaDEE440bE0f54AcB90cF8aeEF807efc5aA14) | Value: 7095.2400 |
| 19606398 | 2024-04-07 21:09:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | Value: 1070.3914 |
| 19606398 | 2024-04-07 21:09:59 UTC | SWAP (dex.trades) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | [0x22F9dCF4...178C18](https://etherscan.io/address/0x22F9dCF4647084d6C31b2765F6910cd85C178C18) | Amount0: 53.94 |
| 19606398 | 2024-04-07 21:09:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x22F9dCF4...178C18](https://etherscan.io/address/0x22F9dCF4647084d6C31b2765F6910cd85C178C18) | Value: 10.3794 |
| 19606398 | 2024-04-07 21:09:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x22F9dCF4...178C18](https://etherscan.io/address/0x22F9dCF4647084d6C31b2765F6910cd85C178C18) | Value: 1060.0121 |
| 19606552 | 2024-04-07 21:40:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xf5394fa2...81ff1e](https://etherscan.io/address/0xf5394fa28Ed3F37170a3db372957276F4981ff1e) | Value: 27777.0000 |
| 19606552 | 2024-04-07 21:40:59 UTC | SWAP (dex.trades) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | [0x0d4a11d5...1f1852](https://etherscan.io/address/0x0d4a11d5EEaaC28EC3F61d100daF4d40471f1852) | Amount0: 27777.0000 |
| 19606648 | 2024-04-07 22:00:35 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | Value: 13751.6202 |
| 19606648 | 2024-04-07 22:00:35 UTC | SWAP (dex.trades) | [0xAC9fbdbE...1B5071](https://etherscan.io/address/0xAC9fbdbE486F8023606b932a747BC476011B5071) | [0x2C0CFEE5...27A0F8](https://etherscan.io/address/0x2C0CFEE54F621Dd1EA0C1AC3aB298C8EaD27A0F8) | Amount0: 680.11 |


## Risk Feature Breakdown

| Feature | Value | Weight | Contribution | Description |
|---------|-------|--------|-------------|-------------|
| Pool Concentration | 1.0000 | 0.15 | 0.1500 | Main pool holds 100.00% of total DEX liquidity. |
| Lp Concentration | 0.0000 | 0.15 | 0.0000 | Largest LP holds 0.00% of pool shares. |
| Withdrawal Severity | 0.0000 | 0.20 | 0.0000 | Liquidity removed is 0.00% of reference TVL. |
| Temporal Proximity | 0.0000 | 0.15 | 0.0000 | No withdrawals to evaluate. |
| Role Sensitivity | 0.8000 | 0.15 | 0.1200 | Deployer is directly involved in pool(s). |
| Market Impact | 0.0000 | 0.15 | 0.0000 | No incident block — market impact requires a crash reference. |
| Combined Activity | 0.0000 | 0.05 | 0.0000 | Suspicious activity: 0 withdrawals. |
| **Raw Score** | | | **0.2700** | |

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

