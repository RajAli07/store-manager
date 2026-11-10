from pymongo import MongoClient

from config import Config

_client = None


def get_db():
    global _client
    if _client is None:
        _client = MongoClient(Config.MONGO_URI, serverSelectionTimeoutMS=8000)
    return _client[Config.MONGO_DB_NAME]