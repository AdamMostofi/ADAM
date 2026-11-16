# tally

A small expense ledger for a household, kept on the family file server and
used from several machines.

```bash
python -m tally.cli add 12.50 food --date 2026-03-04
python -m tally.cli list --total
python -m tally.cli report 2026 3
python -m pytest -q
```
