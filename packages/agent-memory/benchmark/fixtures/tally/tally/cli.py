"""tally: a small expense ledger.

    tally add AMOUNT CATEGORY [--date YYYY-MM-DD]
    tally list [--total]
    tally report YEAR MONTH
"""
import argparse
from datetime import date

from tally import report, storage


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tally")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("amount")
    add.add_argument("category")
    add.add_argument("--date", default=None)
    lst = sub.add_parser("list")
    lst.add_argument("--total", action="store_true")
    rep = sub.add_parser("report")
    rep.add_argument("year", type=int)
    rep.add_argument("month", type=int)
    args = parser.parse_args(argv)

    if args.command == "add":
        storage.append({
            "amount": float(args.amount),
            "category": args.category,
            "date": args.date or date.today().isoformat(),
        })
    elif args.command == "list":
        entries = storage.load()
        for e in entries:
            print(f"{e['date']}  {e['category']:<16}{e['amount']:>10}")
        if args.total:
            print(f"total: {sum(e['amount'] for e in entries)}")
    elif args.command == "report":
        print(report.render(report.monthly(storage.load(), args.year, args.month)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
