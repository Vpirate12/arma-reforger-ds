#!/usr/bin/env python3
"""
Initialize database with admin user.
Run this once before starting the container.
"""

import sqlite3
from werkzeug.security import generate_password_hash
import sys

def init_db():
    """Create database tables"""
    conn = sqlite3.connect('scenarios.db')
    c = conn.cursor()

    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT)''')

    # Active scenario tracking
    c.execute('''CREATE TABLE IF NOT EXISTS active_scenario
                 (id INTEGER PRIMARY KEY, scenario_name TEXT, updated_at TEXT)''')

    conn.commit()
    conn.close()
    print("✓ Database tables created")

def create_user(username, password):
    """Create a user account"""
    conn = sqlite3.connect('scenarios.db')
    c = conn.cursor()

    password_hash = generate_password_hash(password)

    try:
        c.execute('INSERT INTO users (username, password) VALUES (?, ?)',
                  (username, password_hash))
        conn.commit()
        print(f"✓ User '{username}' created successfully")
    except sqlite3.IntegrityError:
        print(f"✗ User '{username}' already exists")
        return False
    finally:
        conn.close()

    return True

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python init-db.py <username> <password>")
        print("Example: python init-db.py admin TheIslandAdmin")
        sys.exit(1)

    username = sys.argv[1]
    password = sys.argv[2]

    init_db()
    create_user(username, password)
