import os
import re
import io
import time
import base64
from pathlib import Path
import mysql.connector
import matplotlib
matplotlib.use("Agg")  # Required for generating charts in Flask without a GUI window
import matplotlib.pyplot as plt
import seaborn as sns
from flask import Flask, render_template, request
from google import genai
from google.genai import types
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

app = Flask(__name__)
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=3306,
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME", "retail_db")
    )

def get_schema_string():
    """Extracts tables, columns, and foreign key relationships for accurate JOINs."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SHOW TABLES")
    tables = [row[0] for row in cursor.fetchall()]

    schema_info = []
    for table in tables:
        cursor.execute(f"DESCRIBE {table}")
        columns = [f"{col[0]} ({col[1]})" for col in cursor.fetchall()]
        schema_info.append(f"Table `{table}`: {', '.join(columns)}")

    # Include Foreign Keys so Gemini knows how to JOIN Star Schema tables
    db_name = os.getenv("DB_NAME", "retail_db")
    cursor.execute("""
        SELECT TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
        FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = %s AND REFERENCED_TABLE_NAME IS NOT NULL
    """, (db_name,))
    for tbl, col, ref_tbl, ref_col in cursor.fetchall():
        schema_info.append(f"Relationship: {tbl}.{col} -> {ref_tbl}.{ref_col}")

    cursor.close()
    conn.close()
    return "\n".join(schema_info)

def generate_sql(user_question, schema):
    """Translates plain English into MySQL with automatic fallback on 503 spikes."""
    system_prompt = f"""
    You are an expert MySQL Database Assistant.
    Convert the user's natural language question into a valid, read-only MySQL query.

    Database Schema:
    {schema}

    Rules:
    1. Output ONLY the raw SQL query. Do not include markdown formatting (like ```sql) or explanations.
    2. ONLY generate SELECT statements.
    3. Use explicit JOINs when combining dimension and fact tables.
    """

    models_to_try = [
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash",
        "gemini-4-hydrogen"
    ]
    last_error = None

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_question,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.1,
                )
            )
            sql_query = response.text.strip()
            return re.sub(r"^```sql\s*|\s*```$", "", sql_query, flags=re.IGNORECASE).strip()
        except Exception as e:
            last_error = e
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                time.sleep(1)
                continue
            raise e
    raise last_error

def is_safe_query(sql):
    forbidden = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "REPLACE"]
    upper_sql = sql.upper().strip()
    if not upper_sql.startswith("SELECT"):
        return False
    return not any(word in upper_sql.split() for word in forbidden)

def generate_chart(columns, rows):
    """Auto-generates a Seaborn bar chart if the result has 2+ rows and at least 1 numeric column."""
    if len(rows) < 2 or len(columns) < 2:
        return None

    # Find first text/label column and first numeric column
    label_idx, num_idx = None, None
    for i, val in enumerate(rows[0]):
        if isinstance(val, (int, float)) or hasattr(val, "__float__"):
            if num_idx is None:
                num_idx = i
        elif label_idx is None:
            label_idx = i

    if label_idx is None or num_idx is None:
        return None

    labels = [str(row[label_idx]) for row in rows[:12]]  # Cap at 12 bars for readability
    values = [float(row[num_idx]) for row in rows[:12]]

    sns.set_theme(style="whitegrid")
    fig, ax = plt.subplots(figsize=(8, 4))
    sns.barplot(x=labels, y=values, hue=labels, palette="viridis", legend=False, ax=ax)

    ax.set_xlabel(columns[label_idx].replace("_", " ").title())
    ax.set_ylabel(columns[num_idx].replace("_", " ").title())
    ax.set_title(f"{columns[num_idx].replace('_', ' ').title()} by {columns[label_idx].replace('_', ' ').title()}")
    plt.xticks(rotation=25, ha="right")
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode("utf-8")

@app.route("/", methods=["GET", "POST"])
def index():
    question = ""
    sql_query = ""
    columns = []
    rows = []
    chart_url = None
    error = None

    if request.method == "POST":
        question = request.form.get("question", "").strip()
        if question:
            try:
                schema = get_schema_string()
                sql_query = generate_sql(question, schema)

                if not is_safe_query(sql_query):
                    error = "Security Alert: Only read-only SELECT queries are permitted."
                else:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute(sql_query)

                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()
                    chart_url = generate_chart(columns, rows)

                    cursor.close()
                    conn.close()
            except Exception as e:
                error = f"Error executing query: {str(e)}"

    return render_template(
        "index.html",
        question=question,
        sql_query=sql_query,
        columns=columns,
        rows=rows,
        chart_url=chart_url,
        error=error
    )

if __name__ == "__main__":
    app.run(debug=True)