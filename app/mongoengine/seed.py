import json
import random
from datetime import datetime

from app.config import config
from app.helpers import get_assets
from app.mongoengine import connection
from app.mongoengine.models import Category, Dimension, Product, Unit


async def fill_database():
    connection.drop_database(config.mongo_db)
    data = json.load(open(get_assets("seed/store.json")))
    categories = dict()
    for name in data["categories"]:
        categories[name] = Category(name=name)
    Category.objects.insert(categories.values())
    products = []
    for i, value in enumerate(data["products"]):
        product = Product(
            title=value["title"],
            description=value["description"],
            price=value["price"],
            dimension=Dimension(
                width=random.randint(10, 100),
                height=random.randint(10, 100),
                unit=list(Unit)[random.randint(0, 2)],
            ),
            created_at=datetime.fromisoformat(value["created_at"]),
            category=Category.objects(name=value["category_name"]).get(),
        )
        product.image.put(
            open(get_assets(f"images/product{(i % 5) + 1}.jpg"), "rb"),
            filename=f"product{(i % 5) + 1}.jpg",
            content_type="image/jpeg",
        )
        product.manual.put(
            open(get_assets("documents/manual.pdf"), "rb"),
            filename="manual.pdf",
            content_type="application/pdf",
        )
        products.append(product)
    Product.objects.insert(products)
