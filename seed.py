import asyncio

from app.mongoengine.seed import fill_database as fill_mongo_database
from app.odmantic.seed import fill_database as fill_odm_database
from app.sqla.seed import fill_database as fill_sqla_database


async def main():
    print("Start filling SQLModel database")
    await fill_sqla_database()
    print("End filling SQLModel database")
    print("Start filling MongoEngine database")
    await fill_mongo_database()
    print("End filling MongoEngine database")
    print("Start filling Odmantic database")
    await fill_odm_database()
    print("End filling Odmantic database")


asyncio.run(main())
