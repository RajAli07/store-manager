import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
    MONGO_URI = os.environ["MONGO_URI"]
    MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "ecommerce")
    PAGE_SIZE = 25

    APP_NAME = os.environ.get("APP_NAME", "StockWise")
    OWNER_NAME = os.environ.get("OWNER_NAME", "Your Name")