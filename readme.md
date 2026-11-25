# Talk to Your Database

A simple web app where you can ask questions about your sales data in plain English instead of writing SQL queries.

I built this using Python, Flask, MySQL, and the Gemini API. You type a question like *"Show total revenue by region manager"*, and the app converts it into a SQL `SELECT` query, runs it on a local MySQL database, and shows the results as both a table and a bar chart.

## What's Inside

- **Star Schema Database (`etl_pipeline.py`)**: Splits raw retail data into `fact_sales`, `dim_products`, and `dim_regions` tables in MySQL.
- **CSV Data Cleaning**: Reads `data/daily_sales.csv` using Pandas, fixes inconsistent text casing (like `north` vs `West`), fills missing quantities, and loads the clean rows into MySQL.
- **Natural Language to SQL (`app.py`)**: Sends your database table structure and foreign keys to Gemini so it writes accurate `JOIN` queries. Only `SELECT` statements are allowed so data can't be modified or deleted.
- **Auto Charts (`templates/index.html`)**: Uses Seaborn and Matplotlib to automatically draw a bar chart whenever the query returns labels and numbers.