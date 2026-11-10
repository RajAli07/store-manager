from db import get_db

INDEXES = {
    "products": ["name", "sku", "brand", "category", "pricing.selling_price", "inventory.total_stock"],
    "orders": ["customer_id", "status", "order_date", "shipping.city", "billing.grand_total", "payment.is_paid"],
    "contacts": ["name", "email", "role", "membership.tier", "addresses.city"],
}

db = get_db()
for coll_name, fields in INDEXES.items():
    c = db[coll_name]
    existing = {
        info["key"][0][0]
        for info in c.index_information().values()
        if len(info["key"]) == 1
    }
    for field in fields:
        if field in existing:
            print(f"skip   {coll_name}.{field}")
        else:
            c.create_index(field)
            print(f"created {coll_name}.{field}")
print("Done.")