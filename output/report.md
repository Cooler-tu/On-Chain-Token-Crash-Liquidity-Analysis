# On-Chain Token Crash & Liquidity Risk Report

## Executive Summary

- **Token:** uPEG ([0x44b28991...125505](https://etherscan.io/address/0x44b28991B167582F18BA0259e0173176ca125505))
- **Chain:** Ethereum (Chain ID: 1)
- **Analysis Window:** Block 25008000 to 25011999
- **Incident Block:** Not specified
- **Report Generated:** 2026-08-02 17:03:06 UTC

### Risk Score

| Metric | Value |
|--------|-------|
| **Final Risk Score** | **0.3338 / 1.00** |
| **Risk Level** | **LOW** |
| Evidence Confidence | 100.00% |
| Visual | `██████░░░░░░░░░░░░░░` |
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

**2** verified pool(s), **0** unverified candidate(s).

| Pool Address | Protocol | Version | Token0 | Token1 | Fee | Confidence |
|-------------|----------|---------|--------|--------|-----|------------|
| [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | uniswap | v4 | 0x44b28991... | 0xA0b86991... | N/A | 83.33% |
| [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | uniswap | v3 | 0x44b28991... | 0xC02aaA39... | 10000 | 100.00% |


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
| [0x00000000...00dead](https://etherscan.io/address/0x000000000000000000000000000000000000dead) | Burn Address | burn | 100% |
| [0x00000000...000000](https://etherscan.io/address/0x0000000000000000000000000000000000000000) | Burn Address | burn | 100% |


## TVL & Price History

| Metric | Value |
|--------|-------|
| Total TVL (in token units) | 1316.4890 |
| Active Pools | 0 |
| Main Pool | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) |
| Main Pool Share | 95.06% |


## Liquidity Events

- **Liquidity Additions:** 98 events
- **Liquidity Removals:** 121 events

### Significant Liquidity Removals

| Block | Timestamp | Pool | Actor | Amount0 | Amount1 |
|-------|-----------|------|-------|---------|---------|
| 25008673 | 2026-05-02 17:06:47 UTC | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [0xC36442b4...11FE88](https://etherscan.io/address/0xC36442b4a4522E871399CD717aBDD847Ab11FE88) | 1.5700 | 6.0527 |
| 25009864 | 2026-05-02 21:05:23 UTC | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [0xC36442b4...11FE88](https://etherscan.io/address/0xC36442b4a4522E871399CD717aBDD847Ab11FE88) | 3.0005 | 0 |
| 25009941 | 2026-05-02 21:20:59 UTC | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [0xC36442b4...11FE88](https://etherscan.io/address/0xC36442b4a4522E871399CD717aBDD847Ab11FE88) | 1.7200 | 0 |
| 25010043 | 2026-05-02 21:41:35 UTC | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [0xC36442b4...11FE88](https://etherscan.io/address/0xC36442b4a4522E871399CD717aBDD847Ab11FE88) | 3.0005 | 0 |
| 25010235 | 2026-05-02 22:19:59 UTC | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [0xC36442b4...11FE88](https://etherscan.io/address/0xC36442b4a4522E871399CD717aBDD847Ab11FE88) | 47.6863 | 0 |
| 25010295 | 2026-05-02 22:31:59 UTC | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [0xC36442b4...11FE88](https://etherscan.io/address/0xC36442b4a4522E871399CD717aBDD847Ab11FE88) | 1.0819 | 475382176325.98 |
| 25010536 | 2026-05-02 23:20:11 UTC | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [0xC36442b4...11FE88](https://etherscan.io/address/0xC36442b4a4522E871399CD717aBDD847Ab11FE88) | 2.9606 | 226330225820.03 |
| 25010649 | 2026-05-02 23:42:47 UTC | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [0xC36442b4...11FE88](https://etherscan.io/address/0xC36442b4a4522E871399CD717aBDD847Ab11FE88) | 4.7928 | 0 |
| 25010657 | 2026-05-02 23:44:23 UTC | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [0xC36442b4...11FE88](https://etherscan.io/address/0xC36442b4a4522E871399CD717aBDD847Ab11FE88) | 1.1223 | 0 |
| 25011243 | 2026-05-03 01:41:59 UTC | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [0xC36442b4...11FE88](https://etherscan.io/address/0xC36442b4a4522E871399CD717aBDD847Ab11FE88) | 1.5076 | 3.3100 |


## LP Concentration

| Metric | Value |
|--------|-------|
| Total LP Positions | 31 |
| Unique LPs | 29 |
| Top LP Share | 52.49% |
| Top 5 LP Share | 64.58% |

### Top LP Holders

| Owner | Share % | Pool | Type |
|-------|---------|------|------|
| [0xB3aA9923...bc92A0](https://etherscan.io/address/0xB3aA9923489Bc2BFEc323Bf05346AcD4afbc92A0) | 52.4880% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1273553 |
| [0x115D731C...0443e0](https://etherscan.io/address/0x115D731C7d556448EB4Dc8a1Aaa36A3D510443e0) | 3.4978% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1273533 |
| [0xfA9baCD0...05567E](https://etherscan.io/address/0xfA9baCD043eCf8c1cC07cfbaf760135AEE05567E) | 3.4147% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1273597 |
| [0x3b947eD8...627262](https://etherscan.io/address/0x3b947eD8194df99B2D21782C3d49eB5593627262) | 2.9506% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1273484 |
| [0x6AcF355f...F27d88](https://etherscan.io/address/0x6AcF355f01e9161Ac6e38eCbA358C23cDfF27d88) | 2.2322% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1273706 |
| [0x4097d1EB...D0A78D](https://etherscan.io/address/0x4097d1EB5F5bCc74a6272b8C2593f29c65D0A78D) | 2.0193% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1273662 |
| [0x1dED7Ea6...5535FD](https://etherscan.io/address/0x1dED7Ea6a86E3d0f83b645cDb47f96CdE15535FD) | 1.2108% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1273697 |
| [0x729BCb94...10a158](https://etherscan.io/address/0x729BCb94Ef37f815F2B5F649C9Ba74599810a158) | 1.1586% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1273615 |
| [0x45A2235b...19cBff](https://etherscan.io/address/0x45A2235b9027eaB23FfcF759c893763F0019cBff) | 0.8750% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1273617 |
| [0xd85E624f...3687aa](https://etherscan.io/address/0xd85E624f35a7506350a2c566bF5B8c3aDD3687aa) | 0.7718% | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | V3 NFT #1273551 |


## Withdrawal Analysis

| Metric | Value |
|--------|-------|
| Pre-Crash Withdrawals | 121 |
| Total Removed (token0) | 13123.7238 |
| Pre-Event TVL | 1316.4890 |
| Withdrawal Severity | 100.00% of pre-event TVL |


## Incident Timeline

| Metric | Value |
|--------|-------|
| Total Events | 34371 |
| Swaps | 14066 |
| Liquidity Events | 219 |
| Block Range | 25008000 → 25011999 |
| Time Range | 2026-05-02 14:51:59 UTC → 2026-05-03 04:14:11 UTC |

### Liquidity Migration Detected

The following migration candidates were found:
- From [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25008029) to [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25008033)
- From [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25008728) to [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25008728)
- From [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25008886) to [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25008886)
- From [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25009080) to [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25009080)
- From [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25009101) to [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) (block 25009105)

### Alternative Cause Check

- Large token distributions detected — possible airdrop or coordinated sell.

### Key Events by Block

| Block | Timestamp | Event | Pool | Actor | Detail |
|-------|-----------|-------|------|-------|--------|
| 25011996 | 2026-05-03 04:13:35 UTC | SWAP (dex.trades) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | [0x7f54F056...A3Be8A](https://etherscan.io/address/0x7f54F05635d15Cde17A49502fEdB9D1803A3Be8A) | Amount0: 113584381127.67 |
| 25011996 | 2026-05-03 04:13:35 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x7f54F056...A3Be8A](https://etherscan.io/address/0x7f54F05635d15Cde17A49502fEdB9D1803A3Be8A) | Value: 113584381127.67 |
| 25011997 | 2026-05-03 04:13:47 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | Value: 40162269077.29 |
| 25011997 | 2026-05-03 04:13:47 UTC | SWAP (dex.trades) | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [0xC10eE903...910fb4](https://etherscan.io/address/0xC10eE9031F2a0B84766A86B55a8D90F357910fb4) | Amount0: 33747223773.56 |
| 25011997 | 2026-05-03 04:13:47 UTC | SWAP (dex.trades) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | [0xC10eE903...910fb4](https://etherscan.io/address/0xC10eE9031F2a0B84766A86B55a8D90F357910fb4) | Amount0: 5.89 |
| 25011997 | 2026-05-03 04:13:47 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | Value: 3092444624.39 |
| 25011997 | 2026-05-03 04:13:47 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xC10eE903...910fb4](https://etherscan.io/address/0xC10eE9031F2a0B84766A86B55a8D90F357910fb4) | Value: 43211122.86 |
| 25011997 | 2026-05-03 04:13:47 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xC10eE903...910fb4](https://etherscan.io/address/0xC10eE9031F2a0B84766A86B55a8D90F357910fb4) | Value: 43211502578.82 |
| 25011997 | 2026-05-03 04:13:47 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x1231DEB6...6F4EaE](https://etherscan.io/address/0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE) | Value: 43211502578.82 |
| 25011998 | 2026-05-03 04:13:59 UTC | SWAP (dex.trades) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | [0x60943cb0...1C325C](https://etherscan.io/address/0x60943cb06b76A24431659165c81a03c16F1C325C) | Amount0: 1271.37 |
| 25011998 | 2026-05-03 04:13:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | Value: 1517.29 |
| 25011998 | 2026-05-03 04:13:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x60943cb0...1C325C](https://etherscan.io/address/0x60943cb06b76A24431659165c81a03c16F1C325C) | Value: 1517.29 |
| 25011998 | 2026-05-03 04:13:59 UTC | SWAP (dex.trades) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | [0x39c06B54...310df1](https://etherscan.io/address/0x39c06B54686b0540D6D57A254b976B1DF4310df1) | Amount0: 12000000000.00 |
| 25011998 | 2026-05-03 04:13:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | Value: 14315676973.35 |
| 25011998 | 2026-05-03 04:13:59 UTC | SWAP (dex.trades) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | [0x39c06B54...310df1](https://etherscan.io/address/0x39c06B54686b0540D6D57A254b976B1DF4310df1) | Amount0: 110.42 |
| 25011998 | 2026-05-03 04:13:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | Value: 57179081027.47 |
| 25011998 | 2026-05-03 04:13:59 UTC | SWAP (dex.trades) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | [0xbc8da18e...23045F](https://etherscan.io/address/0xbc8da18ef4cFc2282487c0fBA2DAA8FA7623045F) | Amount0: 869256926383.10 |
| 25011998 | 2026-05-03 04:13:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | Value: 1.0341 |
| 25011998 | 2026-05-03 04:13:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x13Be2E8e...602992](https://etherscan.io/address/0x13Be2E8e6877061032cDf813cB7FFfD934602992) | Value: 1.0000 |
| 25011998 | 2026-05-03 04:13:59 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | Value: 1.0000 |
| 25011999 | 2026-05-03 04:14:11 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xBc9993fe...7bdeab](https://etherscan.io/address/0xBc9993fe8606fB5DEA1Ba8674d09cE255c7bdeab) | Value: 500000000000.00 |
| 25011999 | 2026-05-03 04:14:11 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xb300000b...c7028d](https://etherscan.io/address/0xb300000b72DEAEb607a12d5f54773D1C19c7028d) | Value: 299970000000.00 |
| 25011999 | 2026-05-03 04:14:11 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xA5F91E59...B730B0](https://etherscan.io/address/0xA5F91E598668040055dC861a7316e677a5B730B0) | Value: 299970000000.00 |
| 25011999 | 2026-05-03 04:14:11 UTC | SWAP (dex.trades) | [0xdc893995...ab0775](https://etherscan.io/address/0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775) | [0x316a51E6...b603d2](https://etherscan.io/address/0x316a51E6D0452D2C56912eA762DbE18938b603d2) | Amount0: 299970000000.00 |
| 25011999 | 2026-05-03 04:14:11 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xb300000b...c7028d](https://etherscan.io/address/0xb300000b72DEAEb607a12d5f54773D1C19c7028d) | Value: 150030000000.00 |
| 25011999 | 2026-05-03 04:14:11 UTC | SWAP (dex.trades) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | [0x6A93eF5f...97006c](https://etherscan.io/address/0x6A93eF5f666eebE84bA130F8404AD56ee197006c) | Amount0: 150030000000.00 |
| 25011999 | 2026-05-03 04:14:11 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x6A93eF5f...97006c](https://etherscan.io/address/0x6A93eF5f666eebE84bA130F8404AD56ee197006c) | Value: 150030000000.00 |
| 25011999 | 2026-05-03 04:14:11 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0xb300000b...c7028d](https://etherscan.io/address/0xb300000b72DEAEb607a12d5f54773D1C19c7028d) | Value: 50000000000.00 |
| 25011999 | 2026-05-03 04:14:11 UTC | SWAP (dex.trades) | [0x00000000...E08A90](https://etherscan.io/address/0x000000000004444c5dc75cB358380D2e3dE08A90) | [0xBc9993fe...7bdeab](https://etherscan.io/address/0xBc9993fe8606fB5DEA1Ba8674d09cE255c7bdeab) | Amount0: 50000000000.00 |
| 25011999 | 2026-05-03 04:14:11 UTC | TOKEN_TRANSFER (Transfer) | [N/A...N/A](https://etherscan.io/address/N/A) | [0x6A93eF5f...97006c](https://etherscan.io/address/0x6A93eF5f666eebE84bA130F8404AD56ee197006c) | Value: 50000000000.00 |


## Risk Feature Breakdown

| Feature | Value | Weight | Contribution | Description |
|---------|-------|--------|-------------|-------------|
| Pool Concentration | 0.9506 | 0.15 | 0.1426 | Main pool holds 95.06% of total DEX liquidity. |
| Lp Concentration | 0.5249 | 0.15 | 0.0787 | Largest LP holds 52.49% of pool shares. |
| Withdrawal Severity | 1.0000 | 0.20 | 0.2000 | Liquidity removed is 100.00% of reference TVL. |
| Temporal Proximity | 0.4500 | 0.15 | 0.0675 | No incident block — 121 liquidity removals in window. |
| Role Sensitivity | 0.8000 | 0.15 | 0.1200 | Deployer is directly involved in pool(s). |
| Market Impact | 0.0000 | 0.15 | 0.0000 | No incident block — market impact requires a crash reference. |
| Combined Activity | 0.5000 | 0.05 | 0.0250 | Suspicious activity: 121 withdrawals. |
| **Raw Score** | | | **0.6338** | |

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

