import os
from pathlib import Path
import pandas as pd
import mysql.connector
from dotenv import load_dotenv

# Load .env reliably
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

def get_connection(use_db=True):
    config = {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": 3306,
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD")
    }
    if use_db:
        config["database"] = os.getenv("DB_NAME", "retail_db")
    return mysql.connector.connect(**config)

def create_star_schema():
    """Creates the Star Schema (2 Dimension tables + 1 Fact table)."""
    conn = get_connection(use_db=False)
    cursor = conn.cursor()
    db_name = os.getenv("DB_NAME", "retail_db")
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
    cursor.execute(f"USE {db_name}")

    # Drop old tables to reset cleanly
    cursor.execute("DROP TABLE IF EXISTS fact_sales")
    cursor.execute("DROP TABLE IF EXISTS sales")
    cursor.execute("DROP TABLE IF EXISTS dim_products")
    cursor.execute("DROP TABLE IF EXISTS dim_regions")

    # Dimension 1: Products
    cursor.execute("""
    CREATE TABLE dim_products (
        product_id INT AUTO_INCREMENT PRIMARY KEY,
        product_name VARCHAR(100) UNIQUE,
        category VARCHAR(50),
        unit_price DECIMAL(10, 2)
    )
    """)

    # Dimension 2: Regions
    cursor.execute("""
    CREATE TABLE dim_regions (
        region_id INT AUTO_INCREMENT PRIMARY KEY,
        region_name VARCHAR(50) UNIQUE,
        manager_name VARCHAR(100)
    )
    """)

    # Fact Table: Sales
    cursor.execute("""
    CREATE TABLE fact_sales (
        sale_id INT AUTO_INCREMENT PRIMARY KEY,
        product_id INT,
        region_id INT,
        quantity INT,
        total_amount DECIMAL(12, 2),
        sale_date DATE,
        FOREIGN KEY (product_id) REFERENCES dim_products(product_id),
        FOREIGN KEY (region_id) REFERENCES dim_regions(region_id)
    )
    """)

    conn.commit()
    cursor.close()
    conn.close()
    print("1. Star Schema created (dim_products, dim_regions, fact_sales).")

def run_etl():
    """Extracts CSV, cleans data, and loads into the Star Schema."""
    # --- EXTRACT ---
    csv_path = Path(__file__).resolve().parent / "data" / "daily_sales.csv"
    df = pd.read_csv(csv_path)
    print(f"2. Extracted {len(df)} raw rows from {csv_path.name}.")

    # --- TRANSFORM ---
    df["category"] = df["category"].str.strip().str.title()       # e.g. 'electronics' -> 'Electronics'
    df["region_name"] = df["region_name"].str.strip().str.title() # e.g. 'WEST' -> 'West'
    df["quantity"] = df["quantity"].fillna(1).astype(int)         # Fill missing quantity with 1
    df["total_amount"] = df["quantity"] * df["unit_price"]        # Calculate derived total
    print("3. Transformed & cleaned data (standardized text, filled nulls, calculated totals).")

    # --- LOAD ---
    conn = get_connection(use_db=True)
    cursor = conn.cursor()

    # Load Dimension: Products
    products = df[["product_name", "category", "unit_price"]].drop_duplicates()
    for _, row in products.iterrows():
        cursor.execute(
            "INSERT IGNORE INTO dim_products (product_name, category, unit_price) VALUES (%s, %s, %s)",
            (row["product_name"], row["category"], float(row["unit_price"]))
        )

    # Load Dimension: Regions
    regions = df[["region_name", "manager_name"]].drop_duplicates()
    for _, row in regions.iterrows():
        cursor.execute(
            "INSERT IGNORE INTO dim_regions (region_name, manager_name) VALUES (%s, %s)",
            (row["region_name"], row["manager_name"])
        )
    conn.commit()

    # Map names to database IDs for the Fact table
    cursor.execute("SELECT product_name, product_id FROM dim_products")
    product_map = dict(cursor.fetchall())

    cursor.execute("SELECT region_name, region_id FROM dim_regions")
    region_map = dict(cursor.fetchall())

    # Load Fact Table: fact_sales
    for _, row in df.iterrows():
        cursor.execute(
            """INSERT INTO fact_sales (product_id, region_id, quantity, total_amount, sale_date)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                product_map[row["product_name"]],
                region_map[row["region_name"]],
                int(row["quantity"]),
                float(row["total_amount"]),
                row["sale_date"]
            )
        )

    conn.commit()
    cursor.close()
    conn.close()
    print(f"4. Loaded {len(df)} clean records into MySQL Star Schema!")

if __name__ == "__main__":
    create_star_schema()
    run_etl()