from app.mongoengine.seed import fill_database as fill_mongo_database
from app.sqla.seed import fill_database as fill_sqla_database

fill_mongo_database()
fill_sqla_database()
