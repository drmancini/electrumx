# ElectrumX Asset Indexing Fix

**Date:** March 7, 2026
**Status:** Proposal
**Scope:** ElectrumX fork at `/home/talon/electrumx/`
**Affects:** Raptoreum (RTM), Raptoreum Testnet (tRTM)

---

## Problem

ElectrumX indexes transactions by hashing the full `scriptPubKey` (the `pk_script` bytes) into a `hashX`. For standard P2PKH outputs this works fine — the script is always the same for a given address:

```
OP_DUP OP_HASH160 <hash160> OP_EQUALVERIFY OP_CHECKSIG
```

Raptoreum asset transfer outputs append asset data after `OP_CHECKSIG`:

```
OP_DUP OP_HASH160 <hash160> OP_EQUALVERIFY OP_CHECKSIG OP_ASSET_ID <asset_payload> OP_DROP OP_DROP
```

Same address, different script bytes, **different hashX**. This means:

1. `blockchain.scripthash.get_history` — misses all asset transactions
2. `blockchain.scripthash.get_balance` — correct (asset vouts carry 0 RTM value)
3. `blockchain.scripthash.listunspent` — misses asset UTXOs
4. `blockchain.scripthash.subscribe` — does NOT fire for asset transfers

In practice: Eyrie's ElectrumX queries only see native RTM activity. Asset transfers are invisible. We currently work around this with daemon RPC (`getaddressdeltas`, `listassetbalancesbyaddress`), but real-time notifications via `scripthash.subscribe` won't trigger for asset activity.

---

## Proposed Fix

Override `hashX_from_script` in the `Raptoreum` coin class to strip asset data before hashing. This makes asset outputs produce the same hashX as standard P2PKH outputs for the same address.

### The Change

File: `src/electrumx/lib/coins.py`, in `class Raptoreum(Coin)`:

```python
class Raptoreum(Coin):
    NAME = "Raptoreum"
    SHORTNAME = "RTM"
    # ... existing fields ...

    # RTM asset opcodes appended after standard P2PKH scripts
    OP_CHECKSIG = 0xac
    OP_ASSET_ID = 0xbc

    @classmethod
    def hashX_from_script(cls, script):
        '''Strip RTM asset payload before hashing.

        Asset transfer scripts are standard P2PKH with asset data appended
        after OP_CHECKSIG:

            <P2PKH script> OP_CHECKSIG OP_ASSET_ID <payload> OP_DROP OP_DROP

        Stripping everything after OP_CHECKSIG produces the same hashX as
        a regular P2PKH output to the same address, so asset transactions
        appear in the address's normal history.
        '''
        marker = bytes([cls.OP_CHECKSIG, cls.OP_ASSET_ID])
        idx = script.find(marker)
        if idx != -1:
            script = script[:idx + 1]  # keep through OP_CHECKSIG
        return super().hashX_from_script(script)
```

`RaptoreumTestnet` inherits from `Raptoreum`, so it gets the fix automatically.

### What This Fixes

| Feature                     | Before | After  |
| --------------------------- | ------ | ------ |
| `get_history` sees asset txs | No    | **Yes** |
| `listunspent` sees asset UTXOs | No  | **Yes** |
| `subscribe` fires for asset transfers | No | **Yes** |
| Asset metadata in responses | No     | No     |

The last row is intentional — ElectrumX still returns raw tx hashes and values, not asset names/amounts. Eyrie continues to use daemon RPC for asset-specific data. The key win is that **`scripthash.subscribe` notifications will fire for asset activity**, enabling real-time updates.

### What This Does NOT Do

- No new ElectrumX RPC methods
- No asset-specific database tables
- No protocol extensions
- No changes to how Eyrie queries ElectrumX

---

## Deployment

### Re-Index Required

Changing `hashX_from_script` alters the hash for every asset-related output. The existing LevelDB index has the old (wrong) hashX values. A full re-index from genesis is required.

**Steps:**

