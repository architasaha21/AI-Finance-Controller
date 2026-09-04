import csv
import os

def normalize_source(data_dir):
    """CSV adapter - reads the 3 CSVs and returns them already in
    canonical schema (this is the existing format, so no transformation
    needed, just centralizes the loading logic here instead of matcher.py)."""
    def load(path):
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    bank = load(os.path.join(data_dir, "bank_statement.csv"))
    gateway = load(os.path.join(data_dir, "gateway_settlement.csv"))
    erp = load(os.path.join(data_dir, "erp_ledger.csv"))
    return bank, gateway, erp
