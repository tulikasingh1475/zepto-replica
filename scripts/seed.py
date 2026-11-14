"""Seed ~200 synthetic SKUs into Mongo and per-store stock into Postgres. Data is synthetic."""
import os
import random

import psycopg
from pymongo import MongoClient, ReplaceOne

rng = random.Random(42)  # deterministic, so re-runs give the same catalog
STORES = ["S-CP", "S-KB"]
CATS = {  # category: (4 fictional brands, 5 item types) -> 20 SKUs each
    "Dairy & Eggs": (["Pure Pasture", "Kisan Fresh", "Meadow Gold", "Daily Dairy"],
                     ["Milk", "Curd", "Paneer", "Butter", "Eggs"]),
    "Fruits & Vegetables": (["GreenBasket", "FarmFirst", "Harvest Co", "OrchardLane"],
                            ["Tomato", "Onion", "Banana", "Apple", "Potato"]),
    "Snacks": (["Crunchy Co", "Snackwell", "Munchies", "Tastebite"],
               ["Salted Chips", "Masala Chips", "Namkeen", "Nachos", "Popcorn"]),
    "Beverages": (["Chillo", "SipUp", "FizzGo", "Juicy"],
                  ["Cola", "Orange Juice", "Iced Tea", "Soda", "Energy Drink"]),
    "Bakery": (["OvenFresh", "Crumb & Co", "BakeHouse", "Golden Loaf"],
               ["White Bread", "Brown Bread", "Pav", "Rusk", "Cake Slice"]),
    "Staples": (["Annapurna", "GrainGold", "Desi Harvest", "Rasoi"],
                ["Atta", "Rice", "Toor Dal", "Sugar", "Salt"]),
    "Personal Care": (["Glow", "PureSkin", "FreshUp", "Bloom"],
                      ["Soap", "Shampoo", "Toothpaste", "Face Wash", "Body Lotion"]),
    "Household": (["SparkleX", "HomeEase", "CleanCo", "BrightHome"],
                  ["Detergent", "Dish Soap", "Floor Cleaner", "Tissues", "Garbage Bags"]),
    "Frozen": (["FrostyFoods", "IceCrown", "ChillBite", "PolarPack"],
               ["Peas", "Fries", "Nuggets", "Ice Cream", "Paratha"]),
    "Breakfast": (["MorningMate", "Wakey", "CerealCo", "Sunrise"],
                  ["Corn Flakes", "Oats", "Muesli", "Peanut Butter", "Jam"]),
}
PACKS = ["100 g", "250 g", "500 g", "1 kg", "1 L", "6 pcs", "12 pcs"]


def main():
    g = os.getenv
    products = []
    n = 0
    for cat, (brands, items) in CATS.items():
        for brand in brands:
            for item in items:
                n += 1
                sku = f"SKU-{n:04d}"
                products.append({"sku": sku, "name": f"{brand} {item}", "brand": brand,
                                 "category": cat, "mrp": rng.randrange(20, 500, 5),
                                 "attributes": {"pack_size": rng.choice(PACKS)},
                                 "image": f"https://images.example.com/{sku}.jpg"})

    mongo = MongoClient(g("MONGO_URL", "mongodb://localhost:27017"), serverSelectionTimeoutMS=3000)
    col = mongo[g("MONGO_DB", "zepto_catalog")]["products"]
    col.create_index("sku", unique=True)
    col.create_index("category")
    col.bulk_write([ReplaceOne({"sku": p["sku"]}, p, upsert=True) for p in products])

    dsn = (f"host={g('POSTGRES_HOST', 'localhost')} port={g('POSTGRES_PORT', '5433')} "
           f"user={g('POSTGRES_USER', 'zepto')} password={g('POSTGRES_PASSWORD', 'zepto_dev')} "
           f"dbname={g('POSTGRES_DB', 'zepto')}")
    rows = [(store, p["sku"], rng.choices([0, 5, 20, 50, 100], weights=[1, 2, 3, 3, 2])[0])
            for store in STORES for p in products]
    with psycopg.connect(dsn) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS stock (
            store_id text NOT NULL, sku text NOT NULL,
            available int NOT NULL CHECK (available >= 0),
            reserved int NOT NULL DEFAULT 0 CHECK (reserved >= 0),
            PRIMARY KEY (store_id, sku))""")
        with c.cursor() as cur:
            cur.executemany(
                "INSERT INTO stock (store_id, sku, available) VALUES (%s,%s,%s) "
                "ON CONFLICT (store_id, sku) DO UPDATE SET available = EXCLUDED.available, reserved = 0",
                rows)
    print(f"seeded {len(products)} products, {len(rows)} stock rows across {len(STORES)} stores")


if __name__ == "__main__":
    main()