1. Stop ElectrumX (`systemctl stop electrumx` or kill the process)
2. Apply the code change to `src/electrumx/lib/coins.py`
3. Delete the existing database (typically `~/.electrumx/db/` or wherever `DB_DIRECTORY` points)
4. Restart ElectrumX — it will re-sync from the daemon
5. Wait for sync to complete (watch logs for "caught up" message)

**Time estimate:** Depends on chain length and disk speed. RTM mainnet (~1.3M blocks) should take a few hours.

### Rollback

If something goes wrong: revert the code change and re-index again. The daemon data is untouched — ElectrumX is a read-only indexer.

### Risks

- **Low:** The change only affects RTM/tRTM. The `marker` pattern (`OP_CHECKSIG OP_ASSET_ID`) should not appear in standard scripts. Other coin classes are untouched.
- **Medium:** Any wallet or tool currently subscribed to ElectrumX would see different scripthash values for the same addresses after re-index. Not currently relevant since only Eyrie connects to this instance.
- **Edge case:** If a script has `OP_CHECKSIG` followed by `0xbc` for a non-asset reason, it would be incorrectly stripped. This is extremely unlikely in practice — `0xbc` is specifically `OP_ASSET_ID` in the RTM opcode table and has no other meaning.

---

## Future: Full Asset Indexing in ElectrumX

The hashX fix above (Level 1) is a quick win, but it still leaves asset data queries going through daemon RPC. That works, but ElectrumX is fundamentally more efficient for address-indexed queries:

| Factor               | ElectrumX (LevelDB)                    | Daemon RPC (addressindex)               |
| -------------------- | --------------------------------------- | --------------------------------------- |
| Lookup speed         | O(1) key-value, pre-indexed             | Secondary index on block storage        |
| Connection           | Persistent TCP, no per-request overhead | HTTP JSON-RPC per call                  |
| Batching             | Multiple addresses in one round-trip    | One call per query                      |
| Push notifications   | Native (`scripthash.subscribe`)         | Not available — poll only               |
| Architecture         | Purpose-built for address queries       | Bolted onto full node                   |

This is the same reason we moved native RTM queries from daemon RPC to ElectrumX in WS1. If assets become a core Talon feature, the same logic applies — they should live in ElectrumX too.

### Level 2 — Asset-Aware Indexing (Deferred)

**Scope:** ~300-500 lines across 4-5 ElectrumX source files.

What's needed:

1. **Parse asset payloads in `block_processor.advance_txs`** — extract asset ID, name, and amount from the `OP_ASSET_ID` data in `pk_script` when indexing outputs
2. **New DB index** — map `hashX → [(tx_hash, asset_id, amount, height)]` in LevelDB (new key prefix or column family)
3. **Undo/reorg logic** — ensure asset state rolls back correctly on chain reorganizations
4. **New session RPC methods** — e.g., `blockchain.scripthash.get_asset_history`, `blockchain.scripthash.list_asset_balances`
5. **Update Eyrie's ElectrumX client** — add methods to call the new RPCs

The tricky parts are the DB schema design and ensuring undo/reorg correctly rolls back asset state. The RPC methods and Eyrie client changes are straightforward.

### Recommended Approach

**Low-hanging fruit:** The hashX fix (Level 1). It's ~15 lines of Python, one re-index, and it immediately fixes correctness of existing Eyrie endpoints. Right now, `/api/v1/transactions/all` returns transaction history from ElectrumX that is **missing every asset transfer**. After the fix, those transactions appear in the normal history — no Eyrie code changes needed. This is a data correctness fix, not a new feature.

**Later — subscriptions + push:** Leveraging `scripthash.subscribe` for real-time notifications requires building out the full push chain: Eyrie subscription manager → WebSocket/SSE server → Talon client. That's a separate, larger project that benefits all data (native balances, fees, prices), not just assets. The hashX fix is a prerequisite but doesn't depend on it.

**Later — full asset indexing (Level 2):** When assets are a core Talon feature, move asset queries from daemon RPC into ElectrumX for better performance and a unified interface.

### Current Hybrid (After Level 1)

- **ElectrumX:** Native TX history (now including asset txs) + UTXOs + subscriptions ready for future use
- **Daemon RPC:** Asset metadata + asset balances + asset transfer details (until Level 2)
