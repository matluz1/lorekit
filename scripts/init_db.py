#!/usr/bin/env python3
"""init_db.py -- Create or verify the LoreKit database schema."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import init_schema, resolve_db_path

db_path = init_schema()
print(f"Database initialized at {db_path}")
