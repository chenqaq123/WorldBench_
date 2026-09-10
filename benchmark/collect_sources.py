#!/usr/bin/env python3
"""Download, locate and freeze 14 excerpts from six real published works."""

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import urlopen

from worldline.artifacts import write_json

BOOKS = {
    11: ("Alice's Adventures in Wonderland", "Lewis Carroll", 1865),
    308: ("Three Men in a Boat", "Jerome K. Jerome", 1889),
    844: ("The Importance of Being Earnest", "Oscar Wilde", 1895),
    1342: ("Pride and Prejudice", "Jane Austen", 1813),
    1661: ("The Adventures of Sherlock Holmes", "Arthur Conan Doyle", 1892),
    514: ("Little Women", "Louisa May Alcott", 1868),
}
# Locators are literal search strings in the whitespace-normalized primary text.
# Topic terms retain a recognizable interaction without copying character names.
PASSAGES = [
    ("alice_riddle", 11, "Chapter VII: A Mad Tea-Party", "Why is a raven like a writing-desk?", "café", ["riddle", "answer"]),
    ("alice_seats", 11, "Chapter VII: A Mad Tea-Party", "I want a clean cup", "café", ["story", "interruption"]),
    ("boat_holiday", 308, "Chapter I: deciding on a holiday", "What we want is rest", "meeting room", ["holiday", "river", "trip"]),
    ("holmes_arrival", 1661, "The Red-Headed League: opening consultation", "I had called upon my friend, Mr. Sherlock Holmes", "meeting room", ["case", "account", "consultation"]),
    ("pride_evening", 1342, "Chapter III: returning from the assembly", "They found Mr. Bennet still up", "living room", ["dance", "evening", "ball"]),
    ("earnest_visit", 844, "Act I: a family visit", "Good afternoon, dear Algernon", "living room", ["visit", "invitation", "dinner"]),
    ("women_breakfast", 514, "Chapter II: A Merry Christmas", "Another bang of the street door", "dining room", ["breakfast", "share", "neighbor"]),
    ("earnest_tea", 844, "Act II: the tea-table disagreement", "Shall I lay tea here as usual", "dining room", ["tea", "preference", "politeness"]),
    ("pride_skills", 1342, "Chapter VIII: discussing accomplishments", "It is amazing to me", "seminar room", ["skill", "accomplishment", "standard"]),
    ("holmes_account", 1661, "The Red-Headed League: requesting the account", "Perhaps, Mr. Wilson, you would have", "seminar room", ["account", "detail", "evidence"]),
    ("women_club", 514, "Chapter X: The P.C. and P.O.", "With a few interruptions, they had kept this up for a year", "game room", ["club", "member", "meeting"]),
    ("alice_rules", 11, "Chapter VII: the meaning of a riddle", "Do you mean that you think you can find out the answer to it?", "game room", ["riddle", "meaning", "rule"]),
    ("boat_stew", 308, "Chapter XIV: planning an Irish stew", "It was still early when we got settled", "kitchen", ["stew", "ingredient", "recipe"]),
    ("women_housekeeping", 514, "Chapter XI: Experiments", "When they got up on Saturday morning", "kitchen", ["breakfast", "housekeeping", "work"]),
]


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def download(book_id):
    url = "https://www.gutenberg.org/files/{0}/{0}-h/{0}-h.htm".format(book_id)
    with urlopen(url, timeout=60) as response:
        raw = response.read()
    parser = TextParser()
    parser.feed(raw.decode("utf-8-sig"))
    return book_id, (url, re.sub(r"\s+", " ", " ".join(parser.parts)).strip())


def main():
    with ThreadPoolExecutor(max_workers=6) as pool:
        books = dict(pool.map(download, BOOKS))
    sources = []
    for source_id, book_id, locator, start, scene, terms in PASSAGES:
        url, text = books[book_id]
        offset = text.find(start)
        if offset < 0:
            raise ValueError("Primary-text locator not found: " + source_id)
        excerpt = " ".join(text[offset:].split()[:300])
        title, author, year = BOOKS[book_id]
        sources.append({
            "id": source_id, "title": title, "author": author, "year": year,
            "url": url, "locator": locator, "start_text": start,
            "scenes": [scene], "topic_terms": terms, "excerpt": excerpt,
            "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            "rights": "Public-domain original text; Project Gutenberg edition. No film adaptation used.",
        })
    destination = Path(__file__).resolve().parent / "sources" / "catalog.json"
    if destination.exists():
        raise FileExistsError("Source catalog already frozen; create an explicit new version to refresh it.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_json(destination, {"version": 1, "retrieved_at": datetime.now(timezone.utc).isoformat(), "sources": sources})
    print("Frozen {} excerpts from {} works: {}".format(len(sources), len(BOOKS), destination))


if __name__ == "__main__":
    main()
