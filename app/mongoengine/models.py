from datetime import datetime
from enum import Enum
from starlette.requests import Request
import mongoengine as me


class Unit(str, Enum):
    m = "m"
    cm = "cm"
    mm = "mm"


class Dimension(me.EmbeddedDocument):
    width = me.IntField(min_value=10, max_value=100)
    height = me.IntField(min_value=10, max_value=100)
    unit = me.EnumField(Unit)


class Product(me.Document):
    title = me.StringField(min_length=3)
    description = me.StringField()
    price = me.DecimalField(min_value=0.01)
    dimension = me.EmbeddedDocumentField(Dimension)
    image = me.ImageField(thumbnail_size=(128, 128))
    manual = me.FileField()
    created_at = me.DateTimeField(default=datetime.utcnow)
    category = me.ReferenceField("Category")


class Category(me.Document):
    name = me.StringField(min_length=3, unique=True)

    def __admin_repr__(self, request: Request):
        return self.name
