"""
Canonical internal schema every adapter must produce. This is exactly
the format matcher.py's load_data() currently returns - the adapter
layer's job is to make this format the ONLY thing matcher.py depends on.

bank_row:    {bank_id, date (ISO 'YYYY-MM-DD'), description, ref_number, credit (float), debit (float)}
gateway_row: {settlement_id, txn_ref, gross_amount, fee, tax, refund, net_amount, settled_date (ISO)}
erp_row:     {entry_id, txn_ref, amount, entry_date (ISO), account_code}
"""
