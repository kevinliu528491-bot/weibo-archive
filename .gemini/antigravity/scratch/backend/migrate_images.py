import sqlite3
import sys

DB_PATH = "weibo_data.db"

def migrate():
    print("Starting migration for images...", file=sys.stderr)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Add images column if not exists
    try:
        c.execute("ALTER TABLE posts ADD COLUMN images TEXT")
        print("Added images column.", file=sys.stderr)
    except sqlite3.OperationalError:
        print("Column images already exists.", file=sys.stderr)
            
    conn.commit()
    conn.close()
    print("Migration complete.", file=sys.stderr)

if __name__ == "__main__":
    migrate()
