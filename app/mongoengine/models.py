from datetime import datetime

import mongoengine as me
from mongoengine import connect


class Product(me.Document):
    title = me.StringField(min_length=3)
    description = me.StringField()
    price = me.DecimalField()
    image = me.ImageField(thumbnail_size=(128, 128))
    manual = me.FileField()
    created_at = me.DateTimeField(default=datetime.utcnow)
    category = me.ReferenceField("Category")


class Category(me.Document):
    name = me.StringField(min_length=3, unique=True)


if __name__ == "__main__":
    connect("demo")
