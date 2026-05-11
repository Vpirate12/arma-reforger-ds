#!/usr/bin/env python3
"""
Setup script to initialize users in the database
Run this once before starting the app, or use it to add new users
"""

import sqlite3
import sys
from werkzeug.security import generate_password_hash

def init_db():
    conn = sqlite3.connect('scenarios.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS active_scenario
                 (id INTEGER PRIMARY KEY, scenario_name TEXT, updated_at TEXT)''')
    conn.commit()
    conn.close()

def add_user(username, password):
    init_db()

    conn = sqlite3.connect('scenarios.db')
    c = conn.cursor()

    # Check if user exists
    c.execute('SELECT id FROM users WHERE username = ?', (username,))
    if c.fetchone():
        print(f"✗ User '{username}' already exists")
        conn.close()
        return False

    # Hash password and insert
    hashed_pwd = generate_password_hash(password)
    c.execute('INSERT INTO users (username, password) VALUES (?, ?)',
              (username, hashed_pwd))
    conn.commit()
    conn.close()

    print(f"✓ User '{username}' created successfully")
    return True

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python setup.py <username> <password>")
        print("Example: python setup.py aaron mypassword123")
        sys.exit(1)

    username = sys.argv[1]
    password = sys.argv[2]

    if len(password) < 6:
        print("✗ Password must be at least 6 characters")
        sys.exit(1)

    add_user(username, password)
