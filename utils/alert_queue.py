"""Durable, bounded catch-up for the source held during VPS migration."""
import json
import logging
from db.database import db_conn
from utils.notifier import _get_chat_ids

log=logging.getLogger(__name__)

def _table(c):
    c.execute('''CREATE TABLE IF NOT EXISTS migration_alert_queue (
        source TEXT NOT NULL, lot_id TEXT NOT NULL, payload TEXT NOT NULL,
        delivered TEXT NOT NULL DEFAULT '[]', PRIMARY KEY(source,lot_id))''')

def enqueue(lots):
    with db_conn() as c:
        _table(c)
        for lot in lots:
            if not c.execute('SELECT 1 FROM seen_lots WHERE source=? AND lot_id=?',
                             (lot['source'],lot['lot_id'])).fetchone():
                c.execute('INSERT OR IGNORE INTO migration_alert_queue(source,lot_id,payload) VALUES(?,?,?)',
                          (lot['source'],lot['lot_id'],json.dumps(lot,ensure_ascii=False)))

def drain(source,sender,limit=5):
    recipients=_get_chat_ids()
    if not recipients:
        log.error('[%s] queue held: no recipients',source)
        return
    with db_conn() as c:
        _table(c)
        rows=c.execute('SELECT lot_id,payload,delivered FROM migration_alert_queue WHERE source=? ORDER BY rowid LIMIT ?',
                       (source,limit)).fetchall()
    completed=0
    for lot_id,payload,delivered_raw in rows:
        lot=json.loads(payload)
        delivered=set(json.loads(delivered_raw))
        for cid in recipients:
            if cid in delivered:
                continue
            if sender(lot,chat_id=cid) is not True:
                log.error('[%s] queue paused after failed delivery',source)
                return
            delivered.add(cid)
            with db_conn() as c:
                c.execute('UPDATE migration_alert_queue SET delivered=? WHERE source=? AND lot_id=?',
                          (json.dumps(sorted(delivered)),source,lot_id))
        with db_conn() as c:
            # Final history and queue removal commit together.
            c.execute('INSERT OR IGNORE INTO seen_lots(lot_id,source) VALUES(?,?)',(lot_id,source))
            c.execute('INSERT INTO found_lots(lot_id,source,url,title,price,photo_url,summary) VALUES(?,?,?,?,?,?,NULL)',
                      (lot_id,source,lot['url'],lot.get('title'),lot.get('price'),lot.get('photo_url')))
            c.execute('DELETE FROM migration_alert_queue WHERE source=? AND lot_id=?',(source,lot_id))
        completed+=1
    with db_conn() as c:
        left=c.execute('SELECT COUNT(*) FROM migration_alert_queue WHERE source=?',(source,)).fetchone()[0]
    log.info('[%s] catch-up delivered=%d pending=%d cap=%d',source,completed,left,limit)
