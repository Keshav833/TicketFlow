import argparse
from collections import Counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def parse_args():
    parser = argparse.ArgumentParser(
        description="Count HTTP 200 and 429 responses from the events API."
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000/api/events/",
    )
    parser.add_argument("--count", type=int, default=200)
    args = parser.parse_args()
    if args.count <= 0:
        parser.error("--count must be positive.")
    return args


def main():
    args = parse_args()
    counts = Counter()
    for _ in range(args.count):
        request = Request(args.url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=10) as response:
                counts[response.status] += 1
        except HTTPError as error:
            counts[error.code] += 1
        except URLError as error:
            raise SystemExit(f"Could not reach {args.url}: {error.reason}") from error

    print(f"Requests: {args.count}")
    print(f"HTTP 200: {counts[200]}")
    print(f"HTTP 429: {counts[429]}")
    other = sum(count for code, count in counts.items() if code not in {200, 429})
    print(f"Other status codes: {other}")
    for code, count in sorted(counts.items()):
        if code not in {200, 429}:
            print(f"  HTTP {code}: {count}")


if __name__ == "__main__":
    main()
