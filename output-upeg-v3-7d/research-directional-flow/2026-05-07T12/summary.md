# Directional Swap Flow Audit

- Pool: `0xdc893995d488e5be8ec8ca1db92cbec2a1ab0775`
- Event window: blocks `25043020`–`25043311`
- Balance snapshots: blocks `25043019` → `25043311`

## Reconciliation

| Metric | uPEG |
|---|---:|
| Sell volume into pool | 39.53559105739822473 |
| Buy volume out of pool | 30.268476394365850053 |
| Net Swap event flow to pool | 9.267114663032374677 |
| Actual ERC-20 transfer net to pool | 10.106754360913178103 |
| Pool balance delta | 10.106754360913178103 |
| Transfer minus Swap | 0.839639697880803426 |
| Balance minus Transfer | 0 |

Transfer/balance reconciliation: **exact**.

## Activity

- Swap events: 119 (48 sells / 71 buys)
- Unique Swap transactions: 118
- Unique transaction senders: 99
- Transfer net inside Swap transactions: 10.052884537040203053 uPEG
- Transfer net outside Swap transactions: 0.05386982387297505 uPEG

## Top transaction senders by sell volume

| tx.from | Sell | Buy | Net Swap to pool | Transactions |
|---|---:|---:|---:|---:|
| `0x7475bcf1e667896d9df683f9c3b17b57b54141d7` | 14.309778685499864869 | 0 | 14.309778685499864869 | 3 |
| `0x3391626561e43d498e95cc44509d30e211abc4ea` | 2.957983102254321376 | 3.642803011128741183 | -0.684819908874419807 | 5 |
| `0x84d2e7b71c765ff0e3ac1f9ed43774387526a3a7` | 1.9616854 | 0 | 1.9616854 | 3 |
| `0x89b585df208c727829232d892a50806c3a20a4e6` | 1.6 | 0 | 1.6 | 1 |
| `0xa9ec08edd196b91bc9177420137804be1d6efda0` | 1.548472647209962374 | 0 | 1.548472647209962374 | 1 |

## Interpretation guardrail

Swap event amounts describe the pool swap calculation. For a token with custom transfer behavior or other same-window pool movements, they need not equal the ERC-20 balance change. Here, target-token Transfer logs reconcile the historical balance exactly; the non-zero Transfer-minus-Swap residual must be investigated rather than labelled automatically as a fee.
