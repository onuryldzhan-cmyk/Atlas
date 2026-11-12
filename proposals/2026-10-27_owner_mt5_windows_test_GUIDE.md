# MT5 demo test on Windows — step-by-step guide for the owner

**Purpose:** run Atlas FOREX for the first time against a real MetaTrader 5 terminal, with a **demo account only**,
and measure what the code cannot know yet: the commission, the swap and the December hours. PAPER only. Atlas
never sends an order to MT5; it reads market data only.

The MT5 Python API behaviour is **UNKNOWN until this test**. The function names were checked against the PyPI wheel
5.0.6231; the MQL5 documentation could not be reached.

## 0. Before you start
- Install the MetaTrader 5 terminal from your broker and log into a **demo** account. Atlas refuses a real account:
  the provider checks the account's trade mode.
- Run on a weekday, while the forex market is open. The server-time offset is measured from a fresh tick. Outside
  market hours, pass `--server-utc-offset N` instead (N = the broker server time minus UTC, in hours).
- Open PowerShell in the repository folder. Check out the `feature/forex-pivot` branch.

## 1. Install the MT5 Python package
```powershell
pip install MetaTrader5
```

## 2. Write the instrument rules (lot step, minimum, tick)
```powershell
python -m tools.refresh_mt5_instrument_rules
```
- This writes `config/instrument_rules_mt5.json`.
- Expected output: `wrote 4 MT5 instrument rules ...`.
- If it says `refused: ...`, stop and send the message.

## 3. Create the forex book (margin book, leverage 2)
```powershell
python -m tools.bootstrap_financial_state --state-directory C:\AtlasState\forex\shadow --leverage 2
python -m tools.bootstrap_financial_state --state-directory C:\AtlasState\forex\shadow --leverage 2 --verify-only
```
- The second command must exit with no error.
- An older forex book without `--leverage 2` is refused (`FINANCIAL_LEVERAGE_CONFLICT`). Use a new, empty folder.

## 4. Start Atlas in FOREX
```powershell
$env:ATLAS_MARKET = "FOREX"
$env:ATLAS_FILL_MODEL = "BOOK"
$env:ATLAS_STATE_DIRECTORY = "C:\AtlasState\forex\shadow"
python main.py
```
- At startup, look for the line `Policy manifest MATCH (registry ...v5.108, proposal FOREX-POLICY-MANIFEST-V5,
  ...)`. A `Policy manifest ... BLOCK_NEW_RISK` line means new risk is blocked. Stop and send that line.
- Let it run for at least one full trading day.

## 5. Check the book
```powershell
python -m tools.data_health_check --state-dir C:\AtlasState\forex\shadow
python -m tools.paper_position_report --no-price
```
`paper_position_report` reads `ATLAS_STATE_DIRECTORY` (set in step 4). Use `--no-price`: its live-price lookup is
still the crypto (Binance) one, so forex prices are not available there (known issue).

## 6. What to measure and send back (the agent cannot measure these)
1. **Commission:** what your demo account charges per lot per side (from the terminal's account or contract
   specification).
2. **Swap:** `swap_long` and `swap_short` for EURUSD, GBPUSD, AUDUSD and NZDUSD (the terminal's symbol
   specification).
3. **December hours:** the broker's closing times on 24 and 31 December.
4. **Spread:** whether BUY fills appear at the ask and SELL fills at the bid (the BOOK model).
5. **Errors:** any error or `refused` line, copied exactly.

These values go into a new, ratified policy manifest (commission, swap). They are never typed into the code
directly.
