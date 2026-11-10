from app import app
from db import get_db

app.testing = True
client = app.test_client()
all_ok = True


def check(url):
    global all_ok
    r = client.get(url)
    if r.status_code != 200:
        all_ok = False
    print("OK  " if r.status_code == 200 else "FAIL", r.status_code, url)


first = get_db()["products"].find_one()

for url in [
    "/",
    "/products/",
    "/products/?q=(&stock=low&sort=price_high&page=2",
    "/products/new",
]:
    check(url)

if first:
    check(f"/products/{first['_id']}")
    check(f"/products/{first['_id']}/edit")

print("\nSab theek hai." if all_ok else "\nKuch fail hua, upar dekho.")