import os
import pymysql
import pymysql.cursors
from flask import g

def get_db():
    if 'db' not in g:
        g.db = pymysql.connect(
            host=os.environ.get('DB_HOST', 'mariadb'),
            user=os.environ.get('DB_USER', 'bootwatch'),
            password=os.environ.get('DB_PASSWORD', 'bootwatch'),
            database=os.environ.get('DB_NAME', 'bootwatch'),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def fetch_one(sql, args=()):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()

def fetch_all(sql, args=()):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()

def execute(sql, args=()):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.lastrowid

def get_or_create_device(ip_addr, name, label=''):
    row = fetch_one('SELECT id FROM bw_devices WHERE ip_addr = %s', (ip_addr,))
    if row:
        return row['id']
    return execute(
        'INSERT INTO bw_devices (ip_addr, name, label) VALUES (%s, %s, %s)',
        (ip_addr, name, label)
    )

def get_or_create_revision(revision):
    row = fetch_one('SELECT id FROM bw_sw_revisions WHERE revision = %s', (revision,))
    if row:
        return row['id']
    return execute('INSERT INTO bw_sw_revisions (revision) VALUES (%s)', (revision,))
