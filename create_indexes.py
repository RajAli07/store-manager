from db import get_db

c = get_db()["products"]

# jin fields par single-field index pehle se hai
existing = {
    info["key"][0][0]
    for info in c.index_information().values()
    if len(info["key"]) == 1
}

for field in ["name", "sku", "brand", "category", "pricing.selling_price", "inventory.total_stock"]:
    if field in existing:
        print(f"skip   {field} (index pehle se hai)")
    else:
        c.create_index(field)
        print(f"banaya {field}")

print("Done.")