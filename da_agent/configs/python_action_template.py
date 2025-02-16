VIEW_TABLE_TEMPLATE = """
import pandas as pd

pd.set_option('display.max_columns', None)
pd.set_option('display.expand_frame_repr', False)

file_path = "{file_path}"
if file_path.endswith('.xlsx') or file_path.endswith('.xls'):
    df = pd.read_excel(file_path)
elif file_path.endswith('.tsv'):
    df = pd.read_csv(file_path, sep='\t')
else:
    df = pd.read_csv(file_path)
    
print(df.head(1))
print('...')
print(f'[{len(df)} rows x {len(df.columns)} columns]')
"""

SQL2DB_TEMPLATE = """
import sqlite3

def convert_sql_to_sqlite(sql_file_path, sqlite_file_path):
    with open(sql_file_path, 'r') as sql_file:
        sql_script = sql_file.read()

    conn = sqlite3.connect(sqlite_file_path)
    cursor = conn.cursor()
    cursor.executescript(sql_script)

    conn.commit()
    conn.close()

sql_file_path = "{file_path}"
sqlite_file_path = "{sqlite_file_path}"
convert_sql_to_sqlite(sql_file_path, sqlite_file_path)
"""

DB_TABLES_TEMPLATE = """
import sqlite3

def get_table_names(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    conn.close()

    return [table[0] for table in tables]


# Example usage
db_path = "{file_path}"
table_names = get_table_names(db_path)
print(table_names)
"""

DB_TABLE_COLUMNS_TEMPLATE = """
import sqlite3

def get_table_columns(db_path, table_names):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    table_columns = {}
    for table_name in table_names:
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = cursor.fetchall()
        table_columns[table_name] = columns

    conn.close()
    return table_columns

db_path = '{file_path}'
table_names = {table_names}
columns_info = get_table_columns(db_path, table_names)
for i, (table, columns) in enumerate(columns_info.items()):
    print(f"{i+1}. Table `{table}` columns:")
    print("```")
    print("name, type, notnull, dflt_value, pk")
    for column in columns:
        print(column[1:])
    print("```")
"""

SQL_TEMPLATE = """
import sqlite3
import pandas as pd

def estimate_str_length(df, sample_rows=5):
    if df.empty or sample_rows <= 0:
        return 0
    sample = df.head(sample_rows)
    num_sample = len(sample)
    if num_sample == 0:
        return 0
    sample_str = sample.to_string()
    sample_len = len(sample_str)
    avg_per_row = sample_len / num_sample
    total_estimate = avg_per_row * len(df)
    return total_estimate

def execute_sql(file_path, command, output_path):
    conn = sqlite3.connect(file_path)
    
    try:
        df = pd.read_sql_query(command, conn)
        
        estimated_len = estimate_str_length(df, 5)
        if estimated_len > 2500:
            df.to_csv(output_path, index=False)
            print(f"Output saved to: {{output_path}}")
        else:
            print(df.to_string(index=False))
    except Exception as e:
        print(f"ERROR: {{e}}")
    finally:
        conn.close()

file_path = "{file_path}"
command = "{command}"
output_path = "{output}"

execute_sql(file_path, command, output_path)

"""


