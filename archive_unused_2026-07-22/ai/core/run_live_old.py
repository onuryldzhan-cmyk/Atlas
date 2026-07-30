from atlas_live_connector import AtlasLiveConnector

# CIO entegreli connector
connector = AtlasLiveConnector({
    'demo_mode': True,
    'min_confidence': 0.2,
    'max_position_size': 0.15,
    'max_positions': 5,
    'symbols': [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT",
        "XRPUSDT", "DOTUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT",
        "MATICUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT", "ETCUSDT",
        "XLMUSDT", "ALGOUSDT", "VETUSDT", "FILUSDT", "TRXUSDT"
    ]
})

print("=" * 70)
print("ATLAS AI - CANLI TEST (CIO Entegreli)")
print("=" * 70)
print("Durdurmak icin: Ctrl+C")
print("=" * 70)

# Surekli calistir (her 60 saniyede bir)
connector.run_continuous(60)