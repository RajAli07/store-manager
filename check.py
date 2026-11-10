from app import app
from db import get_db

app.testing = True
client = app.test_client()
db = get_db()
all_ok = True


def check(url, expect=200):
    global all_ok
    code = client.get(url).status_code
    ok = code == expect
    all_ok = all_ok and ok
    print("OK  " if ok else "FAIL", code, url)


for url in [
    "/",
    "/products/", "/products/?q=%28&stock=low&sort=price_high&page=2", "/products/new",
    "/orders/", "/orders/?status=Shipped&payment=paid&sort=total_high&page=2", "/orders/?q=%28", "/orders/new",
    "/contacts/", "/contacts/?q=%28&prime=yes&sort=points&page=2", "/contacts/new",
]:
    check(url)

for name in ("products", "orders", "contacts"):
    doc = db[name].find_one()
    if doc:
        check(f"/{name}/{doc['_id']}")
        check(f"/{name}/{doc['_id']}/edit")

check("/orders/yeh-id-nahi-hai", expect=404)

print("\nAll good." if all_ok else "\nSomething failed, see above.")