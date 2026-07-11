#!/usr/bin/env python3
"""Search X, Google, and Facebook for the same query."""

import argparse
import urllib.parse
import webbrowser


def build_search_urls(query: str) -> dict[str, str]:
    encoded = urllib.parse.quote_plus(query)
    return {
        "X": f"https://twitter.com/search?q={encoded}&src=typed_query",
        "Google": f"https://www.google.com/search?q={encoded}",
        "Facebook": f"https://www.facebook.com/search/top/?q={encoded}",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Open or print search results for X, Google, and Facebook."
    )
    parser.add_argument(
        "query",
        nargs=argparse.REMAINDER,
        help="Search query to use across the services.",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the search URLs in the default browser.",
    )
    parser.add_argument(
        "--print",
        dest="print_urls",
        action="store_true",
        help="Print the search URLs instead of opening them.",
    )

    args = parser.parse_args()

    if not args.query:
        parser.error("Please provide a search query.")

    query_text = " ".join(args.query).strip()
    urls = build_search_urls(query_text)

    if args.open:
        for service, url in urls.items():
            print(f"Opening {service}: {url}")
            webbrowser.open_new_tab(url)
    else:
        print(f"Search query: {query_text}\n")
        for service, url in urls.items():
            print(f"{service}: {url}")


if __name__ == "__main__":
    main()
