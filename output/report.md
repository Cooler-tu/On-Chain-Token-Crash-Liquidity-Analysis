# On-Chain Token Crash & Liquidity Risk Report

## Executive Summary

- **Token:** uPEG ([0x44b28991...125505](https://etherscan.io/address/0x44b28991B167582F18BA0259e0173176ca125505))
- **Chain:** Ethereum (Chain ID: 1)
- **Analysis Window:** Block 25003546 to 25004000
- **Incident Block:** Not specified
- **Report Generated:** 2026-07-28 07:10:53 UTC

### Risk Score

| Metric | Value |
|--------|-------|
| **Final Risk Score** | **0.4364 / 1.00** |
| **Risk Level** | **MEDIUM** |
| Evidence Confidence | 100.00% |
| Visual | `████████░░░░░░░░░░░░` |
| Migration Adjustment | Liquidity migration detected — reducing risk by 0.30. |


## Token Profile

| Property | Value |
|----------|-------|
| Address | [0x44b28991...125505](https://etherscan.io/address/0x44b28991B167582F18BA0259e0173176ca125505) |
| Symbol | uPEG |
| Name | Unipeg |
| Decimals | 18 (onchain) |
| Total Supply | 10000.0000 |
| Is Contract | True |
| Proxy Address | None |
| Implementation | None |
| Behavior Flags | None |


## Pool Summary

**10** verified pool(s), **0** unverified candidate(s).

| Pool Address | Protocol | Version | Token0 | Token1 | Fee | Confidence |
|-------------|----------|---------|--------|--------|-----|------------|
| [0x21ff5cf7...Bc0078](https://etherscan.io/address/0x21ff5cf76f562c6fb3871b59133a9E214eBc0078) | uniswap | v2 | 0x44b28991... | 0xC02aaA39... | N/A | 87.50% |
| [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | uniswap | v3 | 0x44b28991... | 0xC02aaA39... | 10000 | 91.67% |
| [0x7059A9f1...77a890](https://etherscan.io/address/0x7059A9f16dd2405AeF3Dd4f70a89127Ce577a890) | uniswap | v3 | 0x44b28991... | 0xA0b86991... | 3000 | 91.67% |
| [0x84a69fcD...314230](https://etherscan.io/address/0x84a69fcD071D5c36EF9ca3A31b1ff3aEFB314230) | uniswap | v3 | 0x44b28991... | 0xA0b86991... | 10000 | 91.67% |
| [0x6fe76593...ff5b41](https://etherscan.io/address/0x6fe7659371569e469e06ac1c5469608ceb274997ff00e206378dd6553fff5b41) | uniswap | v4 | 0x00000000... | 0x44b28991... | 10000 | 100.00% |
| [0xcc7ab795...cccc5d](https://etherscan.io/address/0xcc7ab79558e9ea455ca04c420778e513d45b04516af8a89945da76aed2cccc5d) | uniswap | v4 | 0x44b28991... | 0xA0b86991... | 3000 | 100.00% |
| [0x9121084c...1f1a58](https://etherscan.io/address/0x9121084c067825e2e3caf43b5cc9c5c35240c5a09d0fda4aaac08c88f41f1a58) | uniswap | v4 | 0x44b28991... | 0xA0b86991... | 10000 | 100.00% |
| [0x294e13af...6aff50](https://etherscan.io/address/0x294e13af91517ae55dce220995256ce91354c706e149c42ece7b2e832c6aff50) | uniswap | v4 | 0x44b28991... | 0xA0b86991... | 9400 | 100.00% |
| [0xc28dd8d8...b54433](https://etherscan.io/address/0xc28dd8d8f8d1eaca22fb881602122aed85002e1cc2e8b14c9cfa18bffeb54433) | uniswap | v4 | 0x00000000... | 0x44b28991... | 9500 | 100.00% |
| [0x2a1c3953...59cd21](https://etherscan.io/address/0x2a1c3953050d960207992c60878c7371cfab656c2e55c61d10c2a8693559cd21) | uniswap | v4 | 0x44b28991... | 0xA0b86991... | 20000 | 100.00% |


## Related Addresses

| Address | Label | Category | Confidence |
|---------|-------|----------|------------|
| [0x5C69bEe7...c5aA6f](https://etherscan.io/address/0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f) | Factory (uniswap)_v2 | protocol_deployment | 100% |
| [0x21ff5cf7...Bc0078](https://etherscan.io/address/0x21ff5cf76f562c6fb3871b59133a9E214eBc0078) | Uniswap V2 Pool | pool | 100% |
| [0x7a250d56...F2488D](https://etherscan.io/address/0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D) | Router (uniswap_v2) | router | 100% |
| [0x1F98431c...31F984](https://etherscan.io/address/0x1F98431c8aD98523631AE4a59f267346ea31F984) | Factory (uniswap)_v3 | protocol_deployment | 100% |
| [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | Uniswap V3 Pool | pool | 100% |
| [0xC36442b4...11FE88](https://etherscan.io/address/0xC36442b4a4522E871399CD717aBDD847Ab11FE88) | PositionManager (uniswap_v3) | position_manager | 100% |
| [0xE592427A...861564](https://etherscan.io/address/0xE592427A0AEce92De3Edee1F18E0157C05861564) | Router (uniswap_v3) | router | 100% |
| [0x7059A9f1...77a890](https://etherscan.io/address/0x7059A9f16dd2405AeF3Dd4f70a89127Ce577a890) | Uniswap V3 Pool | pool | 100% |
| [0x84a69fcD...314230](https://etherscan.io/address/0x84a69fcD071D5c36EF9ca3A31b1ff3aEFB314230) | Uniswap V3 Pool | pool | 100% |
| [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | Factory (uniswap)_v4 | protocol_deployment | 100% |
| [0xbD216513...64ee9e](https://etherscan.io/address/0xbD216513d74C8cf14cf4747E6AaA6420FF64ee9e) | PositionManager (uniswap_v4) | position_manager | 100% |
| [0x66a9893C...Dd6748](https://etherscan.io/address/0x66a9893Cc07d91d95644cfDcE5591279A7Dd6748) | Router (uniswap_v4) | router | 100% |
| [0x02eD4329...426E83](https://etherscan.io/address/0x02eD43292C6be3F49f2B287C499C77560E426E83) | Deployer | token_creator | 100% |
| [0xB3aA9923...bc92A0](https://etherscan.io/address/0xB3aA9923489Bc2BFEc323Bf05346AcD4afbc92A0) | Whale LP | large_liquidity_provider | 80% |
| [0xfE8e9273...4a509F](https://etherscan.io/address/0xfE8e9273aB86B12C0102202F3DaA073Eb14a509F) | Whale LP | large_liquidity_provider | 80% |
| [0x9a5a3545...5a665C](https://etherscan.io/address/0x9a5a354519902937dcE80e8524c712E22B5a665C) | Whale LP | large_liquidity_provider | 80% |
| [0x9733dd72...A9Da15](https://etherscan.io/address/0x9733dd7281f85Bf60E08eCd1Dc952a46CCA9Da15) | Whale LP | large_liquidity_provider | 80% |
| [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | Frequent Token Receiver | frequent_interactor | 50% |
| [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x163F3103...1856E0](https://etherscan.io/address/0x163F3103De041d25464E2C8A4f8f3187EC1856E0) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x7f54F056...A3Be8A](https://etherscan.io/address/0x7f54F05635d15Cde17A49502fEdB9D1803A3Be8A) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x4C82D1fB...0a2cCA](https://etherscan.io/address/0x4C82D1fBFe28C977cBB58D8C7FF8FCF9F70a2cCA) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x37008364...Bd236A](https://etherscan.io/address/0x37008364eaE6688966Ffd81d4e6F0E8189Bd236A) | Frequent Token Receiver | frequent_interactor | 50% |
| [0xb300000b...c7028d](https://etherscan.io/address/0xb300000b72DEAEb607a12d5f54773D1C19c7028d) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x1231DEB6...6F4EaE](https://etherscan.io/address/0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE) | Frequent Token Receiver | frequent_interactor | 50% |
| [0xD730B101...0d210c](https://etherscan.io/address/0xD730B101790e90051Ee2dB099Ac8Ee2c160d210c) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x6A93eF5f...97006c](https://etherscan.io/address/0x6A93eF5f666eebE84bA130F8404AD56ee197006c) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x66a9893c...dBA8Af](https://etherscan.io/address/0x66a9893cC07D91D95644AEDD05D03f95e1dBA8Af) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x6747BcaF...dfACB5](https://etherscan.io/address/0x6747BcaF9bD5a5F0758Cbe08903490E45DdfACB5) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x74de5d4F...016631](https://etherscan.io/address/0x74de5d4FCbf63E00296fd95d33236B9794016631) | Frequent Token Receiver | frequent_interactor | 50% |
| [0xA5F91E59...B730B0](https://etherscan.io/address/0xA5F91E598668040055dC861a7316e677a5B730B0) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x41A55481...6F9997](https://etherscan.io/address/0x41A5548196A371050B7388EdE2683f32576F9997) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x3611B82c...45aC7c](https://etherscan.io/address/0x3611B82c7B13e72b26eb0E9BE0613bEE7A45aC7c) | Frequent Token Receiver | frequent_interactor | 50% |
| [0xba4c9288...0847bf](https://etherscan.io/address/0xba4c928807450c57E4F5Aa18cd507987840847bf) | Frequent Token Receiver | frequent_interactor | 50% |
| [0xC10eE903...910fb4](https://etherscan.io/address/0xC10eE9031F2a0B84766A86B55a8D90F357910fb4) | Frequent Token Receiver | frequent_interactor | 50% |
| [0xF1fa70f0...52CEbA](https://etherscan.io/address/0xF1fa70f061fDD3021819Aa77deDBb7554652CEbA) | Frequent Token Receiver | frequent_interactor | 50% |
| [0xB2fcE99E...f7e1b9](https://etherscan.io/address/0xB2fcE99E88f9c2a5A9C522D0BB1AcF1Cddf7e1b9) | Frequent Token Receiver | frequent_interactor | 50% |
| [0x88538812...e0F987](https://etherscan.io/address/0x88538812e41b89689f5e23871ef5d5CE2be0F987) | Frequent Token Sender | frequent_interactor | 50% |
| [0xe9f9840b...05B4C5](https://etherscan.io/address/0xe9f9840b805a1C2807C1c0E07EB3d19AbF05B4C5) | Frequent Token Sender | frequent_interactor | 50% |
| [0xF24be340...1F57F0](https://etherscan.io/address/0xF24be3404B723e35d9EbC60977B646d2581F57F0) | Frequent Token Sender | frequent_interactor | 50% |
| [0x8F10B468...13f996](https://etherscan.io/address/0x8F10B468b06c6FD214B65F87778827F7D113f996) | Frequent Token Sender | frequent_interactor | 50% |
| [0x00000000...00dEaD](https://etherscan.io/address/0x000000000000000000000000000000000000dEaD) | Burn Address | burn | 100% |
| [0x00000000...00dead](https://etherscan.io/address/0x000000000000000000000000000000000000dead) | Burn Address | burn | 100% |
| [0x00000000...000000](https://etherscan.io/address/0x0000000000000000000000000000000000000000) | Burn Address | burn | 100% |


## TVL & Price History

| Metric | Value |
|--------|-------|
| Total TVL (in token units) | 10.2168 |
| Active Pools | 0 |
| Main Pool | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) |
| Main Pool Share | 99.29% |


## Liquidity Events

- **Liquidity Additions:** 148 events
- **Liquidity Removals:** 130 events

### Significant Liquidity Removals

| Block | Timestamp | Pool | Actor | Amount0 | Amount1 |
|-------|-----------|------|-------|---------|---------|
| 25003583 | 2026-05-02 00:07:35 UTC | [...](https://etherscan.io/address/) | [...](https://etherscan.io/address/) | 87607.8721 | 1.8767 |
| 25003623 | 2026-05-02 00:15:35 UTC | [...](https://etherscan.io/address/) | [...](https://etherscan.io/address/) | 18.8454 | 0 |
| 25003703 | 2026-05-02 00:31:35 UTC | [...](https://etherscan.io/address/) | [...](https://etherscan.io/address/) | 17.1756 | 82.3273 |
| 25003706 | 2026-05-02 00:32:11 UTC | [...](https://etherscan.io/address/) | [...](https://etherscan.io/address/) | 90.6340 | 0 |
| 25003807 | 2026-05-02 00:52:23 UTC | [...](https://etherscan.io/address/) | [...](https://etherscan.io/address/) | 3.4203 | 10006.07 |
| 25003838 | 2026-05-02 00:58:35 UTC | [...](https://etherscan.io/address/) | [...](https://etherscan.io/address/) | 2.5000 | 0 |
| 25003844 | 2026-05-02 00:59:47 UTC | [...](https://etherscan.io/address/) | [...](https://etherscan.io/address/) | 4405.8550 | 0 |


## LP Concentration

| Metric | Value |
|--------|-------|
| Total LP Positions | 47 |
| Unique LPs | 22 |
| Top LP Share | 100.00% |
| Top 5 LP Share | 147.31% |

### Top LP Holders

| Owner | Share % | Pool | Type |
|-------|---------|------|------|
| [0x9733dd72...A9Da15](https://etherscan.io/address/0x9733dd7281f85Bf60E08eCd1Dc952a46CCA9Da15) | 100.0000% | [0x294e13af...6aff50](https://etherscan.io/address/0x294e13af91517ae55dce220995256ce91354c706e149c42ece7b2e832c6aff50) | V3 NFT #239895 |
| [0xB3aA9923...bc92A0](https://etherscan.io/address/0xB3aA9923489Bc2BFEc323Bf05346AcD4afbc92A0) | 31.3464% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1272150 |
| [0x9a5a3545...5a665C](https://etherscan.io/address/0x9a5a354519902937dcE80e8524c712E22B5a665C) | 7.5442% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1272949 |
| [0xfE8e9273...4a509F](https://etherscan.io/address/0xfE8e9273aB86B12C0102202F3DaA073Eb14a509F) | 5.7839% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1272932 |
| [0xcf392F62...D9735A](https://etherscan.io/address/0xcf392F62151fe078A5C26c6fd7E6bC5F15D9735A) | 2.6383% | [0xc28dd8d8...b54433](https://etherscan.io/address/0xc28dd8d8f8d1eaca22fb881602122aed85002e1cc2e8b14c9cfa18bffeb54433) | V3 NFT #239870 |
| [0xfA9baCD0...05567E](https://etherscan.io/address/0xfA9baCD043eCf8c1cC07cfbaf760135AEE05567E) | 2.2114% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1271096 |
| [0x0d56D0f7...59A190](https://etherscan.io/address/0x0d56D0f7d148b75af0527A5Cea73Ab926b59A190) | 1.6765% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1272943 |
| [0x0504B6c6...a39ef9](https://etherscan.io/address/0x0504B6c68792c5E2E6aA75779DD09CE426a39ef9) | 1.6681% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1272946 |
| [0x0d56D0f7...59A190](https://etherscan.io/address/0x0d56D0f7d148b75af0527A5Cea73Ab926b59A190) | 1.4902% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1272942 |
| [0x0d56D0f7...59A190](https://etherscan.io/address/0x0d56D0f7d148b75af0527A5Cea73Ab926b59A190) | 1.3039% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1272941 |


## Withdrawal Analysis

| Metric | Value |
|--------|-------|
| Pre-Crash Withdrawals | 130 |
| Total Removed (token0) | 83.7553 |
| Pre-Event TVL | 10.2168 |
| Withdrawal Severity | 100.00% of pre-event TVL |


## Incident Timeline

| Metric | Value |
|--------|-------|
| Total Events | 2626 |
| Swaps | 536 |
| Liquidity Events | 601 |
| Block Range | 25003546 → 25004000 |
| Time Range | 2026-05-02 00:00:11 UTC → 2026-05-02 01:31:11 UTC |

### Liquidity Migration Detected

The following migration candidates were found:
- From [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25003584) to [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25003587)
- From [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25003616) to [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25003619)
- From [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25003680) to [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25003681)
- From [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25003680) to [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25003682)
- From [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25003680) to [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25003681)

### Alternative Cause Check

- Large token distributions detected — possible airdrop or coordinated sell.

### Key Events by Block

| Block | Timestamp | Event | Pool | Actor | Detail |
|-------|-----------|-------|------|-------|--------|
| 25003994 | 2026-05-02 01:29:59 UTC | LIQUIDITY_REMOVE (ModifyLiquidity) | [0x2a1c3953...59cd21](https://etherscan.io/address/0x2a1c3953050d960207992c60878c7371cfab656c2e55c61d10c2a8693559cd21) | [0xbD216513...64ee9e](https://etherscan.io/address/0xbD216513d74C8cf14cf4747E6AaA6420FF64ee9e) | Δ: 0 / 0 |
| 25003994 | 2026-05-02 01:29:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x3F6bF69E...E2BB67](https://etherscan.io/address/0x3F6bF69Ef37E6C28D767ceEEe233c3679FE2BB67) | Value: 50000000000.00 |
| 25003994 | 2026-05-02 01:29:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xb300000b...c7028d](https://etherscan.io/address/0xb300000b72DEAEb607a12d5f54773D1C19c7028d) | Value: 50000000000.00 |
| 25003994 | 2026-05-02 01:29:59 UTC | SWAP (Swap) | [0xc28dd8d8...b54433](https://etherscan.io/address/0xc28dd8d8f8d1eaca22fb881602122aed85002e1cc2e8b14c9cfa18bffeb54433) | [0x6A93eF5f...97006c](https://etherscan.io/address/0x6A93eF5f666eebE84bA130F8404AD56ee197006c) | Amount0: 42874318482.70 |
| 25003994 | 2026-05-02 01:29:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x6A93eF5f...97006c](https://etherscan.io/address/0x6A93eF5f666eebE84bA130F8404AD56ee197006c) | Value: 50000000000.00 |
| 25003995 | 2026-05-02 01:30:11 UTC | SWAP (Swap) | [0xc28dd8d8...b54433](https://etherscan.io/address/0xc28dd8d8f8d1eaca22fb881602122aed85002e1cc2e8b14c9cfa18bffeb54433) | [0x6A93eF5f...97006c](https://etherscan.io/address/0x6A93eF5f666eebE84bA130F8404AD56ee197006c) | Amount0: 119400000000.00 |
| 25003995 | 2026-05-02 01:30:11 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | Value: 136428132537.07 |
| 25003995 | 2026-05-02 01:30:11 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x67D66FBe...7B7881](https://etherscan.io/address/0x67D66FBe8710cb32a7cE055D271877b3A57B7881) | Value: 1.0000 |
| 25003996 | 2026-05-02 01:30:23 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x750E7049...1869a4](https://etherscan.io/address/0x750E70496C9EBe5a13551F0147E02206861869a4) | Value: 356822016416.20 |
| 25003996 | 2026-05-02 01:30:23 UTC | SWAP (Swap) | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [0x4C82D1fB...0a2cCA](https://etherscan.io/address/0x4C82D1fBFe28C977cBB58D8C7FF8FCF9F70a2cCA) | Amount0: 356822016416.20 |
| 25003996 | 2026-05-02 01:30:23 UTC | LIQUIDITY_REMOVE (ModifyLiquidity) | [0x2a1c3953...59cd21](https://etherscan.io/address/0x2a1c3953050d960207992c60878c7371cfab656c2e55c61d10c2a8693559cd21) | [0xbD216513...64ee9e](https://etherscan.io/address/0xbD216513d74C8cf14cf4747E6AaA6420FF64ee9e) | Δ: 0 / 0 |
| 25003996 | 2026-05-02 01:30:23 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | Value: 9944910625.21 |
| 25003996 | 2026-05-02 01:30:23 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x9A981cE6...bA776F](https://etherscan.io/address/0x9A981cE637f2638Ee2B7e4083Eb287a697bA776F) | Value: 1.0000 |
| 25003997 | 2026-05-02 01:30:35 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x115D731C...0443e0](https://etherscan.io/address/0x115D731C7d556448EB4Dc8a1Aaa36A3D510443e0) | Value: 52164906752.18 |
| 25003997 | 2026-05-02 01:30:35 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x74de5d4F...016631](https://etherscan.io/address/0x74de5d4FCbf63E00296fd95d33236B9794016631) | Value: 52164906752.18 |
| 25003997 | 2026-05-02 01:30:35 UTC | SWAP (Swap) | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [0x66a9893c...dBA8Af](https://etherscan.io/address/0x66a9893cC07D91D95644AEDD05D03f95e1dBA8Af) | Amount0: 52164906752.18 |
| 25003997 | 2026-05-02 01:30:35 UTC | LIQUIDITY_REMOVE (DecreaseLiquidity) | [N/A...N/A](https://etherscan.io/address/N/A) | [...](https://etherscan.io/address/) | Δ: 0 / 3722.5069 |
| 25003997 | 2026-05-02 01:30:35 UTC | COLLECT_FEES (Collect) | [N/A...N/A](https://etherscan.io/address/N/A) | [...](https://etherscan.io/address/) |  |
| 25003998 | 2026-05-02 01:30:47 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x9A981cE6...bA776F](https://etherscan.io/address/0x9A981cE637f2638Ee2B7e4083Eb287a697bA776F) | Value: 1.0000 |
| 25003999 | 2026-05-02 01:30:59 UTC | POSITION_TRANSFER (Transfer) | [0x2a1c3953...59cd21](https://etherscan.io/address/0x2a1c3953050d960207992c60878c7371cfab656c2e55c61d10c2a8693559cd21) | [0x00000000...000000](https://etherscan.io/address/0x0000000000000000000000000000000000000000) |  |
| 25003999 | 2026-05-02 01:30:59 UTC | LIQUIDITY_ADD (ModifyLiquidity) | [0x2a1c3953...59cd21](https://etherscan.io/address/0x2a1c3953050d960207992c60878c7371cfab656c2e55c61d10c2a8693559cd21) | [0xbD216513...64ee9e](https://etherscan.io/address/0xbD216513d74C8cf14cf4747E6AaA6420FF64ee9e) | Δ: 0 / 0 |
| 25003999 | 2026-05-02 01:30:59 UTC | SWAP (Swap) | [0xc28dd8d8...b54433](https://etherscan.io/address/0xc28dd8d8f8d1eaca22fb881602122aed85002e1cc2e8b14c9cfa18bffeb54433) | [0x4C82D1fB...0a2cCA](https://etherscan.io/address/0x4C82D1fBFe28C977cBB58D8C7FF8FCF9F70a2cCA) | Amount0: 230000000000.00 |
| 25003999 | 2026-05-02 01:30:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | Value: 261191834334.53 |
| 25003999 | 2026-05-02 01:30:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xB0Ad50a9...4ca895](https://etherscan.io/address/0xB0Ad50a94D030A2D887F9eB59c144A3D5D4ca895) | Value: 61300000000.00 |
| 25003999 | 2026-05-02 01:30:59 UTC | SWAP (Swap) | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [0x4313C378...96b27f](https://etherscan.io/address/0x4313C378Cc91eA583C91387B9216e2c03096b27f) | Amount0: 61300000000.00 |
| 25003999 | 2026-05-02 01:30:59 UTC | POSITION_TRANSFER (Transfer) | [0xc28dd8d8...b54433](https://etherscan.io/address/0xc28dd8d8f8d1eaca22fb881602122aed85002e1cc2e8b14c9cfa18bffeb54433) | [0x00000000...000000](https://etherscan.io/address/0x0000000000000000000000000000000000000000) |  |
| 25003999 | 2026-05-02 01:30:59 UTC | LIQUIDITY_ADD (ModifyLiquidity) | [0xc28dd8d8...b54433](https://etherscan.io/address/0xc28dd8d8f8d1eaca22fb881602122aed85002e1cc2e8b14c9cfa18bffeb54433) | [0xbD216513...64ee9e](https://etherscan.io/address/0xbD216513d74C8cf14cf4747E6AaA6420FF64ee9e) | Δ: 0 / 0 |
| 25004000 | 2026-05-02 01:31:11 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x115D731C...0443e0](https://etherscan.io/address/0x115D731C7d556448EB4Dc8a1Aaa36A3D510443e0) | Value: 20000000000.00 |
| 25004000 | 2026-05-02 01:31:11 UTC | LIQUIDITY_ADD (Mint) | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [0xC36442b4...11FE88](https://etherscan.io/address/0xC36442b4a4522E871399CD717aBDD847Ab11FE88) | Δ: 20000000000.00 / 32132736068.22 |
| 25004000 | 2026-05-02 01:31:11 UTC | LIQUIDITY_ADD (IncreaseLiquidity) | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [...](https://etherscan.io/address/) | Δ: 20000000000.00 / 32132736068.22 |


## Risk Feature Breakdown

| Feature | Value | Weight | Contribution | Description |
|---------|-------|--------|-------------|-------------|
| Pool Concentration | 0.9929 | 0.15 | 0.1489 | Main pool holds 99.29% of total DEX liquidity. |
| Lp Concentration | 1.0000 | 0.15 | 0.1500 | Largest LP holds 100.00% of pool shares. |
| Withdrawal Severity | 1.0000 | 0.20 | 0.2000 | Liquidity removed is 100.00% of reference TVL. |
| Temporal Proximity | 0.4500 | 0.15 | 0.0675 | No incident block — 130 liquidity removals in window. |
| Role Sensitivity | 0.8000 | 0.15 | 0.1200 | Deployer is directly involved in pool(s). |
| Market Impact | 0.0000 | 0.15 | 0.0000 | No incident block — market impact requires a crash reference. |
| Combined Activity | 1.0000 | 0.05 | 0.0500 | Suspicious activity: 130 withdrawals and large sells detected. |
| **Raw Score** | | | **0.7364** | |

### Interpretation

Some risk indicators are present, but the evidence is not conclusive.
Additional investigation into specific withdrawal patterns and address relationships
is recommended before drawing firm conclusions.


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

