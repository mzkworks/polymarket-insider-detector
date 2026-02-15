# Polygon/Polymarket Wallet Linking Implementation

## Overview

This document describes the implementation for linking Polygon wallets (EOAs) with Polymarket wallets (proxy contracts) and displaying both addresses with clickable links in the dashboard.

## Background

**Polymarket Wallet System:**
- **Proxy Wallet**: Smart contract wallet that executes trades on Polymarket (what we currently have in the database as `wallet_address`)
- **EOA (Externally Owned Account)**: The real Polygon wallet that controls the proxy wallet (the actual user's wallet)

When users trade on Polymarket, they sign transactions with their EOA, but the trade is executed through their proxy wallet. To properly track users, we need to capture both addresses.

## Changes Implemented

### 1. API Client Updates
**File:** [src/data/polymarket_client.py](src/data/polymarket_client.py)

Added `eoa_address` capture in the `normalize_trade()` function (line 344):

```python
@staticmethod
def normalize_trade(raw: dict, market_id: str) -> dict:
    """Transform a Data API trade response into our DB schema format."""
    return {
        "id": PolymarketClient.make_trade_id(raw),
        "market_id": market_id,
        "condition_id": raw.get("conditionId"),
        "wallet_address": raw.get("proxyWallet", ""),
        "eoa_address": raw.get("makerAddress", ""),  # Polygon EOA that owns the proxy
        "side": raw.get("side", ""),
        # ... other fields
    }
```

### 2. Database Schema Updates
**File:** [src/data/database.py](src/data/database.py)

Added `eoa_address` column to both `trades` and `wallet_scores` tables:

```sql
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    market_id TEXT REFERENCES markets(id),
    condition_id TEXT,
    wallet_address TEXT NOT NULL,
    eoa_address TEXT,  -- NEW COLUMN
    side TEXT NOT NULL,
    -- ... other fields
);

CREATE TABLE IF NOT EXISTS wallet_scores (
    wallet_address TEXT PRIMARY KEY,
    eoa_address TEXT,  -- NEW COLUMN
    total_trades INTEGER,
    -- ... other fields
);

-- NEW INDEX
CREATE INDEX IF NOT EXISTS idx_trades_eoa ON trades(eoa_address);
```

Updated `insert_trades()` method to include `eoa_address` in inserts.

### 3. Wallet Scoring Updates
**File:** [src/analysis/wallet_scorer.py](src/analysis/wallet_scorer.py)

Modified `score_wallet()` to extract and include EOA address (lines 134-148):

```python
# Extract EOA address from first trade (all trades for same proxy have same EOA)
eoa_address = None
if trades:
    eoa_address = trades[0].get("eoa_address")

return {
    "wallet_address": wallet_address,
    "eoa_address": eoa_address,  # NEW FIELD
    "total_trades": total,
    # ... other fields
}
```

Updated `save_scores()` to persist `eoa_address` to database.

### 4. Dashboard Updates
**File:** [src/dashboard/app.py](src/dashboard/app.py)

Updated Wallet Deep-Dive page to display both addresses with clickable links (lines 163-166):

```python
# Display wallet addresses with links
st.markdown(f"**Proxy Wallet:** `{wallet[:10]}...{wallet[-8:]}` [View on Polymarket](https://polymarket.com/profile/{wallet})")
if s.get("eoa_address"):
    eoa = s["eoa_address"]
    st.markdown(f"**EOA (Owner):** `{eoa[:10]}...{eoa[-8:]}` [View on Polygonscan](https://polygonscan.com/address/{eoa})")
```

### 5. Migration Script
**File:** [scripts/migrate_add_eoa.py](scripts/migrate_add_eoa.py)

Created migration script to add `eoa_address` columns to existing database tables.

## Next Steps (After Database Copy Completes)

Once the database copy finishes (currently at 48% complete), follow these steps:

### Step 1: Run Migration Script

```bash
python3 -m scripts.migrate_add_eoa
```

This will add the `eoa_address` column to both `trades` and `wallet_scores` tables in your existing database.

Expected output:
```
Starting migration: adding eoa_address column...
  Adding eoa_address column to trades table...
  ✓ Added eoa_address to trades
  Adding eoa_address column to wallet_scores table...
  ✓ Added eoa_address to wallet_scores
  Creating index on trades.eoa_address...
  ✓ Created index on trades.eoa_address

✅ Migration complete!
```

### Step 2: Re-run Ingestion to Capture EOAs

**Option A: Full Re-ingestion (Recommended)**

If you want EOA data for all 207M trades, re-run the full ingestion:

```bash
# This will take ~10-12 hours but will capture EOA for all trades
python3 -m scripts.ingest --full
```

**Option B: Incremental Ingestion (Faster)**

If you only need EOA data for new trades going forward:

```bash
# Just run normal ingestion, it will capture EOA for new trades
python3 -m scripts.ingest
```

### Step 3: Re-run Wallet Scoring

Once trades have `eoa_address` populated, re-run scoring to add EOA to wallet_scores:

```bash
python3 -m scripts.score
```

This will:
- Score all wallets with their updated trades
- Extract and save the EOA address for each wallet
- Update the `wallet_scores` table with `eoa_address`

### Step 4: View in Dashboard

Launch the dashboard to see the updated wallet links:

```bash
streamlit run src/dashboard/app.py
```

Navigate to "Wallet Deep-Dive" page and select a wallet. You'll now see:
- **Proxy Wallet** with link to Polymarket profile
- **EOA (Owner)** with link to Polygonscan

## Links Generated

### Polymarket Profile
Format: `https://polymarket.com/profile/{proxy_wallet_address}`

Example: https://polymarket.com/profile/0x123abc...

Shows:
- User's trading history on Polymarket
- Current positions
- Total volume
- PnL

### Polygonscan
Format: `https://polygonscan.com/address/{eoa_address}`

Example: https://polygonscan.com/address/0x456def...

Shows:
- On-chain transaction history
- Token balances
- Contract interactions
- Gas usage

## Database Impact

- **trades table**: +1 column (`eoa_address TEXT`)
- **wallet_scores table**: +1 column (`eoa_address TEXT`)
- **New index**: `idx_trades_eoa` on `trades(eoa_address)`
- **Storage increase**: Minimal (~40 bytes per trade ≈ 8GB for 207M trades)

## Future Enhancements

### Phase 1 (Current)
- ✅ Capture EOA from API during ingestion
- ✅ Store EOA in database
- ✅ Display both addresses in dashboard

### Phase 2 (Future)
- 🔄 Group wallets by EOA to detect users with multiple proxy wallets
- 🔄 Add EOA-level aggregation in wallet scoring
- 🔄 Detect sybil attacks where one EOA controls multiple proxies

### Phase 3 (Future)
- 🔄 On-chain verification: Query proxy contract's `owner()` function to verify EOA
- 🔄 Backfill missing EOAs using Web3.py for historical trades
- 🔄 Track EOA changes if proxy ownership transfers

## Troubleshooting

### "Column eoa_address already exists" during migration
This is fine - the migration script checks for existing columns and skips them safely.

### EOA is showing as None in dashboard
This means:
1. The trade data was ingested before the EOA capture was added
2. Solution: Re-run ingestion to capture EOA data (see Step 2 above)

### makerAddress not in API response
Polymarket's Data API should include `makerAddress` in trade responses. If it's missing:
- Check API version/endpoint
- Verify the trade is recent (older trades may have different format)
- Contact Polymarket support if issue persists

## Testing

To verify the implementation is working:

```bash
# 1. Check if columns exist
sqlite3 data/polymarket.db "PRAGMA table_info(trades)" | grep eoa_address

# 2. Check if EOA data is being captured (after re-ingestion)
sqlite3 data/polymarket.db "
SELECT COUNT(*) as total_trades,
       COUNT(eoa_address) as trades_with_eoa,
       COUNT(eoa_address) * 100.0 / COUNT(*) as percentage_with_eoa
FROM trades
"

# 3. Sample trades with EOA
sqlite3 data/polymarket.db "
SELECT wallet_address, eoa_address, market_id, timestamp
FROM trades
WHERE eoa_address IS NOT NULL
LIMIT 5
"

# 4. Check wallet_scores
sqlite3 data/polymarket.db "
SELECT wallet_address, eoa_address, insider_score
FROM wallet_scores
WHERE eoa_address IS NOT NULL
ORDER BY insider_score DESC
LIMIT 10
"
```

## Summary

This implementation allows you to:
1. **Track both wallet types**: Proxy (Polymarket) and EOA (Polygon)
2. **Link to external services**: Polymarket profiles and Polygonscan
3. **Future analysis**: Detect users with multiple wallets, track on-chain activity
4. **Better UX**: Users can quickly navigate to relevant blockchain explorers

The changes are backward-compatible - existing functionality continues to work while new trades capture EOA data.
