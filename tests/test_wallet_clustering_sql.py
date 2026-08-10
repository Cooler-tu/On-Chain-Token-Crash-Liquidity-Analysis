"""Wallet-clustering SQL + signal tests — minimal fetch contract."""
from __future__ import annotations

import re
import unittest

from src.data.dune import _load_sections, _prep, _render
from src.analysis.wallet_clustering import (
    CLUSTER_GAS_COLUMNS,
    CLUSTER_TRANSFER_COLUMNS,
    EDGE_SIGNALS,
    SUPPORT_SIGNALS,
    apply_gas_payer_edges,
    apply_owner_edges,
    build_clusters,
    cluster_from_dune_rows,
    extract_transfer_edges,
)


def _active_sql(text: str) -> str:
    return "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("--")
    )


def _select_aliases(sql: str) -> list[str]:
    """Output column aliases from CAST(...) AS name select lists."""
    active = _active_sql(sql)
    # Use newline-FROM so CAST("from" ...) does not truncate the select list.
    m = re.search(r"\bSELECT\b(.*?)\nFROM\b", active, re.I | re.S)
    if not m:
        m = re.search(r"\bSELECT\b(.*)\bFROM\s+\w", active, re.I | re.S)
    if not m:
        return []
    # Prefer ") AS alias" so inner "AS varchar" is ignored.
    aliases = re.findall(r"\)\s+AS\s+(\w+)", m.group(1), re.I)
    if aliases:
        return [a.lower() for a in aliases]
    return [a.lower() for a in re.findall(r"\bAS\s+(\w+)\s*(?:,|$)", m.group(1), re.I)]


class ClusterSqlMinimalityTest(unittest.TestCase):
    """Dune sections for clustering must be exactly two, minimal columns."""

    @classmethod
    def setUpClass(cls):
        cls.sections = _load_sections()

    def test_only_two_cluster_sql_sections(self):
        cluster_names = [n for n in self.sections if n.startswith("cluster_")]
        self.assertEqual(
            sorted(cluster_names),
            ["cluster_gas_payers", "cluster_transfers"],
            "clustering must use exactly two Dune pulls (transfers + gas)",
        )

    def test_no_traces_or_trades_in_cluster_sql(self):
        for name in ("cluster_transfers", "cluster_gas_payers"):
            sql = self.sections[name].lower()
            self.assertNotIn("ethereum.traces", sql)
            self.assertNotIn("dex.trades", sql)
            self.assertNotIn("creation_traces", sql)

    def test_cluster_transfers_columns_exact(self):
        sql = _render(
            "cluster_transfers",
            _prep({
                "token": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "from_block": 1,
                "to_block": 10,
                "address_list": [
                    "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "0xcccccccccccccccccccccccccccccccccccccccc",
                ],
            }),
        )
        aliases = _select_aliases(sql)
        self.assertEqual(aliases, list(CLUSTER_TRANSFER_COLUMNS))
        active = _active_sql(sql).lower()
        # both endpoints must be candidates
        self.assertIn("in (", active)
        self.assertEqual(active.count("in ("), 2)
        self.assertIn('"from" <> "to"', active.replace(" ", " "))
        # no junk columns
        for banned in ("log_index", "protocol", "version", "pool", "amount_usd"):
            self.assertNotIn(banned, aliases)

    def test_cluster_gas_columns_exact(self):
        sql = _render(
            "cluster_gas_payers",
            _prep({
                "tx_hash_list": [
                    "0x" + "11" * 32,
                    "0x" + "22" * 32,
                ],
            }),
        )
        aliases = _select_aliases(sql)
        self.assertEqual(aliases, list(CLUSTER_GAS_COLUMNS))
        active = _active_sql(sql).lower()
        self.assertIn("ethereum.transactions", active)
        self.assertIn("hash in", active.replace("\n", " "))

    def test_transfers_index_sql_not_used_as_cluster_contract(self):
        """Index `transfers` may keep extra cols; cluster path must not."""
        self.assertIn("transfers", self.sections)
        idx_aliases = _select_aliases(self.sections["transfers"])
        self.assertNotEqual(
            idx_aliases,
            list(CLUSTER_TRANSFER_COLUMNS),
            "index transfers and cluster_transfers must stay separate",
        )


