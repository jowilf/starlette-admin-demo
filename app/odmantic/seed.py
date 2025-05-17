import json
import random

from app.helpers import get_assets
from app.odmantic import engine
from app.odmantic.models import Author, Book


async def fill_database():
    data = json.load(open(get_assets("seed/books.json")))
    authors = []
    for _it in data["authors"]:
        authors.append(Author.model_validate(_it))
    books = []
    for _it in data["books"]:
        _it["author"] = random.choice(authors)  # noqa: S311
        books.append(Book.model_validate(_it))
    await engine.remove(Author)
    await engine.remove(Book)
    await engine.save_all(authors)
    await engine.save_all(books)
