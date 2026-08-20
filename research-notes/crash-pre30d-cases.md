# Crash cases — 30 days before incident

Windows are `[incident-216000, incident]` with `--incident-block` set to the crash block.
Index is Dune-only. These are sudden-crash / collapse events with prior trading history;
one-day rugs (e.g. ApeMars APRZ, listed 2026-06-06 and dumped 2026-06-07) are excluded
because the pre-30d window would be mostly empty.

| Token | Why this event | Incident (UTC) | `--incident-block` | `--from-block` | Output |
|---|---|---|---:|---:|---|
| OM (MANTRA) | ~90% in ~1h (CEX liquidation cascade; DEX still a control) | 2025-04-13 18:28 | 22261846 | 22045846 | `output-om-crash-pre30d` |
| FTT | FTX collapse | 2022-11-08 16:00 | 15926371 | 15710371 | `output-ftt-crash-pre30d` |
| CEL | Celsius paused withdrawals | 2022-06-13 12:00 | 14955880 | 14739880 | `output-cel-crash-pre30d` |
| CREDI | ~97% down from 2025-08-08 ATH | 2025-08-08 22:18 | 23099271 | 22883271 | `output-credi-crash-pre30d` |

Contracts:

- OM `0x3593D125a4f7849a1B059E64F4517A86Dd60c95d`
- FTT `0x50D1C9771902476076eCFc8B2A83Ad6b9355a4c9`
- CEL `0xaaAEBE6Fe48E54f431b0C390CfaF0b017d09D42d`
- CREDI `0xaE6e307c3Fe9E922E5674DBD7F830Ed49c014c6B`

OM/FTT/CEL dumps were largely CEX-driven; this pipeline only sees DEX pools. Treat
DEX-side concentration / withdrawals as incomplete evidence, not the full crash
mechanism.