class ClusterSignalLogicTest(unittest.TestCase):
    def test_reciprocal_forms_edge(self):
        rows = [
            {"from_address": "0xa", "to_address": "0xb", "amount_raw": "100", "tx_hash": "0x1"},
            {"from_address": "0xb", "to_address": "0xa", "amount_raw": "100", "tx_hash": "0x2"},
        ]
        edges = extract_transfer_edges(rows)
        self.assertEqual(len(edges), 1)
        ev = next(iter(edges.values()))
        self.assertIn("reciprocal_transfer", ev.signals)
        self.assertIn("reciprocal_transfer", EDGE_SIGNALS)

    def test_repeated_requires_min_count_and_similarity(self):
        good = [
            {"from_address": "0xa", "to_address": "0xb", "amount_raw": "100", "tx_hash": f"0x{i}"}
            for i in range(3)
        ]
        edges = extract_transfer_edges(good)
        self.assertTrue(any("repeated_transfer" in e.signals for e in edges.values()))

        too_few = good[:2]
        self.assertFalse(
            any("repeated_transfer" in e.signals for e in extract_transfer_edges(too_few).values())
        )

        dissimilar = [
            {"from_address": "0xa", "to_address": "0xb", "amount_raw": str(10 ** i), "tx_hash": f"0x{i}"}
            for i in range(3)
        ]
        self.assertFalse(
            any(
                "repeated_transfer" in e.signals
                for e in extract_transfer_edges(dissimilar).values()
            )
        )

    def test_same_tx_alone_does_not_form_edge(self):
        # Three distinct txs each with A->B once — wait, that's repeated.
        # Same tx co-occurrence without edge signal: use different amounts so
        # repeated fails similarity, and only one direction (no reciprocal).
        # Actually 3 same-direction with dissimilar amounts → no repeated.
        # same_tx_cooccurrence counts distinct txs on undirected pair — still support only.
        rows = [
            {"from_address": "0xa", "to_address": "0xb", "amount_raw": "1", "tx_hash": "0x1"},
            {"from_address": "0xa", "to_address": "0xb", "amount_raw": "1000000", "tx_hash": "0x2"},
            {"from_address": "0xa", "to_address": "0xb", "amount_raw": "999999999", "tx_hash": "0x3"},
        ]
        edges = extract_transfer_edges(rows)
        self.assertEqual(edges, {}, "dissimilar one-way transfers must not create an edge")
        # Internal support path: rebuild with helper that keeps support-only (not exported).
        # pair shares 3 txs but extract drops support-only — correct.

    def test_gas_payer_edge(self):
        transfers = [
            {
                "from_address": "0xaaa0000000000000000000000000000000000001",
                "to_address": "0xbbb0000000000000000000000000000000000002",
                "amount_raw": "1",
                "tx_hash": "0xabc",
            }
        ]
        gas = {"0xabc": "0xccc0000000000000000000000000000000000003"}
        cand = {
            "0xaaa0000000000000000000000000000000000001",
            "0xbbb0000000000000000000000000000000000002",
            "0xccc0000000000000000000000000000000000003",
        }
        edges = apply_gas_payer_edges({}, transfers, gas, cand)
        self.assertTrue(any("same_gas_payer" in e.signals for e in edges.values()))
        # payer not in candidates → no edge
        edges2 = apply_gas_payer_edges({}, transfers, gas, cand - {gas["0xabc"]})
        self.assertEqual(edges2, {})

    def test_owner_contract_edge(self):
        owners = {
            "0xcontract00000000000000000000000000000001": "0xeoa0000000000000000000000000000000000001",
            "0xcontract00000000000000000000000000000002": "0xeoa0000000000000000000000000000000000001",
        }
        cand = set(owners) | {"0xeoa0000000000000000000000000000000000001"}
        edges = apply_owner_edges({}, owners, cand)
        sigs = {s for e in edges.values() for s in e.signals}
        self.assertIn("same_owner_contract", sigs)

    def test_clusters_ignore_support_only_pairs(self):
        # Force an edge via reciprocal, ensure support signal listed as support not edge type
        rows = [
            {"from_address": "0xa", "to_address": "0xb", "amount_raw": "50", "tx_hash": "0x1"},
            {"from_address": "0xb", "to_address": "0xa", "amount_raw": "50", "tx_hash": "0x2"},
            {"from_address": "0xa", "to_address": "0xb", "amount_raw": "50", "tx_hash": "0x3"},
        ]
        edges = extract_transfer_edges(rows)
        clusters = build_clusters(edges)
        self.assertEqual(len(clusters), 1)
        types = {s["type"] for s in clusters[0].signals}
        self.assertTrue(types <= EDGE_SIGNALS)
        self.assertNotIn("same_tx_cooccurrence", types)
        self.assertTrue(SUPPORT_SIGNALS)

    def test_end_to_end_fetch_contract_metadata(self):
        result = cluster_from_dune_rows(
            [
                {"from_address": "0xa", "to_address": "0xb", "amount_raw": "10", "tx_hash": "0x1"},
                {"from_address": "0xb", "to_address": "0xa", "amount_raw": "10", "tx_hash": "0x2"},
            ],
            gas_rows=[],
            candidates=["0xa", "0xb"],
        )
        self.assertEqual(
            result["fetch_contract"]["dune_queries"],
            ["cluster_transfers", "cluster_gas_payers"],
        )
        self.assertIn("ethereum.traces", result["fetch_contract"]["not_used"])
        self.assertEqual(result["num_clusters"], 1)


if __name__ == "__main__":
    unittest.main()
